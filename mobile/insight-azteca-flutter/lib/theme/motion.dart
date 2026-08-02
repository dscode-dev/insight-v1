import 'package:flutter/animation.dart';

/// Motion tokens — durations + curves.
///
/// Material 3 emphasizedDecelerate is the default for outgoing transitions;
/// `emphasized` for two-way transitions. Keep motion restrained — premium
/// feel comes from precision, not exuberance.
class InsightMotion {
  const InsightMotion._();

  // Durations
  static const Duration micro = Duration(milliseconds: 120);   // tap feedback
  static const Duration quick = Duration(milliseconds: 200);   // fades, chips
  static const Duration standard = Duration(milliseconds: 300);// nav push
  static const Duration slow = Duration(milliseconds: 450);    // sheets

  // Curves
  static const Curve emphasized = Curves.easeOutCubic;
  static const Curve emphasizedDecelerate =
      Cubic(0.05, 0.7, 0.1, 1.0); // Material 3 emphasizedDecelerate
  static const Curve emphasizedAccelerate = Cubic(0.3, 0.0, 0.8, 0.15);
  static const Curve standardEasing = Curves.easeInOutCubic;
}
