// AZTECA-INSIGHTS-A — reusable Sports Intelligence UI primitives.
//
// One coherent visual language for intelligence, reusable across Profile, Match
// Detail, Explore, Live and Radar. Compact sports-data density; no dashboard
// cards, no neon trading-terminal aesthetic; theme-aware; localization-ready.
//
// ACCESSIBILITY CONTRACT (enforced here, not left to callers):
//   * direction is NEVER carried by colour alone — every directional read pairs
//     an ICON (↑/↓/→) + TEXT with the optional colour;
//   * every primitive exposes a Semantics label that reads as a sentence;
//   * numbers are locale-formatted (intl), never hardcoded en-US;
//   * text scaling is respected (no fixed-height clipping).
//
// TRUTHFULNESS CONTRACT: these widgets can only render what the semantic model
// permits. A delta needs a baseline; a trend needs ≥2 points; a probability is
// bounded and never derived from confidence. There is deliberately NO widget
// that draws a sparkline from a scalar.

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/spacing.dart';
import '../model/insight_metrics.dart';

// ---------------------------------------------------------------------------
// formatting (locale-aware)
// ---------------------------------------------------------------------------

String _localeOf(BuildContext context) => Localizations.localeOf(context).toString();

/// Compact, locale-aware number. Integers render without decimals.
String formatMetricNumber(BuildContext context, num v, {int decimals = 1}) {
  final locale = _localeOf(context);
  if (v is int || v == v.roundToDouble()) {
    return NumberFormat.decimalPattern(locale).format(v.round());
  }
  return NumberFormat.decimalPattern(locale)
      .format(double.parse(v.toStringAsFixed(decimals)));
}

String formatMetricPercent(BuildContext context, double fraction01) =>
    NumberFormat.percentPattern(_localeOf(context)).format(fraction01);

/// Signed percentage for deltas, e.g. "+8,4%" / "-3,1%".
String formatSignedPercent(BuildContext context, double percent) {
  final s = NumberFormat.decimalPattern(_localeOf(context))
      .format(double.parse(percent.abs().toStringAsFixed(1)));
  return '${percent >= 0 ? '+' : '-'}$s%';
}

// ---------------------------------------------------------------------------
// direction + delta
// ---------------------------------------------------------------------------

/// Icon + text for a direction. NEVER colour-only. `unknown` renders nothing
/// directional (no baseline ⇒ no arrow).
class DirectionIndicator extends StatelessWidget {
  const DirectionIndicator({
    super.key,
    required this.direction,
    this.favourable,
    this.text,
    this.compact = false,
  });

  final MetricDirection direction;

  /// null ⇒ neutral polarity: render a non-judgemental tone.
  final bool? favourable;
  final String? text;
  final bool compact;

  IconData get _icon => switch (direction) {
        MetricDirection.up => Icons.arrow_upward_rounded,
        MetricDirection.down => Icons.arrow_downward_rounded,
        MetricDirection.stable => Icons.trending_flat_rounded,
        MetricDirection.unknown => Icons.remove_rounded,
      };

  String get _word => switch (direction) {
        MetricDirection.up => 'subindo',
        MetricDirection.down => 'caindo',
        MetricDirection.stable => 'estável',
        MetricDirection.unknown => 'sem referência',
      };

  Color _color(BuildContext context) {
    if (direction == MetricDirection.unknown) return context.ds.textLow;
    if (favourable == null) return context.ds.textLow; // neutral: no judgement
    return favourable! ? context.ds.confidenceHigh : context.ds.signal;
  }

  @override
  Widget build(BuildContext context) {
    final color = _color(context);
    final label = text ?? _word;
    return Semantics(
      label: '$label${text != null ? '' : ''}',
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(_icon, size: compact ? 12 : 14, color: color),
          const SizedBox(width: 2),
          Text(
            label,
            style: (compact ? context.tt.labelSmall : context.tt.labelMedium)
                ?.copyWith(color: color, fontFeatures: const [FontFeature.tabularFigures()]),
          ),
        ],
      ),
    );
  }
}

/// A change between two real observations: "↑ +8,4%" (+ absolute when useful).
/// Renders nothing when the percentage is undefined (zero baseline) — falls back
/// to the absolute change rather than inventing a percentage.
class DeltaIndicator extends StatelessWidget {
  const DeltaIndicator({super.key, required this.delta, this.compact = false});

  final MetricDelta delta;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final pct = delta.percentageDelta;
    final text = pct != null
        ? formatSignedPercent(context, pct)
        : '${delta.absoluteDelta >= 0 ? '+' : '-'}'
            '${formatMetricNumber(context, delta.absoluteDelta.abs())}'
            '${delta.unit ?? ''}';
    return Semantics(
      label: '${delta.label}: ${_directionWord(delta.direction)} $text '
          'em relação a ${formatMetricNumber(context, delta.previous)}${delta.unit ?? ''}',
      excludeSemantics: true,
      child: DirectionIndicator(
        direction: delta.direction,
        favourable: delta.isFavourable,
        text: text,
        compact: compact,
      ),
    );
  }
}

