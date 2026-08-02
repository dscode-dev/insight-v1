import 'package:flutter/material.dart';

import '../../../models/feed.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/format/relative_time.dart';
import '../../../theme/spacing.dart';
import '../../../widgets/avatar.dart';
import '../../moderation/moderation_ui.dart';
import 'post_actions.dart';

/// Shared structural shell every feed-item variant composes onto.
///
/// Visual contract:
///   * px=20, py=16 (InsightSpacing.pageHorizontal / feedItemVertical)
///   * avatar lane (40px) on the left
///   * content column on the right with author row + body slot
///   * optional `stripeColor` paints a 3px lateral accent for AI / system
///     posts. Identifies the variant at a glance without chrome.
class FeedItemShell extends StatelessWidget {
  const FeedItemShell({
    super.key,
    required this.author,
    required this.ts,
    required this.children,
    this.stripeColor,
    this.headerDecoration,
    this.onTapAuthor,
    this.onTapPost,
    this.postId,
  });

  final FeedAuthor author;
  final DateTime ts;
  final List<Widget> children;
  final Color? stripeColor;
  final Widget? headerDecoration;
  // Tapping the avatar/name opens the author's profile. Null = no-op
  // (e.g. sponsored placeholders).
  final VoidCallback? onTapAuthor;
  // Tapping the post content opens the dedicated post page. Actions keep their
  // own handlers and are intentionally excluded from this tap region.
  final VoidCallback? onTapPost;
  // Store-A: when set, renders the 3-dot report/block menu for this post.
  // Null (e.g. sponsored placeholders) hides the menu.
  final String? postId;

  @override
  Widget build(BuildContext context) {
    final actionIndex = children.indexWhere((child) => child is PostActions);
    final contentChildren = actionIndex == -1
        ? children
        : children.take(actionIndex).toList(growable: false);
    final actionChildren = actionIndex == -1
        ? const <Widget>[]
        : children.skip(actionIndex).toList(growable: false);
    return Stack(
      children: [
        if (stripeColor != null)
          Positioned(
            left: 0,
            top: InsightSpacing.feedItemVertical,
            bottom: InsightSpacing.feedItemVertical,
            child: Container(
              width: 3,
              decoration: BoxDecoration(
                color: stripeColor,
                borderRadius: const BorderRadius.only(
                  topRight: Radius.circular(2),
                  bottomRight: Radius.circular(2),
                ),
              ),
            ),
          ),
        Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: InsightSpacing.pageHorizontal,
            vertical: InsightSpacing.feedItemVertical,
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              GestureDetector(
                onTap: onTapAuthor,
                child: InsightAvatar(
                  initials: author.initials,
                  colorHex: author.accentColor,
                ),
              ),
              const SizedBox(width: InsightSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _HeaderRow(
                      author: author,
                      ts: ts,
                      decoration: headerDecoration,
                      onTapAuthor: onTapAuthor,
                      postId: postId,
                    ),
                    _PostTapRegion(
                      onTap: onTapPost,
                      children: contentChildren,
                    ),
                    ...actionChildren,
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _PostTapRegion extends StatelessWidget {
  const _PostTapRegion({required this.children, this.onTap});

  final List<Widget> children;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    if (children.isEmpty) return const SizedBox.shrink();
    final child = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: children,
    );
    if (onTap == null) return child;
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

class _HeaderRow extends StatelessWidget {
  const _HeaderRow({
    required this.author,
    required this.ts,
    this.decoration,
    this.onTapAuthor,
    this.postId,
  });

  final FeedAuthor author;
  final DateTime ts;
  final Widget? decoration;
  final VoidCallback? onTapAuthor;
  final String? postId;

  @override
  Widget build(BuildContext context) {
    return DefaultTextStyle.merge(
      style: context.tt.titleMedium,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Wrap(
              spacing: 6,
              runSpacing: 2,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                GestureDetector(
                  onTap: onTapAuthor,
                  child: Text(
                    author.displayName,
                    style: context.tt.titleMedium,
                  ),
                ),
                if (decoration != null) decoration!,
                Text(
                  '· ${relativeTime(ts)}',
                  style: context.tt.labelSmall
                      ?.copyWith(color: context.ds.textLow),
                ),
              ],
            ),
          ),
          // Store-A: report/block menu on every post (Part 4).
          if (postId != null)
            PostMenuButton(
              postId: postId!,
              authorId: author.id,
              authorName: author.displayName,
              authorIsAgent: author.isSystem,
            ),
        ],
      ),
    );
  }
}
