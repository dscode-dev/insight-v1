import 'dart:math';

import '../../models/live.dart';
import '../../models/match.dart';

DateTime _minAgo(int m) => DateTime.now().subtract(Duration(minutes: m));
DateTime _hAhead(int h) => DateTime.now().add(Duration(hours: h));

List<LiveMatch> kLiveMatches() => [
      LiveMatch(
        summary: MatchSummary(
          matchId: 'm_pal_fla',
          league: 'Brasileirão',
          home: const MatchTeam(short: 'PAL', name: 'Palmeiras', crestColor: '#1B6E3A'),
          away: const MatchTeam(short: 'FLA', name: 'Flamengo', crestColor: '#C00C29'),
          status: MatchStatus(
            state: MatchState.live,
            minute: 67,
            period: '2T',
            score: const MatchScore(home: 1, away: 1),
            kickoff: _minAgo(67),
          ),
          pills: const [
            IntelligencePill(label: '↑ pressão visitante', tone: IntelligencePillTone.signal),
          ],
        ),
        momentum: -0.34,
        pressure: 0.72,
      ),
      LiveMatch(
        summary: MatchSummary(
          matchId: 'm_liv_mci',
          league: 'Premier League',
          home: const MatchTeam(short: 'LIV', name: 'Liverpool', crestColor: '#B91C1C'),
          away: const MatchTeam(short: 'MCI', name: 'Manchester City', crestColor: '#0EA5E9'),
          status: MatchStatus(
            state: MatchState.live,
            minute: 41,
            period: '1T',
            score: const MatchScore(home: 2, away: 1),
            kickoff: _minAgo(41),
          ),
          pills: const [
            IntelligencePill(label: '↑ pressão sustentada', tone: IntelligencePillTone.signal),
          ],
        ),
        momentum: 0.42,
        pressure: 0.83,
      ),
      LiveMatch(
        summary: MatchSummary(
          matchId: 'm_atl_sev',
          league: 'LaLiga',
          home: const MatchTeam(short: 'ATL', name: 'Atlético', crestColor: '#CC2229'),
          away: const MatchTeam(short: 'SEV', name: 'Sevilla', crestColor: '#D71E26'),
          status: MatchStatus(
            state: MatchState.live,
            minute: 22,
            period: '1T',
            score: const MatchScore(home: 0, away: 0),
            kickoff: _minAgo(22),
          ),
        ),
        momentum: 0.08,
        pressure: 0.35,
      ),
      LiveMatch(
        summary: MatchSummary(
          matchId: 'm_rma_bar',
          league: 'LaLiga',
          home: const MatchTeam(short: 'RMA', name: 'Real Madrid', crestColor: '#E5E7EB'),
          away: const MatchTeam(short: 'BAR', name: 'Barcelona', crestColor: '#1E40AF'),
          status: MatchStatus(
            state: MatchState.scheduled,
            kickoff: _hAhead(3),
          ),
        ),
        momentum: 0.0,
        pressure: 0.0,
      ),
      LiveMatch(
        summary: MatchSummary(
          matchId: 'm_bay_dor',
          league: 'Bundesliga',
          home: const MatchTeam(short: 'BAY', name: 'Bayern', crestColor: '#DC052D'),
          away: const MatchTeam(short: 'DOR', name: 'Dortmund', crestColor: '#FDE100'),
          status: MatchStatus(
            state: MatchState.scheduled,
            kickoff: _hAhead(5),
          ),
        ),
        momentum: 0.0,
        pressure: 0.0,
      ),
    ];

MatchDetail kMatchDetail(String matchId) {
  // Find the live match — fall back to PAL × FLA.
  final live = kLiveMatches().firstWhere(
    (m) => m.summary.matchId == matchId,
    orElse: () => kLiveMatches().first,
  );

  final rng = Random(matchId.hashCode);
  // Synth pressure timeline + odds — small monotone-with-jitter series.
  final now = DateTime.now();
  final pressure = List<TimelinePoint>.generate(
    18,
    (i) => TimelinePoint(
      ts: now.subtract(Duration(minutes: 17 - i)),
      value: (0.3 + (i / 24) + (rng.nextDouble() * 0.2 - 0.1)).clamp(0.0, 1.0),
    ),
  );
  final odds = List<OddsPoint>.generate(12, (i) {
    final j = rng.nextDouble() * 0.05;
    return OddsPoint(
      ts: now.subtract(Duration(minutes: 33 - (i * 3))),
      home: 1.8 + j + (i / 80),
      draw: 3.4 - j - (i / 60),
      away: 4.6 + (j * 2) - (i / 30),
    );
  });

  return MatchDetail(
    summary: live.summary,
    pressureTimeline: pressure,
    oddsTimeline: odds,
    signals: [
      MatchSignal(
        id: 's1',
        source: 'community',
        label: 'Sinal coletivo',
        body: 'Pressão sustentada pelo time da casa.',
        ts: now.subtract(const Duration(minutes: 4)),
      ),
      MatchSignal(
        id: 's2',
        source: 'expert',
        label: 'Análise Lab',
        body: 'Janela alta de gol nos próximos 8 minutos.',
        ts: now.subtract(const Duration(minutes: 11)),
      ),
      MatchSignal(
        id: 's3',
        source: 'model',
        label: 'Magnus',
        body: 'Shock score em 0.82 — banda alta.',
        ts: now.subtract(const Duration(minutes: 18)),
      ),
    ],
  );
}
