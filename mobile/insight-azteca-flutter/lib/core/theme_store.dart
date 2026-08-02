import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Device-local persistence for the user's theme choice (AZTECA-QUALITY-A).
///
/// Theme is a DEVICE preference — never a backend/account setting (the Settings
/// UI already states "salvo apenas neste dispositivo"). We reuse the same
/// secure-storage strategy as [TokenStorage]/[ComposerDraftStore] — no new
/// dependency, no second storage mechanism. All I/O degrades safely: a read
/// failure falls back to [ThemeMode.system] and a write failure is swallowed
/// (the in-memory choice still applies for the session).
class ThemeStore {
  ThemeStore({FlutterSecureStorage? backend})
      : _store = backend ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
              iOptions: IOSOptions(
                accessibility: KeychainAccessibility.first_unlock,
              ),
            );

  final FlutterSecureStorage _store;

  static const _kKey = 'insight.settings.theme_mode';

  /// Read the persisted mode. Never throws — unknown/absent/failed → system.
  Future<ThemeMode> read() async {
    try {
      return decode(await _store.read(key: _kKey));
    } catch (_) {
      return ThemeMode.system;
    }
  }

  /// Persist the chosen mode. Never throws — a storage failure degrades to a
  /// session-only choice (the caller already updated in-memory state).
  Future<void> write(ThemeMode mode) async {
    try {
      await _store.write(key: _kKey, value: encode(mode));
    } catch (_) {
      /* degrade safely: keep the in-memory choice for this session */
    }
  }

  static String encode(ThemeMode mode) => switch (mode) {
        ThemeMode.light => 'light',
        ThemeMode.dark => 'dark',
        ThemeMode.system => 'system',
      };

  static ThemeMode decode(String? raw) => switch (raw) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };
}