String _directionWord(MetricDirection d) => switch (d) {
      MetricDirection.up => 'subiu',
      MetricDirection.down => 'caiu',
      MetricDirection.stable => 'estável',
      MetricDirection.unknown => 'sem referência',
    };

// ---------------------------------------------------------------------------
// freshness
// ---------------------------------------------------------------------------

/// Small textual freshness chip. `unknown` renders nothing — we never invent a
/// freshness the contract did not provide.
class FreshnessIndicator extends StatelessWidget {
  const FreshnessIndicator({super.key, required this.freshness});
  final MetricFreshness freshness;

  @override
  Widget build(BuildContext context) {
    if (freshness == MetricFreshness.unknown) return const SizedBox.shrink();
    final (label, icon) = switch (freshness) {
      MetricFreshness.live => ('Ao vivo', Icons.sensors_rounded),
      MetricFreshness.recent => ('Recente', Icons.schedule_rounded),
      MetricFreshness.stale => ('Desatualizado', Icons.history_rounded),
      MetricFreshness.historical => ('Histórico', Icons.calendar_month_rounded),
      MetricFreshness.unknown => ('', Icons.remove),
    };
    return Semantics(
      label: 'Atualização: $label',
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 11, color: context.ds.textLow),
          const SizedBox(width: 3),
          Text(label, style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// scalar
// ---------------------------------------------------------------------------

/// A scalar metric tile. The honest default: a number + its label. An optional
/// delta is rendered ONLY when a real baseline exists (the type guarantees it).
class InsightMetricCard extends StatelessWidget {
  const InsightMetricCard({
    super.key,
    required this.metric,
    this.delta,
    this.dense = false,
  });

  final MetricValue metric;
  final MetricDelta? delta;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final value = metric.formattedValue ??
        '${formatMetricNumber(context, metric.value)}${metric.unit ?? ''}';
    return Semantics(
      label: '${metric.label}: $value',
      child: Container(
        padding: EdgeInsets.all(dense ? InsightSpacing.sm : InsightSpacing.md),
        decoration: BoxDecoration(
          color: context.ds.card,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: context.ds.divider, width: 0.6),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    metric.label,
                    style: context.tt.labelSmall?.copyWith(color: context.ds.textLow),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                FreshnessIndicator(freshness: metric.freshness),
              ],
            ),
            const SizedBox(height: 2),
            Text(
              value,
              style: (dense ? context.tt.titleSmall : context.tt.titleMedium)
                  ?.copyWith(fontFeatures: const [FontFeature.tabularFigures()]),
            ),
            if (delta != null) ...[
              const SizedBox(height: 2),
              DeltaIndicator(delta: delta!, compact: true),
            ],
          ],
        ),
      ),
    );
  }
}

/// A compact label→value row for dense stat lists.
class MetricValueRow extends StatelessWidget {
  const MetricValueRow({super.key, required this.metric, this.delta});

  final MetricValue metric;
  final MetricDelta? delta;

