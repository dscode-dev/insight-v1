// Offline state — Sprint 2 (Part 11).
//
// Rendered when a load failed because of CONNECTIVITY (NetworkException)
// rather than a server problem: distinct copy + icon so the user knows
// the fix is on their side, plus the standard retry affordance.

import 'package:flutter/material.dart';

import '../core/errors.dart';
import '../shared/extensions/build_context_x.dart';
import '../shared/strings/pt_br.dart';
import '../theme/spacing.dart';

/// True when [error] is a connectivity failure (the request never got
/// a server answer) — the UI should render [OfflineState].
bool isOfflineError(Object? error) =>
    error is NetworkException ||
    (error is Exception && error.toString().contains('NetworkException'));

class OfflineState extends StatelessWidget {
  const OfflineState({super.key, this.onRetry});

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
          Icon(
            Icons.wifi_off_rounded,
            size: 32,
            color: context.ds.textLow,
          ),
          const SizedBox(height: InsightSpacing.md),
          Text(
            S.offlineTitle,
            style: context.tt.titleMedium,
          ),
          const SizedBox(height: InsightSpacing.sm),
          Text(
            S.offlineDescription,
            style: context.tt.bodyMedium?.copyWith(color: context.ds.textMid),
          ),
          if (onRetry != null) ...[
            const SizedBox(height: InsightSpacing.lg),
            FilledButton.tonal(onPressed: onRetry, child: const Text(S.retry)),
          ],
        ],
      ),
    );
  }
}
