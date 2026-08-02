import '../../models/notifications.dart';

DateTime _minAgo(int m) => DateTime.now().subtract(Duration(minutes: m));
DateTime _hAgo(int h) => DateTime.now().subtract(Duration(hours: h));

List<AppNotification> kNotifications() => [
      AppNotification(
        id: 'n_001',
        kind: NotificationKind.matchEvent,
        title: 'Gol — Liverpool 1 × 0 Manchester City',
        body: 'Salah aos 32\' do primeiro tempo. Pressão alta confirmou.',
        ts: _minAgo(2),
        deeplink: '/live/match/m_liv_mci',
      ),
      AppNotification(
        id: 'n_002',
        kind: NotificationKind.agentInsight,
        title: 'Pulse: janela alta de gol em LIV × MCI',
        body: 'Pressão cruzou 72% pelo lado mandante nos últimos 6 minutos.',
        ts: _minAgo(7),
        deeplink: '/live/match/m_liv_mci',
      ),
      AppNotification(
        id: 'n_003',
        kind: NotificationKind.signalReply,
        title: 'Marina Aragão respondeu seu sinal',
        body: '"Concordo, mas a janela parece mais curta…"',
        ts: _minAgo(14),
      ),
      AppNotification(
        id: 'n_004',
        kind: NotificationKind.communityMention,
        title: 'Você foi mencionado em #tatica',
        body: 'Henrique Tavares te marcou em "Mudança Liverpool 4-3-3".',
        ts: _minAgo(28),
        deeplink: '/hub/community/c_tatica',
        read: true,
      ),
      AppNotification(
        id: 'n_005',
        kind: NotificationKind.matchEvent,
        title: 'Cartão amarelo — PAL × FLA',
        body: 'Endrick aos 48\'. Tensão crescente no segundo tempo.',
        ts: _hAgo(1),
        deeplink: '/live/match/m_pal_fla',
        read: true,
      ),
      AppNotification(
        id: 'n_006',
        kind: NotificationKind.systemUpdate,
        title: 'Nova versão disponível',
        body: 'Atualize para receber as melhorias de Radar e Hub.',
        ts: _hAgo(3),
        read: true,
      ),
    ];
