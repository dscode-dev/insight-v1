// AZTECA-INSIGHTS-A — Sports Intelligence semantic model (presentation layer).
//
// A SMALL, product-facing vocabulary for expressing intelligence truthfully.
// Deliberately NOT one generic "Metric" that can mean anything: a scalar, a
// delta, a probability, a confidence, a comparison, a series and an explanation
// are different claims about the world and must not share a representation (or a
// visual treatment). Each type can only be constructed with the data its claim
// requires — the type system is the first line of defence against fabrication:
//
//   * a delta CANNOT exist without a previous value (no baseline ⇒ no arrow);
//   * a trend CANNOT exist from a single observation (needs ≥2 ordered points);
//   * a probability is bounded 0..1 and is NEVER derived from a confidence;
//   * a confidence is a separate bounded score about an estimate's reliability.
//
// This layer is pure Dart (no widgets, no Flutter deps) so it is unit-testable
// and reusable by Profile, Match Detail, Explore, Live and Radar later. It
// consumes PRODUCT projections only — never Atlas/Explorer internals.

import 'package:flutter/foundation.dart';

/// How fresh a value is. Categories are only assigned when the producing
/// contract actually carries a timestamp — never guessed.
enum MetricFreshness {
  /// Backend-authoritative "now" data (e.g. live match state).
  live,

  /// Recently produced; still representative.
  recent,

  /// Known to be old enough that the user should read it as historical.
  stale,

  /// Explicitly a historical/aggregate value (e.g. lifetime totals).
  historical,

  /// The contract carries no timestamp — we do NOT invent one.
  unknown,
}

/// Direction of a change. `unknown` is a first-class outcome: with no baseline
/// there is no direction, and the UI must render no arrow.
enum MetricDirection { up, down, stable, unknown }

/// Whether "up" is good, bad, or neutral for this metric. Never assumed — the
/// caller states it, because e.g. "conceded goals up" is not an improvement.
enum MetricPolarity { higherIsBetter, lowerIsBetter, neutral }

/// A single scalar observation. The most common (and most honest) claim.
@immutable
class MetricValue {
  const MetricValue({
    required this.label,
    required this.value,
    this.unit,
    this.formattedValue,
    this.freshness = MetricFreshness.unknown,
  });

  final String label;
  final num value;

  /// e.g. '%', 'pts', 'min'. Null when the value is a bare count.
  final String? unit;

  /// Locale-formatted display string when the caller already has one; the UI
  /// falls back to a locale-aware format when null.
  final String? formattedValue;

  final MetricFreshness freshness;
}

/// A change between two REAL observations. Construction requires both values —
/// there is deliberately no way to build a delta without a baseline.
@immutable
class MetricDelta {
  const MetricDelta({
    required this.label,
    required this.current,
    required this.previous,
    this.unit,
    this.polarity = MetricPolarity.neutral,
    this.freshness = MetricFreshness.unknown,
  });

  final String label;
  final num current;
  final num previous;
  final String? unit;
  final MetricPolarity polarity;
  final MetricFreshness freshness;

  num get absoluteDelta => current - previous;

  /// Null when the baseline is zero — a percentage change from zero is
  /// undefined, and we never render a fabricated ∞/100%.
  double? get percentageDelta {
    if (previous == 0) return null;
    return (current - previous) / previous.abs() * 100;
  }

  MetricDirection get direction {
    final d = absoluteDelta;
    if (d == 0) return MetricDirection.stable;
    return d > 0 ? MetricDirection.up : MetricDirection.down;
  }

  /// True when the movement is favourable given the metric's polarity. Null for
  /// neutral metrics (no value judgement is implied).
  bool? get isFavourable => switch (polarity) {
        MetricPolarity.neutral => null,
        MetricPolarity.higherIsBetter => direction == MetricDirection.up,
        MetricPolarity.lowerIsBetter => direction == MetricDirection.down,
      };
}

/// A bounded probability (0..1) about an outcome. NEVER produced from a
/// confidence score. Asserts its own bounds — an out-of-range probability is a
/// contract bug, not something to clamp silently.
@immutable
class ProbabilityMetric {
  const ProbabilityMetric({
    required this.label,
    required this.probability,
    this.confidence,
    this.explanation,
    this.freshness = MetricFreshness.unknown,
  }) : assert(probability >= 0 && probability <= 1,
            'probability must be 0..1 — got $probability');

  final String label;
  final double probability;

  /// OPTIONAL and SEPARATE: how reliable this estimate is. Rendered distinctly
  /// from the probability itself.
  final ConfidenceMetric? confidence;

  final InsightExplanation? explanation;
  final MetricFreshness freshness;

  int get percent => (probability * 100).round();
}

/// Confidence band. Thresholds are a PRESENTATION decision applied to a
/// backend-provided score; they never turn a confidence into a probability.
enum ConfidenceBand { low, medium, high }

/// How reliable an estimate is (0..1). A different claim from probability.
@immutable
class ConfidenceMetric {
  const ConfidenceMetric({
    required this.score,
    this.explanation,
    this.hasEvidence = false,
  }) : assert(score >= 0 && score <= 1, 'confidence must be 0..1 — got $score');

