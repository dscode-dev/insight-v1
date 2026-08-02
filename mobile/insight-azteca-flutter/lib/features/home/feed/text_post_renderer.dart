import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../models/feed.dart';
import '../../../models/match.dart';
import '../../../routing/routes.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/format/relative_time.dart';
import '../../../theme/spacing.dart';
import '../../../widgets/avatar.dart';
import '../../moderation/moderation_ui.dart';
import '../widgets/post_actions.dart';
import '../widgets/posts/open_author.dart';
import 'feed_item_renderer.dart';

/// The ONLY production renderer implemented this sprint (AZTECA-FEED-A): a
/// polished, accessible text-post card. Handles the human text kinds
/// (`user_opinion` / `quick_analysis`). All other kinds are routed elsewhere by
/// the registry — this renderer carries no business logic beyond "is this text".
class TextPostRenderer extends FeedItemRenderer {
  const TextPostRenderer();

  @override
  bool canRender(FeedPost post) =>
      post.kind == FeedPostKind.userOpinion ||
      post.kind == FeedPostKind.quickAnalysis;

  @override
  Widget render(
    BuildContext context,
    FeedPost post, {
    ValueChanged<String>? onOpenMatch,
  }) =>
      // Stable key per post → cheap diffing during infinite scroll.
      _TextPostCard(
        key: ValueKey('text_${post.id}'),
        post: post,
        onOpenMatch: onOpenMatch,
      );
}

class _TextPostCard extends StatelessWidget {
  const _TextPostCard({super.key, required this.post, this.onOpenMatch});

  final FeedPost post;
  final ValueChanged<String>? onOpenMatch;

  @override
  Widget build(BuildContext context) {
    final author = post.author;
    return Semantics(
      container: true,
      label: 'Publicação de ${author.displayName}',
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: InsightSpacing.pageHorizontal,
          vertical: InsightSpacing.feedItemVertical,
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Avatar lane (44dp touch target → tap opens the author profile).
            Semantics(
              button: true,
              label: 'Perfil de ${author.displayName}',
              child: GestureDetector(
                onTap: openAuthorProfile(context, post),
                child: InsightAvatar(
                  avatarUrl: null,
                  initials: author.initials,
                  colorHex: author.accentColor,
                  size: 44,
                ),
              ),
            ),
            const SizedBox(width: InsightSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _Header(post: post),
                  _OpenPostRegion(
                    onTap: () => context.push(R.postThreadFor(post.id)),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        // Stage 3: optional sports context — rendered ONLY when
                        // the backend attached a match (no empty space reserved).
                        if (post.match != null) ...[
                          const SizedBox(height: InsightSpacing.sm),
                          _SportsContext(
                            match: post.match!,
                            onTap: onOpenMatch == null
                                ? null
                                : () => onOpenMatch!(post.match!.matchId),
                          ),
                        ],
                        const SizedBox(height: InsightSpacing.sm),
                        // Body — highest readability: comfortable line-height,
                        // full size, selectable for long reads.
                        SelectableText(
                          post.body,
                          style: context.tt.bodyLarge?.copyWith(height: 1.45),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: InsightSpacing.sm),
                  _Actions(post: post),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _OpenPostRegion extends StatelessWidget {
  const _OpenPostRegion({required this.child, required this.onTap});

  final Widget child;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Abrir publicação',
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: SizedBox(
          width: double.infinity,
          child: Padding(
            padding: const EdgeInsets.only(right: 4),
            child: child,
          ),
        ),
      ),
    );
  }
}

/// Author name (largest) · @username (secondary) · timestamp (low emphasis).
class _Header extends StatelessWidget {
  const _Header({required this.post});

  final FeedPost post;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final author = post.author;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Flexible(
                child: Text(
                  author.displayName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.tt.titleSmall
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
              if (author.username != null && author.username!.isNotEmpty) ...[
                const SizedBox(width: 6),
                Flexible(
                  child: Text(
                    '@${author.username}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.tt.bodySmall?.copyWith(color: ds.textMid),
                  ),
                ),
              ],
              const SizedBox(width: 6),
              Text(
                '· ${relativeTime(post.ts)}',
                style: context.tt.labelSmall?.copyWith(color: ds.textLow),
              ),
            ],
          ),
        ),
        const SizedBox(width: 6),
        PostMenuButton(
          postId: post.id,
          authorId: author.id,
          authorName: author.displayName,
          authorIsAgent: author.isSystem,
        ),
      ],
    );
  }
}

/// Competition badge (medium emphasis) + "Home x Away". Tappable when a match
/// open handler is provided. Compact — never a heavy embed.
class _SportsContext extends StatelessWidget {
  const _SportsContext({required this.match, this.onTap});

  final MatchSummary match;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final teams = '${match.home.short} x ${match.away.short}';
    return Semantics(
      button: onTap != null,
      label: '${match.league}: $teams',
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: ds.subtle,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: ds.divider, width: 0.8),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.sports_soccer_rounded, size: 14, color: ds.signal),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  match.league,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.tt.labelSmall?.copyWith(
                    color: ds.textHigh,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(width: 6),
              Text('·', style: TextStyle(color: ds.textLow)),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  teams,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.tt.labelSmall?.copyWith(color: ds.textMid),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Like · Comment · Boost · Save — all networked via [PostActions]
/// (AZTECA-SOCIAL-A). Share is removed (not part of V1).
class _Actions extends StatelessWidget {
  const _Actions({required this.post});

  final FeedPost post;

  @override
  Widget build(BuildContext context) {
    return PostActions(
      reactions: post.reactions,
      likedByMe: post.likedByMe,
      postId: post.id,
      onReply: () => context.push(R.postThreadFor(post.id)),
    );
  }
}
