/// Build-time environment + feature configuration — Sprint 2
/// (Production Foundation, Part 14).
///
/// Everything is `--dart-define`d at build time; NO secrets live in
/// the app. Examples:
///
///   flutter run --dart-define=ENVIRONMENT=local \
///               --dart-define=API_MODE=mock \
///               --dart-define=ENABLE_DEMO_MODE=true
///
///   flutter build ipa --dart-define=ENVIRONMENT=production
///
/// The app talks to the PUBLIC GATEWAY ONLY — never directly to
/// Atlas, Sport Hub, Nexus or any internal Robozão API.
library;

enum InsightEnvironment { dev, local, staging, production }

class InsightEnv {
  const InsightEnv._();

  // ---- environment ------------------------------------------------------

  static const String _environmentRaw = String.fromEnvironment(
    'ENVIRONMENT',
    defaultValue: 'local',
  );

  /// Runtime override (Azteca-X Part 7) — a dev/staging-only environment
  /// switcher (Settings) persists the chosen environment here at startup so the
  /// operator can point the app at local / staging / production without a
  /// rebuild. Never honored in a production BUILD (guarded below).
  static InsightEnvironment? runtimeEnvironment;

  static InsightEnvironment get _buildEnvironment => switch (_environmentRaw) {
        'production' || 'prod' => InsightEnvironment.production,
        'staging' => InsightEnvironment.staging,
        'local' => InsightEnvironment.local,
        _ => InsightEnvironment.dev,
      };

  static InsightEnvironment get environment {
    // A production build is immutable; dev/staging builds may switch at runtime.
    if (_buildEnvironment == InsightEnvironment.production) {
      return InsightEnvironment.production;
    }
    return runtimeEnvironment ?? _buildEnvironment;
  }

  static String get environmentLabel => switch (environment) {
        InsightEnvironment.production => 'production',
        InsightEnvironment.staging => 'staging',
        InsightEnvironment.local => 'local',
        InsightEnvironment.dev => 'dev',
      };

  /// Runtime environment switching is only allowed in non-production builds;
  /// a production build is locked to its public Gateway.
  static bool get allowRuntimeSwitch =>
      _buildEnvironment != InsightEnvironment.production;

  /// Base URL a given environment would resolve to (for the Settings switcher
  /// display — no side effects). Mirrors [apiBaseUrl]'s per-environment map.
  ///
  /// STAGING-INTEGRATION-B: the Cloud is the single official environment. Every
  /// environment resolves to the public Gateway `https://insight-api.konohalabs.com.br`
  /// (no region prefix; `/v1` lives in the path layer). Local LAN labs and
  /// loopback have been removed — devs needing another endpoint use API_BASE_URL.
  static String baseUrlForEnvironment(InsightEnvironment env) => _cloudBaseUrl;

  static bool get isProduction => environment == InsightEnvironment.production;

  // ---- API --------------------------------------------------------------

  /// `mock` | `gateway` (default). Read by `ApiMode` resolver — mock
  /// is ONLY honored when demo mode is enabled and the build is not
  /// production (see api_mode.dart).
  static const String apiModeRaw = String.fromEnvironment(
    'API_MODE',
    defaultValue: 'gateway',
  );

  static const String _apiBaseUrlOverride = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: '',
  );

  /// The single official public Gateway (STAGING-INTEGRATION-B). The app talks
  /// to the GATEWAY ONLY (never Atlas/Sport-Hub/Nexus/Social directly). NO
  /// trailing `/v1` — that lives in the path layer (every service prepends
  /// `/v1/...`). No region prefix: the cloud nginx routes `/v1/` straight to
  /// the gateway. Old hosts (`insight.konohalabs.com.br/cloud|big-robot`), LAN
  /// labs and loopback have been removed.
  static const String _cloudBaseUrl = 'https://insight-api.konohalabs.com.br';

  /// Public Gateway base URL. An explicit `API_BASE_URL` dart-define wins
  /// (unless it points at loopback, which is invalid for physical devices and
  /// is ignored in favor of the cloud). Every environment otherwise resolves to
  /// the single official cloud Gateway.
  static String get apiBaseUrl {
    if (_apiBaseUrlOverride.isNotEmpty &&
        !_isLoopbackGatewayUrl(_apiBaseUrlOverride)) {
      return _apiBaseUrlOverride;
    }
    return _cloudBaseUrl;
  }

  static bool _isLoopbackGatewayUrl(String value) {
    final url = Uri.tryParse(value);
    final host = url?.host.toLowerCase();
    return host == 'localhost' || host == '127.0.0.1' || host == '::1';
  }

  // ---- feature flags ------------------------------------------------------

  /// Comma-separated flag list, e.g. FEATURE_FLAGS=social_v1,club_badges.
  ///
  /// V1.1 closure (Sprint X finding M1): shipped foundations are ON by
  /// default — a production build with no FEATURE_FLAGS must not
  /// silently fall back to the empty social service. To turn a default
  /// flag off, prefix it with `-` (e.g. FEATURE_FLAGS=-social_v1).
  static const String _featureFlagsRaw = String.fromEnvironment(
    'FEATURE_FLAGS',
    defaultValue: '',
  );

  /// Flags every build carries unless explicitly disabled.
  static const Set<String> defaultFlags = {'social_v1'};

  static Set<String> get featureFlags {
    final raw = _featureFlagsRaw
        .split(',')
        .map((f) => f.trim())
        .where((f) => f.isNotEmpty)
        .toSet();
    final disabled =
        raw.where((f) => f.startsWith('-')).map((f) => f.substring(1)).toSet();
    final enabled = raw.where((f) => !f.startsWith('-')).toSet();
    return {...defaultFlags, ...enabled}.difference(disabled);
  }

  static bool flag(String name) => featureFlags.contains(name);

  /// Demo mode gates EVERY mock/fixture path. Defaults off; never
  /// honored in production builds (api_mode.dart enforces).
  static const bool enableDemoMode = bool.fromEnvironment(
    'ENABLE_DEMO_MODE',
    defaultValue: false,
  );

  static const bool enableAnalytics = bool.fromEnvironment(
    'ENABLE_ANALYTICS',
    defaultValue: false,
  );

  static const bool enableLogging = bool.fromEnvironment(
    'ENABLE_LOGGING',
    // Loud in dev, quiet by default in release builds.
    defaultValue: true,
  );

  // ---- known flag names ---------------------------------------------------
  // `social_v1` is the ONLY default-on flag — it gates the real Social
  // Foundation client (production requires it; see StartupDiagnostics).
  // The rest are OFF by default: they gate features whose Gateway routes
  // do not exist yet, so a production build never fires a 404.
  static const String flagSocialV1 = 'social_v1';
  static const String flagLiveV1 = 'live_v1'; // /v1/live/*, /v1/context/*
  static const String flagRadarV1 = 'radar_v1'; // /v1/radar/*
  static const String flagNotificationsV1 =
      'notifications_v1'; // /v1/notifications*
  static const String flagPostUploads = 'post_uploads'; // /v1/feed/uploads

  // ---- branding ------------------------------------------------------------

  static const String appName = String.fromEnvironment(
    'APP_NAME',
    defaultValue: 'Insight',
  );
}