  final double score;
  final InsightExplanation? explanation;

  /// Whether the producing contract supplied supporting evidence.
  final bool hasEvidence;

  ConfidenceBand get band {
    if (score >= 0.75) return ConfidenceBand.high;
    if (score >= 0.45) return ConfidenceBand.medium;
    return ConfidenceBand.low;
  }
}

/// A like-for-like comparison between two entities on ONE metric with ONE unit.
@immutable
class ComparisonMetric {
  const ComparisonMetric({
    required this.label,
    required this.leftLabel,
    required this.rightLabel,
    required this.leftValue,
    required this.rightValue,
    this.unit,
    this.freshness = MetricFreshness.unknown,
  });

  final String label;
  final String leftLabel;
  final String rightLabel;
  final num leftValue;
  final num rightValue;
  final String? unit;
  final MetricFreshness freshness;

  /// left ÷ right. Null when the denominator is zero — a ratio against zero is
  /// meaningless and must not be rendered as a number.
  double? get ratio {
    if (rightValue == 0) return null;
    return leftValue / rightValue;
  }

  /// Share of the total held by the left side (0..1), for a two-sided bar.
  /// Null when both sides are zero (nothing to compare).
  double? get leftShare {
    final total = leftValue + rightValue;
    if (total == 0) return null;
    return leftValue / total;
  }
}

/// One observation in a series.
@immutable
class TrendPoint {
  const TrendPoint({required this.at, required this.value});
  final DateTime at;
  final num value;
}

/// An ordered series. Requires ≥2 points BY CONSTRUCTION: a "trend" from a
/// single scalar is a fabrication, so the type refuses to represent one.
@immutable
class TrendSeries {
  TrendSeries({
    required this.label,
    required List<TrendPoint> points,
    this.unit,
    this.referenceValue,
    this.polarity = MetricPolarity.neutral,
    this.freshness = MetricFreshness.unknown,
  })  : assert(points.length >= 2,
            'a trend needs at least 2 ordered observations — got ${points.length}'),
        points = List<TrendPoint>.unmodifiable(
          List<TrendPoint>.of(points)..sort((a, b) => a.at.compareTo(b.at)),
        );

  final String label;
  final List<TrendPoint> points;
  final String? unit;

  /// Optional baseline/threshold line (e.g. a market average).
  final num? referenceValue;
  final MetricPolarity polarity;
  final MetricFreshness freshness;

  num get first => points.first.value;
  num get last => points.last.value;

  /// Direction across the whole window (last vs first) — a real comparison
  /// between two real observations.
  MetricDirection get direction {
    final d = last - first;
    if (d == 0) return MetricDirection.stable;
    return d > 0 ? MetricDirection.up : MetricDirection.down;
  }

  /// The series as a delta (first → last), reusing the delta semantics.
  MetricDelta get asDelta => MetricDelta(
        label: label,
        current: last,
        previous: first,
        unit: unit,
        polarity: polarity,
        freshness: freshness,
      );
}

/// A statistical distribution bucket.
@immutable
class DistributionBucket {
  const DistributionBucket({required this.label, required this.weight});
  final String label;

  /// Relative weight/probability mass. Non-negative.
  final double weight;
}

/// A distribution over outcomes. Requires ≥2 buckets (a single bucket is not a
/// distribution).
@immutable
class DistributionMetric {
  DistributionMetric({
    required this.label,
    required List<DistributionBucket> buckets,
    this.freshness = MetricFreshness.unknown,
  })  : assert(buckets.length >= 2,
            'a distribution needs at least 2 buckets — got ${buckets.length}'),
        buckets = List<DistributionBucket>.unmodifiable(buckets);

  final String label;
  final List<DistributionBucket> buckets;
  final MetricFreshness freshness;

  double get totalWeight =>
      buckets.fold<double>(0, (sum, b) => sum + b.weight);

  /// Normalized share per bucket (0..1). Empty when total weight is zero.
  List<double> get shares {
    final total = totalWeight;
    if (total <= 0) return const [];
    return buckets.map((b) => b.weight / total).toList(growable: false);
  }
}

/// Where an explanation/metric came from, in PRODUCT terms (never a class name,
/// detector id, or internal pipeline stage).
enum InsightSource { platform, community, market, historical, unknown }

/// A product-language explanation. Deliberately has no field that could carry
/// model internals (no vectors, no detector names, no replay metadata).
@immutable
class InsightExplanation {
  const InsightExplanation({
    required this.summary,
    this.factors = const [],
    this.evidenceSummary,
    this.source = InsightSource.unknown,
    this.freshness = MetricFreshness.unknown,
  });

  /// One product sentence: what changed / why it matters.
  final String summary;

  /// Short human-readable contributing factors (product language only).
  final List<String> factors;

  /// e.g. "Baseado em 12 partidas semelhantes" — a summary, never raw evidence.
  final String? evidenceSummary;

  final InsightSource source;
  final MetricFreshness freshness;
}
