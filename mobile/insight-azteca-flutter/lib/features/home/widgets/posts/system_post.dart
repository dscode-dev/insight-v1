import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../../models/feed.dart';
import '../../../../routing/routes.dart';
import '../../../../shared/extensions/build_context_x.dart';
import '../../../../widgets/insight_badge.dart';
import '../crowd_snippet.dart';
import '../feed_item_shell.dart';
import '../match_embed.dart';
import '../post_actions.dart';
import '../reply_preview.dart';
import 'open_author.dart';

/// `system_insight` + `market_movement` — system-generated. A small signal
/// stripe identifies the origin; a "Verificado" dot in the header keeps
/// it distinguishable from a regular user post even when the badge is
/// the same colour.
class SystemInsightPost extends StatelessWidget {
  const SystemInsightPost({super.key, required this.post, this.onOpenMatch});

  final FeedPost post;
  final ValueChanged<String>? onOpenMatch;

  @override
  Widget build(BuildContext context) {
    return FeedItemShell(
      onTapAuthor: openAuthorProfile(context, post),
      onTapPost: () => context.push(R.postThreadFor(post.id)),
      author: post.author,
      ts: post.ts,
      postId: post.id,
      stripeColor: context.ds.signal,
      headerDecoration: Wrap(
        spacing: 6,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          _VerifiedDot(color: context.ds.signal),
          if (post.badge != null) InsightBadge(data: post.badge!),
        ],
      ),
      children: [
        const SizedBox(height: 4),
        Text(post.body, style: context.tt.bodyLarge),
        if (post.match != null)
          MatchEmbed(
            match: post.match!,
            onTap: onOpenMatch == null
                ? null
                : () => onOpenMatch!(post.match!.matchId),
          ),
        if (post.crowd != null) CrowdSnippet(data: post.crowd!),
        PostActions(
          reactions: post.reactions,
          likedByMe: post.likedByMe,
          postId: post.id,
          onReply: () => context.push(R.postThreadFor(post.id)),
        ),
        if (post.replyPreview != null)
          ReplyPreviewView(
            data: post.replyPreview!,
            onTap: () => context.push(R.postThreadFor(post.id)),
          ),
      ],
    );
  }
}

class _VerifiedDot extends StatelessWidget {
  const _VerifiedDot({required this.color});
  final Color color;
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 6,
          height: 6,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 4),
        Text(
          'VERIFICADO',
          style: context.tt.labelSmall?.copyWith(
            color: color,
            letterSpacing: 0.5,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}
