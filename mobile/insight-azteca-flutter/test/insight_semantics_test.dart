// AZTECA-INSIGHTS-A — semantic model truthfulness.
// These tests exist to make FABRICATION structurally impossible.
import 'package:flutter_test/flutter_test.dart';
import 'package:azteca/features/insights/model/insight_metrics.dart';

void main() {
  group('MetricDelta — needs a real baseline', () {
    test('positive delta: direction up, signed percentage', () {
      const d = MetricDelta(label: 'Pressão', current: 108, previous: 100);
      expect(d.direction, MetricDirection.up);
      expect(d.absoluteDelta, 8);
      expect(d.percentageDelta, closeTo(8.0, 0.001));
    });
    test('negative delta: direction down', () {
      const d = MetricDelta(label: 'Pressão', current: 90, previous: 100);
      expect(d.direction, MetricDirection.down);
      expect(d.percentageDelta, closeTo(-10.0, 0.001));
    });
    test('stable delta', () {
      const d = MetricDelta(label: 'x', current: 5, previous: 5);
      expect(d.direction, MetricDirection.stable);
      expect(d.absoluteDelta, 0);
    });
    test('zero baseline → percentage is NULL (never a fabricated ∞/100%)', () {
      const d = MetricDelta(label: 'x', current: 7, previous: 0);
      expect(d.percentageDelta, isNull);
      expect(d.absoluteDelta, 7); // absolute is still honest
    });
    test('polarity decides favourability; neutral makes no judgement', () {
      const up = MetricDelta(
          label: 'x', current: 2, previous: 1, polarity: MetricPolarity.higherIsBetter);
      const conceded = MetricDelta(
          label: 'sofridos', current: 2, previous: 1, polarity: MetricPolarity.lowerIsBetter);
      const neutral = MetricDelta(label: 'x', current: 2, previous: 1);
      expect(up.isFavourable, isTrue);
      expect(conceded.isFavourable, isFalse); // "up" is NOT always good
      expect(neutral.isFavourable, isNull);
    });
  });

  group('ProbabilityMetric — bounded, never from confidence', () {
    test('bounds enforced', () {
      expect(() => ProbabilityMetric(label: 'x', probability: 1.4), throwsAssertionError);
      expect(() => ProbabilityMetric(label: 'x', probability: -0.1), throwsAssertionError);
    });
    test('percent rounds honestly', () {
      expect(const ProbabilityMetric(label: 'x', probability: 0.641).percent, 64);
    });
    test('confidence is a SEPARATE optional claim, not the probability', () {
      const p = ProbabilityMetric(
        label: 'Vitória A',
        probability: 0.64,
        confidence: ConfidenceMetric(score: 0.82),
      );
      expect(p.probability, 0.64);
      expect(p.confidence!.score, 0.82);
      expect(p.confidence!.band, ConfidenceBand.high);
      // The two values are independent — no derivation between them.
      expect(p.probability, isNot(equals(p.confidence!.score)));
    });
  });

  group('ConfidenceMetric — bounded bands', () {
    test('bounds enforced', () {
      expect(() => ConfidenceMetric(score: 1.2), throwsAssertionError);
    });
    test('bands', () {
      expect(const ConfidenceMetric(score: 0.9).band, ConfidenceBand.high);
      expect(const ConfidenceMetric(score: 0.5).band, ConfidenceBand.medium);
      expect(const ConfidenceMetric(score: 0.2).band, ConfidenceBand.low);
    });
  });

  group('ComparisonMetric — meaningful denominators only', () {
    test('ratio + share', () {
      const c = ComparisonMetric(
          label: 'Pressão', leftLabel: 'A', rightLabel: 'B', leftValue: 71, rightValue: 50);
      expect(c.ratio, closeTo(1.42, 0.001));
      expect(c.leftShare, closeTo(71 / 121, 0.001));
    });
    test('zero denominator → ratio NULL (no meaningless number)', () {
      const c = ComparisonMetric(
          label: 'x', leftLabel: 'A', rightLabel: 'B', leftValue: 5, rightValue: 0);
      expect(c.ratio, isNull);
    });
    test('nothing to compare → share NULL (UI renders an honest dash)', () {
      const c = ComparisonMetric(
          label: 'x', leftLabel: 'A', rightLabel: 'B', leftValue: 0, rightValue: 0);
      expect(c.leftShare, isNull);
    });
  });

  group('TrendSeries — a trend cannot be faked from a scalar', () {
    final t0 = DateTime.utc(2026, 1, 1, 10);
    test('single observation is REJECTED by construction', () {
      expect(
        () => TrendSeries(label: 'momentum', points: [TrendPoint(at: t0, value: 1)]),
        throwsAssertionError,
      );
    });
    test('empty series is REJECTED', () {
      expect(() => TrendSeries(label: 'x', points: const []), throwsAssertionError);
    });
    test('orders points and derives a real direction', () {
      final s = TrendSeries(label: 'momentum', points: [
        TrendPoint(at: t0.add(const Duration(minutes: 10)), value: 8),
        TrendPoint(at: t0, value: 5),
      ]);
      expect(s.points.first.value, 5); // sorted by time
      expect(s.direction, MetricDirection.up);
      expect(s.asDelta.percentageDelta, closeTo(60.0, 0.001));
    });
  });

  group('DistributionMetric', () {
    test('single bucket is not a distribution', () {
      expect(
        () => DistributionMetric(
            label: 'x', buckets: const [DistributionBucket(label: 'a', weight: 1)]),
        throwsAssertionError,
      );
    });
    test('shares normalize', () {
      final d = DistributionMetric(label: '1X2', buckets: const [
        DistributionBucket(label: '1', weight: 2),
        DistributionBucket(label: 'X', weight: 1),
        DistributionBucket(label: '2', weight: 1),
      ]);
      expect(d.shares, [0.5, 0.25, 0.25]);
    });
  });

  group('Freshness + explanation honesty', () {
    test('freshness defaults to unknown (never guessed)', () {
      const m = MetricValue(label: 'Publicações', value: 12);
      expect(m.freshness, MetricFreshness.unknown);
    });
    test('explanation carries product language only (no internals field exists)', () {
      const e = InsightExplanation(
        summary: 'Pressão de mercado subiu após movimento sustentado.',
        evidenceSummary: 'Baseado em 12 partidas semelhantes',
        source: InsightSource.market,
      );
      expect(e.summary, isNotEmpty);
      expect(e.source, InsightSource.market);
      // There is deliberately no API to attach vectors/detector names/replay data.
    });
  });
}
