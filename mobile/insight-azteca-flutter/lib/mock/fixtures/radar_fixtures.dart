import '../../models/match.dart';
import '../../models/radar.dart';
import 'live_fixtures.dart';

DateTime _minAgo(int m) => DateTime.now().subtract(Duration(minutes: m));

RadarBundle kRadarBundle() => RadarBundle(
      trending: kLiveMatches().take(4).map((m) {
        return TrendingMatch(
          summary: m.summary,
          reason: m.summary.status.state.isLive
              ? 'Pressão acima da média'
              : 'Volume alto de leituras',
        );
      }).toList(),
      movements: [
        MarketMovement(
          id: 'mv_001',
          matchId: 'm_pal_fla',
          matchLabel: 'PAL × FLA',
          league: 'Brasileirão',
          direction: MovementDirection.compressing,
          summary: 'Empate 3.20 → 3.05 em 8 casas simultaneamente.',
          magnitude: 0.78,
          ts: _minAgo(6),
        ),
        MarketMovement(
          id: 'mv_002',
          matchId: 'm_rma_bar',
          matchLabel: 'RMA × BAR',
          league: 'LaLiga',
          direction: MovementDirection.compressing,
          summary: 'Vitória do mandante 1.80 → 1.65 em 12 minutos.',
          magnitude: 0.62,
          ts: _minAgo(12),
        ),
        MarketMovement(
          id: 'mv_003',
          matchId: 'm_liv_mci',
          matchLabel: 'LIV × MCI',
          league: 'Premier League',
          direction: MovementDirection.reversal,
          summary: 'Favoritismo trocou de lado em 6 minutos.',
          magnitude: 0.55,
          ts: _minAgo(18),
        ),
      ],
      signals: [
        CommunitySignalCard(
          id: 'cs_001',
          authorDisplayName: 'Lucas Scout',
          authorAccent: '#5BA8FF',
          authorInitials: 'LS',
          body: 'Sustento Under 2.5 — base tática + leitura coletiva alinhadas.',
          matchLabel: 'LIV × MCI',
          confidence: 0.78,
          ts: _minAgo(5),
        ),
        CommunitySignalCard(
          id: 'cs_002',
          authorDisplayName: 'Marina Aragão',
          authorAccent: '#F59E0B',
          authorInitials: 'MA',
          body: 'Visitante virando — pressão crescente nos últimos 6 minutos.',
          matchLabel: 'PAL × FLA',
          confidence: 0.71,
          ts: _minAgo(8),
        ),
        CommunitySignalCard(
          id: 'cs_003',
          authorDisplayName: 'Analyst Lab',
          authorAccent: '#34D399',
          authorInitials: 'AL',
          body: 'Janela alta — histórico apoia gol em 8min.',
          matchLabel: 'LIV × MCI',
          confidence: 0.84,
          ts: _minAgo(14),
        ),
      ],
    );
