// FEATURE-COMMUNITIES-V1 Stage 3 — controller behaviour:
// optimistic join/leave + rollback, members pagination + dedupe, role filter
// reuses the same endpoint (no parallel owner/admin calls).
// ignore_for_file: prefer_const_constructors
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:azteca/features/hub/community/data/community_service.dart';
import 'package:azteca/features/hub/community/model/community_models.dart';
import 'package:azteca/features/hub/community/state/community_providers.dart';

CommunityDetail _detail({
  String viewerRole = 'none',
  String status = 'not_member',
  int members = 10,
  CommunityCapabilities caps = CommunityCapabilities.none,
}) =>
    CommunityDetail(
      id: 'c1', slug: 'tatica-fc', name: 'Tática FC', description: '', avatarUrl: '',
      bannerUrl: '', accentColor: '#5BA8FF', kind: 'topic', privacy: 'public',
      deepLink: '/hub/community/c1', memberCount: members, discussionCount: 0, onlineCount: 0,
      roleCounts: RoleCounts.zero, viewerRole: viewerRole, membershipStatus: status,
      ownerAssigned: true, capabilities: caps, partial: false, failedSections: const [],
    );

class _FakeService extends CommunityService {
  _FakeService() : super(Dio());

  CommunityDetail detailResult = _detail(
    caps: const CommunityCapabilities(
      canJoin: true, canLeave: false, canCreateDiscussion: false, canDeleteDiscussion: false,
      canManageMembers: false, canInviteMembers: false, canManageSettings: false, canViewAdminPanel: false,
    ),
  );
  Object? joinError;
  MembershipResult joinResult = const MembershipResult(
    communityId: 'c1', viewerRole: 'member', membershipStatus: 'member', memberCount: 11,
    capabilities: CommunityCapabilities(
      canJoin: false, canLeave: true, canCreateDiscussion: true, canDeleteDiscussion: false,
      canManageMembers: false, canInviteMembers: false, canManageSettings: false, canViewAdminPanel: false,
    ),
  );

  final List<String?> memberRoleCalls = [];
  List<MembersPage> memberPages = const [];
  int _memberPage = 0;

  @override
  Future<CommunityDetail> detail(String id, {CancelToken? cancel}) async => detailResult;

  @override
  Future<MembershipResult> join(String id, {CancelToken? cancel}) async {
    if (joinError != null) throw joinError!;
    return joinResult;
  }

  @override
  Future<MembersPage> members(String id, {String? cursor, String? role, CancelToken? cancel}) async {
    memberRoleCalls.add(role);
    if (_memberPage < memberPages.length) return memberPages[_memberPage++];
    return const MembersPage(members: [], nextCursor: '', roleFilter: '');
  }
}

ProviderContainer _container(_FakeService svc) {
  final c = ProviderContainer(overrides: [communityServiceProvider.overrideWithValue(svc)]);
  addTearDown(c.dispose);
  return c;
}

/// Keep an autoDispose family provider alive for the duration of a test (no
/// widget is listening, so without this the controller is disposed + recreated
/// between reads, restarting its constructor load()).
void _keep<T>(ProviderContainer c, ProviderListenable<T> p) {
  final sub = c.listen(p, (_, __) {});
  addTearDown(sub.close);
}

CommunityMember _m(String id, String role) => CommunityMember(
      userId: id, username: id, displayName: id, initials: 'X', accentColor: '#fff',
      avatarUrl: '', reputation: 0, role: role, deepLink: '/users/$id',
    );

void main() {
  test('detail loads the aggregate', () async {
    final svc = _FakeService();
    final c = _container(svc);
    _keep(c, communityDetailProvider('c1'));
    await Future<void>.delayed(Duration.zero);
    final s = c.read(communityDetailProvider('c1'));
    expect(s.phase, Loadable.ready);
    expect(s.detail!.capabilities.canJoin, true);
  });

  test('optimistic join flips membership + count, then applies SERVER capabilities', () async {
    final svc = _FakeService();
    final c = _container(svc);
    _keep(c, communityDetailProvider('c1'));
    await Future<void>.delayed(Duration.zero);

    final notifier = c.read(communityDetailProvider('c1').notifier);
    final future = notifier.join();
    // Optimistic frame: already a member, count bumped, button busy.
    var s = c.read(communityDetailProvider('c1'));
    expect(s.detail!.membershipStatus, 'member');
    expect(s.detail!.memberCount, 11);
    expect(s.membershipBusy, true);

    await future;
    s = c.read(communityDetailProvider('c1'));
    // Server authoritative capabilities applied (can_leave now true).
    expect(s.membershipBusy, false);
    expect(s.detail!.capabilities.canLeave, true);
    expect(s.detail!.capabilities.canJoin, false);
  });

  test('join error ROLLS BACK to the pre-action snapshot', () async {
    final svc = _FakeService()..joinError = Exception('boom');
    final c = _container(svc);
    _keep(c, communityDetailProvider('c1'));
    await Future<void>.delayed(Duration.zero);

    final notifier = c.read(communityDetailProvider('c1').notifier);
    await notifier.join();
    final s = c.read(communityDetailProvider('c1'));
    // Back to not_member with original count; not left in an optimistic state.
    expect(s.detail!.membershipStatus, 'not_member');
    expect(s.detail!.memberCount, 10);
    expect(s.membershipBusy, false);
  });

  test('members paginate with dedupe by user id', () async {
    final svc = _FakeService()
      ..memberPages = [
        MembersPage(members: [_m('u1', 'owner'), _m('u2', 'member')], nextCursor: 'p2', roleFilter: ''),
        MembersPage(members: [_m('u2', 'member'), _m('u3', 'member')], nextCursor: '', roleFilter: ''),
      ];
    final c = _container(svc);
    _keep(c, communityMembersProvider('c1'));
    await Future<void>.delayed(Duration.zero);
    final notifier = c.read(communityMembersProvider('c1').notifier);

    await notifier.loadMore();
    final s = c.read(communityMembersProvider('c1'));
    // u2 must not duplicate across pages.
    expect(s.members.map((m) => m.userId).toList(), ['u1', 'u2', 'u3']);
    expect(s.hasMore, false);
  });

  test('role filter reuses the SAME members endpoint (no parallel owner/admin calls)', () async {
    final svc = _FakeService()
      ..memberPages = [const MembersPage(members: [], nextCursor: '', roleFilter: '')];
    final c = _container(svc);
    _keep(c, communityMembersProvider('c1'));
    await Future<void>.delayed(Duration.zero);
    final notifier = c.read(communityMembersProvider('c1').notifier);

    await notifier.setRoleFilter('admin');
    await Future<void>.delayed(Duration.zero);
    // First call (initial load) role='', then the filtered call role='admin'.
    expect(svc.memberRoleCalls.contains('admin'), true);
    // Exactly one endpoint used — never three parallel role calls.
    expect(svc.memberRoleCalls.where((r) => r == 'admin').length, 1);
  });
}
