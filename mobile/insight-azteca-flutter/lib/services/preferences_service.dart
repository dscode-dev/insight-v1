// Sprint D — UserPreferences service.
//
// GET  /v1/users/me/preferences
// PUT  /v1/users/me/preferences  body: {locale?, push_enabled?, ...}
//
// All fields on the PUT body are optional — pass only what changes.
// The server applies COALESCE under the hood so absent fields keep
// their persisted value.
import 'package:dio/dio.dart';

import '../models/preferences.dart';

abstract class PreferencesService {
  Future<UserPreferences> get();

  Future<UserPreferences> update({
    String? locale,
    bool? pushEnabled,
    bool? emailEnabled,
    String? digestFrequency,
  });
}

class GatewayPreferencesService implements PreferencesService {
  GatewayPreferencesService(this._dio);
  final Dio _dio;

  @override
  Future<UserPreferences> get() async {
    final r = await _dio.get<Map<String, dynamic>>('/v1/users/me/preferences');
    return UserPreferences.fromJson(r.data ?? const <String, dynamic>{});
  }

  @override
  Future<UserPreferences> update({
    String? locale,
    bool? pushEnabled,
    bool? emailEnabled,
    String? digestFrequency,
  }) async {
    final body = <String, dynamic>{};
    if (locale != null) body['locale'] = locale;
    if (pushEnabled != null) body['push_enabled'] = pushEnabled;
    if (emailEnabled != null) body['email_enabled'] = emailEnabled;
    if (digestFrequency != null) body['digest_frequency'] = digestFrequency;

    final r = await _dio.put<Map<String, dynamic>>(
      '/v1/users/me/preferences',
      data: body,
    );
    return UserPreferences.fromJson(r.data ?? const <String, dynamic>{});
  }
}

/// Mock — in-memory state per session so toggling sticks across
/// settings navigations during design/QA passes.
class MockPreferencesService implements PreferencesService {
  UserPreferences _current = UserPreferences(
    userId: 'mock',
    locale: SupportedLocales.ptBR,
    pushEnabled: false,
    emailEnabled: false,
    digestFrequency: DigestFrequency.daily,
    updatedAt: DateTime.now(),
  );

  @override
  Future<UserPreferences> get() async {
    await Future<void>.delayed(const Duration(milliseconds: 120));
    return _current;
  }

  @override
  Future<UserPreferences> update({
    String? locale,
    bool? pushEnabled,
    bool? emailEnabled,
    String? digestFrequency,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 120));
    _current = _current.copyWith(
      locale: locale ?? _current.locale,
      pushEnabled: pushEnabled ?? _current.pushEnabled,
      emailEnabled: emailEnabled ?? _current.emailEnabled,
      digestFrequency: digestFrequency ?? _current.digestFrequency,
      updatedAt: DateTime.now(),
    );
    return _current;
  }
}
