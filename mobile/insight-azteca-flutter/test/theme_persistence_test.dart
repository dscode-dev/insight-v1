// AZTECA-QUALITY-A — theme persistence (device-local) tests.
//
// Proves: default is system; a choice persists via ThemeStore; a fresh
// provider container restores the persisted value (restart simulation); and a
// storage failure degrades safely to system without throwing.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/core/theme_store.dart';
import 'package:azteca/providers/settings_provider.dart';

/// In-memory ThemeStore fake — models device storage across "restarts".
class _MemThemeStore implements ThemeStore {
  String? _raw;
  bool failWrites = false;

  @override
  Future<ThemeMode> read() async => ThemeStore.decode(_raw);

  @override
  Future<void> write(ThemeMode mode) async {
    if (failWrites) throw StateError('storage unavailable');
    _raw = ThemeStore.encode(mode);
  }
}

void main() {
  test('encode/decode round-trips every mode; unknown → system', () {
    for (final m in ThemeMode.values) {
      expect(ThemeStore.decode(ThemeStore.encode(m)), m);
    }
    expect(ThemeStore.decode(null), ThemeMode.system);
    expect(ThemeStore.decode('garbage'), ThemeMode.system);
  });

  test('default (unseeded) is system', () {
    final c = ProviderContainer();
    addTearDown(c.dispose);
    expect(c.read(themeModeProvider), ThemeMode.system);
  });

  test('set() updates state and persists to the store', () async {
    final store = _MemThemeStore();
    final c = ProviderContainer(
      overrides: [themeStoreProvider.overrideWithValue(store)],
    );
    addTearDown(c.dispose);

    c.read(themeModeProvider.notifier).set(ThemeMode.dark);
    expect(c.read(themeModeProvider), ThemeMode.dark);
    // fire-and-forget persistence completes on the microtask queue.
    await Future<void>.delayed(Duration.zero);
    expect(await store.read(), ThemeMode.dark);
  });

  test('persisted choice is restored after a container recreation (restart)',
      () async {
    final store = _MemThemeStore();
    final c1 = ProviderContainer(
      overrides: [themeStoreProvider.overrideWithValue(store)],
    );
    c1.read(themeModeProvider.notifier).set(ThemeMode.light);
    await Future<void>.delayed(Duration.zero);
    c1.dispose();

    // Simulate app restart: main() reads the store and seeds bootThemeMode.
    final boot = await store.read();
    final c2 = ProviderContainer(
      overrides: [
        themeStoreProvider.overrideWithValue(store),
        bootThemeModeProvider.overrideWithValue(boot),
      ],
    );
    addTearDown(c2.dispose);
    expect(c2.read(themeModeProvider), ThemeMode.light);
  });

  test('storage write failure degrades safely (choice still applies)',
      () async {
    final store = _MemThemeStore()..failWrites = true;
    final c = ProviderContainer(
      overrides: [themeStoreProvider.overrideWithValue(store)],
    );
    addTearDown(c.dispose);
    // Must not throw even though the store write fails.
    c.read(themeModeProvider.notifier).set(ThemeMode.dark);
    expect(c.read(themeModeProvider), ThemeMode.dark);
    await Future<void>.delayed(Duration.zero);
  });
}
