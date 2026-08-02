import 'package:flutter/material.dart';

import '../../../widgets/skeleton.dart';
import '../../../widgets/section_header.dart';

/// Mirrors the RadarScreen layout: section headers are real (not shimmered)
/// so navigation orientation isn't lost, but their content blocks shimmer.
class RadarScreenSkeleton extends StatelessWidget {
  const RadarScreenSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: const [
        SectionHeader(title: 'Em alta agora'),
        SizedBox(
          height: 132,
          child: Skeleton(
            child: _HorizontalCards(itemWidth: 240, height: 132),
          ),
        ),
        SectionHeader(title: 'Movimentos de mercado'),
        Skeleton(child: _MovementListSkeleton(count: 4)),
        SectionHeader(title: 'Sinais da comunidade'),
        Skeleton(child: _SignalListSkeleton(count: 4)),
        SizedBox(height: 32),
      ],
    );
  }
}

class _HorizontalCards extends StatelessWidget {
  const _HorizontalCards({required this.itemWidth, required this.height});
  final double itemWidth;
  final double height;

  @override
  Widget build(BuildContext context) {
    return ListView.separated(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 20),
      itemCount: 4,
      physics: const NeverScrollableScrollPhysics(),
      separatorBuilder: (_, __) => const SizedBox(width: 10),
      itemBuilder: (_, __) => SkeletonBox(
        width: itemWidth,
        height: height - 8,
      ),
    );
  }
}

class _MovementListSkeleton extends StatelessWidget {
  const _MovementListSkeleton({required this.count});
  final int count;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var i = 0; i < count; i++)
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 20, vertical: 12),
            child: Row(
              children: [
                SkeletonCircle(size: 28),
                SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SkeletonBar(width: 140, height: 14),
                      SizedBox(height: 6),
                      SkeletonBar(width: 200, height: 12),
                    ],
                  ),
                ),
                SizedBox(width: 12),
                SkeletonBar(width: 36, height: 10),
              ],
            ),
          ),
      ],
    );
  }
}

class _SignalListSkeleton extends StatelessWidget {
  const _SignalListSkeleton({required this.count});
  final int count;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var i = 0; i < count; i++)
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 20, vertical: 12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SkeletonCircle(size: 32),
                SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SkeletonBar(width: 160, height: 14),
                      SizedBox(height: 6),
                      SkeletonBar(width: 240, height: 12),
                      SizedBox(height: 8),
                      SkeletonBar(width: 100, height: 4, radius: 2),
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
