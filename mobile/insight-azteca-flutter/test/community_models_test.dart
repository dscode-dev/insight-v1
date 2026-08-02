// FEATURE-COMMUNITIES-V1 Stage 3 — model + deep-link contract tests.
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/features/hub/community/model/community_models.dart';
import 'package:azteca/features/hub/community/navigation/community_deep_link.dart';

void main() {
  test('CommunityDetail.fromJson parses the aggregate WITHOUT a members array', () {
    final d = CommunityDetail.fromJson(const {
      'id': 'c1',
      'slug': 'tatica-fc',
      'name': 'Tática FC',
      'description': '4-3-3',
      'accent_color': '#5BA8FF',
      'kind': 'topic',
      'privacy': 'public',
      'deep_link': '/hub/community/c1',
      'member_count': 10,
      'discussion_count': 4,
      'online_count': 3,
      'role_counts': {'owner': 1, 'admin': 1, 'moderator': 2, 'member': 6},
      'viewer_role': 'member',
      'membership_status': 'member',
      'owner_assigned': true,
      'capabilities': {'can_leave': true, 'can_create_discussion': true},
      'partial': false,
      // NOTE: deliberately NO 'members' key — the old required field is gone.
    });
    expect(d.name, 'Tática FC');
    expect(d.isMember, true);
    expect(d.roleCounts.total, 10);
    expect(d.capabilities.canLeave, true);
    expect(d.capabilities.canManageMembers, false); // absent => false, never inferred
  });

  test('capabilities default to all-false when absent (no accidental admin UI)', () {
    final caps = CommunityCapabilities.fromJson(null);
    expect(caps.canJoin, false);
    expect(caps.canViewAdminPanel, false);
  });

  test('partial + failed_sections parsed honestly', () {
    final d = CommunityDetail.fromJson(const {
      'id': 'c1', 'name': 'X',
      'partial': true, 'failed_sections': ['stats'],
    });
    expect(d.partial, true);
    expect(d.failedSections, ['stats']);
  });

  test('MembersPage exposes hasMore from next_cursor', () {
    final p = MembersPage.fromJson(const {
      'members': [
        {'user_id': 'u1', 'username': 'ney', 'display_name': 'Ney', 'role': 'owner'},
      ],
      'next_cursor': 'abc',
    });
    expect(p.members.single.role, 'owner');
    expect(p.hasMore, true);
  });

  test('deep-link validator accepts real routes, rejects null/unknown', () {
    expect(communityDeepLinkIsNavigable('/users/u1'), true);
    expect(communityDeepLinkIsNavigable('/hub/community/c1'), true);
    expect(communityDeepLinkIsNavigable('/discussion/d1'), true);
    expect(communityDeepLinkIsNavigable(null), false);
    expect(communityDeepLinkIsNavigable(''), false);
    expect(communityDeepLinkIsNavigable('/evil/x'), false);
  });
}
