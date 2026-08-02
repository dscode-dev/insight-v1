import 'package:flutter/material.dart';

import '../shared/extensions/build_context_x.dart';
import '../shared/strings/pt_br.dart';
import '../theme/spacing.dart';

class ErrorState extends StatelessWidget {
  const ErrorState({
    super.key,
    required this.title,
    this.description,
    this.onRetry,
  });

  final String title;
  final String? description;
  final VoidCallback? onRetry;

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
          Text(
            title,
            style: context.tt.titleMedium
                ?.copyWith(color: context.ds.confidenceLow),
          ),
          if (description != null) ...[
            const SizedBox(height: InsightSpacing.sm),
            Text(
              description!,
              style: context.tt.bodyMedium?.copyWith(color: context.ds.textMid),
            ),
          ],
          if (onRetry != null) ...[
            const SizedBox(height: InsightSpacing.lg),
            FilledButton.tonal(onPressed: onRetry, child: const Text(S.retry)),
          ],
        ],
      ),
    );
  }
}
