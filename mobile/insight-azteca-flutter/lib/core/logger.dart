import 'dart:developer' as developer;

/// Minimal logger wrapper so the app never calls `print` directly
/// (analysis_options forbids it). Routes through `dart:developer` so
/// DevTools / IDE integration shows category-coloured logs.
///
/// In production we'd swap to a structured backend (Sentry, Crashlytics);
/// for V1 we keep it stdlib-only.
class L {
  const L._();

  static void d(String tag, String message, {Object? data}) {
    developer.log(message, name: tag, level: 500, error: data);
  }

  static void i(String tag, String message, {Object? data}) {
    developer.log(message, name: tag, level: 800, error: data);
  }

  static void w(String tag, String message, {Object? data}) {
    developer.log(message, name: tag, level: 900, error: data);
  }

  static void e(
    String tag,
    String message, {
    Object? error,
    StackTrace? stackTrace,
  }) {
    developer.log(
      message,
      name: tag,
      level: 1000,
      error: error,
      stackTrace: stackTrace,
    );
  }
}
