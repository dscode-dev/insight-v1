// FEATURE-COMMUNITIES-V1 Stage 3 — Discussion card.
//
// A Discussion is NOT a Post. This card is deliberately its own component (not
// the global timeline card): it foregrounds the CONVERSATION — the title, the
// reply and reaction counts, and recent activity — so the user reads it as a
// forum thread inside a community. It follows the Insight design system but
// never borrows the post/feed layout.

import 'package:flutter/material.dart';

import '../../../../shared/extensions/build_context_x.dart';
import '../../../../shared/format/count.dart';
import '../../../../shared/format/relative_time.dart';
import '../../../../theme/radii.dart';
import '../../../../theme/spacing.dart';
import '../model/community_models.dart';

class DiscussionCard extends StatelessWidget {
  const DiscussionCard({super.key, required this.discussion, this.onTap});
  final CommunityDiscussion discussion;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: onTap != null,
      label: 'Discussão: ${discussion.title}',
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: InsightSpacing.xl, vertical: InsightSpacing.xs),
        decoration: BoxDecoration(
          color: context.ds.card,
          borderRadius: BorderRadius.circular(InsightRadii.md),
          border: Border.all(color: context.ds.divider),
        ),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(InsightRadii.md),
          child: Padding(
            padding: const EdgeInsets.all(InsightSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.forum_outlined, size: 16, color: context.ds.signal),
                    const SizedBox(width: InsightSpacing.sm),
                    Text('Discussão', style: context.tt.labelSmall?.copyWith(color: context.ds.signal)),
                    const Spacer(),
                    if (discussion.lastActivityTs.isNotEmpty)
                      Text(_activity(discussion.lastActivityTs),
                          style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
                  ],
                ),
                const SizedBox(height: InsightSpacing.sm),
                Text(
                  discussion.title,
                  style: context.tt.titleMedium?.copyWith(fontWeight: FontWeight.w600),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: InsightSpacing.md),
                Row(
                  children: [
                    _Metric(
                      icon: Icons.mode_comment_outlined,
                      label: '${formatCount(discussion.replyCount)} '
                          '${discussion.replyCount == 1 ? 'resposta' : 'respostas'}',
                    ),
                    const SizedBox(width: InsightSpacing.xl),
                    _Metric(
                      icon: Icons.favorite_outline,
                      label: formatCount(discussion.reactionCount),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  String _activity(String iso) {
    final dt = DateTime.tryParse(iso);
    if (dt == null) return '';
    return 'ativa ${relativeTime(dt)}';
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.icon, required this.label});
  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 15, color: context.ds.textLow),
        const SizedBox(width: InsightSpacing.xs),
        Text(label, style: context.tt.labelSmall?.copyWith(color: context.ds.textMid)),
      ],
    );
  }
}
