import 'package:dio/dio.dart';

import '../core/errors.dart';
import '../core/legal.dart';
import '../models/auth.dart';
import 'gateway_client.dart';

/// Gateway-owned phone auth service contract.
///
/// Three steps:
///   1. `requestOtp(phone)`               → Gateway asks its provider to send SMS
///   2. `verifyOtp(phone, code)`          → Gateway verifies and returns tokens
///   3. `completeRegistration(payload)`   → tokens (new user signup)
///
/// Plus `refresh(refreshToken)` for long-lived sessions.
///
/// Gateway impl talks to the real gateway; mock impl is pure-Dart for
/// offline UI work. Both throw `InsightException` on failure; the
/// notifier translates to pt-BR copy.
abstract class AuthService {
  /// Returns nothing on success (202 from Gateway). Throws on cooldown,
  /// invalid phone, SMS dispatch failure.
  Future<void> requestOtp(RequestOtpRequest req);

  /// Either returns tokens (existing phone — login) or a registration
  /// handoff token (new phone — caller must follow up with /register).
  Future<VerifyOtpResponse> verifyOtp(VerifyOtpRequest req);

  /// Finishes the signup flow with the username chosen by the user.
  Future<AuthResponse> completeRegistration(CompleteRegistrationRequest req);

  Future<Tokens> refresh(String refreshToken);

  /// Auth-A Part 7/8: revoke the refresh token's server-side session so it can
  /// no longer be refreshed. Idempotent server-side; best-effort client-side
  /// (logout must succeed locally even if the network call fails).
  Future<void> logout(String refreshToken);
}

class GatewayAuthService implements AuthService {
  GatewayAuthService(this._dio);
  final Dio _dio;

  @override
  Future<void> requestOtp(RequestOtpRequest req) async {
    await _dio.postJson(
      '/v1/auth/phone/request',
      body: req.toJson(),
      options: Options(extra: {kSkipAuth: true}),
    );
  }

  @override
  Future<VerifyOtpResponse> verifyOtp(VerifyOtpRequest req) async {
    final body = await _dio.postJson(
      '/v1/auth/phone/verify',
      body: req.toJson(),
      options: Options(extra: {kSkipAuth: true}),
    );
    return VerifyOtpResponse.fromJson(body);
  }

  @override
  Future<void> logout(String refreshToken) async {
    await _dio.postJson(
      '/v1/auth/logout',
      body: {'refresh_token': refreshToken},
      options: Options(extra: {kSkipAuth: true}),
    );
  }

  @override
  Future<AuthResponse> completeRegistration(
    CompleteRegistrationRequest req,
  ) async {
    final body = await _dio.postJson(
      '/v1/auth/register',
      body: {
        ...req.toJson(),
        'accepted_terms_version': kTermsVersion,
        'accepted_privacy_version': kPrivacyVersion,
        'accepted_ugc_policy_version': kUgcPolicyVersion,
      },
      options: Options(extra: {kSkipAuth: true}),
    );
    // Gateway returns just tokens on /register. We hydrate a minimal
    // AuthUser from the request payload (the /me endpoint lands later).
    final tokens = Tokens.fromJson(body);
    return AuthResponse(
      tokens: tokens,
      user: AuthUser(
        id: body['user_id'] as String,
        username: req.username,
        displayName: req.displayName,
        accentColor: req.accentColor,
      ),
    );
  }

  @override
  Future<Tokens> refresh(String refreshToken) async {
    final body = await _dio.postJson(
      '/v1/auth/refresh',
      body: {'refresh_token': refreshToken},
      options: Options(extra: {kSkipAuth: true}),
    );
    return Tokens.fromJson(body);
  }
}

/// Mock auth: accepts any well-formed phone, the OTP "123456" always
/// verifies. First verify of a phone returns the registration handoff;
/// subsequent verifies of the SAME phone return tokens (login path) —
/// mirrors the real backend's branching for demo / offline use.
class MockAuthService implements AuthService {
  MockAuthService();

