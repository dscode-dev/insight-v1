import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/logger.dart';
import '../services/moderation_service.dart';
import '../services/services_providers.dart';

/// Store-A — client moderation state.
///
/// Two session sets drive OPTIMISTIC local hiding so content disappears the
/// instant the user acts, before any backend round-trip (and on top of the
/// Gateway's own server-side filtering on the next fetch):
///   * [blockedUsersProvider] — author ids the user blocked → their posts +
///     comments are filtered out of the feed locally.
///   * [hiddenPostsProvider]  — individual post ids the user chose to hide
///     (e.g. after reporting) → removed from the feed locally.

class BlockedUsersNotifier extends Notifier<Set<String>> {
  @override
  Set<String> build() => <String>{};

  /// Optimistically blocks [userId] (hides immediately), then persists to the
  /// Gateway. Reverts on failure. Returns true on success.
  Future<bool> block(String userId) async {
    if (state.contains(userId)) return true;
    state = {...state, userId};
    try {
      await ref.read(moderationApiProvider).blockUser(userId);
      return true;
    } catch (e) {
      L.w('moderation', 'block_failed', data: e);
      state = {...state}..remove(userId); // revert optimistic hide
      return false;
    }
  }

  Future<bool> unblock(String userId) async {
    final had = state.contains(userId);
    state = {...state}..remove(userId);
    try {
      await ref.read(moderationApiProvider).unblockUser(userId);
      return true;
    } catch (e) {
      L.w('moderation', 'unblock_failed', data: e);
      if (had) state = {...state, userId}; // revert
      return false;
    }
  }

  bool isBlocked(String userId) => state.contains(userId);
}

final blockedUsersProvider =
    NotifierProvider<BlockedUsersNotifier, Set<String>>(
        BlockedUsersNotifier.new);

class HiddenPostsNotifier extends Notifier<Set<String>> {
  @override
  Set<String> build() => <String>{};

  void hide(String postId) => state = {...state, postId};
}

final hiddenPostsProvider =
    NotifierProvider<HiddenPostsNotifier, Set<String>>(HiddenPostsNotifier.new);

/// Files a content report. Throws on transport failure so the caller can show
/// an error; success path shows the confirmation.
Future<void> submitReport(
  WidgetRef ref, {
  required ReportTarget target,
  required String targetId,
  required ReportReason reason,
  String? description,
}) {
  return ref.read(moderationApiProvider).report(
        target: target,
        targetId: targetId,
        reason: reason,
        description: description,
      );
}
