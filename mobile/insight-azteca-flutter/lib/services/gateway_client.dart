import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/env.dart';
import '../core/errors.dart';
import '../core/logger.dart';
import '../core/token_storage.dart';
import '../models/auth.dart';

/// Gateway HTTP client.
///
/// Two interceptors:
///   1. `_AuthInterceptor` — attaches `Authorization: Bearer <access>` to
///      every request unless the caller opts out via the
///      `Options(extra: {kSkipAuth: true})` channel.
///   2. `_RefreshInterceptor` — on 401, attempts one refresh and replays
///      the original request. On a second 401, propagates a
///      `TokenRefreshFailedException` and triggers the auth notifier to
///      clear local state (login redirect handled in routing).
///
/// Failure shape: every non-2xx becomes an `GatewayException` with the
/// status code + parsed `detail` string.
const String kSkipAuth = 'insight.skip_auth';

final tokenStorageProvider = Provider<TokenStorage>((ref) => TokenStorage());

/// Internal session cache. Loaded lazily on first access; written by the
/// auth notifier. Exposed as a separate provider so interceptors can read
/// without depending on the full auth state machine.
class GatewaySession {
  GatewaySession({this.tokens});
  Tokens? tokens;

  void update(Tokens? next) {
    tokens = next;
  }
}

final gatewaySessionProvider =
    Provider<GatewaySession>((ref) => GatewaySession());

final gatewayDioProvider = Provider<Dio>((ref) {
  final session = ref.watch(gatewaySessionProvider);
  final dio = Dio(
    BaseOptions(
      baseUrl: InsightEnv.apiBaseUrl,
      connectTimeout: const Duration(seconds: 5),
      receiveTimeout: const Duration(seconds: 10),
      sendTimeout: const Duration(seconds: 10),
      contentType: 'application/json',
      responseType: ResponseType.json,
    ),
  );
  dio.interceptors.addAll([
    _AuthInterceptor(session: session),
    _RefreshInterceptor(session: session, dio: dio, ref: ref),
    _RetryInterceptor(dio: dio),
    _ErrorMapper(),
  ]);
  return dio;
});

Future<Tokens> refreshGatewaySession(Ref ref) async {
  final session = ref.read(gatewaySessionProvider);
  final refresh = session.tokens?.refreshToken;
  if (refresh == null || refresh.isEmpty) {
    throw const TokenRefreshFailedException();
  }
  try {
    final dio = Dio(
      BaseOptions(
        baseUrl: InsightEnv.apiBaseUrl,
        connectTimeout: const Duration(seconds: 5),
        receiveTimeout: const Duration(seconds: 10),
        sendTimeout: const Duration(seconds: 10),
        contentType: 'application/json',
        responseType: ResponseType.json,
      ),
    );
    final r = await dio.post<Map<String, dynamic>>(
      '/v1/auth/refresh',
      data: {'refresh_token': refresh},
    );
    if (r.data == null) {
      throw const TokenRefreshFailedException();
    }
    final next = Tokens.fromJson(r.data!);
    session.update(next);
    await ref.read(tokenStorageProvider).write(
          access: next.accessToken,
          refresh: next.refreshToken,
          accessExpiresAt: next.accessExpiresAt,
        );
    return next;
  } catch (e) {
    L.w('gateway', 'token_refresh_failed', data: e);
    session.update(null);
    await ref.read(tokenStorageProvider).clear();
    throw TokenRefreshFailedException(cause: e);
  }
}

/// Retry policy (Sprint 2, Part 3): idempotent GETs retry up to
/// [maxAttempts] on transient failures (connectivity, timeouts, 5xx)
/// with exponential backoff. Mutations are NEVER retried here — the
/// caller owns those semantics (optimistic UI + manual retry).
class _RetryInterceptor extends Interceptor {
  _RetryInterceptor({required this.dio});

  final Dio dio;
  static const int maxAttempts = 3;

  static const _retryKey = 'insight.retry_attempt';

  bool _transient(DioException err) {
    if (err.type == DioExceptionType.connectionError ||
        err.type == DioExceptionType.connectionTimeout ||
        err.type == DioExceptionType.sendTimeout ||
        err.type == DioExceptionType.receiveTimeout) {
      return true;
    }
    final status = err.response?.statusCode ?? 0;
    return status >= 500;
  }

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    final options = err.requestOptions;
    final attempt = (options.extra[_retryKey] as int?) ?? 1;
    final retriable = options.method.toUpperCase() == 'GET' &&
        _transient(err) &&
        attempt < maxAttempts;
    if (!retriable) {
      return super.onError(err, handler);
    }
    // 250ms, 500ms, 1s... capped by maxAttempts.
    await Future<void>.delayed(
      Duration(milliseconds: 250 * (1 << (attempt - 1))),
    );
    options.extra[_retryKey] = attempt + 1;
    try {
      final response = await dio.fetch<dynamic>(options);
      return handler.resolve(response);
    } on DioException catch (retryErr) {
      return handler.reject(retryErr);
    }
  }
}

