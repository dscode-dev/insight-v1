import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../models/hub.dart';
import '../../../routing/routes.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/format/count.dart';
import '../../../theme/radii.dart';

class CommunityTile extends StatelessWidget {
  const CommunityTile({super.key, required this.community});
  final Community community;

  Color _accent() {
    final raw = community.accentColor.replaceFirst('#', '');
    final v = int.tryParse(raw, radix: 16) ?? 0;
    return Color(0xFF000000 | (v & 0xFFFFFF));
  }

  @override
  Widget build(BuildContext context) {
    final accent = _accent();
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: () => context.push(R.communityDetailFor(community.id)),
        borderRadius: InsightRadii.brLg,
        child: Container(
          width: 200,
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
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Center(
                  child: Text(
                    community.name.substring(0, 1),
                    style: TextStyle(
                      color: accent,
                      fontWeight: FontWeight.w700,
                      fontSize: 14,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  community.handle,
                  style: context.tt.labelSmall
                      ?.copyWith(color: context.ds.textLow),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            community.name,
            style: context.tt.titleMedium,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          const SizedBox(height: 2),
          Text(
            '${formatCount(community.activeMembers)} ativos',
            style: context.tt.labelSmall
                ?.copyWith(color: context.ds.textMid),
          ),
        ],
          ),
        ),
      ),
    );
  }
}
