import 'package:flutter/material.dart';

import '../../../models/profile.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/radii.dart';

class BadgesRow extends StatelessWidget {
  const BadgesRow({super.key, required this.badges});
  final List<UserBadge> badges;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 92,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 20),
        itemCount: badges.length,
        separatorBuilder: (_, __) => const SizedBox(width: 10),
        itemBuilder: (_, i) {
          final b = badges[i];
          return Container(
            width: 168,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: context.ds.card,
              borderRadius: InsightRadii.brLg,
              border: Border.all(color: context.ds.divider),
            ),
            child: Row(
              children: [
                Text(b.emoji, style: const TextStyle(fontSize: 28)),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        b.label,
                        style: context.tt.titleMedium,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      Text(
                        b.description,
                        style: context.tt.labelSmall
                            ?.copyWith(color: context.ds.textMid),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}
