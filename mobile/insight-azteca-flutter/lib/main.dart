import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'app.dart';
import 'clubs/club_registry.dart';
import 'core/startup_diagnostics.dart';
import 'core/theme_store.dart';
import 'providers/settings_provider.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // V1.1 — log the effective config; CRASH production builds with
  // invalid configuration (mock mode, http://, social_v1 off, …)
  // instead of shipping a broken app.
  StartupDiagnostics.run();

  // Canonical club identity layer (bundled crests, no runtime logo API).
  // Best-effort: a load failure leaves badges on the initials fallback.
  try {
    await ClubRegistry.instance.load();
  } catch (_) {/* badges fall back to initials */}

  // Intl date-symbol data must be loaded before any `DateFormat('pt_BR')`
  // is constructed. Without this the first relative-time / kickoff format
  // call throws "LocaleDataException: LocaleData has not been initialized".
  await initializeDateFormatting('pt_BR');

  // Keep the status bar transparent so the AppBar colour bleeds through.
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.dark,
    ),
  );
  // Hydrate the device-local theme BEFORE the first frame so the app opens in
  // the saved theme with no flash. Degrades to system on any read failure.
  final bootTheme = await ThemeStore().read();

  runApp(
    ProviderScope(
      overrides: [bootThemeModeProvider.overrideWithValue(bootTheme)],
      child: const InsightApp(),
    ),
  );
}
