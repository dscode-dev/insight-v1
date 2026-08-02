import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../models/match.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/strings/pt_br.dart';
import '../../../theme/spacing.dart';
import '../../../widgets/intelligence_pill.dart';

/// Single-column ambient match context. No card chrome, no team avatars,
/// no score in title type. Three short rows max:
///   Palmeiras × Flamengo · Brasileirão
///   Ao vivo · 67' · 1 — 1
///   ↑ pressão visitante   Movimento atrasado
///
/// Pills wrap; the embed never produces a horizontal scroll.
class MatchEmbed extends StatelessWidget {
  const MatchEmbed({
    super.key,
    required this.match,
    this.onTap,
  });

  final MatchSummary match;
  final VoidCallback? onTap;

  bool get _isLive => match.status.state.isLive;

  String _statusLine() {
    final s = match.status;
    final score = s.score;
    if (_isLive) {
      final minute = s.minute != null ? "${s.minute}'" : (s.period ?? S.matchStatusLive);
      final scoreStr = score != null ? ' · ${score.home} — ${score.away}' : '';
      return '${S.matchStatusLive} · $minute$scoreStr';
    }
    if (s.state == MatchState.scheduled) {
      final fmt = DateFormat.Hm('pt_BR');
      return '${S.matchStatusToday} · ${fmt.format(s.kickoff.toLocal())}';
    }
    final scoreStr = score != null ? ' · ${score.home} — ${score.away}' : '';
    return '${S.matchStatusFinished}$scoreStr';
  }

  @override
  Widget build(BuildContext context) {
    final pills = match.pills.take(3).toList();

    final body = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            if (_isLive) ...[
              _LivePulseDot(color: context.ds.confidenceLow),
              const SizedBox(width: 8),
            ],
            Expanded(
              child: Text(
                '${match.home.name} × ${match.away.name}',
                style: context.tt.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            const SizedBox(width: 6),
            Text(
              '· ${match.league}',
              style: context.tt.labelSmall?.copyWith(color: context.ds.textLow),
            ),
          ],
        ),
        const SizedBox(height: 2),
        Text(
          _statusLine(),
          style: context.tt.bodySmall?.copyWith(color: context.ds.textMid),
        ),
        if (pills.isNotEmpty) ...[
          const SizedBox(height: InsightSpacing.xs),
          Wrap(
            spacing: InsightSpacing.md,
            runSpacing: InsightSpacing.xs,
            children: [for (final p in pills) IntelligencePillView(pill: p)],
          ),
        ],
      ],
    );

    if (onTap == null) {
      return Padding(
        padding: const EdgeInsets.only(top: InsightSpacing.md),
        child: body,
      );
    }
    return Padding(
      padding: const EdgeInsets.only(top: InsightSpacing.md),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: body),
      ),
    );
  }
}

class _LivePulseDot extends StatefulWidget {
  const _LivePulseDot({required this.color});
  final Color color;

  @override
  State<_LivePulseDot> createState() => _LivePulseDotState();
}

class _LivePulseDotState extends State<_LivePulseDot>
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
