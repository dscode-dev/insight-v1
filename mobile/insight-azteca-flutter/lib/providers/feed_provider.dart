import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/errors.dart';
import '../core/logger.dart';
import '../models/feed.dart';
import '../models/social.dart';
import '../services/social_mapping.dart';
import '../services/social_service.dart';
import 'interaction_provider.dart';

/// Which Social Foundation feed the home shows.
enum FeedScope { global, following }

/// Active feed scope. Switching it triggers a feed reload (the feed
/// notifier watches it). Global is the default landing feed.
final feedScopeProvider = StateProvider<FeedScope>((_) => FeedScope.global);

/// A mapped feed page (UI models), decoupled from the wire DTO.
typedef MappedFeedPage = ({List<FeedPost> items, String? nextCursor});

/// Stateful feed controller — Social Foundation backed
/// (`/v1/feed/global` and `/v1/feed/following` through the Gateway).
/// Cursor pagination + pull-to-refresh + optimistic prepend (the
/// composer calls `prepend` ONLY after a successful POST /v1/posts).
class FeedListState {
  const FeedListState({
    required this.items,
    required this.nextCursor,
    required this.isLoadingMore,
  });
  final List<FeedPost> items;
  final String? nextCursor;
  final bool isLoadingMore;

  bool get hasMore => nextCursor != null && nextCursor!.isNotEmpty;

  FeedListState copyWith({
    List<FeedPost>? items,
    String? nextCursor,
    bool? isLoadingMore,
    bool clearCursor = false,
  }) =>
      FeedListState(
        items: items ?? this.items,
        nextCursor: clearCursor ? null : (nextCursor ?? this.nextCursor),
        isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      );

  static const empty = FeedListState(
    items: <FeedPost>[],
    nextCursor: null,
    isLoadingMore: false,
  );
}

class FeedNotifier extends AsyncNotifier<FeedListState> {
  SocialApi get _social => ref.read(socialApiProvider);

  Future<MappedFeedPage> _fetch({int? limit, String? cursor}) async {
    final scope = ref.read(feedScopeProvider);
    final page = switch (scope) {
      FeedScope.global =>
        await _social.globalFeed(limit: limit, cursor: cursor),
      FeedScope.following =>
        await _social.followingFeed(limit: limit, cursor: cursor),
    };
    await _hydrateInteractions(page.items);
    return (
      items: page.items.map(feedItemToFeedPost).toList(growable: false),
      nextCursor: page.nextCursor,
    );
  }

  Future<void> _hydrateInteractions(List<SocialFeedItemDto> items) async {
    final ids =
        items.map((item) => item.post.id).where((id) => id.isNotEmpty).toList();
    if (ids.isEmpty) return;
    try {
      final states = await _social.interactionStates(ids);
      ref.read(interactionSnapshotsProvider.notifier).merge(states);
    } catch (e, st) {
      L.w('feed', 'interaction_states.load.failed', data: {
        'error_type': e.runtimeType.toString(),
      });
      L.e('feed', 'interaction_states.load.failed.debug',
          error: e, stackTrace: st);
    }
  }

  @override
  Future<FeedListState> build() async {
    // Rebuild when the scope flips (global ↔ following).
    ref.watch(feedScopeProvider);
    final page = await _fetchLogged('initial');
    return FeedListState(
      items: page.items,
      nextCursor: page.nextCursor,
      isLoadingMore: false,
    );
  }

  /// Pull-to-refresh (and Home re-tap) — discards the cursor, reloads
  /// page 1 of the current scope.
  Future<void> refresh() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      final page = await _fetchLogged('refresh');
      return FeedListState(
        items: page.items,
        nextCursor: page.nextCursor,
        isLoadingMore: false,
      );
    });
  }

  /// Infinite scroll — fetches the next page using the current cursor.
  Future<void> loadMore() async {
    final current = state.valueOrNull;
    if (current == null || !current.hasMore || current.isLoadingMore) return;
    state = AsyncValue.data(current.copyWith(isLoadingMore: true));
    try {
      final page = await _fetchLogged('load_more', cursor: current.nextCursor);
      state = AsyncValue.data(
        FeedListState(
          items: [...current.items, ...page.items],
          nextCursor: page.nextCursor,
          isLoadingMore: false,
        ),
      );
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }

  Future<MappedFeedPage> _fetchLogged(String reason, {String? cursor}) async {
    final scope = ref.read(feedScopeProvider);
    try {
      final page = await _fetch(cursor: cursor);
      L.i(
        'feed',
        'feed.load.success',
        data: {
          'scope': scope.name,
          'reason': reason,
          'items': page.items.length,
          'has_next': page.nextCursor?.isNotEmpty == true,
        },
      );
      return page;
    } catch (e, st) {
      L.w(
        'feed',
        'feed.load.failed',
        data: {
          'scope': scope.name,
          'reason': reason,
          'error_type': e.runtimeType.toString(),
          'offline': e is NetworkException,
          if (e is GatewayException) 'status': e.statusCode,
        },
      );
      L.e('feed', 'feed.load.failed.debug', error: e, stackTrace: st);
      rethrow;
    }
  }

  /// Optimistic prepend — used by the composer AFTER a successful
  /// POST /v1/posts (never on local-only state).
  void prepend(FeedPost post) {
    final current = state.valueOrNull;
    if (current == null) return;
    state = AsyncValue.data(
      current.copyWith(items: [post, ...current.items]),
    );
  }

  /// Reconcile one feed card with a backend-sourced comment count.
  void setCommentCount(String postId, int count) {
    final current = state.valueOrNull;
    if (current == null) return;
    state = AsyncValue.data(
      current.copyWith(
        items: [
          for (final item in current.items)
            if (item.id == postId)
              item.copyWith(
                reactions: item.reactions.copyWith(replies: count),
              )
            else
              item,
        ],
      ),
    );
  }
}

final feedProvider =
    AsyncNotifierProvider<FeedNotifier, FeedListState>(FeedNotifier.new);

/// Counter of new posts the user hasn't seen yet. Driven by the
/// `/v1/feed/updates` poll / SSE channel when wired; tapping the
/// affordance calls FeedNotifier.refresh() AND clears this counter.
final pendingNewPostsProvider = StateProvider<int>((_) => 0);
