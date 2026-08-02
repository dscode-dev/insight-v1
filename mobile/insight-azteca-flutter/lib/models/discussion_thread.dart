// Sprint A — DiscussionThread + DiscussionMessage models.
//
// Wire shapes match the gateway BFF (Go) declared in
// internal/interfaces/http/social/dto.go on the gateway side.
// snake_case on the wire → camelCase in Dart via field_rename: snake
// (configured in build.yaml).
import 'package:freezed_annotation/freezed_annotation.dart';

part 'discussion_thread.freezed.dart';
part 'discussion_thread.g.dart';

@freezed
class DiscussionDetail with _$DiscussionDetail {
  const factory DiscussionDetail({
    required String id,
    required String title,
    required String body,
    required String communityId,
    String? communityName,
    String? communityHandle,
    required String authorId,
    String? authorDisplayName,
    String? authorInitials,
    String? authorAccent,
    String? matchId,
    required int replyCount,
    required int reactionCount,
    required DateTime createdAt,
    required DateTime lastActivityTs,
  }) = _DiscussionDetail;

  factory DiscussionDetail.fromJson(Map<String, dynamic> json) =>
      _$DiscussionDetailFromJson(json);
}

@freezed
class DiscussionMessage with _$DiscussionMessage {
  const factory DiscussionMessage({
    required String id,
    required String authorId,
    String? authorDisplayName,
    String? authorInitials,
    String? authorAccent,
    required String body,
    required DateTime ts,
  }) = _DiscussionMessage;

  factory DiscussionMessage.fromJson(Map<String, dynamic> json) =>
      _$DiscussionMessageFromJson(json);
}

/// Paged messages response. NextCursor is null when no more pages.
@freezed
class DiscussionMessagesPage with _$DiscussionMessagesPage {
  const factory DiscussionMessagesPage({
    required List<DiscussionMessage> messages,
    String? nextCursor,
  }) = _DiscussionMessagesPage;

  factory DiscussionMessagesPage.fromJson(Map<String, dynamic> json) =>
      _$DiscussionMessagesPageFromJson(json);
}
