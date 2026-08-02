import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/logger.dart';
import '../core/user_facing_error.dart';
import '../models/auth.dart';
import '../models/social.dart';
import '../services/gateway_client.dart';
import '../services/auth_service.dart';
import '../services/services_providers.dart';
import '../services/social_service.dart';

/// Authentication state machine — WhatsApp-style.
///
///   hydrating → (boot) → anonymous | authenticated
///                ▲                       │
///                └────── logout ─────────┘
///
/// The OTP flow itself lives in screen state + `authFlowProvider`. This
/// notifier owns persisted session state only: tokens + user + the
/// AuthStatus that drives the router redirect.
///
/// Mutations exposed:
///   * `requestOtp(phone)`          — proxy to service
///   * `verifyOtp(phone, code)`     — returns the response so the screen
///     can branch: login (tokens) vs registration_required (handoff)
///   * `completeRegistration(req, phoneE164)` — finishes signup, accepts
///     tokens, plus tells the mock service the phone is now registered.
///   * `logout()`
@immutable
class AuthState {
  const AuthState({
    required this.status,
    this.user,
    this.tokens,
    this.errorMessage,
  });

  final AuthStatus status;
  final AuthUser? user;
  final Tokens? tokens;
  final String? errorMessage;

  bool get isAuthenticated => status == AuthStatus.authenticated;
  bool get isHydrating => status == AuthStatus.hydrating;

  AuthState copyWith({
    AuthStatus? status,
    AuthUser? user,
    Tokens? tokens,
    String? errorMessage,
    bool clearError = false,
    bool clearTokens = false,
    bool clearUser = false,
  }) =>
      AuthState(
        status: status ?? this.status,
        user: clearUser ? null : (user ?? this.user),
        tokens: clearTokens ? null : (tokens ?? this.tokens),
        errorMessage: clearError ? null : (errorMessage ?? this.errorMessage),
      );

  static const AuthState hydrating = AuthState(status: AuthStatus.hydrating);
}

class AuthNotifier extends Notifier<AuthState> {
  @override
  AuthState build() {
    // ignore: discarded_futures
    Future<void>.microtask(hydrate);
    return AuthState.hydrating;
  }

  Future<void> hydrate() async {
    final storage = ref.read(tokenStorageProvider);
    final session = ref.read(gatewaySessionProvider);
    try {
      final stored = await storage.read();
      if (stored.access == null || stored.refresh == null) {
        state = const AuthState(status: AuthStatus.anonymous);
        return;
      }
      final tokens = Tokens(
        accessToken: stored.access!,
        refreshToken: stored.refresh!,
        userId: _userIdFromAccessToken(stored.access!),
        accessExpiresAt: stored.accessExpiresAt,
      );
      session.update(tokens);
      final user = await _hydrateUser(
        tokens,
        fallback: const AuthUser(
          id: 'me',
          username: 'me',
          displayName: 'Você',
        ),
      );
      state = AuthState(
        status: AuthStatus.authenticated,
        tokens: tokens,
        user: user,
      );
    } catch (e, st) {
      L.e('auth', 'hydrate_failed', error: e, stackTrace: st);
      state = const AuthState(status: AuthStatus.anonymous);
    }
  }

  // -- OTP flow --------------------------------------------------------------

  /// Step 1: ask Gateway to send the SMS. Returns void; throws on error
  /// (translated to pt-BR copy via `errorMessage`).
  Future<void> requestOtp(RequestOtpRequest req) async {
    state = state.copyWith(clearError: true);
    try {
      await ref.read(authServiceProvider).requestOtp(req);
    } catch (e) {
      state = state.copyWith(errorMessage: _toMessage(e));
      rethrow;
    }
  }

  /// Step 2: verify the code. Returns the response so the screen branches
  /// on `status`. If the phone existed, tokens are persisted here. If
  /// the phone is new, the caller stashes the registration token + nav.
  Future<VerifyOtpResponse> verifyOtp(VerifyOtpRequest req) async {
    state = state.copyWith(clearError: true);
    try {
      final res = await ref.read(authServiceProvider).verifyOtp(req);
      if (res.status == 'ok' && res.tokens != null) {
        await _accept(
          AuthResponse(
            tokens: res.tokens!,
            user: res.user ??
                AuthUser(
                  id: 'me',
                  username: 'me',
                  displayName: 'Você',
                  phoneE164: req.phone,
                ),
          ),
        );
      }
      return res;
    } catch (e) {
      state = state.copyWith(errorMessage: _toMessage(e));
      rethrow;
    }
  }

  /// Step 3: finishes signup. `phoneE164` is the number the user just
  /// verified — used only to inform the mock service in dev mode so the
  /// next verify of the same phone routes to login.
  Future<void> completeRegistration(
    CompleteRegistrationRequest req, {
    required String phoneE164,
  }) async {
    state = state.copyWith(clearError: true);
    try {
      final res = await ref.read(authServiceProvider).completeRegistration(req);
      final service = ref.read(authServiceProvider);
      if (service is MockAuthService) {
        service.markRegistered(phoneE164);
      }
      await _accept(
        AuthResponse(
          tokens: res.tokens,
          user: res.user.copyWith(phoneE164: phoneE164),
        ),
      );
    } catch (e) {
      state = state.copyWith(errorMessage: _toMessage(e));
      rethrow;
    }
  }

