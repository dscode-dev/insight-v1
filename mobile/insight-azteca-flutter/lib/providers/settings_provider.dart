import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/theme_store.dart';

/// Device-local theme store (secure storage). Overridable in tests.
final themeStoreProvider = Provider<ThemeStore>((_) => ThemeStore());

/// Boot seed for the theme mode. `main()` reads the persisted value BEFORE the
/// first frame and overrides this with it, so the app opens in the saved theme
/// with no flash. Defaults to system when unseeded (e.g. widget tests).
final bootThemeModeProvider = Provider<ThemeMode>((_) => ThemeMode.system);

/// Active theme mode — the single source of truth shared by the MaterialApp and
/// the Settings screen. Persisted device-locally (AZTECA-QUALITY-A): a user
/// choice survives app restart; system/default is preserved when never changed.
/// Theme is a DEVICE preference — never a backend/account setting.
class ThemeModeNotifier extends Notifier<ThemeMode> {
  @override
  ThemeMode build() => ref.read(bootThemeModeProvider);

  /// Set + persist the user's explicit choice. Persistence is fire-and-forget
  /// and degrades safely (a storage failure keeps the choice for this session).
  void set(ThemeMode mode) {
    if (state == mode) return;
    state = mode;
    // Fire-and-forget + defensive: a throwing/unavailable store must never crash
    // the app — the in-memory choice still applies for this session.
    unawaited(ref.read(themeStoreProvider).write(mode).catchError((_) {}));
  }
}

final themeModeProvider =
    NotifierProvider<ThemeModeNotifier, ThemeMode>(ThemeModeNotifier.new);
