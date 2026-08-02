import 'package:flutter/material.dart';

import '../../../../models/feed.dart';
import '../../../../shared/extensions/build_context_x.dart';
import '../../../../theme/icon_sizing.dart';
import '../../../../theme/radii.dart';
import '../crowd_snippet.dart';
import '../feed_item_shell.dart';
import '../match_embed.dart';
import '../post_actions.dart';

/// Sponsored Intelligence Post.
///
/// Looks structurally identical to a User/Community post — same shell,
/// same body type, same reactions — so it never reads as a banner ad.
/// The ONLY distinguishing chrome is a discreet "Patrocinado" pill on
/// the author row. By design we never use bordered banners, full-bleed
/// images, or popups for sponsored content.
///
/// Sponsor copy must abide by:
///   * No betting calls-to-action.
///   * No misleading "agent" or "system" framings — the sponsor brand
///     name is the author, and the source is always transparent.
///   * No emoji-heavy headlines.
class SponsoredPost extends StatelessWidget {
  const SponsoredPost({super.key, required this.post, this.onOpenMatch});

  final FeedPost post;
  final ValueChanged<String>? onOpenMatch;

  @override
  Widget build(BuildContext context) {
    final sponsor = post.sponsor;
    return FeedItemShell(
      author: post.author,
      ts: post.ts,
      headerDecoration: sponsor == null
          ? null
          : _SponsoredPill(label: sponsor.label),
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
        PostActions(reactions: post.reactions, likedByMe: post.likedByMe),
      ],
    );
  }
}

class _SponsoredPill extends StatelessWidget {
  const _SponsoredPill({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: ds.subtle,
        borderRadius: InsightRadii.brSm,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.bolt_outlined,
            size: InsightIconSize.inline,
            color: ds.textMid,
          ),
          const SizedBox(width: 4),
          Text(
            label,
            style: context.tt.labelSmall?.copyWith(
              color: ds.textMid,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.2,
            ),
          ),
        ],
      ),
    );
  }
}
