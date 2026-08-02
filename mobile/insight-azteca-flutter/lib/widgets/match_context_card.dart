import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/match.dart';
import '../models/match_context.dart';
import '../shared/extensions/build_context_x.dart';
import '../shared/strings/pt_br.dart';
import '../theme/elevation.dart';
import '../theme/icon_sizing.dart';
import '../theme/radii.dart';
import '../theme/spacing.dart';

/// Reusable "match readable" card.
///
/// One card, three layers:
///   * Heading — `<Home> × <Away>` + the league badge.
///   * Status line — "Ao vivo • 63'" / "Hoje · 21:30" / "Encerrado · 2-1".
///   * Signals — short pt-BR clauses with directional cues, NOT chips
///     of numbers. (Spec example: "↑ Pressão ofensiva", "Movimento
///     incomum detectado".)
///   * Probability row — Casa / Empate / Fora in three equal columns.
///     The leading side gets a tinted background. We deliberately omit
///     bars / sparklines so this never reads as a betting screen.
///
/// Used inside the feed, on the Match detail header, and as a tappable
/// embed inside discussion posts. Pass `onTap` to wire navigation.
class MatchContextCard extends StatelessWidget {
  const MatchContextCard({
    super.key,
    required this.summary,
    this.reading,
    this.onTap,
    this.compact = false,
  });

  final MatchSummary summary;
  final MatchContextReading? reading;
  final VoidCallback? onTap;
  // `compact` strips the probability row + tightens spacing. Use when
  // embedding inside another card (e.g., agent insight quoting a match).
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final card = Container(
      decoration: BoxDecoration(
        color: ds.card,
        borderRadius: InsightRadii.brXl,
        border: Border.all(color: ds.divider),
        boxShadow: InsightElevation.card(),
      ),
      padding: EdgeInsets.symmetric(
        horizontal: InsightSpacing.lg,
        vertical: compact ? InsightSpacing.md : InsightSpacing.lg,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Heading(summary: summary),
          const SizedBox(height: InsightSpacing.sm),
          _StatusLine(summary: summary),
          if (reading != null && reading!.signals.isNotEmpty) ...[
            const SizedBox(height: InsightSpacing.md),
            _SignalList(signals: reading!.signals),
          ],
          if (!compact &&
              reading?.probabilities != null) ...[
            const SizedBox(height: InsightSpacing.lg),
            _ProbabilityRow(probabilities: reading!.probabilities!),
          ],
        ],
      ),
    );

    if (onTap == null) return card;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: InsightRadii.brXl,
        child: card,
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Heading: "<Home> × <Away>" + league
// ---------------------------------------------------------------------------

class _Heading extends StatelessWidget {
  const _Heading({required this.summary});
  final MatchSummary summary;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Text(
            '${summary.home.name} × ${summary.away.name}',
            style: context.tt.titleMedium?.copyWith(
              fontWeight: FontWeight.w700,
            ),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ),
        const SizedBox(width: InsightSpacing.md),
        Text(
          summary.league,
          style: context.tt.labelSmall?.copyWith(color: context.ds.textLow),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Status: "Ao vivo • 63'" / "Hoje · 21:30" / "Encerrado · 2 - 1"
// ---------------------------------------------------------------------------

class _StatusLine extends StatelessWidget {
  const _StatusLine({required this.summary});
  final MatchSummary summary;

  String _composeText(BuildContext context) {
    final s = summary.status;
    final score = s.score;
    if (s.state.isLive) {
      final minute = s.minute != null ? "${s.minute}'" : (s.period ?? '');
      final scoreText = score == null ? '' : '  ${score.home} - ${score.away}';
      return '${S.matchStatusLive} • $minute$scoreText';
    }
    if (s.state == MatchState.scheduled) {
      final fmt = DateFormat.Hm('pt_BR');
      return '${S.matchStatusToday} · ${fmt.format(s.kickoff.toLocal())}';
    }
    final scoreText = score == null ? '' : ' · ${score.home} - ${score.away}';
    return '${S.matchStatusFinished}$scoreText';
  }

  @override
  Widget build(BuildContext context) {
    final isLive = summary.status.state.isLive;
    return Row(
      children: [
        if (isLive) ...[
          _LiveDot(color: context.ds.confidenceLow),
          const SizedBox(width: 6),
        ],
        Text(
          _composeText(context),
          style: context.tt.bodySmall?.copyWith(
            color: isLive ? context.ds.confidenceLow : context.ds.textMid,
            fontWeight: isLive ? FontWeight.w600 : FontWeight.w500,
            fontFeatures: const [FontFeature.tabularFigures()],
          ),
        ),
      ],
    );
  }
}

class _LiveDot extends StatefulWidget {
  const _LiveDot({required this.color});
  final Color color;
  @override
  State<_LiveDot> createState() => _LiveDotState();
}

class _LiveDotState extends State<_LiveDot>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 1),
  )..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      builder: (_, __) => Container(
        width: 7,
        height: 7,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: widget.color.withValues(alpha: 0.55 + (_c.value * 0.45)),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Signal list: "↑ Pressão ofensiva" / "Movimento incomum detectado"
// ---------------------------------------------------------------------------

class _SignalList extends StatelessWidget {
  const _SignalList({required this.signals});
  final List<MatchContextSignal> signals;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < signals.length; i++) ...[
          if (i > 0) const SizedBox(height: InsightSpacing.xs),
          _SignalLine(signal: signals[i]),
        ],
      ],
    );
  }
}

