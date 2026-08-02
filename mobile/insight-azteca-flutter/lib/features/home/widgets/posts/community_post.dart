import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../../models/feed.dart';
import '../../../../routing/routes.dart';
import '../../../../shared/extensions/build_context_x.dart';
import '../feed_item_shell.dart';
import '../match_embed.dart';
import '../post_actions.dart';
import '../reply_preview.dart';
import 'open_author.dart';

/// `community_signal` — breadcrumb "em #handle" instead of tier label.
class CommunityPost extends StatelessWidget {
  const CommunityPost({super.key, required this.post, this.onOpenMatch});

  final FeedPost post;
  final ValueChanged<String>? onOpenMatch;

  @override
  Widget build(BuildContext context) {
    final c = post.community;
    return FeedItemShell(
      onTapAuthor: openAuthorProfile(context, post),
      onTapPost: () => context.push(R.postThreadFor(post.id)),
      author: post.author,
      ts: post.ts,
      postId: post.id,
      headerDecoration: c == null
          ? null
          : Text(
              'em ${c.handle}',
              style: context.tt.labelSmall?.copyWith(color: context.ds.signal),
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
