import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../../models/feed.dart';
import '../../../../routing/routes.dart';
import '../../../../shared/extensions/build_context_x.dart';
import '../../../../widgets/insight_badge.dart';
import '../feed_item_shell.dart';
import '../match_embed.dart';
import '../post_actions.dart';
import 'open_author.dart';

/// `signal` — user post with a strong inline badge ("Sinal forte"). No
/// crowd snippet by design; signals are individual reads, not aggregates.
class SignalPost extends StatelessWidget {
  const SignalPost({super.key, required this.post, this.onOpenMatch});

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
      headerDecoration:
          post.badge == null ? null : InsightBadge(data: post.badge!),
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
      ],
    );
  }
}
