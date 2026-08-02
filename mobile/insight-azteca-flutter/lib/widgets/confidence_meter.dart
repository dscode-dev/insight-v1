import 'package:flutter/material.dart';

import '../shared/extensions/build_context_x.dart';

/// Slim confidence bar (4px) — used inside AgentInsightPost.
///
/// Animates from 0 → value the first time it appears (and across value
/// changes). `TweenAnimationBuilder` rebuilds itself; the rest of the
/// post tree is unaffected.
class ConfidenceMeter extends StatelessWidget {
  const ConfidenceMeter({
    super.key,
    required this.value,
    this.height = 4,
    this.duration = const Duration(milliseconds: 600),
  });

  /// 0..1.
  final double value;
  final double height;
  final Duration duration;

  Color _colorFor(BuildContext context, double v) {
    if (v >= 0.75) return context.ds.confidenceHigh;
    if (v >= 0.5) return context.ds.confidenceMid;
    return context.ds.confidenceLow;
  }

  @override
  Widget build(BuildContext context) {
    final target = value.clamp(0.0, 1.0);
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: target),
      duration: duration,
      curve: Curves.easeOutCubic,
      builder: (context, v, _) {
        return Stack(
          children: [
            Container(
              height: height,
              decoration: BoxDecoration(
                color: context.ds.subtle,
                borderRadius: BorderRadius.circular(height),
              ),
            ),
            FractionallySizedBox(
              widthFactor: v,
              child: Container(
                height: height,
                decoration: BoxDecoration(
                  color: _colorFor(context, v),
                  borderRadius: BorderRadius.circular(height),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}
