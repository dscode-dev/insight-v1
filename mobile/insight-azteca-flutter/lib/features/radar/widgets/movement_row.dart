import 'package:flutter/material.dart';

import '../../../models/radar.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/format/relative_time.dart';
import '../../../theme/icon_sizing.dart';

/// One market-signal row in the Radar.
///
/// Stage 5.2 reframe: drop the all-caps "COMPRESSÃO / ABERTURA /
/// REVERSÃO" market-watch pill. The summary text already carries that
/// intent in plain pt-BR ("Empate 3.20 → 3.05 em 8 casas"), and the
/// icon hints at direction. Keeps the row reading as a discovery feed
/// item, not a trading desk row.
class MovementRow extends StatelessWidget {
  const MovementRow({super.key, required this.movement});
  final MarketMovement movement;

  IconData get _icon {
    switch (movement.direction) {
      case MovementDirection.compressing:
        return Icons.arrow_downward_rounded;
      case MovementDirection.widening:
        return Icons.arrow_upward_rounded;
      case MovementDirection.reversal:
        return Icons.swap_horiz_rounded;
    }
  }

  @override
  Widget build(BuildContext context) {
    final accent = movement.direction == MovementDirection.reversal
        ? context.ds.confidenceMid
        : context.ds.signal;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(_icon, size: InsightIconSize.action, color: accent),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      movement.matchLabel,
                      style: context.tt.titleMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Flexible(
                      child: Text(
                        '· ${movement.league}',
                        style: context.tt.labelSmall
                            ?.copyWith(color: context.ds.textLow),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  movement.summary,
                  style: context.tt.bodyMedium
                      ?.copyWith(color: context.ds.textMid),
                ),
                const SizedBox(height: 4),
                Text(
                  relativeTime(movement.ts),
                  style: context.tt.labelSmall
                      ?.copyWith(color: context.ds.textLow),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
