import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/logger.dart';
import '../models/auth.dart';
import 'auth_provider.dart';

/// Auth-A.1 — Gateway-orchestrated phone-verification flow state machine.
///
/// Azteca talks only to the Gateway. Gateway selects and calls the upstream
/// phone provider (Supabase now, future providers later), then returns either
/// an Insight session or a registration handoff.
///
/// The two screens (PhoneEntry / OtpVerify) drive this imperatively and
/// `ref.listen` to [AuthFlowState.status] to navigate:
///   * codeSent             → PhoneEntry pushes the OTP screen
///   * registrationRequired → push the Username screen
///   * error                → show [errorMessage]
///   * login                → AuthNotifier flips auth status; router redirects.
enum AuthFlowStatus {
  idle,
  sendingCode,
  codeSent,
  verifying,
  registrationRequired,
  error,
}

class AuthFlowState {
  const AuthFlowState({
    this.status = AuthFlowStatus.idle,
    this.phoneE164,
    this.registrationToken,
    this.errorMessage,
  });

  final AuthFlowStatus status;
  final String? phoneE164;
  final String? registrationToken;
  final String? errorMessage;

  AuthFlowState copyWith({
    AuthFlowStatus? status,
    String? phoneE164,
    String? registrationToken,
    String? errorMessage,
    bool clearError = false,
    bool clearRegistrationToken = false,
  }) =>
      AuthFlowState(
        status: status ?? this.status,
        phoneE164: phoneE164 ?? this.phoneE164,
        registrationToken: clearRegistrationToken
            ? null
            : (registrationToken ?? this.registrationToken),
        errorMessage: clearError ? null : (errorMessage ?? this.errorMessage),
      );

  static const empty = AuthFlowState();
}

class AuthFlowNotifier extends Notifier<AuthFlowState> {
  @override
  AuthFlowState build() => AuthFlowState.empty;

  void setPhone(String phoneE164) {
    state = state.copyWith(phoneE164: phoneE164);
  }

  void setRegistrationToken(String token) {
    state = state.copyWith(registrationToken: token);
  }

  /// Step 1: ask Gateway to dispatch the SMS through its configured provider.
  Future<void> startPhoneVerification(String phoneE164) async {
    state = AuthFlowState(
      status: AuthFlowStatus.sendingCode,
      phoneE164: phoneE164,
    );
    try {
      await ref.read(authProvider.notifier).requestOtp(
            RequestOtpRequest(phone: phoneE164),
          );
      state = state.copyWith(status: AuthFlowStatus.codeSent, clearError: true);
    } catch (e) {
      L.w('auth_flow', 'phone_request_failed', data: e);
      final msg = ref.read(authProvider).errorMessage ??
          'Não foi possível enviar o código. Tente novamente.';
      state = state.copyWith(status: AuthFlowStatus.error, errorMessage: msg);
    }
  }

  /// Step 2: ask Gateway to verify the user-entered SMS [code].
  Future<void> confirmSmsCode(String code) async {
    final phone = state.phoneE164;
    if (phone == null) {
      state = state.copyWith(
        status: AuthFlowStatus.error,
        errorMessage: 'Sessão de verificação expirou. Reenvie o código.',
      );
      return;
    }
    state = state.copyWith(status: AuthFlowStatus.verifying, clearError: true);
    try {
      final res = await ref.read(authProvider.notifier).verifyOtp(
            VerifyOtpRequest(phone: phone, code: code),
          );
      if (res.status == 'registration_required' && res.registration != null) {
        state = state.copyWith(
          status: AuthFlowStatus.registrationRequired,
          registrationToken: res.registration!.registrationToken,
          clearError: true,
        );
      }
      // status == "ok" -> AuthNotifier accepted the session; the router
      // redirect flips to /home.
    } catch (e) {
      L.w('auth_flow', 'phone_verify_failed', data: e);
      // AuthNotifier already mapped the Gateway error to pt-BR copy.
      final msg = ref.read(authProvider).errorMessage ??
          'Não foi possível concluir a verificação.';
      state = state.copyWith(status: AuthFlowStatus.error, errorMessage: msg);
    }
  }

  void reset() {
    state = AuthFlowState.empty;
  }
}

final authFlowProvider =
    NotifierProvider<AuthFlowNotifier, AuthFlowState>(AuthFlowNotifier.new);
