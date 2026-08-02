import 'package:flutter/material.dart';

/// Elevation tokens — used by floating surfaces (compose FAB, bottom
/// nav, sheets) and resting cards.
///
/// Material 3 derives elevation from the surfaceTint blend; we want a
/// more "iOS-feel" stack with explicit shadow values, so we keep our
/// own table here and reference it from each surface.
///
/// Rule of thumb:
///   * `floating` — anything that visually lifts off the canvas (FAB,
///     nav, picker sheet preview).
///   * `card` — resting card surface (match context, sponsored post
///     identity block). Subtle, never feels glossy.
///   * `overlay` — fully detached layer (drag handles, picker dialogs
///     mid-gesture). Higher pop, used briefly.
class InsightElevation {
  const InsightElevation._();

  /// Shadow stack for resting cards. Two layers — a tight near-shadow
  /// (1px blur, 0.04 alpha) for the edge, and a broad 6px diffuse
  /// shadow at 0.06 alpha for the body. Reads as "lifted but quiet".
  static List<BoxShadow> card({Color seed = Colors.black}) => [
        BoxShadow(
          color: seed.withValues(alpha: 0.04),
          offset: const Offset(0, 1),
          blurRadius: 1,
        ),
        BoxShadow(
          color: seed.withValues(alpha: 0.06),
          offset: const Offset(0, 6),
          blurRadius: 16,
        ),
      ];

  /// Floating surfaces (bottom nav, FAB). Slightly taller stack with
  /// a 14px ambient and a 22px diffuse — strong enough to read as
  /// "above the canvas", not so strong that it competes with content.
  static List<BoxShadow> floating({Color seed = Colors.black}) => [
        BoxShadow(
          color: seed.withValues(alpha: 0.08),
          offset: const Offset(0, 4),
          blurRadius: 14,
        ),
        BoxShadow(
          color: seed.withValues(alpha: 0.06),
          offset: const Offset(0, 12),
          blurRadius: 28,
        ),
      ];

  /// Overlay surfaces (active picker sheet, drag handles). Highest pop
  /// in the system. Use sparingly.
  static List<BoxShadow> overlay({Color seed = Colors.black}) => [
        BoxShadow(
          color: seed.withValues(alpha: 0.10),
          offset: const Offset(0, 8),
          blurRadius: 24,
        ),
        BoxShadow(
          color: seed.withValues(alpha: 0.10),
          offset: const Offset(0, 24),
          blurRadius: 48,
        ),
      ];
}
