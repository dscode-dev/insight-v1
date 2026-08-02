import 'package:flutter/material.dart';

import '../models/feed.dart';
import '../shared/extensions/build_context_x.dart';
import '../theme/radii.dart';

/// Compact uppercase pill rendered next to the author name in a feed
/// item. Tones map to the `SignalBadgeTone` enum.
class InsightBadge extends StatelessWidget {
  const InsightBadge({super.key, required this.data});

  final SignalBadgeData data;

  @override
  Widget build(BuildContext context) {
    final (bg, fg) = _palette(context, data.tone);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(color: bg, borderRadius: InsightRadii.brSm),
      child: Text(
        data.label.toUpperCase(),
        style: TextStyle(
          color: fg,
          fontSize: 11,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.4,
        ),
      ),
    );
  }

  (Color, Color) _palette(BuildContext c, SignalBadgeTone tone) {
    final ds = c.ds;
    switch (tone) {
      case SignalBadgeTone.signal:
        return (ds.signalMuted, ds.signal);
      case SignalBadgeTone.warning:
        return (ds.confidenceMid.withValues(alpha: 0.15), ds.confidenceMid);
      case SignalBadgeTone.success:
        return (ds.confidenceHigh.withValues(alpha: 0.15), ds.confidenceHigh);
      case SignalBadgeTone.info:
        return (ds.subtle, ds.textMid);
    }
  }
}
