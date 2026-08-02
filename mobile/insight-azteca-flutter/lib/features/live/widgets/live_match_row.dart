import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../models/live.dart';
import '../../../models/match.dart';
import '../../../routing/routes.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/strings/pt_br.dart';
import '../../../theme/icon_sizing.dart';
import '../../../widgets/club_badge.dart';

class LiveMatchRow extends StatelessWidget {
  const LiveMatchRow({super.key, required this.match});
  final LiveMatch match;

  String _statusText(MatchSummary s) {
    if (s.status.state.isLive) {
      final m = s.status.minute != null ? "${s.status.minute}'" : (s.status.period ?? S.matchStatusLive);
      return '${S.matchStatusLive} · $m';
    }
    if (s.status.state == MatchState.scheduled) {
      return '${S.matchStatusToday} · ${DateFormat.Hm('pt_BR').format(s.status.kickoff.toLocal())}';
    }
    return S.matchStatusFinished;
  }

  @override
  Widget build(BuildContext context) {
    final s = match.summary;
    final isLive = s.status.state.isLive;
    final score = s.status.score;

    return InkWell(
      onTap: () => context.go(R.matchDetailFor(s.matchId)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (isLive) ...[
                  const _LivePulse(),
                  const SizedBox(width: 6),
                ],
                Text(
                  s.league,
                  style: context.tt.labelSmall
                      ?.copyWith(color: context.ds.textLow),
                ),
                const Spacer(),
                Text(
                  _statusText(s),
                  style: context.tt.labelSmall
                      ?.copyWith(color: context.ds.textMid),
                ),
              ],
            ),
            const SizedBox(height: 8),
            _TeamLine(
              team: s.home,
              score: score?.home,
              leading: score != null && score.home > score.away,
            ),
            const SizedBox(height: 2),
            _TeamLine(
              team: s.away,
              score: score?.away,
              leading: score != null && score.away > score.home,
            ),
            if (isLive) ...[
              const SizedBox(height: 8),
              _NarrativeSignal(
                momentum: match.momentum,
                pressure: match.pressure,
                homeShort: s.home.short,
                awayShort: s.away.short,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// One-line, pt-BR descriptive read of a live match — replaces the
/// bidirectional MomentumBar + "Pressão XX%" chip from the previous
/// dashboardy row.
///
/// Composition rules:
///   * |momentum| >= 0.35 produces a sided phrasing ("crescendo na
///     casa" / "...no visitante").
///   * |pressure| >= 0.7 amplifies to "alta", < 0.4 softens to
///     "começando a esquentar", anything between is "subindo".
///   * Neutral momentum + low pressure produces a quieter line so the
///     row doesn't shout for no reason.
class _NarrativeSignal extends StatelessWidget {
  const _NarrativeSignal({
    required this.momentum,
    required this.pressure,
    required this.homeShort,
    required this.awayShort,
  });

  final double momentum;
  final double pressure;
  final String homeShort;
  final String awayShort;

  String _intensity() {
    if (pressure >= 0.7) return 'alta';
    if (pressure < 0.4) return 'começando a esquentar';
    return 'subindo';
  }

  String _sentence() {
    final intensity = _intensity();
    if (momentum >= 0.35) {
      return 'Pressão $intensity a favor de $homeShort';
    }
    if (momentum <= -0.35) {
      return 'Pressão $intensity a favor de $awayShort';
    }
    if (pressure >= 0.6) {
      return 'Pressão alta, jogo equilibrado';
    }
    return 'Ritmo ainda tranquilo';
  }

  IconData _icon() {
    if (momentum.abs() >= 0.35) return Icons.arrow_outward_rounded;
    if (pressure >= 0.6) return Icons.local_fire_department_rounded;
    return Icons.waves_rounded;
  }

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final loud = pressure >= 0.6 || momentum.abs() >= 0.35;
    final color = loud ? ds.signal : ds.textLow;
    return Row(
      children: [
        Icon(_icon(), size: InsightIconSize.inline, color: color),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            _sentence(),
            style: context.tt.bodySmall?.copyWith(
              color: ds.textMid,
              fontWeight: loud ? FontWeight.w600 : FontWeight.w500,
            ),
          ),
        ),
      ],
    );
  }
}

/// Breathing live indicator — subtle opacity pulse, dashboard-style.
class _LivePulse extends StatefulWidget {
  const _LivePulse();

  @override
  State<_LivePulse> createState() => _LivePulseState();
}

class _LivePulseState extends State<_LivePulse>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
  )..repeat(reverse: true);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: Tween<double>(begin: 0.35, end: 1).animate(
        CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
      ),
      child: Container(
        width: 6,
        height: 6,
        decoration: BoxDecoration(
          color: context.ds.confidenceLow,
          shape: BoxShape.circle,
        ),
      ),
    );
  }
}

/// One team line: badge → name → (emphasized) score. The LEADING side
/// gets the signal tint so the score hierarchy reads at a glance —
/// emphasis without anything betting-flavored.
class _TeamLine extends StatelessWidget {
  const _TeamLine({
    required this.team,
    required this.score,
    required this.leading,
  });

  final MatchTeam team;
  final int? score;
  final bool leading;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        ClubBadge(
          short: team.short,
          name: team.name,
          crestColor: team.crestColor,
          size: 20,
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            team.name,
            style: context.tt.titleMedium?.copyWith(
              fontWeight: leading ? FontWeight.w700 : FontWeight.w500,
            ),
          ),
        ),
        if (score != null)
          Text(
            '$score',
            style: context.tt.titleLarge?.copyWith(
              fontFeatures: const [FontFeature.tabularFigures()],
              fontWeight: FontWeight.w800,
              color: leading ? context.ds.signal : null,
            ),
          ),
      ],
    );
  }
}
