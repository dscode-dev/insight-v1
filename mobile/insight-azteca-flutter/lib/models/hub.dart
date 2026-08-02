import 'package:freezed_annotation/freezed_annotation.dart';

part 'hub.freezed.dart';
part 'hub.g.dart';

@freezed
class Community with _$Community {
  const factory Community({
    required String id,
    required String name,
    required String handle, // "#tatica"
    required String accentColor,
    required int activeMembers,
    String? description,
  }) = _Community;

  factory Community.fromJson(Map<String, dynamic> json) =>
      _$CommunityFromJson(json);
}

@freezed
class Discussion with _$Discussion {
  const factory Discussion({
    required String id,
    required String communityHandle,
    required String authorDisplayName,
    required String authorAccent,
    required String authorInitials,
    required String title,
    required String snippet,
    required int replies,
    required DateTime lastActivityTs,
  }) = _Discussion;

  factory Discussion.fromJson(Map<String, dynamic> json) =>
      _$DiscussionFromJson(json);
}

@freezed
class Tipster with _$Tipster {
  const factory Tipster({
    required String id,
    required String displayName,
    required String username,
    required String accentColor,
    required String initials,
    required double accuracy, // 0..1
    required int signals,
    required String tier, // labelPtBr already
  }) = _Tipster;

  factory Tipster.fromJson(Map<String, dynamic> json) =>
      _$TipsterFromJson(json);
}

/// Segment chips at the top of the Hub. Drives which slice of communities /
/// tipsters / discussions appears below.
enum HubSegment {
  @JsonValue('mine')
  mine,
  @JsonValue('hot')
  hot,
  @JsonValue('new')
  fresh,
}

extension HubSegmentX on HubSegment {
  String get labelPtBr {
    switch (this) {
      case HubSegment.mine:
        return 'Minhas';
      case HubSegment.hot:
        return 'Em alta';
      case HubSegment.fresh:
        return 'Novas';
    }
  }
}

@freezed
class HubBundle with _$HubBundle {
  const factory HubBundle({
    required List<Community> communities,
    required List<Tipster> tipsters,
    required List<Discussion> discussions,
  }) = _HubBundle;

  factory HubBundle.fromJson(Map<String, dynamic> json) =>
      _$HubBundleFromJson(json);
}

@freezed
class CommunityMember with _$CommunityMember {
  const factory CommunityMember({
    required String id,
    required String displayName,
    required String username,
    required String initials,
    required String accentColor,
    required String roleLabel, // "Moderador" / "Membro" / "Convidado"
  }) = _CommunityMember;

  factory CommunityMember.fromJson(Map<String, dynamic> json) =>
      _$CommunityMemberFromJson(json);
}

@freezed
class CommunityDetail with _$CommunityDetail {
  const factory CommunityDetail({
    required Community community,
    required List<Discussion> discussions,
    required List<CommunityMember> members,
  }) = _CommunityDetail;

  factory CommunityDetail.fromJson(Map<String, dynamic> json) =>
      _$CommunityDetailFromJson(json);
}