  static const String _kFakeAccess = 'mock.access.token';
  static const String _kFakeRefresh = 'mock.refresh.token';
  static const String _kMockOtpCode = '123456';
  static const String _kMockRegistrationToken = 'mock.registration.token';

  // Phones that have completed registration. In-process only — survives
  // a single session so the same flow repeats correctly across screens.
  final Set<String> _registeredPhones = <String>{};
  // Phones with a live (unverified) OTP challenge.
  final Set<String> _pendingPhones = <String>{};

  @override
  Future<void> requestOtp(RequestOtpRequest req) async {
    await Future<void>.delayed(const Duration(milliseconds: 250));
    if (req.phone.replaceAll(RegExp(r'[^0-9+]'), '').length < 10) {
      throw const ValidationException('invalid_phone', field: 'phone');
    }
    _pendingPhones.add(_normalize(req.phone));
  }

  @override
  Future<VerifyOtpResponse> verifyOtp(VerifyOtpRequest req) async {
    await Future<void>.delayed(const Duration(milliseconds: 250));
    final phone = _normalize(req.phone);
    if (!_pendingPhones.contains(phone)) {
      throw const ValidationException('otp_invalid_or_expired', field: 'code');
    }
    if (req.code != _kMockOtpCode) {
      throw const ValidationException('otp_invalid_or_expired', field: 'code');
    }
    _pendingPhones.remove(phone);

    if (_registeredPhones.contains(phone)) {
      return VerifyOtpResponse(
        status: 'ok',
        tokens: Tokens(
          accessToken: _kFakeAccess,
          refreshToken: _kFakeRefresh,
          accessExpiresAt: DateTime.now().add(const Duration(minutes: 15)),
        ),
        user: AuthUser(
          id: 'mock-user-id',
          username: 'mock_user',
          displayName: 'Você',
          phoneE164: phone,
        ),
      );
    }
    return const VerifyOtpResponse(
      status: 'registration_required',
      registration: RegistrationHandoff(
        registrationToken: _kMockRegistrationToken,
        registrationTtlSeconds: 600,
      ),
    );
  }

  @override
  Future<AuthResponse> completeRegistration(
    CompleteRegistrationRequest req,
  ) async {
    await Future<void>.delayed(const Duration(milliseconds: 350));
    if (req.registrationToken != _kMockRegistrationToken) {
      throw const ValidationException(
        'invalid_registration_token',
        field: 'registrationToken',
      );
    }
    // The mock token doesn't carry the original phone; the notifier
    // injects the phone separately when accepting the response.
    return AuthResponse(
      tokens: Tokens(
        accessToken: _kFakeAccess,
        refreshToken: _kFakeRefresh,
        accessExpiresAt: DateTime.now().add(const Duration(minutes: 15)),
      ),
      user: AuthUser(
        id: 'mock-user-id',
        username: req.username,
        displayName: req.displayName,
        accentColor: req.accentColor ?? '#5BA8FF',
      ),
    );
  }

  @override
  Future<void> logout(String refreshToken) async {
    await Future<void>.delayed(const Duration(milliseconds: 60));
  }

  /// Internal hook used by the notifier in mock mode to mark a phone
  /// as registered so the next verify flips to the login path.
  void markRegistered(String phoneE164) {
    _registeredPhones.add(_normalize(phoneE164));
  }

  @override
  Future<Tokens> refresh(String refreshToken) async {
    await Future<void>.delayed(const Duration(milliseconds: 120));
    return Tokens(
      accessToken: _kFakeAccess,
      refreshToken: _kFakeRefresh,
      accessExpiresAt: DateTime.now().add(const Duration(minutes: 15)),
    );
  }

  String _normalize(String raw) => raw.replaceAll(RegExp(r'[^0-9+]'), '');
}
