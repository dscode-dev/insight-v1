// FEATURE-COMMUNITIES-V1 Stage 3 — typed models mirroring the GATEWAY public
// contract (communitybff DTOs). The client knows ONLY this contract; it never
// sees social.v1 shapes and never infers permissions from roles.
//
// CommunityDetail is the AGGREGATE: header + counters + role_counts +
// viewer_role + membership_status + capabilities. It carries NO members array
// (that was the old bug) — the Members tab paginates its own endpoint.
//
// ignore_for_file: sort_constructors_first
import 'package:flutter/foundation.dart';

/// Explicit permission set from the Gateway. The UI renders affordances ONLY
/// from these booleans — never from the role. Defaults are all-false so a
/// missing/partial response never accidentally exposes an admin control.
@immutable
class CommunityCapabilities {
  const CommunityCapabilities({
    required this.canJoin,
    required this.canLeave,
    required this.canCreateDiscussion,
    required this.canDeleteDiscussion,
    required this.canManageMembers,
    required this.canInviteMembers,
    required this.canManageSettings,
    required this.canViewAdminPanel,
  });

  final bool canJoin, canLeave, canCreateDiscussion, canDeleteDiscussion;
  final bool canManageMembers, canInviteMembers, canManageSettings, canViewAdminPanel;

  static const none = CommunityCapabilities(
    canJoin: false, canLeave: false, canCreateDiscussion: false,
    canDeleteDiscussion: false, canManageMembers: false, canInviteMembers: false,
    canManageSettings: false, canViewAdminPanel: false,
  );

  factory CommunityCapabilities.fromJson(Map<String, dynamic>? j) {
    j ??= const {};
    bool b(String k) => j![k] == true;
    return CommunityCapabilities(
      canJoin: b('can_join'),
      canLeave: b('can_leave'),
      canCreateDiscussion: b('can_create_discussion'),
      canDeleteDiscussion: b('can_delete_discussion'),
      canManageMembers: b('can_manage_members'),
      canInviteMembers: b('can_invite_members'),
      canManageSettings: b('can_manage_settings'),
      canViewAdminPanel: b('can_view_admin_panel'),
    );
  }
}

@immutable
class RoleCounts {
  const RoleCounts({required this.owner, required this.admin, required this.moderator, required this.member});
  final int owner, admin, moderator, member;

  int get total => owner + admin + moderator + member;

  static const zero = RoleCounts(owner: 0, admin: 0, moderator: 0, member: 0);

  factory RoleCounts.fromJson(Map<String, dynamic>? j) {
    j ??= const {};
    int n(String k) => (j![k] as num?)?.toInt() ?? 0;
    return RoleCounts(owner: n('owner'), admin: n('admin'), moderator: n('moderator'), member: n('member'));
  }
}

/// The community overview aggregate. Everything the header + overview need in
/// ONE response — loaded once, never re-fetched on tab switch.
@immutable
class CommunityDetail {
  const CommunityDetail({
    required this.id,
    required this.slug,
    required this.name,
    required this.description,
    required this.avatarUrl,
    required this.bannerUrl,
    required this.accentColor,
    required this.kind,
    required this.privacy,
    required this.deepLink,
    required this.memberCount,
    required this.discussionCount,
    required this.onlineCount,
    required this.roleCounts,
    required this.viewerRole,
    required this.membershipStatus,
    required this.ownerAssigned,
    required this.capabilities,
    required this.partial,
    required this.failedSections,
  });

  final String id, slug, name, description, avatarUrl, bannerUrl, accentColor, kind, privacy, deepLink;
  final int memberCount, discussionCount, onlineCount;
  final RoleCounts roleCounts;
  final String viewerRole;       // owner|admin|moderator|member|none (DISPLAY only)
  final String membershipStatus; // member|not_member
  final bool ownerAssigned;
  final CommunityCapabilities capabilities;
  final bool partial;
  final List<String> failedSections;

  bool get isMember => membershipStatus == 'member';

  factory CommunityDetail.fromJson(Map<String, dynamic> j) {
    int n(String k) => (j[k] as num?)?.toInt() ?? 0;
    String s(String k) => '${j[k] ?? ''}';
    return CommunityDetail(
      id: s('id'),
      slug: s('slug'),
      name: s('name'),
      description: s('description'),
      avatarUrl: s('avatar_url'),
      bannerUrl: s('banner_url'),
      accentColor: j['accent_color'] as String? ?? '#5BA8FF',
      kind: s('kind'),
      privacy: j['privacy'] as String? ?? 'public',
      deepLink: s('deep_link'),
      memberCount: n('member_count'),
      discussionCount: n('discussion_count'),
      onlineCount: n('online_count'),
      roleCounts: RoleCounts.fromJson(j['role_counts'] as Map<String, dynamic>?),
      viewerRole: j['viewer_role'] as String? ?? 'none',
      membershipStatus: j['membership_status'] as String? ?? 'not_member',
      ownerAssigned: j['owner_assigned'] == true,
      capabilities: CommunityCapabilities.fromJson(j['capabilities'] as Map<String, dynamic>?),
      partial: j['partial'] == true,
      failedSections: ((j['failed_sections'] as List?) ?? const [])
          .map((e) => '$e')
          .toList(growable: false),
    );
  }

