import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../providers/feed_provider.dart';
import '../../providers/nav_visibility_provider.dart';
import '../../routing/routes.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../shared/strings/pt_br.dart';
import '../../widgets/nav_scroll_listener.dart';
import '../../widgets/notifications_action.dart';
import '../../widgets/search_action.dart';
import 'widgets/compose_fab.dart';
import 'widgets/feed_list.dart';
import 'widgets/new_posts_toast.dart';
import 'widgets/featured_competitions_rail.dart';

/// Home — the social timeline.
///
/// One CustomScrollView covers the whole page so scroll position and
/// pull-to-refresh behave as a single surface. The top bar is a
/// `SliverAppBar(floating: true, snap: true)` so it auto-hides when the
/// user scrolls down to read and snaps back as soon as they pull up.
/// The backend-driven FeaturedCompetitionsRail sits as its own sliver below
/// the header (24dp above / 20dp below) and scrolls with the feed.
///
/// Posting lives in a `ComposeFab` (bottom-right pill), not an inline
/// row at the top of the feed — the inline composer was crowding the
/// match reads.
class HomeScreen extends HookConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = useScrollController();
    // The "X novos posts" pill is driven by realtimeCoordinatorProvider
    // (mounted in InsightApp) — bumps come from HUMAN_SIGNAL /
    // AGENT_INSIGHT events on the SSE stream (mock fires the first
    // signal after 8s, then every 18s).

    // Plug the same scroll controller into the floating-nav visibility
    // provider so the bottom nav fades on scroll-down + snaps back on
    // scroll-up, in sync with the ComposeFab.
    useNavScrollListener(ref, controller);

    // Sprint 2 (Part 5) — Home-tab re-tap = manual refresh: jump to
    // top, reload page 1, clear the pending-posts pill. Same semantics
    // as tapping the "X novos posts" affordance.
    ref.listen<int>(homeRetapTickProvider, (prev, next) async {
      if (prev == next) return;
      if (controller.hasClients) {
        await controller.animateTo(
          0,
          duration: const Duration(milliseconds: 280),
          curve: Curves.easeOutCubic,
        );
      }
      ref.read(pendingNewPostsProvider.notifier).state = 0;
      await ref.read(feedProvider.notifier).refresh();
    });

    return Scaffold(
      body: Stack(
        children: [
          FeedList(
            scrollController: controller,
            onOpenMatch: (matchId) => context.go(R.matchDetailFor(matchId)),
            headerSlivers: [
              SliverAppBar(
                title: const Text(S.appName),
                floating: true,
                snap: true,
                scrolledUnderElevation: 0.5,
                surfaceTintColor: context.ds.signal,
                actions: [
                  IconButton(
                    tooltip: 'Agentes',
                    icon: const Icon(Icons.smart_toy_outlined),
                    onPressed: () => context.push(R.agents),
                  ),
                  const SearchAction(),
                  const NotificationsAction(),
                ],
              ),
              // AZTECA-HOME-A Stage 0: the header (AppBar) breathes into the
              // backend-driven Featured Competitions Rail — 24dp above, 20dp
              // below before the global feed. The rail scrolls with the feed.
              const SliverToBoxAdapter(
                child: Column(
                  children: [
                    SizedBox(height: 24),
                    FeaturedCompetitionsRail(),
                    SizedBox(height: 20),
                  ],
                ),
              ),
            ],
          ),
          // New-posts toast — floats just under the (collapsing) AppBar.
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SafeArea(
              child: NewPostsToast(scrollController: controller),
            ),
          ),
          // Compose pill — bottom-right. The bottom nav is now a fixed
          // `bottomNavigationBar` (the body is laid out above it), so the FAB
          // only needs a small breathing gap from the body's bottom edge — no
          // floating-nav height math.
          Positioned(
            right: 16,
            bottom: 16,
            child: ComposeFab(scrollController: controller),
          ),
        ],
      ),
    );
  }
}
