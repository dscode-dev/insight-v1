import 'package:flutter/material.dart';

import '../../../theme/spacing.dart';
import '../../../widgets/skeleton.dart';

/// Shimmering placeholder that mirrors the rough silhouette of a feed
/// item. Three rows are enough — more starts to look fake.
///
/// The shimmer wrapper lives at the *list* level (`FeedListSkeleton`), so
/// all items pulse in phase. Use this widget standalone only inside a
/// `Skeleton(...)` parent.
class FeedItemSkeleton extends StatelessWidget {
  const FeedItemSkeleton({super.key, this.withEmbed = false});
  final bool withEmbed;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: InsightSpacing.pageHorizontal,
        vertical: InsightSpacing.feedItemVertical,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SkeletonCircle(size: 40),
          const SizedBox(width: InsightSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const SkeletonBar(width: 120, height: 14),
                const SizedBox(height: 10),
                const SkeletonBar(height: 14),
                const SizedBox(height: 8),
                const SkeletonBar(width: 220, height: 14),
                if (withEmbed) ...[
                  const SizedBox(height: 14),
                  const SkeletonBar(width: 180, height: 14),
                  const SizedBox(height: 6),
                  const SkeletonBar(width: 140, height: 12),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// List-level shimmer wrapper for the home feed loading state. Stacks 5
/// item skeletons in a single shimmer parent for in-phase pulsing.
class FeedListSkeleton extends StatelessWidget {
  const FeedListSkeleton({super.key, this.count = 5});
  final int count;

  @override
  Widget build(BuildContext context) {
    return Skeleton(
      child: Column(
        children: [
          for (var i = 0; i < count; i++)
            // Every third item shows an embed silhouette — matches the
            // organic distribution of MatchEmbed in the real feed.
            FeedItemSkeleton(withEmbed: i % 3 == 1),
        ],
      ),
    );
  }
}
