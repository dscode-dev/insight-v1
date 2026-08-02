import 'package:flutter/material.dart';

import '../shared/extensions/build_context_x.dart';
import '../theme/spacing.dart';

/// Quiet empty-state block. No icon by default — the silence is the message.
class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.title,
    this.description,
    this.action,
  });

  final String title;
  final String? description;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: InsightSpacing.xl2,
        vertical: InsightSpacing.xl4,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: context.tt.titleMedium),
          if (description != null) ...[
            const SizedBox(height: InsightSpacing.sm),
            Text(
              description!,
              style: context.tt.bodyMedium?.copyWith(color: context.ds.textMid),
            ),
          ],
          if (action != null) ...[
            const SizedBox(height: InsightSpacing.lg),
            action!,
          ],
        ],
      ),
    );
  }
}
