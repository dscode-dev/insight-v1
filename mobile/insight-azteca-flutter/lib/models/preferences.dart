// Sprint D — UserPreferences model.
//
// Wire shape matches the gateway BFF
// (internal/interfaces/http/social/preferences.go:PreferencesDTO).
import 'package:freezed_annotation/freezed_annotation.dart';

part 'preferences.freezed.dart';
part 'preferences.g.dart';

@freezed
class UserPreferences with _$UserPreferences {
  const factory UserPreferences({
    required String userId,
    required String locale, // BCP 47 — "pt-BR", "en-US", "es"
    required bool pushEnabled,
    required bool emailEnabled,
    // "daily" | "weekly" | "never" — backed by a CHECK constraint
    // server-side. Use the DigestFrequency helpers to keep callers
    // off the raw strings.
    required String digestFrequency,
    required DateTime updatedAt,
  }) = _UserPreferences;

  factory UserPreferences.fromJson(Map<String, dynamic> json) =>
      _$UserPreferencesFromJson(json);
}

class DigestFrequency {
  const DigestFrequency._();
  static const daily = 'daily';
  static const weekly = 'weekly';
  static const never = 'never';

  static const all = <String>[daily, weekly, never];

  static String labelPtBr(String v) {
    switch (v) {
      case daily:
        return 'Diário';
      case weekly:
        return 'Semanal';
      case never:
        return 'Desativado';
      default:
        return v;
    }
  }
}

class SupportedLocales {
  const SupportedLocales._();
  static const ptBR = 'pt-BR';
  static const enUS = 'en-US';
  static const es = 'es';

  static const all = <String>[ptBR, enUS, es];

  static String label(String code) {
    switch (code) {
      case ptBR:
        return 'Português (Brasil)';
      case enUS:
        return 'English (US)';
      case es:
        return 'Español';
      default:
        return code;
    }
  }
}
