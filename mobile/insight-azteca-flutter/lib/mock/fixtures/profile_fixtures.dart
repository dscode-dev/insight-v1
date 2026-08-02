import '../../models/profile.dart';

DateTime _dAgo(int d) => DateTime.now().subtract(Duration(days: d));
DateTime _hAgo(int h) => DateTime.now().subtract(Duration(hours: h));

ProfileBundle kProfileBundle() => ProfileBundle(
      stats: const UserStats(
        reputation: 78,
        posts: 142,
        signals: 64,
        accuracy: 0.71,
      ),
      badges: [
        UserBadge(
          id: 'b_001',
          label: 'Primeira leitura',
          description: 'Publicou sua primeira leitura.',
          emoji: '🎯',
          earnedAt: _dAgo(34),
        ),
        UserBadge(
          id: 'b_002',
          label: 'Sequência de 7',
          description: '7 sinais consecutivos com acerto.',
          emoji: '🔥',
          earnedAt: _dAgo(12),
        ),
        UserBadge(
          id: 'b_003',
          label: 'Antecipou o mercado',
          description: 'Sinal antes do movimento de 5%+ de odd.',
          emoji: '📈',
          earnedAt: _dAgo(5),
        ),
        UserBadge(
          id: 'b_004',
          label: 'Comunidade ativa',
          description: '50+ interações no Hub neste mês.',
          emoji: '💬',
          earnedAt: _dAgo(2),
        ),
      ],
      activity: [
        ProfileActivity(
          id: 'a_001',
          kind: ProfileActivityKind.signal,
          title: 'Sinal forte em LIV × MCI',
          body: 'Under 2.5 — base estatística + leitura tática.',
          ts: _hAgo(2),
        ),
        ProfileActivity(
          id: 'a_002',
          kind: ProfileActivityKind.post,
          title: 'Leitura em PAL × FLA',
          body: 'Palmeiras perdeu intensidade após os 60…',
          ts: _hAgo(6),
        ),
        ProfileActivity(
          id: 'a_003',
          kind: ProfileActivityKind.reply,
          title: 'Resposta em #tatica',
          body: 'Concordo com a leitura — a dispersão entre casas…',
          ts: _hAgo(11),
        ),
        ProfileActivity(
          id: 'a_004',
          kind: ProfileActivityKind.badgeEarned,
          title: 'Antecipou o mercado',
          body: 'Você ganhou uma nova insígnia.',
          ts: _dAgo(5),
        ),
      ],
    );
