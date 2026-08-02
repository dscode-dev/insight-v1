// Feature gate — V1 closure (Azteca Social Foundation migration).
//
// Some screens (Live, Radar, Notifications, match context) call Gateway
// routes that DO NOT EXIST yet (`/v1/live/*`, `/v1/radar/*`,
// `/v1/notifications*`, `/v1/context/*`). To guarantee a production
// build never fires a 404, those providers are gated behind flags that
// are OFF by default. When a flag is off the provider throws
// [FeatureUnavailable] WITHOUT touching the network, and the screen
// renders a calm "coming soon" placeholder via [FeatureUnavailableView].
import 'package:flutter/material.dart';

import '../shared/extensions/build_context_x.dart';
import '../theme/spacing.dart';

/// Thrown by a gated provider when its feature flag is disabled — the
/// network call is skipped entirely (no 404 in production).
class FeatureUnavailable implements Exception {
  const FeatureUnavailable(this.feature);
  final String feature;
  @override
  String toString() => 'FeatureUnavailable($feature)';
}

bool isFeatureUnavailable(Object? error) => error is FeatureUnavailable;

/// Friendly placeholder for a disabled feature.
class FeatureUnavailableView extends StatelessWidget {
  const FeatureUnavailableView({super.key, this.message});
  final String? message;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(InsightSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.hourglass_empty_rounded,
                size: 40, color: context.ds.textLow),
            const SizedBox(height: InsightSpacing.md),
            Text(
              message ?? 'Em breve.',
              style: context.tt.titleSmall,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: InsightSpacing.xs),
            Text(
              'Este recurso ainda não está disponível nesta versão.',
              style:
                  context.tt.bodySmall?.copyWith(color: context.ds.textLow),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}
