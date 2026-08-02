import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';

import '../shared/extensions/build_context_x.dart';

/// Wraps `child` with a shimmer effect tuned for our subtle surfaces. Use
/// it once per *screen* (not per primitive) so all shimmering boxes pulse
/// in unison — multiple Shimmer parents look phasey.
class Skeleton extends StatelessWidget {
  const Skeleton({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Shimmer.fromColors(
      baseColor: context.ds.subtle,
      highlightColor: context.ds.divider.withValues(alpha: 0.4),
      period: const Duration(milliseconds: 1100),
      child: child,
    );
  }
}

/// Rectangular block with rounded corners — for text bars, cards, tiles.
/// The fill colour is opaque black on purpose; `Shimmer.fromColors` paints
/// the gradient overlay on top of whatever colour the child has.
class SkeletonBar extends StatelessWidget {
  const SkeletonBar({
    super.key,
    this.width,
    this.height = 14,
    this.radius = 6,
  });
  final double? width;
  final double height;
  final double radius;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: Colors.black,
        borderRadius: BorderRadius.circular(radius),
      ),
    );
  }
}

/// Circular block — avatars, dots.
class SkeletonCircle extends StatelessWidget {
  const SkeletonCircle({super.key, required this.size});
  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: const BoxDecoration(
        color: Colors.black,
        shape: BoxShape.circle,
      ),
    );
  }
}

/// Larger fixed-size box — cards, tiles, thumbnails.
class SkeletonBox extends StatelessWidget {
  const SkeletonBox({
    super.key,
    required this.width,
    required this.height,
    this.radius = 12,
  });
  final double width;
  final double height;
  final double radius;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: Colors.black,
        borderRadius: BorderRadius.circular(radius),
      ),
    );
  }
}
