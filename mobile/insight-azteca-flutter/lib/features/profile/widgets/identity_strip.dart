import 'package:flutter/material.dart';

import '../../../models/profile.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/format/count.dart';

/// Quiet inline strip of social stats — Threads-style. Replaces the
/// 4-KPI tile grid that used to live at the top of Profile.
///
/// Each pair (count + label) is rendered as a dot-separated row, with
/// tabular figures so the counts align even as they grow. The leading
/// metric ("posts") sets the social-first ordering — reputation is
/// surfaced last because it's the most derived of the four.
class IdentityStrip extends StatelessWidget {
  const IdentityStrip({super.key, required this.stats});
  final UserStats stats;

  @override
  Widget build(BuildContext context) {
    final entries = [
      _Stat(formatCount(stats.posts), 'posts'),
      _Stat(formatCount(stats.signals), 'sinais'),
      _Stat('${(stats.accuracy * 100).round()}%', 'precisão'),
      _Stat('${stats.reputation}', 'reputação'),
    ];

    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 8),
      child: Wrap(
        spacing: 14,
        runSpacing: 6,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          for (var i = 0; i < entries.length; i++) ...[
            if (i > 0) _Sep(color: context.ds.textLow),
            _StatChip(stat: entries[i]),
          ],
        ],
      ),
    );
  }
}

class _Stat {
  const _Stat(this.value, this.label);
  final String value;
  final String label;
}

class _StatChip extends StatelessWidget {
  const _StatChip({required this.stat});
  final _Stat stat;

  @override
  Widget build(BuildContext context) {
    return RichText(
      text: TextSpan(
        style: context.tt.bodySmall?.copyWith(color: context.ds.textMid),
        children: [
          TextSpan(
            text: stat.value,
            style: TextStyle(
              color: context.ds.textHigh,
              fontWeight: FontWeight.w700,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
          const TextSpan(text: ' '),
          TextSpan(
            text: stat.label,
            style: TextStyle(color: context.ds.textLow),
          ),
        ],
      ),
    );
  }
}

class _Sep extends StatelessWidget {
  const _Sep({required this.color});
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2),
      child: Text(
        '·',
        style: context.tt.bodySmall?.copyWith(color: color),
      ),
    );
  }
}
