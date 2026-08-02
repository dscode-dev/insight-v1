import 'package:freezed_annotation/freezed_annotation.dart';

part 'auth.freezed.dart';
part 'auth.g.dart';

/// JWT pair returned by Gateway `/v1/auth/otp/verify`,
/// `/v1/auth/register`, and `/v1/auth/refresh`.
@freezed
class Tokens with _$Tokens {
  const factory Tokens({
    required String accessToken,
    required String refreshToken,
    String? userId,
    DateTime? accessExpiresAt,
  }) = _Tokens;

  factory Tokens.fromJson(Map<String, dynamic> json) => _$TokensFromJson(json);
}

/// User identity payload. `phoneE164` is the durable identifier in V1
/// (WhatsApp-style auth); username can change later.
@freezed
class AuthUser with _$AuthUser {
  const factory AuthUser({
    required String id,
    required String username,
    required String displayName,
    String? accentColor,
    String? phoneE164,
    // Sprint C — full URL of the uploaded avatar. Null means the
    // client should render the initials+accent fallback.
    String? avatarUrl,
  }) = _AuthUser;

  factory AuthUser.fromJson(Map<String, dynamic> json) =>
      _$AuthUserFromJson(json);
}

// ---- OTP request/response payloads ----------------------------------------

/// POST /v1/auth/otp/request {phone}. Backend normalizes the phone to
/// E.164 — we send whatever the user typed.
@freezed
class RequestOtpRequest with _$RequestOtpRequest {
  const factory RequestOtpRequest({required String phone}) = _RequestOtpRequest;

  factory RequestOtpRequest.fromJson(Map<String, dynamic> json) =>
      _$RequestOtpRequestFromJson(json);
}

/// POST /v1/auth/otp/verify {phone, code}.
@freezed
class VerifyOtpRequest with _$VerifyOtpRequest {
  const factory VerifyOtpRequest({
    required String phone,
    required String code,
  }) = _VerifyOtpRequest;

  factory VerifyOtpRequest.fromJson(Map<String, dynamic> json) =>
      _$VerifyOtpRequestFromJson(json);
}

/// Handoff payload returned when /otp/verify succeeds but the phone
/// has no user yet. Carries the short-lived registration token the
/// client must send to /register.
@freezed
class RegistrationHandoff with _$RegistrationHandoff {
  const factory RegistrationHandoff({
    required String registrationToken,
    required int registrationTtlSeconds,
  }) = _RegistrationHandoff;

  factory RegistrationHandoff.fromJson(Map<String, dynamic> json) =>
      _$RegistrationHandoffFromJson(json);
}

/// Discriminated-union response from /v1/auth/otp/verify.
///   * `status == "ok"`                    → `tokens` populated (login)
///   * `status == "registration_required"` → `registration` populated
@freezed
class VerifyOtpResponse with _$VerifyOtpResponse {
  const factory VerifyOtpResponse({
    required String status,
    Tokens? tokens,
    RegistrationHandoff? registration,
    AuthUser? user,
  }) = _VerifyOtpResponse;

  factory VerifyOtpResponse.fromJson(Map<String, dynamic> json) =>
      _$VerifyOtpResponseFromJson(json);
}

/// POST /v1/auth/register payload.
@freezed
class CompleteRegistrationRequest with _$CompleteRegistrationRequest {
  const factory CompleteRegistrationRequest({
    required String registrationToken,
    required String username,
    required String displayName,
    String? accentColor,
  }) = _CompleteRegistrationRequest;

  factory CompleteRegistrationRequest.fromJson(Map<String, dynamic> json) =>
      _$CompleteRegistrationRequestFromJson(json);
}

/// Composite response from /register and /otp/verify (login path).
/// Gateway returns tokens directly without a user object in V1; the
/// notifier hydrates a placeholder user until /me lands.
@freezed
class AuthResponse with _$AuthResponse {
  const factory AuthResponse({
    required Tokens tokens,
    required AuthUser user,
  }) = _AuthResponse;

  factory AuthResponse.fromJson(Map<String, dynamic> json) =>
      _$AuthResponseFromJson(json);
}

/// Local auth lifecycle. Drives the GoRouter redirect.
enum AuthStatus { hydrating, anonymous, authenticated }
