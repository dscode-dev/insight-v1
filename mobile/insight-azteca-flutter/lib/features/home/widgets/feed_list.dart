import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../providers/feed_provider.dart';
import '../../../providers/moderation_provider.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/strings/pt_br.dart';
import '../../../widgets/empty_state.dart';
import '../../../widgets/error_state.dart';
import '../../../widgets/offline_state.dart';
import '../../../widgets/skeleton.dart';
import 'feed_item.dart';
import 'feed_skeleton.dart';

/// Infinite-scrolling, pull-to-refresh feed.
///
/// Uses a `ScrollController` + `addListener` for end-of-list detection
/// rather than a sentinel widget — it stays inside the SliverList without
/// extra widget churn. Pull-to-refresh is the native Material 3 indicator.
class FeedList extends HookConsumerWidget {
  const FeedList({
    super.key,
    required this.scrollController,
    this.onOpenMatch,
    this.headerSlivers = const <Widget>[],
  });

  /// Provided by the Home screen so the same controller drives end-of-list
  /// detection and any future scroll-aware affordances (FAB hide, etc.).
  final ScrollController scrollController;
  final ValueChanged<String>? onOpenMatch;

  /// Sliver-shaped widgets inserted ABOVE the feed (Quick Pulse, Composer).
  /// Kept here so the same CustomScrollView covers the whole page — one
  /// scroll surface, one pull-to-refresh.
  final List<Widget> headerSlivers;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncState = ref.watch(feedProvider);

    // End-of-list detection: when the user scrolls to within ~600px of the
    // bottom, ask the notifier to fetch the next page.
    useEffect(() {
      void onScroll() {
        if (!scrollController.hasClients) return;
        final pos = scrollController.position;
        if (pos.pixels >= pos.maxScrollExtent - 600) {
          // ignore: discarded_futures
          ref.read(feedProvider.notifier).loadMore();
        }
      }
      scrollController.addListener(onScroll);
      return () => scrollController.removeListener(onScroll);
    }, [scrollController]);

    return RefreshIndicator(
      onRefresh: () => ref.read(feedProvider.notifier).refresh(),
      color: context.ds.signal,
      backgroundColor: context.ds.card,
      child: CustomScrollView(
        controller: scrollController,
        physics: const AlwaysScrollableScrollPhysics(),
        // Azteca-X Part 5: dragging the feed dismisses the keyboard
        // (e.g. after composing/search) — production keyboard behavior.
        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
        slivers: [
          ...headerSlivers,
          asyncState.when(
            loading: () => const SliverToBoxAdapter(child: FeedListSkeleton(count: 4)),
            // Part 11: connectivity failures get the offline state
            // (the fix is on the user's side); everything else keeps
            // the generic error + retry.
            error: (e, _) => SliverFillRemaining(
              hasScrollBody: false,
              child: isOfflineError(e)
                  ? OfflineState(
                      onRetry: () =>
                          ref.read(feedProvider.notifier).refresh(),
                    )
                  : ErrorState(
                      title: S.feedErrorTitle,
                      description: S.feedErrorDescription,
                      onRetry: () =>
                          ref.read(feedProvider.notifier).refresh(),
                    ),
            ),
            data: (state) {
              // Store-A: optimistic local hide — drop blocked authors' posts
              // and individually hidden posts the instant the user acts, on
              // top of the Gateway's own server-side filtering.
              final blocked = ref.watch(blockedUsersProvider);
              final hidden = ref.watch(hiddenPostsProvider);
              final items = state.items
                  .where((p) =>
                      !blocked.contains(p.author.id) && !hidden.contains(p.id))
                  .toList();
              if (items.isEmpty) {
                return const SliverFillRemaining(
                  hasScrollBody: false,
                  child: EmptyState(
                    title: S.feedEmptyTitle,
                    description: S.feedEmptyDescription,
                  ),
                );
              }
              return SliverList.separated(
                itemCount: items.length + 1,
                itemBuilder: (context, i) {
                  if (i == items.length) {
                    // Floating bottom nav (~64dp) + margin (~16) + safe
                    // area + comfortable buffer for the ComposeFab that
                    // sits 80dp above the nav. 160dp keeps the last
                    // tappable element well above both.
                    const trailingInset = SizedBox(height: 160);
                    if (state.isLoadingMore) {
                      return const Skeleton(child: FeedItemSkeleton());
                    }
                    if (!state.hasMore && items.length > 3) {
                      return Padding(
                        padding: const EdgeInsets.only(
                          top: 24,
                          bottom: 160,
                        ),
                        child: Center(
                          child: Text(
                            S.feedEnd,
                            style: context.tt.labelSmall
                                ?.copyWith(color: context.ds.textLow),
                          ),
                        ),
                      );
                    }
                    return trailingInset;
                  }
                  return FeedItem(
                    post: items[i],
                    onOpenMatch: onOpenMatch,
                  );
                },
                separatorBuilder: (context, _) => Divider(
                  height: 1,
                  thickness: 0.6,
                  color: context.ds.divider,
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