/// Attaches the bearer token unless `kSkipAuth` is set on the request.
class _AuthInterceptor extends Interceptor {
  _AuthInterceptor({required this.session});
  final GatewaySession session;

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    final skip = options.extra[kSkipAuth] == true;
    final access = session.tokens?.accessToken;
    if (!skip && access != null && access.isNotEmpty) {
      options.headers['Authorization'] = 'Bearer $access';
    }
    super.onRequest(options, handler);
  }
}

/// On a 401, performs one refresh attempt and replays the original
/// request. On a second 401, surfaces TokenRefreshFailedException so the
/// caller can route the user to /login.
class _RefreshInterceptor extends Interceptor {
  _RefreshInterceptor({
    required this.session,
    required this.dio,
    required this.ref,
  });

  final GatewaySession session;
  final Dio dio;
  final Ref ref;

  bool _refreshing = false;
  Completer<void>? _waiter;

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    final status = err.response?.statusCode;
    final skip = err.requestOptions.extra[kSkipAuth] == true;
    final isAuthEndpoint = err.requestOptions.path.startsWith('/v1/auth/');

    // Only handle authenticated 401s. Auth endpoints fail naturally.
    if (status != 401 || skip || isAuthEndpoint) {
      return super.onError(err, handler);
    }

    // If another request is already refreshing, wait for it.
    if (_refreshing) {
      try {
        await _waiter?.future;
      } catch (_) {
        return handler.reject(err);
      }
    } else {
      _refreshing = true;
      _waiter = Completer<void>();
      try {
        await refreshGatewaySession(ref);
        _waiter!.complete();
      } catch (e) {
        _waiter!.completeError(e);
        _refreshing = false;
        return handler.reject(err);
      }
      _refreshing = false;
    }

    // Replay the original request with the new token.
    try {
      final retried = await dio.fetch<dynamic>(err.requestOptions);
      return handler.resolve(retried);
    } on DioException catch (e) {
      return handler.reject(e);
    }
  }
}

/// Maps Dio errors to the typed `InsightException` hierarchy at the
/// boundary so services + UI never need to handle Dio types directly.
class _ErrorMapper extends Interceptor {
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final mapped = _map(err);
    handler.reject(
      DioException(
        requestOptions: err.requestOptions,
        response: err.response,
        type: err.type,
        error: mapped,
        message: mapped.message,
      ),
    );
  }

  InsightException _map(DioException err) {
    if (err.type == DioExceptionType.connectionError ||
        err.type == DioExceptionType.connectionTimeout ||
        err.type == DioExceptionType.sendTimeout ||
        err.type == DioExceptionType.receiveTimeout) {
      return NetworkException(err.message ?? 'network_error', cause: err);
    }
    final status = err.response?.statusCode;
    if (status != null) {
      String? detail;
      final data = err.response?.data;
      if (data is Map<String, dynamic>) {
        final d = data['detail'];
        if (d is String) detail = d;
      }
      return GatewayException(
        statusCode: status,
        message: detail ?? 'gateway_http_$status',
        detail: detail,
        cause: err,
      );
    }
    return UnknownInsightException(err.message ?? 'unknown', cause: err);
  }
}

/// Thin helper for service files: typed GET that returns the decoded body
/// or throws an `InsightException`. Keeps each service file from
/// repeating the same try/catch shape.
extension GatewayDioX on Dio {
  Future<Map<String, dynamic>> getJson(
    String path, {
    Map<String, dynamic>? query,
    Options? options,
  }) async {
    try {
      final r = await get<Map<String, dynamic>>(
        path,
        queryParameters: query,
        options: options,
      );
      return r.data ?? const <String, dynamic>{};
    } on DioException catch (e) {
      final mapped = e.error;
      if (mapped is InsightException) throw mapped;
      rethrow;
    }
  }

  Future<Map<String, dynamic>> postJson(
    String path, {
    Object? body,
    Options? options,
  }) async {
    try {
      final r = await post<Map<String, dynamic>>(
        path,
        data: body,
        options: options,
      );
      return r.data ?? const <String, dynamic>{};
    } on DioException catch (e) {
      final mapped = e.error;
      if (mapped is InsightException) throw mapped;
      rethrow;
    }
  }

  Future<Map<String, dynamic>> patchJson(
    String path, {
    Object? body,
    Options? options,
  }) async {
    try {
      final r = await patch<Map<String, dynamic>>(
        path,
        data: body,
        options: options,
      );
      return r.data ?? const <String, dynamic>{};
    } on DioException catch (e) {
      final mapped = e.error;
      if (mapped is InsightException) throw mapped;
      rethrow;
    }
  }
}
