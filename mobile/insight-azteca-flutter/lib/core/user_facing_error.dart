import 'errors.dart';

String userFacingErrorMessage(Object error) {
  if (error is ValidationException) {
    return _validationMessage(error.message);
  }
  if (error is NetworkException) {
    return 'Verifique sua conexão e tente novamente.';
  }
  if (error is TokenRefreshFailedException) {
    return 'Sua sessão expirou. Entre novamente.';
  }
  if (error is GatewayException) {
    return _gatewayMessage(error);
  }
  final raw = error.toString().toLowerCase();
  if (raw.contains('network') ||
      raw.contains('connection') ||
      raw.contains('socket')) {
    return 'Verifique sua conexão e tente novamente.';
  }
  if (raw.contains('timeout')) {
    return 'Tempo esgotado. Tente novamente.';
  }
  return 'Algo não saiu como esperado. Tente novamente.';
}

String _validationMessage(String code) {
  switch (code) {
    case 'invalid_phone':
      return 'Número de telefone inválido.';
    case 'otp_invalid_or_expired':
      return 'Código incorreto ou expirado.';
    case 'invalid_registration_token':
      return 'Sessão de cadastro expirada. Comece de novo.';
    case 'unsupported_media_type':
      return 'Formato não aceito. Use JPG, PNG ou WebP.';
    default:
      return 'Algo não saiu como esperado. Tente novamente.';
  }
}

String _gatewayMessage(GatewayException error) {
  final code = error.detail ?? error.message;
  switch (code) {
    case 'invalid_request':
    case 'invalid_json':
    case 'invalid_json_body':
      return 'Algo não saiu como esperado. Tente novamente.';
    case 'network_error':
      return 'Verifique sua conexão e tente novamente.';
    case 'invalid_phone':
      return 'Número de telefone inválido.';
    case 'otp_invalid_or_expired':
      return 'Código incorreto ou expirado.';
    case 'otp_expired':
      return 'O código expirou. Peça um novo.';
    case 'otp_resend_cooldown':
      return 'Aguarde um momento antes de pedir outro código.';
    case 'username_taken':
      return 'Esse nome de usuário já está em uso.';
    case 'terms_not_accepted':
    case 'legal_acceptance_required':
      return 'Aceite os documentos legais para continuar.';
    case 'payload_too_large':
      return 'Imagem grande demais. Escolha outra.';
    case 'unsupported_media_type':
      return 'Formato não aceito. Use JPG, PNG ou WebP.';
    case 'upload_failed':
      return 'Não foi possível atualizar sua foto agora. Tente novamente em alguns instantes.';
    case 'sms_dispatch_failed':
    case 'phone_provider_not_configured':
      return 'Não conseguimos enviar o SMS agora. Tente em alguns minutos.';
  }
  if (error.isRateLimited) {
    return 'Muitas tentativas agora. Aguarde um pouco e tente novamente.';
  }
  if (error.isServerError) {
    return 'Não foi possível concluir agora. Tente novamente em alguns instantes.';
  }
  if (error.isNotFound) {
    return 'Não encontramos esse conteúdo.';
  }
  if (error.isUnauthorized) {
    return 'Sua sessão expirou. Entre novamente.';
  }
  return 'Algo não saiu como esperado. Tente novamente.';
}