  Future<void> logout() async {
    final storage = ref.read(tokenStorageProvider);
    final session = ref.read(gatewaySessionProvider);

    // Auth-A: revoke the refresh session server-side so the token can't be
    // reused, then drop the local session. Best-effort — a network failure
    // must never trap the user in a logged-in state, so we always clear
    // locally regardless of the call's outcome.
    final refresh = session.tokens?.refreshToken;
    if (refresh != null && refresh.isNotEmpty) {
      try {
        await ref.read(authServiceProvider).logout(refresh);
      } catch (e) {
        L.w('auth', 'logout_revoke_failed', data: e);
      }
    }
    await storage.clear();
    session.update(null);
    state = const AuthState(status: AuthStatus.anonymous);
  }

  Future<void> clearSessionDueToAuthFailure() async {
    await ref.read(tokenStorageProvider).clear();
    ref.read(gatewaySessionProvider).update(null);
    state = const AuthState(status: AuthStatus.anonymous);
  }

  /// Sprint C — patch the in-memory user with a new avatar URL after
  /// a successful upload. The persisted tokens are unchanged; we only
  /// refresh the user profile field other screens read from.
  void updateAvatar(String? avatarUrl) {
    final cur = state.user;
    if (cur == null) return;
    L.i(
      'avatar',
      'avatar.profile.updated',
      data: {'user_id': cur.id, 'has_avatar': avatarUrl?.isNotEmpty == true},
    );
    state = state.copyWith(user: cur.copyWith(avatarUrl: avatarUrl));
  }

  /// AZTECA-PROFILE-B — patch the in-memory user with a new display name after
  /// an authoritative backend confirmation, so every surface that reads identity
  /// (profile header, feed author, comments) reflects the change immediately.
  void updateDisplayName(String displayName) {
    final cur = state.user;
    if (cur == null) return;
    state = state.copyWith(user: cur.copyWith(displayName: displayName));
  }

  Future<void> _accept(AuthResponse res) async {
    final storage = ref.read(tokenStorageProvider);
    final session = ref.read(gatewaySessionProvider);
    await storage.write(
      access: res.tokens.accessToken,
      refresh: res.tokens.refreshToken,
      accessExpiresAt: res.tokens.accessExpiresAt,
    );
    session.update(res.tokens);
    final user = await _hydrateUser(res.tokens, fallback: res.user);
    state = AuthState(
      status: AuthStatus.authenticated,
      user: user,
      tokens: res.tokens,
    );
  }

  Future<AuthUser> _hydrateUser(
    Tokens tokens, {
    required AuthUser fallback,
  }) async {
    final userID = tokens.userId ?? _userIdFromAccessToken(tokens.accessToken);
    if (userID == null || userID.isEmpty || userID == 'me') {
      return fallback;
    }
    try {
      final social = await ref.read(socialApiProvider).getUser(userID);
      if (social.avatarUrl.isNotEmpty) {
        L.i(
          'avatar',
          'avatar.profile.loaded',
          data: {'user_id': userID, 'has_avatar': true},
        );
      }
      return _authUserFromSocial(social, fallback: fallback);
    } catch (e, st) {
      L.w('auth', 'user_profile_hydration_failed',
          data: {'user_id': userID, 'error': e.toString()});
      if (kDebugMode) {
        L.e('auth', 'user_profile_hydration_debug', error: e, stackTrace: st);
      }
      return fallback.id == 'me' ? fallback.copyWith(id: userID) : fallback;
    }
  }

  AuthUser _authUserFromSocial(SocialUserDto user,
      {required AuthUser fallback}) {
    return AuthUser(
      id: user.id.isNotEmpty ? user.id : fallback.id,
      username: user.username.isNotEmpty ? user.username : fallback.username,
      displayName:
          user.displayName.isNotEmpty ? user.displayName : fallback.displayName,
      accentColor:
          user.accentColor.isNotEmpty ? user.accentColor : fallback.accentColor,
      phoneE164: fallback.phoneE164,
      avatarUrl:
          user.avatarUrl.isNotEmpty ? user.avatarUrl : fallback.avatarUrl,
    );
  }

  String? _userIdFromAccessToken(String token) {
    final parts = token.split('.');
    if (parts.length < 2) return null;
    try {
      final normalized = base64Url.normalize(parts[1]);
      final payload = jsonDecode(utf8.decode(base64Url.decode(normalized)));
      if (payload is Map && payload['sub'] is String) {
        return payload['sub'] as String;
      }
    } catch (_) {
      return null;
    }
    return null;
  }

  String _toMessage(Object e) {
    return userFacingErrorMessage(e);
  }
}

final authProvider =
    NotifierProvider<AuthNotifier, AuthState>(AuthNotifier.new);

/// Derived: current AuthStatus only. Cheaper to watch from places that
/// don't need user/tokens (router redirect, splash).
final authStatusProvider = Provider<AuthStatus>(
  (ref) => ref.watch(authProvider.select((s) => s.status)),
);
