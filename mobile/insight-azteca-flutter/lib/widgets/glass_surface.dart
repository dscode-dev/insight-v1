import 'dart:ui';

import 'package:flutter/material.dart';

import '../shared/extensions/build_context_x.dart';

/// Translucent "frosted glass" surface used by the floating bottom nav,
/// floating composer entry, and toast-style overlays.
///
/// Internally: `BackdropFilter` (gaussian blur) + a tinted overlay
/// `Container` so the surface picks up the colour underneath but reads
/// distinct. Layered shadow comes from the caller via `boxShadow`.
///
/// We intentionally render a real blur (sigma > 0) instead of fake
/// translucent overlays. On low-spec devices the blur degrades to a
/// 0-sigma noop, which keeps the surface still readable.
class GlassSurface extends StatelessWidget {
  const GlassSurface({
    super.key,
    required this.child,
    this.borderRadius,
    this.sigma = 18,
    this.tintOpacity = 0.72,
    this.borderOpacity = 0.06,
    this.boxShadow,
    this.padding,
  });

  final Widget child;
  final BorderRadius? borderRadius;
  final double sigma;
  final double tintOpacity;
  final double borderOpacity;
  final List<BoxShadow>? boxShadow;
  final EdgeInsetsGeometry? padding;

  @override
  Widget build(BuildContext context) {
    final radius = borderRadius ?? BorderRadius.circular(28);
    final base = context.ds.card;
    return Container(
      decoration: BoxDecoration(
        borderRadius: radius,
        boxShadow: boxShadow,
      ),
      child: ClipRRect(
        borderRadius: radius,
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: sigma, sigmaY: sigma),
          child: Container(
            decoration: BoxDecoration(
              color: base.withValues(alpha: tintOpacity),
              borderRadius: radius,
              border: Border.all(
                color: Colors.white.withValues(alpha: borderOpacity),
                width: 0.6,
              ),
            ),
            padding: padding,
            child: child,
          ),
        ),
      ),
    );
  }
}
