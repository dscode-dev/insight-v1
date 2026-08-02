// API layer tests — Sprint 2 (Parts 3 + 14 + 15).
import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/core/api_mode.dart';
import 'package:azteca/core/env.dart';
import 'package:azteca/core/errors.dart';
import 'package:azteca/services/gateway_client.dart';
import 'package:azteca/services/social_service.dart';

/// Adapter that fails [failures] times with a connection error, then
/// succeeds — exercises the retry policy without a network.
class _FlakyAdapter implements HttpClientAdapter {
  _FlakyAdapter({required this.failures});
  int failures;
  int attempts = 0;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<List<int>>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    attempts++;
    if (attempts <= failures) {
      throw DioException.connectionError(
        requestOptions: options,
        reason: 'simulated outage',
      );
    }
    return ResponseBody.fromString(
      '{"ok": true}',
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  group('environment config (Part 14)', () {
    test('defaults are production-safe', () {
      // Tests run without --dart-define: local environment, gateway mode.
      // STAGING-INTEGRATION-B: LAN labs/loopback were removed — every
      // environment (including local, absent an API_BASE_URL override) resolves
      // to the single official public Gateway. The old LAN default
      // (http://192.168.1.61:8080) no longer exists; the production-safe default
      // is the cloud Gateway.
      expect(InsightEnv.environment, InsightEnvironment.local);
      expect(InsightEnv.isProduction, isFalse);
      expect(InsightEnv.apiBaseUrl, 'https://insight-api.konohalabs.com.br');
      expect(InsightEnv.enableDemoMode, isFalse);
    });

    test('mock transport requires explicit demo mode', () {
      // API_MODE was not set to mock AND demo mode is off → gateway.
      // The product rule: fixtures can never reach users by accident.
      expect(ApiMode.current, ApiMode.gateway);
      expect(ApiMode.current.isMock, isFalse);
    });

    test('shipped foundations are on by default (V1.1)', () {
      // No FEATURE_FLAGS in the test build — defaults apply, so a
      // production build without flags can never ship empty social.
      expect(InsightEnv.featureFlags, contains(kSocialV1Flag));
      expect(InsightEnv.flag(kSocialV1Flag), isTrue);
    });
  });

  group('retry policy (Part 3)', () {
    ProviderContainer buildContainer(_FlakyAdapter adapter) {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      container.read(gatewayDioProvider).httpClientAdapter = adapter;
      return container;
    }

    test('GET retries transient failures and succeeds', () async {
      final adapter = _FlakyAdapter(failures: 2);
      final dio = buildContainer(adapter).read(gatewayDioProvider);

      final response = await dio.get<Map<String, dynamic>>('/v1/anything');
      expect(response.statusCode, 200);
      expect(adapter.attempts, 3, reason: '2 failures + 1 success');
    });

    test('GET gives up after max attempts and maps to NetworkException',
        () async {
      final adapter = _FlakyAdapter(failures: 99);
      final dio = buildContainer(adapter).read(gatewayDioProvider);

      try {
        await dio.get<Map<String, dynamic>>('/v1/anything');
        fail('must throw');
      } on DioException catch (e) {
        expect(e.error, isA<NetworkException>(),
            reason: 'offline failures map to the typed error (Part 11)');
      }
      expect(adapter.attempts, 3, reason: 'bounded retries');
    });

    test('mutations are never retried', () async {
      final adapter = _FlakyAdapter(failures: 99);
      final dio = buildContainer(adapter).read(gatewayDioProvider);

      try {
        await dio.post<Map<String, dynamic>>('/v1/posts', data: {});
        fail('must throw');
      } on DioException catch (_) {}
      expect(adapter.attempts, 1,
          reason: 'POST must fail fast — the caller owns retry semantics');
    });
  });

  group('social contracts (Part 4)', () {
    test('gateway adapter is selected in gateway mode', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final api = container.read(socialApiProvider);
      expect(api, isA<GatewaySocialService>(),
          reason: 'gateway mode → real Social Foundation client');
    });

    test('demo fallback degrades reads to empty, never throws', () async {
      final api = DemoFallbackSocialService();
      final feed = await api.globalFeed();
      expect(feed.items, isEmpty);
      expect(await api.listAgents(), isEmpty);
      await api.follow('someone'); // no-op, no crash
    });
  });
}
