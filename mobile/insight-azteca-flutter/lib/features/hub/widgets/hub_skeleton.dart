import 'package:flutter/material.dart';

import '../../../widgets/skeleton.dart';
import '../../../widgets/section_header.dart';

class HubScreenSkeleton extends StatelessWidget {
  const HubScreenSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: const [
        SectionHeader(title: 'Suas comunidades'),
        SizedBox(
          height: 124,
          child: Skeleton(
            child: _HorizontalTiles(itemWidth: 200, height: 116),
          ),
        ),
        SectionHeader(title: 'Tipsters em alta'),
        SizedBox(
          height: 140,
          child: Skeleton(
            child: _HorizontalTiles(itemWidth: 180, height: 132),
          ),
        ),
        SectionHeader(title: 'Discussões recentes'),
        Skeleton(child: _DiscussionListSkeleton(count: 4)),
        SizedBox(height: 32),
      ],
    );
  }
}

class _HorizontalTiles extends StatelessWidget {
  const _HorizontalTiles({required this.itemWidth, required this.height});
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
      itemBuilder: (_, __) => SkeletonBox(width: itemWidth, height: height),
    );
  }
}

class _DiscussionListSkeleton extends StatelessWidget {
  const _DiscussionListSkeleton({required this.count});
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
                      SkeletonBar(width: 150, height: 12),
                      SizedBox(height: 6),
                      SkeletonBar(width: double.infinity, height: 14),
                      SizedBox(height: 6),
                      SkeletonBar(width: 220, height: 12),
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
