// User profiles — Social Foundation (/v1/users/{id},
// /v1/users/{id}/posts) through the Gateway.
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/feed.dart';
import '../models/social.dart';
import '../services/social_mapping.dart';
import '../services/social_service.dart';

/// One user's public profile (GET /v1/users/{id}).
final userProfileProvider =
    FutureProvider.family<SocialUserDto, String>((ref, id) async {
  return ref.read(socialApiProvider).getUser(id);
});

/// AZTECA-IDENTITY-B — the enriched, unified Sports Profile (single payload:
/// identity + grouped stats + versioned avatar + role). Used by both the own
/// and public profile headers. GET /v1/users/{id}/sports-profile.
final sportsProfileProvider =
    FutureProvider.family<SportsProfileDto, String>((ref, id) async {
  return ref.read(socialApiProvider).sportsProfile(id);
});

/// A user's posts, mapped to the shared feed-card model
/// (GET /v1/users/{id}/posts). First page only.
final userPostsProvider =
    FutureProvider.family<List<FeedPost>, String>((ref, id) async {
  final page = await ref.read(socialApiProvider).userPosts(id);
  return page.items.map(feedItemToFeedPost).toList(growable: false);
});

/// Follow/mute for another user, optimistic with rollback (mirrors the
/// agent relation notifier).
class UserRelationState {
  const UserRelationState({this.following = false, this.muted = false});
  final bool following;
  final bool muted;
  UserRelationState copyWith({bool? following, bool? muted}) =>
      UserRelationState(
        following: following ?? this.following,
        muted: muted ?? this.muted,
      );
}

class UserRelationNotifier
    extends AutoDisposeFamilyNotifier<UserRelationState, String> {
  SocialApi get _api => ref.read(socialApiProvider);

  @override
  UserRelationState build(String userId) => const UserRelationState();

  Future<void> toggleFollow() async {
    final prev = state;
    final next = !prev.following;
    state = state.copyWith(following: next);
    try {
      next ? await _api.follow(arg) : await _api.unfollow(arg);
    } catch (_) {
      state = prev;
    }
  }

  Future<void> toggleMute() async {
    final prev = state;
    final next = !prev.muted;
    state = state.copyWith(muted: next);
    try {
      next ? await _api.mute(arg) : await _api.unmute(arg);
    } catch (_) {
      state = prev;
    }
  }
}

final userRelationProvider = AutoDisposeNotifierProviderFamily<
    UserRelationNotifier, UserRelationState, String>(UserRelationNotifier.new);
