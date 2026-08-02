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

/// `match_discussion` — match context anchors the post; commentary is
/// secondary. We render the MatchEmbed BEFORE the body to set context.
///
/// Sprint A: the reply button opens the DiscussionThreadScreen. The
/// feed item id IS the social.v1.Discussion id (gateway BFF emits
/// one feed item per Discussion today).
class DiscussionPost extends StatelessWidget {
  const DiscussionPost({super.key, required this.post, this.onOpenMatch});

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
      headerDecoration: Text(
        'comentou',
        style: context.tt.labelSmall?.copyWith(color: context.ds.textLow),
      ),
      children: [
        if (post.match != null)
          MatchEmbed(
            match: post.match!,
            onTap: onOpenMatch == null
                ? null
                : () => onOpenMatch!(post.match!.matchId),
          ),
        const SizedBox(height: 8),
        Text(post.body, style: context.tt.bodyLarge),
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
