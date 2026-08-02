import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../models/match.dart';
import '../../../models/radar.dart';
import '../../../routing/routes.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/radii.dart';

class TrendingMatchCard extends StatelessWidget {
  const TrendingMatchCard({super.key, required this.match});
  final TrendingMatch match;

  @override
  Widget build(BuildContext context) {
    final s = match.summary;
    final isLive = s.status.state.isLive;
    return InkWell(
      onTap: () => context.go(R.matchDetailFor(s.matchId)),
      borderRadius: InsightRadii.brLg,
      child: Container(
        width: 240,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: context.ds.card,
          borderRadius: InsightRadii.brLg,
          border: Border.all(color: context.ds.divider),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (isLive) ...[
                  Container(
                    width: 6,
                    height: 6,
                    decoration: BoxDecoration(
                      color: context.ds.confidenceLow,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 6),
                ],
                Text(
                  s.league,
                  style: context.tt.labelSmall
                      ?.copyWith(color: context.ds.textLow),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              '${s.home.short} × ${s.away.short}',
              style: context.tt.titleMedium,
            ),
            const SizedBox(height: 4),
            Text(
              match.reason,
              style: context.tt.bodySmall?.copyWith(color: context.ds.textMid),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
      ),
    );
  }
}
