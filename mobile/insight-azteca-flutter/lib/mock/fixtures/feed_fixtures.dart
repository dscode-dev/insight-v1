import '../../models/feed.dart';
import '../../models/match.dart';

DateTime _minAgo(int m) => DateTime.now().subtract(Duration(minutes: m));
DateTime _hAgo(int h) => DateTime.now().subtract(Duration(hours: h));

const _kAuthorLucas = FeedAuthor(
  id: 'u_lucas',
  displayName: 'Lucas Scout',
  username: 'lucas.scout',
  initials: 'LS',
  accentColor: '#5BA8FF',
  isSystem: false,
  reputation: 78,
  tier: 'analyst',
);
const _kAuthorMarina = FeedAuthor(
  id: 'u_marina',
  displayName: 'Marina Aragão',
  username: 'marina.aragao',
  initials: 'MA',
  accentColor: '#F59E0B',
  isSystem: false,
  reputation: 64,
  tier: 'scout',
);
const _kAuthorSouth = FeedAuthor(
  id: 'u_south_sharp',
  displayName: 'South Sharp',
  username: 'south.sharp',
  initials: 'SS',
  accentColor: '#A78BFA',
  isSystem: false,
  reputation: 71,
  tier: 'analyst',
);
const _kAuthorAnalystLab = FeedAuthor(
  id: 'u_analyst_lab',
  displayName: 'Analyst Lab',
  username: 'analyst.lab',
  initials: 'AL',
  accentColor: '#34D399',
  isSystem: false,
  reputation: 91,
  tier: 'oracle',
);
const _kAuthorSystem = FeedAuthor(
  id: 'sys_insight',
  displayName: 'Insight',
  initials: 'IN',
  accentColor: '#5BA8FF',
  isSystem: true,
);
FeedAuthor _agentAuthor(
        String id, String name, String initials, String accent) =>
    FeedAuthor(
      id: id,
      displayName: name,
      initials: initials,
      accentColor: accent,
      isSystem: true,
    );

MatchSummary _palFla() => MatchSummary(
      matchId: 'm_pal_fla',
      league: 'Brasileirão',
      home: const MatchTeam(
          short: 'PAL', name: 'Palmeiras', crestColor: '#1B6E3A'),
      away: const MatchTeam(
          short: 'FLA', name: 'Flamengo', crestColor: '#C00C29'),
      status: MatchStatus(
        state: MatchState.live,
        minute: 67,
        period: '2T',
        score: const MatchScore(home: 1, away: 1),
        kickoff: _minAgo(67),
      ),
    );

MatchSummary _livMci() => MatchSummary(
      matchId: 'm_liv_mci',
      league: 'Premier League',
      home: const MatchTeam(
          short: 'LIV', name: 'Liverpool', crestColor: '#B91C1C'),
      away: const MatchTeam(
          short: 'MCI', name: 'Manchester City', crestColor: '#0EA5E9'),
      status: MatchStatus(
        state: MatchState.live,
        minute: 41,
        period: '1T',
        score: const MatchScore(home: 2, away: 1),
        kickoff: _minAgo(41),
      ),
    );

MatchSummary _rmaBar() => MatchSummary(
      matchId: 'm_rma_bar',
      league: 'LaLiga',
      home: const MatchTeam(
          short: 'RMA', name: 'Real Madrid', crestColor: '#E5E7EB'),
      away: const MatchTeam(
          short: 'BAR', name: 'Barcelona', crestColor: '#1E40AF'),
      status: MatchStatus(
        state: MatchState.scheduled,
        kickoff: DateTime.now().add(const Duration(hours: 3)),
      ),
    );

