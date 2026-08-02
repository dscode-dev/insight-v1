import 'package:flutter/material.dart';

import '../../../widgets/skeleton.dart';
import '../../../widgets/section_header.dart';

/// Profile body skeleton — header is rendered by ProfileScreen itself
/// (name comes from auth state, not the async profile bundle), so we
/// only shimmer the parts that depend on the bundle.
///
/// Layout mirrors the post-Stage-5.2 reframe: IdentityStrip (inline
/// stats row) replaces the 4-KPI grid; Conquistas + Atividade rows
/// unchanged.
class ProfileBodySkeleton extends StatelessWidget {
  const ProfileBodySkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Skeleton(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // IdentityStrip silhouette — 4 small "value+label" pairs
          // separated by dot. Each pair is two stacked bars.
          const Padding(
            padding: EdgeInsets.fromLTRB(20, 4, 20, 8),
            child: Row(
              children: [
                _StripBar(),
                SizedBox(width: 14),
                _StripBar(),
                SizedBox(width: 14),
                _StripBar(),
                SizedBox(width: 14),
                _StripBar(),
              ],
            ),
          ),
          const SectionHeader(title: 'Conquistas'),
          SizedBox(
            height: 96,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 20),
              physics: const NeverScrollableScrollPhysics(),
              itemCount: 4,
              separatorBuilder: (_, __) => const SizedBox(width: 10),
              itemBuilder: (_, __) => const SkeletonBox(width: 96, height: 88),
            ),
          ),
          const SectionHeader(title: 'Atividade recente'),
          for (var i = 0; i < 4; i++)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SkeletonCircle(size: 28),
                  SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SkeletonBar(width: 200, height: 14),
                        SizedBox(height: 6),
                        SkeletonBar(width: 140, height: 12),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          const SizedBox(height: 32),
        ],
      ),
    );
  }
}

class _StripBar extends StatelessWidget {
  const _StripBar();

  @override
  Widget build(BuildContext context) {
    // Value (bold short bar) + label (lighter, wider bar).
    return const Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        SkeletonBar(width: 22, height: 12),
        SizedBox(width: 6),
        SkeletonBar(width: 40, height: 10),
      ],
    );
  }
}
