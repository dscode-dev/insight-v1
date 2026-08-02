/// Application error hierarchy.
///
/// Services throw subtypes of `InsightException`. The presentation layer
/// matches on the type to render the right message and (when relevant)
/// recovery action. `dynamic` errors that escape services get mapped to
/// `UnknownInsightException` at the boundary.
sealed class InsightException implements Exception {
  const InsightException(this.message, {this.cause});

  final String message;
  final Object? cause;

  @override
  String toString() => '$runtimeType: $message';
}

/// Wraps an HTTP error from Gateway. `statusCode` is the HTTP status; `detail`
/// is the parsed `detail` field from the JSON body if present.
final class GatewayException extends InsightException {
  const GatewayException({
    required this.statusCode,
    required String message,
    this.detail,
    Object? cause,
  }) : super(message, cause: cause);

  final int statusCode;
  final String? detail;

  bool get isUnauthorized => statusCode == 401;
  bool get isForbidden => statusCode == 403;
  bool get isNotFound => statusCode == 404;
  bool get isRateLimited => statusCode == 429;
  bool get isServerError => statusCode >= 500;
}

/// The token refresh attempt itself failed — user must re-authenticate.
final class TokenRefreshFailedException extends InsightException {
  const TokenRefreshFailedException({Object? cause})
      : super('token_refresh_failed', cause: cause);
}

/// Local validation (form errors) — never round-trips to the server.
final class ValidationException extends InsightException {
  const ValidationException(super.message, {this.field});
  final String? field;
}

/// Network connectivity / DNS / TLS — distinct from server-side errors.
final class NetworkException extends InsightException {
  const NetworkException(super.message, {super.cause});
}

/// Mapping fell off the known cases.
final class UnknownInsightException extends InsightException {
  const UnknownInsightException(super.message, {super.cause});
}