List<FeedPost> kFeedPosts() => [
      FeedPost(
        id: 'p_001',
        kind: FeedPostKind.userOpinion,
        author: _kAuthorLucas,
        body:
            'Palmeiras perdeu intensidade depois dos 60\'. Mercado ainda não absorveu '
            '— a linha do empate está mais larga do que deveria.',
        match: _palFla().copyWith(pills: const [
          IntelligencePill(
              label: '↑ pressão visitante', tone: IntelligencePillTone.signal),
          IntelligencePill(
              label: 'Movimento atrasado', tone: IntelligencePillTone.warning),
        ]),
        crowd: const FeedCrowdSentiment(
          homePct: 0.42,
          drawPct: 0.31,
          awayPct: 0.27,
          participants: 2140,
        ),
        reactions: const FeedReactions(likes: 124, replies: 38, shares: 9),
        replyPreview: const FeedReplyPreview(
          count: 38,
          preview: FeedReplyPreviewBody(
            authorDisplayName: 'Marina Aragão',
            text: 'Concordo. Vi o mesmo na dispersão do consenso.',
          ),
        ),
        ts: _minAgo(4),
      ),
      FeedPost(
        id: 'p_002',
        kind: FeedPostKind.agentInsight,
        author: _agentAuthor('agent_momentum', 'Momentum AI', 'MO', '#EF4444'),
        body: 'Pressão líquida moveu Δ -0.34 nos últimos 6 minutos. '
            'Visitante está virando o jogo.',
        match: _palFla().copyWith(pills: const [
          IntelligencePill(
              label: 'Reversão', tone: IntelligencePillTone.danger),
        ]),
        agent: const FeedAgentMeta(
          id: FeedAgentId.momentum,
          label: 'Momentum AI',
          confidence: 0.78,
          minute: 67,
        ),
        reactions: const FeedReactions(likes: 86, replies: 21, shares: 14),
        ts: _minAgo(6),
      ),
      FeedPost(
        id: 'p_003',
        kind: FeedPostKind.communitySignal,
        author: _kAuthorSouth,
        body:
            '4 tipsters independentes postaram Under 2.5 em ATL × SEV nos últimos '
            '6 minutos. Vale checar antes de entrar.',
        community: const FeedCommunityRef(
          id: 'c_tipsters',
          handle: '#tipsters-br',
          name: 'Tipsters BR',
        ),
        reactions: const FeedReactions(likes: 47, replies: 19, shares: 6),
        replyPreview: const FeedReplyPreview(
          count: 19,
          preview: FeedReplyPreviewBody(
            authorDisplayName: 'Caio Borges',
            text: 'Confirmando. Analyst Lab também postou.',
          ),
        ),
        ts: _minAgo(9),
      ),
      FeedPost(
        id: 'p_004',
        kind: FeedPostKind.agentInsight,
        author: _agentAuthor('agent_stats', 'Stats AI', 'ST', '#22C55E'),
        body:
            'Mercado inverteu favoritismo em PAL × FLA. Odds: casa 2.40 × fora 2.05.',
        match: _palFla().copyWith(pills: const [
          IntelligencePill(
              label: 'Flip de favoritismo', tone: IntelligencePillTone.warning),
        ]),
        agent: const FeedAgentMeta(
          id: FeedAgentId.stats,
          label: 'Stats AI',
          confidence: 0.72,
          minute: 64,
        ),
        reactions: const FeedReactions(likes: 64, replies: 12, shares: 8),
        ts: _minAgo(12),
      ),
      FeedPost(
        id: 'p_005',
        kind: FeedPostKind.matchDiscussion,
        author: _kAuthorMarina,
        body:
            'A maioria está interpretando isso como mudança de momento, não pressão '
            'aleatória. Vale acompanhar os próximos 10 minutos.',
        match: _palFla().copyWith(pills: const [
          IntelligencePill(
              label: '↑ pressão visitante', tone: IntelligencePillTone.signal),
        ]),
        reactions: const FeedReactions(likes: 52, replies: 14, shares: 2),
        likedByMe: true,
        replyPreview: const FeedReplyPreview(
          count: 14,
          preview: FeedReplyPreviewBody(
            authorDisplayName: 'Henrique Tavares',
            text: 'Faz sentido. A dispersão entre casas mostra isso bem.',
          ),
        ),
        ts: _minAgo(18),
      ),
      FeedPost(
        id: 'p_006',
        kind: FeedPostKind.quickAnalysis,
        author: _kAuthorAnalystLab,
        badge: const SignalBadgeData(
            label: 'Análise', tone: SignalBadgeTone.success),
        body:
            'Liverpool × Manchester City — pressão sustentada acima de 0.8 desde '
            'os 35\'. Histórico aponta janela de gol nos próximos 8 minutos em '
            '62% dos casos similares.',
        match: _livMci().copyWith(pills: const [
          IntelligencePill(
              label: '↑ pressão sustentada', tone: IntelligencePillTone.signal),
          IntelligencePill(
              label: 'Janela alta', tone: IntelligencePillTone.success),
        ]),
        crowd: const FeedCrowdSentiment(
          homePct: 0.58,
          drawPct: 0.22,
          awayPct: 0.20,
          participants: 3120,
        ),
        reactions: const FeedReactions(likes: 287, replies: 71, shares: 33),
        replyPreview: const FeedReplyPreview(
          count: 71,
          preview: FeedReplyPreviewBody(
            authorDisplayName: 'Beatriz Lemos',
            text: 'Acompanhando. O xP_home tá em 0.83 agora.',
          ),
        ),
        ts: _minAgo(26),
      ),
      FeedPost(
        id: 'p_007',
        kind: FeedPostKind.agentInsight,
        author: _agentAuthor('agent_scout', 'Scout AI', 'SC', '#F59E0B'),
        body:
            'Mudança tática: 4-3-3 → 4-5-1. Reorganização defensiva na equipe mandante.',
        match: _livMci().copyWith(pills: const [
          IntelligencePill(
              label: 'Mudança tática', tone: IntelligencePillTone.neutral),
        ]),
        agent: const FeedAgentMeta(
          id: FeedAgentId.scout,
          label: 'Scout AI',
          confidence: 0.82,
          minute: 38,
        ),
        reactions: const FeedReactions(likes: 142, replies: 28, shares: 19),
        ts: _minAgo(34),
      ),
      FeedPost(
        id: 'p_008',
        kind: FeedPostKind.systemInsight,
        author: _kAuthorSystem,
        badge: const SignalBadgeData(
            label: 'Insight automático', tone: SignalBadgeTone.info),
        body:
            'Movimento incomum em RMA × BAR: odds do Real caíram 7% em 4 minutos '
            'sem gatilho aparente. Volume concentrado em 6 casas.',
        match: _rmaBar().copyWith(pills: const [
          IntelligencePill(
              label: 'Movimento incomum', tone: IntelligencePillTone.warning),
        ]),
        crowd: const FeedCrowdSentiment(
          homePct: 0.61,
          drawPct: 0.18,
          awayPct: 0.21,
          participants: 1834,
        ),
        reactions: const FeedReactions(likes: 312, replies: 64, shares: 42),
        replyPreview: const FeedReplyPreview(
          count: 64,
          preview: FeedReplyPreviewBody(
            authorDisplayName: 'Análise Coletiva',
            text: 'Steam clássico — dinheiro entrando antes da escalação.',
          ),
        ),
        ts: _minAgo(42),
      ),
      FeedPost(
        id: 'p_009',
        kind: FeedPostKind.agentInsight,
        author: _agentAuthor('agent_pulse', 'Pulse AI', 'PU', '#5BA8FF'),
        body: 'Sentimento em queda: Δ -0.28. '
            'Agregado passou de 0.61 para 0.33 em 10 minutos.',
        match: _palFla().copyWith(pills: const [
          IntelligencePill(
              label: '↓ confiança casa', tone: IntelligencePillTone.danger),
        ]),
        crowd: const FeedCrowdSentiment(
          homePct: 0.33,
          drawPct: 0.34,
          awayPct: 0.33,
          participants: 2210,
          delta: FeedCrowdDelta(side: 'home', pp: -28, windowMinutes: 10),
        ),
        agent: const FeedAgentMeta(
          id: FeedAgentId.pulse,
          label: 'Pulse AI',
          confidence: 0.74,
          minute: 60,
        ),
        reactions: const FeedReactions(likes: 58, replies: 11, shares: 5),
        ts: _minAgo(48),
      ),
      FeedPost(
        id: 'p_010',
        kind: FeedPostKind.marketMovement,
        author: _kAuthorSystem,
        badge: const SignalBadgeData(
            label: 'Movimento de mercado', tone: SignalBadgeTone.warning),
        body:
            'Linha do empate em PAL × FLA comprimiu de 3.20 → 3.05 em 8 casas '
            'simultaneamente. Inconsistente com a métrica atual.',
        match: _palFla().copyWith(pills: const [
          IntelligencePill(
              label: 'Compressão coordenada',
              tone: IntelligencePillTone.warning),
        ]),
        reactions: const FeedReactions(likes: 96, replies: 22, shares: 11),
        ts: _minAgo(56),
      ),
      FeedPost(
        id: 'p_011',
        kind: FeedPostKind.agentInsight,
        author: _agentAuthor('agent_history', 'History AI', 'HI', '#94A3B8'),
        body: 'Primeiro encontro entre PAL e FLA neste estádio desde 2021. '
            'Mandante chega com 7 jogos sem derrota neste palco.',
        match: _palFla().copyWith(pills: const [
          IntelligencePill(
              label: 'Contexto histórico', tone: IntelligencePillTone.neutral),
        ]),
        agent: const FeedAgentMeta(
          id: FeedAgentId.history,
          label: 'History AI',
          confidence: 0.7,
        ),
        reactions: const FeedReactions(likes: 41, replies: 6, shares: 3),
        ts: _hAgo(1),
      ),
      FeedPost(
        id: 'p_012',
        kind: FeedPostKind.signal,
        author: _kAuthorLucas,
        badge: const SignalBadgeData(
            label: 'Sinal forte', tone: SignalBadgeTone.signal),
        body:
            'Entrei em Under 2.5 LIV × MCI — base estatística + leitura tática alinhadas.',
        match: _livMci(),
        reactions: const FeedReactions(likes: 73, replies: 18, shares: 4),
        ts: _hAgo(2),
      ),
    ];
