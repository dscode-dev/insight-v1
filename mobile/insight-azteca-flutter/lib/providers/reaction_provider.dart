// Reaction state per POST (Social Foundation).
//
// One state per post id; seeded from the FeedPost (likedByMe,
// likeCount). The notifier owns the optimistic toggle: it flips state
// immediately, fires POST/DELETE /v1/posts/{id}/like, and rolls back
// on failure.
//
// Why a notifier instead of inlining hooks in PostActions: the heart
// state must persist across screen pops (open thread → like → pop back
// to feed should keep the like). A family-keyed provider shared across
// screens gives us that for free.
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/social_service.dart';

class ReactionState {
  const ReactionState({required this.liked, required this.count});
  final bool liked;
  final int count;

  ReactionState copyWith({bool? liked, int? count}) =>
      ReactionState(liked: liked ?? this.liked, count: count ?? this.count);

  static const zero = ReactionState(liked: false, count: 0);
}

class ReactionNotifier extends StateNotifier<ReactionState> {
  ReactionNotifier({
    required this.ref,
    required this.postId,
    required ReactionState seed,
  })  : _inFlight = false,
        super(seed);

  final Ref ref;
  final String postId;
  bool _inFlight;

  /// Hydrate from a freshly-seeded snapshot — e.g. when a card mounts
  /// with the feed's (likedByMe, likeCount). Won't run while a toggle
  /// is in flight (would clobber the optimistic value).
  void hydrate(ReactionState fromServer) {
    if (_inFlight) return;
    state = fromServer;
  }

  Future<bool> toggle() async {
    if (_inFlight) return state.liked;
    _inFlight = true;

    final prev = state;
    final next = ReactionState(
      liked: !prev.liked,
      count: (prev.count + (prev.liked ? -1 : 1)).clamp(0, 1 << 31),
    );
    state = next;

    try {
      final api = ref.read(socialApiProvider);
      if (next.liked) {
        await api.like(postId);
      } else {
        await api.unlike(postId);
      }
      return next.liked;
    } catch (_) {
      // Roll back on failure.
      state = prev;
      return prev.liked;
    } finally {
      _inFlight = false;
    }
  }
}

/// Family-keyed by post id. Seed defaults to zero; cards call
/// `notifier.hydrate(...)` right after they read the FeedPost so the
/// heart shows the right starting state.
final reactionNotifierProvider = StateNotifierProvider.autoDispose
    .family<ReactionNotifier, ReactionState, String>((ref, postId) {
  return ReactionNotifier(
    ref: ref,
    postId: postId,
    seed: ReactionState.zero,
  );
});
