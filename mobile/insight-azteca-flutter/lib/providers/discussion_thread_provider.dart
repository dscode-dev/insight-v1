// Sprint A — Discussion thread state.
//
// Two providers, both family-keyed by discussion_id:
//
//   * discussionDetailProvider(id)
//       AutoDispose<AsyncValue<DiscussionDetail?>> — header. Returns
//       null on 404 so the screen renders an EmptyState rather than
//       blowing up. Invalidated by the reply notifier so the reply
//       count refreshes after a successful post.
//
//   * discussionThreadNotifierProvider(id)
//       AutoDispose StateNotifier over a typed ThreadState — owns the
//       paged messages list + the reply mutation. Optimistically
//       prepends a local message on submit, then reconciles with the
//       server's id when the POST resolves.
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../models/discussion_thread.dart';
import '../providers/auth_provider.dart';
import '../services/discussion_service.dart';
import '../services/services_providers.dart';

const _uuid = Uuid();

// ---- header ----

final discussionDetailProvider = FutureProvider.autoDispose
    .family<DiscussionDetail?, String>((ref, id) async {
  final svc = ref.watch(discussionServiceProvider);
  return svc.get(id);
});

// ---- thread state ----

/// ThreadState carries the paged messages + transient reply UI state.
/// Pure value type so it's cheap to copy on every mutation.
class ThreadState {
  const ThreadState({
    required this.messages,
    required this.nextCursor,
    required this.isLoadingInitial,
    required this.isLoadingMore,
    required this.isPosting,
    this.loadError,
    this.postError,
  });

  final List<DiscussionMessage> messages;
  final String? nextCursor; // null = no more pages
  final bool isLoadingInitial;
  final bool isLoadingMore;
  final bool isPosting;
  final Object? loadError;
  final Object? postError;

  bool get hasMore => nextCursor != null;

  static const empty = ThreadState(
    messages: [],
    nextCursor: null,
    isLoadingInitial: true,
    isLoadingMore: false,
    isPosting: false,
  );

  ThreadState copyWith({
    List<DiscussionMessage>? messages,
    String? nextCursor,
    bool? isLoadingInitial,
    bool? isLoadingMore,
    bool? isPosting,
    Object? loadError,
    Object? postError,
    bool clearLoadError = false,
    bool clearPostError = false,
    bool clearNextCursor = false,
  }) {
    return ThreadState(
      messages: messages ?? this.messages,
      nextCursor: clearNextCursor ? null : (nextCursor ?? this.nextCursor),
      isLoadingInitial: isLoadingInitial ?? this.isLoadingInitial,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      isPosting: isPosting ?? this.isPosting,
      loadError: clearLoadError ? null : (loadError ?? this.loadError),
      postError: clearPostError ? null : (postError ?? this.postError),
    );
  }
}

class DiscussionThreadNotifier extends StateNotifier<ThreadState> {
  DiscussionThreadNotifier({
    required this.ref,
    required this.discussionId,
  }) : super(ThreadState.empty) {
    // Kick off the initial fetch AFTER the current build phase. The
    // notifier is first instantiated when a widget calls `ref.watch`
    // during its build — calling `loadInitial()` synchronously here
    // would mutate `state` while Riverpod is mid-watch, which trips
    // the `_debugCanModifyProviders` assertion. Microtask defers the
    // mutation until the build is finished.
    Future.microtask(loadInitial);
  }

  final Ref ref;
  final String discussionId;

  DiscussionService get _svc => ref.read(discussionServiceProvider);

  Future<void> loadInitial() async {
    state = state.copyWith(isLoadingInitial: true, clearLoadError: true);
    try {
      final page = await _svc.messages(discussionId);
      state = state.copyWith(
        messages: page.messages,
        nextCursor: page.nextCursor,
        clearNextCursor: page.nextCursor == null,
        isLoadingInitial: false,
      );
    } catch (e) {
      state = state.copyWith(isLoadingInitial: false, loadError: e);
    }
  }

  Future<void> loadMore() async {
    if (state.isLoadingMore || !state.hasMore) return;
    state = state.copyWith(isLoadingMore: true, clearLoadError: true);
    try {
      final page = await _svc.messages(discussionId, cursor: state.nextCursor);
      state = state.copyWith(
        messages: [...state.messages, ...page.messages],
        nextCursor: page.nextCursor,
        clearNextCursor: page.nextCursor == null,
        isLoadingMore: false,
      );
    } catch (e) {
      state = state.copyWith(isLoadingMore: false, loadError: e);
    }
  }

  /// Posts a reply. Optimistic: prepends a local message immediately,
  /// then replaces it with the server's persisted message when the
  /// POST resolves. On failure, removes the optimistic entry + surfaces
  /// the error so the composer can present a retry.
  Future<bool> postReply(String body) async {
    final trimmed = body.trim();
    if (trimmed.isEmpty) return false;

    final user = ref.read(authProvider).user;
    final tempId = 'local_${_uuid.v4()}';
    final optimistic = DiscussionMessage(
      id: tempId,
      authorId: user?.id ?? 'me',
      authorDisplayName: user?.displayName ?? 'Você',
      authorInitials: _initials(user?.displayName ?? 'Você'),
      authorAccent: user?.accentColor ?? '#5BA8FF',
      body: trimmed,
      ts: DateTime.now(),
    );

    state = state.copyWith(
      messages: [...state.messages, optimistic],
      isPosting: true,
      clearPostError: true,
    );

    try {
      final persisted = await _svc.postMessage(discussionId, body: trimmed);
      // Replace the optimistic placeholder with the persisted record.
      final updated = state.messages
          .map((m) => m.id == tempId ? persisted : m)
          .toList(growable: false);
      state = state.copyWith(messages: updated, isPosting: false);
      // Refresh the header so the reply count stays in sync.
      ref.invalidate(discussionDetailProvider(discussionId));
      return true;
    } catch (e) {
      // Roll back the optimistic insert.
      final rolledBack =
          state.messages.where((m) => m.id != tempId).toList(growable: false);
      state = state.copyWith(
        messages: rolledBack,
        isPosting: false,
        postError: e,
      );
      return false;
    }
  }

  String _initials(String name) {
    final parts = name.trim().split(RegExp(r'\s+'));
    if (parts.isEmpty || parts.first.isEmpty) return 'EU';
    if (parts.length == 1) {
      return parts.first
          .substring(0, parts.first.length.clamp(0, 2))
          .toUpperCase();
    }
    return (parts.first[0] + parts.last[0]).toUpperCase();
  }
}

final discussionThreadNotifierProvider = StateNotifierProvider.autoDispose
    .family<DiscussionThreadNotifier, ThreadState, String>((ref, id) {
  return DiscussionThreadNotifier(ref: ref, discussionId: id);
});
