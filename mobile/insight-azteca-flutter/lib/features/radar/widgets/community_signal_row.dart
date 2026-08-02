import 'package:flutter/material.dart';

import '../../../models/radar.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/format/relative_time.dart';
import '../../../widgets/avatar.dart';

class CommunitySignalRow extends StatelessWidget {
  const CommunitySignalRow({super.key, required this.signal});
  final CommunitySignalCard signal;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InsightAvatar(
            initials: signal.authorInitials,
            colorHex: signal.authorAccent,
            size: 36,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      signal.authorDisplayName,
                      style: context.tt.titleMedium,
                    ),
                    const SizedBox(width: 6),
                    Text(
                      '· ${signal.matchLabel}',
                      style: context.tt.labelSmall
                          ?.copyWith(color: context.ds.textLow),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  signal.body,
                  style: context.tt.bodyMedium,
                ),
                const SizedBox(height: 4),
                // Stage 5.2: textual confidence + relative time, no bar.
                // The bar + numeric % combo read too dashboardy on a
                // discovery row — natural language carries the same
                // signal without competing with the body text.
                Text(
                  'Confiança ${(signal.confidence * 100).round()}% · ${relativeTime(signal.ts)}',
                  style: context.tt.labelSmall?.copyWith(
                    color: context.ds.textLow,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
