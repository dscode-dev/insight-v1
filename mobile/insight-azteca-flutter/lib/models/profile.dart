import 'package:freezed_annotation/freezed_annotation.dart';

part 'profile.freezed.dart';
part 'profile.g.dart';

@freezed
class UserStats with _$UserStats {
  const factory UserStats({
    required int reputation, // 0..100
    required int posts,
    required int signals,
    required double accuracy, // 0..1
  }) = _UserStats;

  factory UserStats.fromJson(Map<String, dynamic> json) =>
      _$UserStatsFromJson(json);
}

@freezed
class UserBadge with _$UserBadge {
  const factory UserBadge({
    required String id,
    required String label,
    required String description,
    required String emoji,
    required DateTime earnedAt,
  }) = _UserBadge;

  factory UserBadge.fromJson(Map<String, dynamic> json) =>
      _$UserBadgeFromJson(json);
}

enum ProfileActivityKind {
  @JsonValue('post')
  post,
  @JsonValue('signal')
  signal,
  @JsonValue('reply')
  reply,
  @JsonValue('badge_earned')
  badgeEarned,
}

@freezed
class ProfileActivity with _$ProfileActivity {
  const factory ProfileActivity({
    required String id,
    required ProfileActivityKind kind,
    required String title,
    required String body,
    required DateTime ts,
  }) = _ProfileActivity;

  factory ProfileActivity.fromJson(Map<String, dynamic> json) =>
      _$ProfileActivityFromJson(json);
}

@freezed
class ProfileBundle with _$ProfileBundle {
  const factory ProfileBundle({
    required UserStats stats,
    required List<UserBadge> badges,
    required List<ProfileActivity> activity,
  }) = _ProfileBundle;

  factory ProfileBundle.fromJson(Map<String, dynamic> json) =>
      _$ProfileBundleFromJson(json);
}
