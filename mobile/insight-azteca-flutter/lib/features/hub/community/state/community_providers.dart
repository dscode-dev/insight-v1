// FEATURE-COMMUNITIES-V1 Stage 3 — state layer.
//
// Three independent controllers share the same community context but load and
// fail independently, so one failing section never brings down the screen:
//   - CommunityDetailController  : the aggregate, loaded ONCE; optimistic
//                                  join/leave with rollback; capabilities come
//                                  from the server (never inferred from role).
//   - MembersController          : keyset pagination (+ optional role filter).
//   - DiscussionsController      : keyset pagination (community feed).
//
// All are autoDispose.family(communityId) with keepAlive, so switching tabs
// preserves state and never re-fetches the header.

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../data/community_service.dart';
import '../model/community_models.dart';

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

enum Loadable { loading, ready, error }

class DetailState {
  const DetailState({required this.phase, this.detail, this.error, this.membershipBusy = false});
  final Loadable phase;
  final CommunityDetail? detail;
  final Object? error;
  final bool membershipBusy;

  DetailState copyWith({Loadable? phase, CommunityDetail? detail, Object? error, bool? membershipBusy}) =>
      DetailState(
        phase: phase ?? this.phase,
        detail: detail ?? this.detail,
        error: error,
        membershipBusy: membershipBusy ?? this.membershipBusy,
      );

  static const initial = DetailState(phase: Loadable.loading);
}

class CommunityDetailController extends StateNotifier<DetailState> {
  CommunityDetailController(this._service, this._id) : super(DetailState.initial) {
    load();
  }
  final CommunityService _service;
  final String _id;

  Future<void> load() async {
    state = const DetailState(phase: Loadable.loading);
    try {
      final d = await _service.detail(_id);
      state = DetailState(phase: Loadable.ready, detail: d);
    } on CommunityCancelled {
      // ignore
    } catch (e) {
      state = DetailState(phase: Loadable.error, error: e);
    }
  }

  Future<void> join() => _mutate(joining: true);
  Future<void> leave() => _mutate(joining: false);

  Future<void> _mutate({required bool joining}) async {
    final current = state.detail;
    if (current == null || state.membershipBusy) return;

    // Optimistic: flip membership + adjust count immediately; keep the existing
    // capabilities until the server returns the authoritative set. The button
    // shows a busy state via membershipBusy.
    final optimistic = current.withMembership(MembershipResult(
      communityId: current.id,
      viewerRole: joining ? 'member' : 'none',
      membershipStatus: joining ? 'member' : 'not_member',
      memberCount: joining ? current.memberCount + 1 : (current.memberCount - 1).clamp(0, 1 << 31),
      capabilities: current.capabilities,
    ));
    state = state.copyWith(phase: Loadable.ready, detail: optimistic, membershipBusy: true);

    try {
      final res = joining ? await _service.join(_id) : await _service.leave(_id);
      // Authoritative server state (real capabilities included).
      state = state.copyWith(detail: current.withMembership(res), membershipBusy: false);
    } on CommunityCancelled {
      state = state.copyWith(membershipBusy: false);
    } catch (e) {
      // Rollback to the pre-action snapshot; surface the error transiently.
      state = state.copyWith(detail: current, membershipBusy: false, error: e);
    }
  }
}

final communityDetailProvider = StateNotifierProvider.autoDispose
    .family<CommunityDetailController, DetailState, String>((ref, id) {
  final c = CommunityDetailController(ref.watch(communityServiceProvider), id);
  ref.keepAlive();
  return c;
});

// ---------------------------------------------------------------------------
// Members (paginated + optional role filter)
// ---------------------------------------------------------------------------

class MembersState {
  const MembersState({
    required this.phase,
    this.members = const [],
    this.cursor = '',
    this.hasMore = false,
    this.loadingMore = false,
    this.roleFilter = '',
    this.error,
  });
  final Loadable phase;
  final List<CommunityMember> members;
  final String cursor;
  final bool hasMore;
  final bool loadingMore;
  final String roleFilter;
  final Object? error;

  MembersState copyWith({
    Loadable? phase,
    List<CommunityMember>? members,
    String? cursor,
    bool? hasMore,
    bool? loadingMore,
    String? roleFilter,
    Object? error,
  }) =>
      MembersState(
        phase: phase ?? this.phase,
        members: members ?? this.members,
        cursor: cursor ?? this.cursor,
        hasMore: hasMore ?? this.hasMore,
        loadingMore: loadingMore ?? this.loadingMore,
        roleFilter: roleFilter ?? this.roleFilter,
        error: error,
      );

  static const initial = MembersState(phase: Loadable.loading);
}

class MembersController extends StateNotifier<MembersState> {
  MembersController(this._service, this._id) : super(MembersState.initial) {
    load();
  }
  final CommunityService _service;
  final String _id;
  CancelToken? _inflight;

