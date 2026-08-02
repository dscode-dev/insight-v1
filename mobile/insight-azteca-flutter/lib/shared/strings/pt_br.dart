/// Centralised pt-BR copy.
///
/// Every visible string in the app lives here. Two reasons:
///   1. Copy auditing happens in one place (legal / brand can read a
///      single file to review tone).
///   2. When EN/ES localisation arrives, this becomes the source the
///      `intl` translator consumes.
///
/// Naming convention: `domain.subdomain.specificThing`.
class S {
  const S._();

  // App
  static const String appName = 'Insight';

  // Auth — WhatsApp-style (phone + OTP + username).
  static const String authPhoneTitle = 'Confirme seu número';
  static const String authPhoneSubtitle =
      'Insight vai te mandar um SMS para confirmar seu número. Qual é o seu DDD e número de telefone?';
  static const String authPhoneCountryLabel = 'País';
  static const String authPhoneCountryBR = 'Brasil';
  static const String authPhoneCountryDial = '+55';
  static const String authPhoneLabel = 'Número de telefone';
  static const String authPhoneHint = '(11) 99999-9999';
  static const String authPhoneFootnote =
      'Ao tocar em Continuar, você confirma que o número informado é seu.';
  static const String authPhoneCta = 'Continuar';

  static const String authOtpTitle = 'Digite o código';
  static const String authOtpSubtitle = 'Enviamos um SMS de 6 dígitos para';
  static const String authOtpResend = 'Reenviar código';
  static const String authOtpResendIn = 'Reenviar em';
  static const String authOtpChangeNumber = 'Trocar número';

  static const String authUsernameTitle = 'Como quer ser chamado?';
  static const String authUsernameSubtitle =
      'Escolha um nome de usuário (só você pode ter) e como aparece pros outros.';
  static const String authUsernameLabel = 'Nome de usuário';
  static const String authDisplayNameLabel = 'Nome de exibição';
  static const String authUsernameCta = 'Finalizar cadastro';

  static const String authErrorGeneric = 'Algo deu errado. Tente novamente.';

  // Home
  static const List<String> composerPlaceholders = [
    'Qual sua leitura desse jogo?',
    'Compartilhe um sinal',
    'Qual time você está acompanhando?',
  ];

  static const String feedEmptyTitle = 'Seu feed ainda está calmo';
  static const String feedEmptyDescription =
      'Quando a comunidade postar uma leitura, ela vai aparecer aqui.';
  static const String offlineTitle = 'Sem conexão';
  static const String offlineDescription =
      'Verifique sua internet e tente novamente.';
  static const String feedErrorTitle = 'Não foi possível carregar o feed';
  static const String feedErrorDescription = 'Tente novamente em alguns instantes.';
  static const String feedEnd = 'Você chegou ao fim por enquanto.';

  static const String pullToRefresh = 'Puxe para atualizar';
  static const String releaseToRefresh = 'Solte para atualizar';
  static const String refreshing = 'Atualizando…';

  // Quick Pulse
  static const String quickPulseLabel = 'Pulse';
  static const String pulseHintLive = 'AO VIVO';
  static const String pulseHintTrending = 'Em alta';
  static const String pulseHintAgent = 'Agente';
  static const String pulseHintCommunity = 'Comunidade';

  // Match embed
  static const String matchStatusLive = 'Ao vivo';
  static const String matchStatusFinished = 'Encerrado';
  static const String matchStatusToday = 'Hoje';

  // Crowd snippet
  static const String confidenceHomeLabel = 'casa';
  static const String confidenceDrawLabel = 'empate';
  static const String confidenceAwayLabel = 'fora';
  static const String peopleLabel = 'pessoas';

  // Bottom nav
  static const String navHome = 'Home';
  static const String navLive = 'Ao vivo';
  static const String navRadar = 'Radar';
  static const String navHub = 'Hub';
  static const String navExplore = 'Explorar';
  static const String navProfile = 'Perfil';

  // Profile
  static const String profileLogout = 'Sair';
  static const String profileLogoutConfirmTitle = 'Sair da conta?';
  static const String profileLogoutConfirmDescription =
      'Você precisará entrar de novo da próxima vez.';
  static const String profileLogoutCancel = 'Cancelar';

  // Generic
  static const String retry = 'Tentar de novo';
  static const String loading = 'Carregando…';
  static const String unknownError = 'Algo deu errado.';
}