  /// Local optimistic patch after join/leave — new viewer state + capabilities
  /// + member count, without a re-fetch.
  CommunityDetail withMembership(MembershipResult r) => CommunityDetail(
        id: id, slug: slug, name: name, description: description, avatarUrl: avatarUrl,
        bannerUrl: bannerUrl, accentColor: accentColor, kind: kind, privacy: privacy,
        deepLink: deepLink, memberCount: r.memberCount > 0 ? r.memberCount : memberCount,
        discussionCount: discussionCount, onlineCount: onlineCount, roleCounts: roleCounts,
        viewerRole: r.viewerRole, membershipStatus: r.membershipStatus, ownerAssigned: ownerAssigned,
        capabilities: r.capabilities, partial: partial, failedSections: failedSections,
      );
}

@immutable
class CommunityMember {
  const CommunityMember({
    required this.userId,
    required this.username,
    required this.displayName,
    required this.initials,
    required this.accentColor,
    required this.avatarUrl,
    required this.reputation,
    required this.role,
    required this.deepLink,
  });

  final String userId, username, displayName, initials, accentColor, avatarUrl, role, deepLink;
  final int reputation;

  String get key => userId;

  factory CommunityMember.fromJson(Map<String, dynamic> j) => CommunityMember(
        userId: '${j['user_id'] ?? ''}',
        username: '${j['username'] ?? ''}',
        displayName: '${j['display_name'] ?? ''}',
        initials: '${j['initials'] ?? ''}',
        accentColor: j['accent_color'] as String? ?? '#5BA8FF',
        avatarUrl: '${j['avatar_url'] ?? ''}',
        reputation: (j['reputation'] as num?)?.toInt() ?? 0,
        role: j['role'] as String? ?? 'member',
        deepLink: '${j['deep_link'] ?? ''}',
      );
}

@immutable
class MembersPage {
  const MembersPage({required this.members, required this.nextCursor, required this.roleFilter});
  final List<CommunityMember> members;
  final String nextCursor;
  final String roleFilter;

  bool get hasMore => nextCursor.isNotEmpty;

  factory MembersPage.fromJson(Map<String, dynamic> j) => MembersPage(
        members: ((j['members'] as List?) ?? const [])
            .map((e) => CommunityMember.fromJson(e as Map<String, dynamic>))
            .toList(growable: false),
        nextCursor: j['next_cursor'] as String? ?? '',
        roleFilter: j['role_filter'] as String? ?? '',
      );
}

/// A community discussion — NOT a Post. Its own shape emphasises the
/// conversation (replies, reactions, recent activity), never the timeline card.
@immutable
class CommunityDiscussion {
  const CommunityDiscussion({
    required this.id,
    required this.communityId,
    required this.authorId,
    required this.title,
    required this.replyCount,
    required this.reactionCount,
    required this.lastActivityTs,
    required this.deepLink,
  });

  final String id, communityId, authorId, title, lastActivityTs, deepLink;
  final int replyCount, reactionCount;

  String get key => id;

  factory CommunityDiscussion.fromJson(Map<String, dynamic> j) => CommunityDiscussion(
        id: '${j['id'] ?? ''}',
        communityId: '${j['community_id'] ?? ''}',
        authorId: '${j['author_id'] ?? ''}',
        title: '${j['title'] ?? ''}',
        replyCount: (j['reply_count'] as num?)?.toInt() ?? 0,
        reactionCount: (j['reaction_count'] as num?)?.toInt() ?? 0,
        lastActivityTs: '${j['last_activity_ts'] ?? ''}',
        deepLink: '${j['deep_link'] ?? ''}',
      );
}

@immutable
class DiscussionsPage {
  const DiscussionsPage({required this.discussions, required this.nextCursor});
  final List<CommunityDiscussion> discussions;
  final String nextCursor;

  bool get hasMore => nextCursor.isNotEmpty;

  factory DiscussionsPage.fromJson(Map<String, dynamic> j) => DiscussionsPage(
        discussions: ((j['discussions'] as List?) ?? const [])
            .map((e) => CommunityDiscussion.fromJson(e as Map<String, dynamic>))
            .toList(growable: false),
        nextCursor: j['next_cursor'] as String? ?? '',
      );
}

@immutable
class MembershipResult {
  const MembershipResult({
    required this.communityId,
    required this.viewerRole,
    required this.membershipStatus,
    required this.memberCount,
    required this.capabilities,
  });

  final String communityId, viewerRole, membershipStatus;
  final int memberCount;
  final CommunityCapabilities capabilities;

  factory MembershipResult.fromJson(Map<String, dynamic> j) => MembershipResult(
        communityId: '${j['community_id'] ?? ''}',
        viewerRole: j['viewer_role'] as String? ?? 'none',
        membershipStatus: j['membership_status'] as String? ?? 'not_member',
        memberCount: (j['member_count'] as num?)?.toInt() ?? 0,
        capabilities: CommunityCapabilities.fromJson(j['capabilities'] as Map<String, dynamic>?),
      );
}
