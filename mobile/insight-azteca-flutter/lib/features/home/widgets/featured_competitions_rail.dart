import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';
import 'package:shimmer/shimmer.dart';

import '../../../models/competition.dart';
import '../../../providers/competition_provider.dart';
import '../../../routing/routes.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/spacing.dart';

/// Featured Competitions Rail (AZTECA-HOME-A).
///
/// The authoritative competition entry point below the Home header. 100%
/// backend-driven: the entries, their order, and the `featured` emphasis all
/// come from insight-social via `GET /v1/competitions/highlights`. There is NO
/// mock data and the client never re-sorts the list. A `featured` competition
/// (currently Copa do Mundo, configured in the backend) renders larger, first,
/// and with a "Destaque" badge + highlight.
class FeaturedCompetitionsRail extends ConsumerWidget {
  const FeaturedCompetitionsRail({super.key});

  static const double _height = 116;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(featuredCompetitionsProvider);
    return SizedBox(
      height: _height,
      child: async.when(
        loading: () => const _RailSkeleton(),
        // A transient backend hiccup must not break Home — show nothing rather
        // than an error band in the header area.
        error: (_, __) => const SizedBox.shrink(),
        data: (items) {
          if (items.isEmpty) return const _RailEmpty();
          return ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(
              horizontal: InsightSpacing.pageHorizontal,
            ),
            itemCount: items.length,
            separatorBuilder: (_, __) =>
                const SizedBox(width: InsightSpacing.md),
            // Order is exactly as returned by the backend.
            itemBuilder: (_, i) => _CompetitionTile(competition: items[i]),
          );
        },
      ),
    );
  }
}

class _CompetitionTile extends StatelessWidget {
  const _CompetitionTile({required this.competition});

  final Competition competition;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final featured = competition.featured;
    final width = featured ? 132.0 : 104.0;
    final discSize = featured ? 56.0 : 48.0;

    return SizedBox(
      width: width,
      child: Material(
        color: featured ? ds.signal.withValues(alpha: 0.08) : ds.subtle,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: () => context.go(R.radar),
          child: Container(
            padding: const EdgeInsets.symmetric(
              horizontal: InsightSpacing.sm,
              vertical: InsightSpacing.md,
            ),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(16),
              border: Border.all(
                color: featured ? ds.signal.withValues(alpha: 0.55) : ds.divider,
                width: featured ? 1.2 : 0.8,
              ),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // Icon disc (emoji from the backend `icon` field).
                Container(
                  width: discSize,
                  height: discSize,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: featured
                        ? ds.signal.withValues(alpha: 0.16)
                        : context.scheme.surface,
                    border: Border.all(
                      color: featured
                          ? ds.signal.withValues(alpha: 0.5)
                          : ds.divider,
                      width: 1,
                    ),
                  ),
                  child: Text(
                    competition.icon ?? '⚽',
                    style: TextStyle(fontSize: featured ? 26 : 22),
                  ),
                ),
                const SizedBox(height: InsightSpacing.sm),
                Text(
                  competition.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: context.tt.labelMedium?.copyWith(
                    color: featured ? ds.textHigh : ds.textMid,
                    fontWeight: featured ? FontWeight.w700 : FontWeight.w600,
                  ),
                ),
                if (featured) ...[
                  const SizedBox(height: 3),
                  _FeaturedBadge(),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _FeaturedBadge extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1.5),
      decoration: BoxDecoration(
        color: ds.signal,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.star_rounded, size: 10, color: Colors.white),
          const SizedBox(width: 3),
          Text(
            'Destaque',
            style: context.tt.labelSmall?.copyWith(
              fontSize: 9,
              height: 1,
              color: Colors.white,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

class _RailEmpty extends StatelessWidget {
  const _RailEmpty();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: InsightSpacing.pageHorizontal,
        ),
        child: Text(
          'Nenhuma competição em destaque no momento.',
          style: context.tt.bodySmall?.copyWith(color: context.ds.textLow),
        ),
      ),
    );
  }
}

class _RailSkeleton extends StatelessWidget {
  const _RailSkeleton();

  @override
  Widget build(BuildContext context) {
    return Shimmer.fromColors(
      baseColor: context.ds.subtle,
      highlightColor: context.ds.divider.withValues(alpha: 0.4),
      period: const Duration(milliseconds: 1100),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(
          horizontal: InsightSpacing.pageHorizontal,
        ),
        itemCount: 5,
        separatorBuilder: (_, __) => const SizedBox(width: InsightSpacing.md),
        itemBuilder: (_, i) => Container(
          width: i == 0 ? 132 : 104,
          decoration: BoxDecoration(
            color: context.ds.subtle,
            borderRadius: BorderRadius.circular(16),
          ),
        ),
      ),
    );
  }
}
