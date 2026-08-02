import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Secure persistence for the JWT pair returned by Gateway.
///
/// Replaces the Next.js `localStorage` approach (XSS-exposed). On iOS this
/// uses Keychain, on Android the EncryptedSharedPreferences-backed store.
class TokenStorage {
  TokenStorage({FlutterSecureStorage? backend})
      : _store = backend ?? const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
              iOptions: IOSOptions(
                accessibility: KeychainAccessibility.first_unlock,
              ),
            );

  final FlutterSecureStorage _store;

  static const _kAccess = 'insight.token.access';
  static const _kRefresh = 'insight.token.refresh';
  static const _kAccessExp = 'insight.token.access_expires_at';

  Future<({String? access, String? refresh, DateTime? accessExpiresAt})> read() async {
    final access = await _store.read(key: _kAccess);
    final refresh = await _store.read(key: _kRefresh);
    final expStr = await _store.read(key: _kAccessExp);
    final exp = expStr == null ? null : DateTime.tryParse(expStr);
    return (access: access, refresh: refresh, accessExpiresAt: exp);
  }

  Future<void> write({
    required String access,
    required String refresh,
    DateTime? accessExpiresAt,
  }) async {
    await _store.write(key: _kAccess, value: access);
    await _store.write(key: _kRefresh, value: refresh);
    if (accessExpiresAt != null) {
      await _store.write(
        key: _kAccessExp,
        value: accessExpiresAt.toUtc().toIso8601String(),
      );
    } else {
      await _store.delete(key: _kAccessExp);
    }
  }

  Future<void> clear() async {
    await _store.delete(key: _kAccess);
    await _store.delete(key: _kRefresh);
    await _store.delete(key: _kAccessExp);
  }
}
