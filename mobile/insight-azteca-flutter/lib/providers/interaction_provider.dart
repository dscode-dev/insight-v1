// AZTECA-SOCIAL-A — Saved Posts + Boost interaction state, per POST.
//
// Mirrors ReactionNotifier (likes): family-keyed by post id, optimistic toggle
// with a VISIBLE pending flag while the request is in flight, and rollback on
// failure. insight-social is the source of truth — the client never persists
// locally and never computes ranking; Boost only records the toggle and the
// backend returns the resulting count.
//
// State persists across screen pops (open thread → save → pop keeps the save)
// because the family provider is shared across screens.
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/social_service.dart';

class InteractionSnapshot {
  const InteractionSnapshot({
    required this.saved,
    required this.boosted,
    required this.boostCount,
  });

  final bool saved;
  final bool boosted;
  final int boostCount;
}

class InteractionSnapshotsNotifier
    extends StateNotifier<Map<String, InteractionSnapshot>> {
  InteractionSnapshotsNotifier() : super(const {});

  void merge(Map<String, PostInteractionStateDto> states) {
    if (states.isEmpty) return;
    state = {
      ...state,
      for (final entry in states.entries)
        entry.key: InteractionSnapshot(
          saved: entry.value.saved,
          boosted: entry.value.boosted,
          boostCount: entry.value.boostCount,
        ),
    };
  }

  void setSaved(String postId, bool saved) {
    final current = state[postId] ??
        const InteractionSnapshot(saved: false, boosted: false, boostCount: 0);
    state = {
      ...state,
      postId: InteractionSnapshot(
          saved: saved,
          boosted: current.boosted,
          boostCount: current.boostCount)
    };
  }

  void setBoost(String postId, {required bool boosted, required int count}) {
    final current = state[postId] ??
        const InteractionSnapshot(saved: false, boosted: false, boostCount: 0);
    state = {
      ...state,
      postId: InteractionSnapshot(
          saved: current.saved, boosted: boosted, boostCount: count)
    };
  }
}

final interactionSnapshotsProvider = StateNotifierProvider<
    InteractionSnapshotsNotifier, Map<String, InteractionSnapshot>>(
  (_) => InteractionSnapshotsNotifier(),
);

/// Saved (bookmark) state for one post.
class SaveState {
  const SaveState({required this.saved, this.pending = false});
  final bool saved;
  final bool pending;

  SaveState copyWith({bool? saved, bool? pending}) =>
      SaveState(saved: saved ?? this.saved, pending: pending ?? this.pending);

  static const zero = SaveState(saved: false);
}

class SaveNotifier extends StateNotifier<SaveState> {
  SaveNotifier({required this.ref, required this.postId})
      : super(SaveState.zero);

  final Ref ref;
  final String postId;
  bool _inFlight = false;

  /// Seed from a server snapshot (when the feed/post starts carrying
  /// `saved_by_me`). Won't clobber an in-flight optimistic value.
  void hydrate(bool saved) {
    if (_inFlight) return;
    state = SaveState(saved: saved);
  }

  Future<void> toggle() async {
    if (_inFlight) return;
    _inFlight = true;
    final prev = state;
    final next = !prev.saved;
    state = SaveState(saved: next, pending: true); // optimistic + pending
    try {
      final api = ref.read(socialApiProvider);
      if (next) {
        await api.save(postId);
      } else {
        await api.unsave(postId);
      }
      ref.read(interactionSnapshotsProvider.notifier).setSaved(postId, next);
      state = SaveState(saved: next);
    } catch (_) {
      state = prev; // rollback
    } finally {
      _inFlight = false;
    }
  }
}

final saveNotifierProvider =
    StateNotifierProvider.autoDispose.family<SaveNotifier, SaveState, String>(
  (ref, postId) => SaveNotifier(ref: ref, postId: postId),
);

/// Boost state for one post: whether the caller boosted it + the post's active
/// boost count (server-owned).
class BoostState {
  const BoostState(
      {required this.boosted, required this.count, this.pending = false});
  final bool boosted;
  final int count;
  final bool pending;

  BoostState copyWith({bool? boosted, int? count, bool? pending}) => BoostState(
        boosted: boosted ?? this.boosted,
        count: count ?? this.count,
        pending: pending ?? this.pending,
      );

  static const zero = BoostState(boosted: false, count: 0);
}

class BoostNotifier extends StateNotifier<BoostState> {
  BoostNotifier({required this.ref, required this.postId})
      : super(BoostState.zero);

  final Ref ref;
  final String postId;
  bool _inFlight = false;

  void hydrate({required bool boosted, required int count}) {
    if (_inFlight) return;
    state = BoostState(boosted: boosted, count: count);
  }

  Future<void> toggle() async {
    if (_inFlight) return;
    _inFlight = true;
    final prev = state;
    final next = !prev.boosted;
    state = BoostState(
      boosted: next,
      count: (prev.count + (next ? 1 : -1)).clamp(0, 1 << 31),
      pending: true,
    );
    try {
      final api = ref.read(socialApiProvider);
      if (next) {
        await api.boost(postId);
      } else {
        await api.unboost(postId);
      }
      ref
          .read(interactionSnapshotsProvider.notifier)
          .setBoost(postId, boosted: next, count: state.count);
      state = state.copyWith(pending: false);
    } catch (_) {
      state = prev; // rollback
    } finally {
      _inFlight = false;
    }
  }
}

final boostNotifierProvider =
    StateNotifierProvider.autoDispose.family<BoostNotifier, BoostState, String>(
  (ref, postId) => BoostNotifier(ref: ref, postId: postId),
);