  @override
  Widget build(BuildContext context) {
    final value = metric.formattedValue ??
        '${formatMetricNumber(context, metric.value)}${metric.unit ?? ''}';
    return Semantics(
      label: '${metric.label}: $value',
      excludeSemantics: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: InsightSpacing.sm),
        child: Row(
          children: [
            Expanded(child: Text(metric.label, style: context.tt.bodyMedium)),
            if (delta != null) ...[
              DeltaIndicator(delta: delta!, compact: true),
              const SizedBox(width: InsightSpacing.sm),
            ],
            Text(
              value,
              style: context.tt.bodyMedium?.copyWith(
                fontWeight: FontWeight.w600,
                fontFeatures: const [FontFeature.tabularFigures()],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// probability (bounded) — visually DISTINCT from confidence
// ---------------------------------------------------------------------------

/// A bounded probability bar. Filled track + explicit "%" text. Visually
/// distinct from [ConfidenceIndicator] (which is a segmented band) so the two
/// claims can never be confused.
class ProbabilityBar extends StatelessWidget {
  const ProbabilityBar({super.key, required this.metric});
  final ProbabilityMetric metric;

  @override
  Widget build(BuildContext context) {
    final pct = formatMetricPercent(context, metric.probability);
    return Semantics(
      label: 'Probabilidade de ${metric.label}: $pct',
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Expanded(child: Text(metric.label, style: context.tt.bodySmall)),
              Text(
                pct,
                style: context.tt.labelLarge?.copyWith(
                  fontFeatures: const [FontFeature.tabularFigures()],
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: metric.probability,
              minHeight: 6,
              backgroundColor: context.ds.subtle,
              valueColor: AlwaysStoppedAnimation(context.ds.signal),
            ),
          ),
          if (metric.confidence != null) ...[
            const SizedBox(height: InsightSpacing.xs),
            ConfidenceIndicator(metric: metric.confidence!),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// confidence — segmented band + word, NOT a probability bar
// ---------------------------------------------------------------------------

/// Confidence in an estimate. Rendered as 3 discrete segments + a word, which is
/// deliberately a DIFFERENT visual language from the continuous probability bar.
class ConfidenceIndicator extends StatelessWidget {
  const ConfidenceIndicator({super.key, required this.metric});
  final ConfidenceMetric metric;

  @override
  Widget build(BuildContext context) {
    final (word, filled, tone) = switch (metric.band) {
      ConfidenceBand.high => ('Alta', 3, context.ds.confidenceHigh),
      ConfidenceBand.medium => ('Média', 2, context.ds.confidenceMid),
      ConfidenceBand.low => ('Baixa', 1, context.ds.confidenceLow),
    };
    return Semantics(
      label: 'Confiança na estimativa: $word'
          '${metric.hasEvidence ? ', com evidências' : ''}',
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('Confiança',
              style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
          const SizedBox(width: InsightSpacing.xs),
          for (var i = 0; i < 3; i++) ...[
            Container(
              width: 10,
              height: 4,
              margin: const EdgeInsets.only(right: 2),
              decoration: BoxDecoration(
                color: i < filled ? tone : context.ds.subtle,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ],
          const SizedBox(width: 4),
          Text(word, style: context.tt.labelSmall),
          if (metric.hasEvidence) ...[
            const SizedBox(width: 4),
            Icon(Icons.fact_check_outlined, size: 11, color: context.ds.textLow),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// comparison
// ---------------------------------------------------------------------------

/// A two-sided comparison bar. Renders an honest "—" when there is nothing to
/// compare (both sides zero) instead of a misleading empty/half bar.
class ComparisonBar extends StatelessWidget {
  const ComparisonBar({super.key, required this.metric});
  final ComparisonMetric metric;

  @override
  Widget build(BuildContext context) {
    final share = metric.leftShare;
    final unit = metric.unit ?? '';
    final left = '${formatMetricNumber(context, metric.leftValue)}$unit';
    final right = '${formatMetricNumber(context, metric.rightValue)}$unit';
    return Semantics(
      label: '${metric.label}: ${metric.leftLabel} $left contra '
          '${metric.rightLabel} $right',
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(metric.label,
              style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
          const SizedBox(height: 3),
          Row(
            children: [
              Text(left,
                  style: context.tt.labelMedium?.copyWith(
                      fontFeatures: const [FontFeature.tabularFigures()])),
              const SizedBox(width: InsightSpacing.sm),
              Expanded(
                child: share == null
                    ? Text('—',
                        textAlign: TextAlign.center,
                        style: context.tt.labelSmall
                            ?.copyWith(color: context.ds.textLow))
                    : ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: Row(
                          children: [
                            Expanded(
                              flex: (share * 1000).round().clamp(1, 999),
                              child: Container(height: 6, color: context.ds.signal),
                            ),
                            Expanded(
                              flex: ((1 - share) * 1000).round().clamp(1, 999),
                              child: Container(height: 6, color: context.ds.subtle),
                            ),
                          ],
                        ),
                      ),
              ),
              const SizedBox(width: InsightSpacing.sm),
              Text(right,
                  style: context.tt.labelMedium?.copyWith(
                      fontFeatures: const [FontFeature.tabularFigures()])),
            ],
          ),
          const SizedBox(height: 2),
          Row(
            children: [
              Text(metric.leftLabel,
                  style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
              const Spacer(),
              Text(metric.rightLabel,
                  style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
            ],
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// explanation
// ---------------------------------------------------------------------------

/// Product-language explanation. Structurally incapable of showing model
/// internals — it renders only the summary/factors/evidence-summary the product
/// contract provides.
class InsightExplanationCard extends StatelessWidget {
  const InsightExplanationCard({super.key, required this.explanation});
  final InsightExplanation explanation;

  String get _sourceWord => switch (explanation.source) {
        InsightSource.platform => 'Análise da plataforma',
        InsightSource.community => 'Leitura da comunidade',
        InsightSource.market => 'Movimento de mercado',
        InsightSource.historical => 'Base histórica',
        InsightSource.unknown => '',
      };

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Explicação: ${explanation.summary}'
          '${explanation.evidenceSummary != null ? '. ${explanation.evidenceSummary}' : ''}',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.all(InsightSpacing.md),
        decoration: BoxDecoration(
          color: context.ds.card,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: context.ds.divider, width: 0.6),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                if (_sourceWord.isNotEmpty)
                  Expanded(
                    child: Text(_sourceWord,
                        style: context.tt.labelSmall
                            ?.copyWith(color: context.ds.textLow)),
                  )
                else
                  const Spacer(),
                FreshnessIndicator(freshness: explanation.freshness),
              ],
            ),
            const SizedBox(height: 3),
            Text(explanation.summary, style: context.tt.bodyMedium),
            if (explanation.factors.isNotEmpty) ...[
              const SizedBox(height: InsightSpacing.sm),
              for (final f in explanation.factors)
                Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(Icons.circle, size: 5, color: context.ds.textLow),
                      const SizedBox(width: InsightSpacing.sm),
                      Expanded(child: Text(f, style: context.tt.bodySmall)),
                    ],
                  ),
                ),
            ],
            if (explanation.evidenceSummary != null) ...[
              const SizedBox(height: InsightSpacing.xs),
              Text(explanation.evidenceSummary!,
                  style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
            ],
          ],
        ),
      ),
    );
  }
}
