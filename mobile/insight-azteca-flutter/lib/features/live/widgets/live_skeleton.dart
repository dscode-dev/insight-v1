import 'package:flutter/material.dart';

import '../../../shared/extensions/build_context_x.dart';
import '../../../widgets/skeleton.dart';

/// Shimmer placeholder that mirrors LiveMatchRow's silhouette. We render 5
/// rows — enough to look like a populated list, few enough to avoid the
/// "obviously fake" feel.
///
/// The Skeleton wrapper sits at the top so every bar pulses in phase.
class LiveScreenSkeleton extends StatelessWidget {
  const LiveScreenSkeleton({super.key, this.count = 5});
  final int count;

  @override
  Widget build(BuildContext context) {
    return Skeleton(
      child: Column(
        children: [
          for (var i = 0; i < count; i++) ...[
            _LiveRowSkeleton(live: i.isEven),
            Divider(height: 1, thickness: 0.6, color: context.ds.divider),
          ],
        ],
      ),
    );
  }
}

class _LiveRowSkeleton extends StatelessWidget {
  const _LiveRowSkeleton({required this.live});
  final bool live;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // League + status row
          const Row(
            children: [
              SkeletonBar(width: 110, height: 11),
              Spacer(),
              SkeletonBar(width: 70, height: 11),
            ],
          ),
          const SizedBox(height: 12),
          // Home team + score
          const Row(
            children: [
              Expanded(child: SkeletonBar(width: 160, height: 16)),
              SizedBox(width: 12),
              SkeletonBar(width: 24, height: 22),
            ],
          ),
          const SizedBox(height: 6),
          const Row(
            children: [
              Expanded(child: SkeletonBar(width: 140, height: 16)),
              SizedBox(width: 12),
              SkeletonBar(width: 24, height: 22),
            ],
          ),
          if (live) ...[
            const SizedBox(height: 12),
            const SkeletonBar(width: double.infinity, height: 8, radius: 4),
            const SizedBox(height: 6),
            const Row(
              children: [
                SkeletonBar(width: 80, height: 10),
                Spacer(),
                SkeletonBar(width: 90, height: 10),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