class _SignalLine extends StatelessWidget {
  const _SignalLine({required this.signal});
  final MatchContextSignal signal;

  IconData _icon() {
    switch (signal.direction) {
      case SignalDirection.up:
        return Icons.arrow_upward_rounded;
      case SignalDirection.down:
        return Icons.arrow_downward_rounded;
      case SignalDirection.neutral:
        return Icons.fiber_manual_record_rounded;
    }
  }

  Color _color(BuildContext c) {
    switch (signal.direction) {
      case SignalDirection.up:
        return c.ds.confidenceHigh;
      case SignalDirection.down:
        return c.ds.confidenceLow;
      case SignalDirection.neutral:
        return c.ds.textMid;
    }
  }

  @override
  Widget build(BuildContext context) {
    final color = _color(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Icon(_icon(), size: InsightIconSize.inline, color: color),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            signal.label,
            style: context.tt.bodyMedium?.copyWith(
              color: context.ds.textHigh,
              fontWeight: FontWeight.w500,
            ),
          ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Probability row — three equal columns. Leading side gets a soft tint.
// ---------------------------------------------------------------------------

class _ProbabilityRow extends StatelessWidget {
  const _ProbabilityRow({required this.probabilities});
  final MatchProbabilities probabilities;

  int _leadingIndex() {
    final p = probabilities;
    final values = [p.home, p.draw, p.away];
    var bestI = 0;
    var bestV = values[0];
    for (var i = 1; i < values.length; i++) {
      if (values[i] > bestV) {
        bestV = values[i];
        bestI = i;
      }
    }
    return bestI;
  }

  @override
  Widget build(BuildContext context) {
    final leading = _leadingIndex();
    final cols = [
      ('Casa', probabilities.home),
      ('Empate', probabilities.draw),
      ('Fora', probabilities.away),
    ];
    return Row(
      children: [
        for (var i = 0; i < cols.length; i++) ...[
          Expanded(
            child: _ProbabilityCell(
              label: cols[i].$1,
              value: cols[i].$2,
              leading: i == leading,
            ),
          ),
          if (i < cols.length - 1) const SizedBox(width: InsightSpacing.sm),
        ],
      ],
    );
  }
}

class _ProbabilityCell extends StatelessWidget {
  const _ProbabilityCell({
    required this.label,
    required this.value,
    required this.leading,
  });

  final String label;
  final double value;
  final bool leading;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final pct = (value * 100).round();
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
      decoration: BoxDecoration(
        color: leading
            ? ds.signal.withValues(alpha: 0.10)
            : ds.subtle.withValues(alpha: 0.6),
        borderRadius: InsightRadii.brMd,
      ),
      child: Column(
        children: [
          Text(
            label,
            style: context.tt.labelSmall?.copyWith(
              color: leading ? ds.signal : ds.textMid,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.3,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            '$pct%',
            style: context.tt.titleMedium?.copyWith(
              color: leading ? ds.signal : ds.textHigh,
              fontWeight: FontWeight.w700,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
        ],
      ),
    );
  }
}
