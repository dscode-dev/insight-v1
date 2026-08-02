import 'package:freezed_annotation/freezed_annotation.dart';

part 'notifications.freezed.dart';
part 'notifications.g.dart';

/// What triggered the notification. Drives icon + accent in the row.
enum NotificationKind {
  @JsonValue('match_event')
  matchEvent,
  @JsonValue('signal_reply')
  signalReply,
  @JsonValue('community_mention')
  communityMention,
  @JsonValue('agent_insight')
  agentInsight,
  @JsonValue('system_update')
  systemUpdate,
}

@freezed
class AppNotification with _$AppNotification {
  const factory AppNotification({
    required String id,
    required NotificationKind kind,
    required String title,
    required String body,
    required DateTime ts,
    @Default(false) bool read,
    String? deeplink,
  }) = _AppNotification;

  factory AppNotification.fromJson(Map<String, dynamic> json) =>
      _$AppNotificationFromJson(json);
}