  /// Role filter uses the SAME endpoint — never a parallel owner/admin call.
  Future<void> setRoleFilter(String role) async {
    if (role == state.roleFilter) return;
    state = MembersState(phase: Loadable.loading, roleFilter: role);
    await load();
  }

  Future<void> load() async {
    _inflight?.cancel('superseded');
    final token = _inflight = CancelToken();
    state = state.copyWith(phase: Loadable.loading, members: const [], cursor: '', hasMore: false);
    try {
      final page = await _service.members(_id, role: state.roleFilter, cancel: token);
      state = state.copyWith(
        phase: Loadable.ready, members: page.members, cursor: page.nextCursor, hasMore: page.hasMore,
      );
    } on CommunityCancelled {
      // ignore
    } catch (e) {
      state = state.copyWith(phase: Loadable.error, error: e);
    }
  }

  Future<void> loadMore() async {
    if (!state.hasMore || state.loadingMore || state.cursor.isEmpty) return;
    state = state.copyWith(loadingMore: true);
    final token = CancelToken();
    try {
      final page = await _service.members(_id, cursor: state.cursor, role: state.roleFilter, cancel: token);
      // Dedupe by user id; a page failure preserves already-loaded items.
      final seen = {for (final m in state.members) m.key};
      final merged = [...state.members, ...page.members.where((m) => !seen.contains(m.key))];
      state = state.copyWith(
        members: merged, cursor: page.nextCursor, hasMore: page.hasMore, loadingMore: false, phase: Loadable.ready,
      );
    } on CommunityCancelled {
      state = state.copyWith(loadingMore: false);
    } catch (_) {
      // Preserve loaded items; keep hasMore so the user can retry the page.
      state = state.copyWith(loadingMore: false, phase: Loadable.ready);
    }
  }
}

final communityMembersProvider = StateNotifierProvider.autoDispose
    .family<MembersController, MembersState, String>((ref, id) {
  final c = MembersController(ref.watch(communityServiceProvider), id);
  ref.keepAlive();
  return c;
});

// ---------------------------------------------------------------------------
// Discussions (community feed — paginated)
// ---------------------------------------------------------------------------

class DiscussionsState {
  const DiscussionsState({
    required this.phase,
    this.items = const [],
    this.cursor = '',
    this.hasMore = false,
    this.loadingMore = false,
    this.error,
  });
  final Loadable phase;
  final List<CommunityDiscussion> items;
  final String cursor;
  final bool hasMore;
  final bool loadingMore;
  final Object? error;

  DiscussionsState copyWith({
    Loadable? phase,
    List<CommunityDiscussion>? items,
    String? cursor,
    bool? hasMore,
    bool? loadingMore,
    Object? error,
  }) =>
      DiscussionsState(
        phase: phase ?? this.phase,
        items: items ?? this.items,
        cursor: cursor ?? this.cursor,
        hasMore: hasMore ?? this.hasMore,
        loadingMore: loadingMore ?? this.loadingMore,
        error: error,
      );

  static const initial = DiscussionsState(phase: Loadable.loading);
}

class DiscussionsController extends StateNotifier<DiscussionsState> {
  DiscussionsController(this._service, this._id) : super(DiscussionsState.initial) {
    load();
  }
  final CommunityService _service;
  final String _id;

  Future<void> load() async {
    state = const DiscussionsState(phase: Loadable.loading);
    try {
      final page = await _service.discussions(_id);
      state = state.copyWith(
        phase: Loadable.ready, items: page.discussions, cursor: page.nextCursor, hasMore: page.hasMore,
      );
    } on CommunityCancelled {
      // ignore
    } catch (e) {
      state = state.copyWith(phase: Loadable.error, error: e);
    }
  }

  Future<void> loadMore() async {
    if (!state.hasMore || state.loadingMore || state.cursor.isEmpty) return;
    state = state.copyWith(loadingMore: true);
    try {
      final page = await _service.discussions(_id, cursor: state.cursor);
      final seen = {for (final d in state.items) d.key};
      final merged = [...state.items, ...page.discussions.where((d) => !seen.contains(d.key))];
      state = state.copyWith(
        items: merged, cursor: page.nextCursor, hasMore: page.hasMore, loadingMore: false, phase: Loadable.ready,
      );
    } on CommunityCancelled {
      state = state.copyWith(loadingMore: false);
    } catch (_) {
      state = state.copyWith(loadingMore: false, phase: Loadable.ready);
    }
  }
}

final communityDiscussionsProvider = StateNotifierProvider.autoDispose
    .family<DiscussionsController, DiscussionsState, String>((ref, id) {
  final c = DiscussionsController(ref.watch(communityServiceProvider), id);
  ref.keepAlive();
  return c;
});
