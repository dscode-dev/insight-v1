import 'package:flutter/material.dart';

import '../models/match.dart';
import '../shared/extensions/build_context_x.dart';

/// Inline intelligence pill — text-only, no chrome. Used inside
/// `MatchEmbed` so the feed never feels card-heavy.
class IntelligencePillView extends StatelessWidget {
  const IntelligencePillView({super.key, required this.pill});

  final IntelligencePill pill;

  Color _color(BuildContext c) {
    final ds = c.ds;
    switch (pill.tone) {
      case IntelligencePillTone.neutral:
        return ds.textMid;
      case IntelligencePillTone.signal:
        return ds.signal;
      case IntelligencePillTone.warning:
        return ds.confidenceMid;
      case IntelligencePillTone.success:
        return ds.confidenceHigh;
      case IntelligencePillTone.danger:
        return ds.confidenceLow;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Text(
      pill.label,
      style: context.tt.bodySmall?.copyWith(color: _color(context)),
    );
  }
}
