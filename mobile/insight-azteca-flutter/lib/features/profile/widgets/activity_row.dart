import 'package:flutter/material.dart';

import '../../../models/profile.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/format/relative_time.dart';

class ActivityRow extends StatelessWidget {
  const ActivityRow({super.key, required this.entry});
  final ProfileActivity entry;

  (IconData, Color) _icon(BuildContext c) {
    final ds = c.ds;
    switch (entry.kind) {
      case ProfileActivityKind.post:
        return (Icons.edit_note_rounded, ds.textMid);
      case ProfileActivityKind.signal:
        return (Icons.bolt_rounded, ds.signal);
      case ProfileActivityKind.reply:
        return (Icons.mode_comment_outlined, ds.textMid);
      case ProfileActivityKind.badgeEarned:
        return (Icons.workspace_premium_rounded, ds.confidenceMid);
    }
  }

  @override
  Widget build(BuildContext context) {
    final (icon, color) = _icon(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Icon(icon, size: 16, color: color),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        entry.title,
                        style: context.tt.titleMedium,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      relativeTime(entry.ts),
                      style: context.tt.labelSmall
                          ?.copyWith(color: context.ds.textLow),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  entry.body,
                  style: context.tt.bodySmall
                      ?.copyWith(color: context.ds.textMid),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
