// Sprint D — User preferences state.
//
// Single AsyncNotifier (one per app instance — preferences are
// user-scoped + cheap to refetch on auth change). Exposes typed
// mutators that PUT only the changed field, so a toggle hits the
// wire as `{push_enabled: true}` not the full bag.
//
// The optimistic mode applies the patch locally first, then awaits
// the server confirmation. Failure rolls back + surfaces the error
// via the AsyncNotifier state.
import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../models/preferences.dart';
import '../services/services_providers.dart';

class PreferencesNotifier extends AsyncNotifier<UserPreferences> {
  @override
  Future<UserPreferences> build() async {
    return ref.read(preferencesServiceProvider).get();
  }

  Future<void> setLocale(String locale) async {
    await _patch((p) => p.copyWith(locale: locale), () async {
      return ref
          .read(preferencesServiceProvider)
          .update(locale: locale);
    });
  }

  Future<void> setPushEnabled(bool enabled) async {
    await _patch((p) => p.copyWith(pushEnabled: enabled), () async {
      return ref
          .read(preferencesServiceProvider)
          .update(pushEnabled: enabled);
    });
  }

  Future<void> setEmailEnabled(bool enabled) async {
    await _patch((p) => p.copyWith(emailEnabled: enabled), () async {
      return ref
          .read(preferencesServiceProvider)
          .update(emailEnabled: enabled);
    });
  }

  Future<void> setDigestFrequency(String frequency) async {
    await _patch((p) => p.copyWith(digestFrequency: frequency), () async {
      return ref
          .read(preferencesServiceProvider)
          .update(digestFrequency: frequency);
    });
  }

  /// _patch: apply the optimistic update + the network call. On
  /// failure roll the state back to the prior snapshot so the toggle
  /// in the UI snaps back. Errors surface via the AsyncNotifier
  /// state — UI can present a SnackBar via `state.hasError`.
  Future<void> _patch(
    UserPreferences Function(UserPreferences) optimistic,
    Future<UserPreferences> Function() commit,
  ) async {
    final prev = state.valueOrNull;
    if (prev == null) return;
    state = AsyncData(optimistic(prev));
    try {
      final next = await commit();
      state = AsyncData(next);
    } catch (e, st) {
      state = AsyncData(prev); // roll back optimistic
      state = AsyncError(e, st);
    }
  }
}

final preferencesNotifierProvider =
    AsyncNotifierProvider<PreferencesNotifier, UserPreferences>(
  PreferencesNotifier.new,
);

/// localeProvider — derives the active Locale from the persisted
/// preferences. Defaults to pt-BR while the AsyncNotifier is loading
/// so the MaterialApp boots without a frame of "no locale".
///
/// Wire MaterialApp.locale to this provider and the app rebuilds
/// automatically when the user picks a different language in the
/// settings screen.
///
/// Note: string localization (ARB files / per-locale labels) is its
/// own sprint — flipping the locale today only shifts the value but
/// the visible strings stay pt-BR. The persisted preference is the
/// load-bearing part.
final localeProvider = Provider<Locale>((ref) {
  final prefs = ref.watch(preferencesNotifierProvider);
  final code = prefs.valueOrNull?.locale ?? SupportedLocales.ptBR;
  return _parseLocale(code);
});

Locale _parseLocale(String code) {
  final parts = code.split('-');
  if (parts.length == 2) {
    return Locale(parts[0], parts[1]);
  }
  return Locale(parts.first);
}
