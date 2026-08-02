import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../models/hub.dart';
import '../../../routing/routes.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/format/relative_time.dart';
import '../../../widgets/avatar.dart';

class DiscussionRow extends StatelessWidget {
  const DiscussionRow({super.key, required this.discussion});
  final Discussion discussion;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: kDebugMode
          ? () => context.push(R.discussionThreadFor(discussion.id))
          : null, // legacy discussion screen is debug-only (V1 closure)
      child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InsightAvatar(
            initials: discussion.authorInitials,
            colorHex: discussion.authorAccent,
            size: 36,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      discussion.authorDisplayName,
                      style: context.tt.titleMedium,
                    ),
                    const SizedBox(width: 6),
                    Text(
                      'em ${discussion.communityHandle}',
                      style: context.tt.labelSmall
                          ?.copyWith(color: context.ds.signal),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  discussion.title,
                  style: context.tt.bodyMedium
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 2),
                Text(
                  discussion.snippet,
                  style: context.tt.bodySmall
                      ?.copyWith(color: context.ds.textMid),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 4),
                Row(
                  children: [
                    Icon(Icons.mode_comment_outlined,
                        size: 14, color: context.ds.textLow),
                    const SizedBox(width: 4),
                    Text(
                      '${discussion.replies}',
                      style: context.tt.labelSmall
                          ?.copyWith(color: context.ds.textMid),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '· ${relativeTime(discussion.lastActivityTs)}',
                      style: context.tt.labelSmall
                          ?.copyWith(color: context.ds.textLow),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
      ),
    );
  }
}
