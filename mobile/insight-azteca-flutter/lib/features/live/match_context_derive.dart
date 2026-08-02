import '../../models/live.dart';
import '../../models/match_context.dart';

/// Builds a [MatchContextReading] from the data we already have in
/// [MatchDetail].
///
/// Two derivations:
///   * **Probabilities** — invert the latest 1/X/2 odds (1/o) and
///     normalise the triple so they sum to 1. This is the standard
///     "implied probability" without overround removal — accurate
///     enough for a social read; no betting copy attached.
///   * **Signals** — short pt-BR clauses derived from the pressure
///     timeline (rising / falling / stable) and an odds-movement check
///     (compressing favourite). Never numeric.
///
/// Pure function — easy to unit-test once we add tests for it.
MatchContextReading deriveMatchContextReading(MatchDetail detail) {
  final probs = _probabilitiesFromOdds(detail.oddsTimeline);
  final signals = _signalsFrom(detail);
  return MatchContextReading(
    matchId: detail.summary.matchId,
    probabilities: probs,
    signals: signals,
  );
}

MatchProbabilities? _probabilitiesFromOdds(List<OddsPoint> timeline) {
  if (timeline.isEmpty) return null;
  final last = timeline.last;
  // Guard against zero/negative odds — they'd blow up the inversion
  // and a bad upstream tick shouldn't crash the screen.
  if (last.home <= 0 || last.draw <= 0 || last.away <= 0) return null;
  final invH = 1 / last.home;
  final invD = 1 / last.draw;
  final invA = 1 / last.away;
  final z = invH + invD + invA;
  if (z <= 0) return null;
  return MatchProbabilities(
    home: invH / z,
    draw: invD / z,
    away: invA / z,
  );
}

List<MatchContextSignal> _signalsFrom(MatchDetail detail) {
  final out = <MatchContextSignal>[];
  final pressure = detail.pressureTimeline;
  if (pressure.length >= 3) {
    final tail = pressure.sublist(pressure.length - 3);
    final delta = tail.last.value - tail.first.value;
    if (delta >= 0.10) {
      out.add(const MatchContextSignal(
        label: 'Pressão crescente',
        direction: SignalDirection.up,
      ));
    } else if (delta <= -0.10) {
      out.add(const MatchContextSignal(
        label: 'Pressão recuando',
        direction: SignalDirection.down,
      ));
    } else if (tail.last.value >= 0.6) {
      out.add(const MatchContextSignal(
        label: 'Pressão alta e estável',
        direction: SignalDirection.neutral,
      ));
    }
  }

  // Compressing favourite — favourite's odd dropped sharply over the
  // window. Read as "movimento incomum detectado", matching the spec.
  final odds = detail.oddsTimeline;
  if (odds.length >= 2) {
    final first = odds.first;
    final last = odds.last;
    bool compressed(double a, double b) =>
        a > 0 && b > 0 && (a - b) / a > 0.05;
    if (compressed(first.home, last.home) ||
        compressed(first.draw, last.draw) ||
        compressed(first.away, last.away)) {
      out.add(const MatchContextSignal(
        label: 'Movimento incomum detectado',
        direction: SignalDirection.neutral,
      ));
    }
  }

  return out;
}
