// Agents — Social Foundation (/v1/agents, /v1/agents/{id},
// /v1/agents/{id}/posts) through the Gateway.
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/feed.dart';
import '../models/social.dart';
import '../services/social_mapping.dart';
import '../services/social_service.dart';

/// Active agents list (GET /v1/agents?active_only=true).
final agentsListProvider = FutureProvider<List<AgentProfileDto>>((ref) async {
  return ref.read(socialApiProvider).listAgents();
});

/// One agent profile (GET /v1/agents/{id}).
final agentProfileProvider =
    FutureProvider.family<AgentProfileDto, String>((ref, id) async {
  return ref.read(socialApiProvider).getAgent(id);
});

/// An agent's posts, mapped to the shared feed-card model
/// (GET /v1/agents/{id}/posts). First page only — the agent profile
/// shows a recent slice, not an infinite timeline.
final agentPostsProvider =
    FutureProvider.family<List<FeedPost>, String>((ref, id) async {
  final page = await ref.read(socialApiProvider).agentPosts(id);
  return page.items.map(feedItemToFeedPost).toList(growable: false);
});

/// Follow/mute actions for an agent, with optimistic local state so the
/// profile button reflects the tap immediately and rolls back on error.
class AgentRelationState {
  const AgentRelationState({this.following = false, this.muted = false});
  final bool following;
  final bool muted;
  AgentRelationState copyWith({bool? following, bool? muted}) =>
      AgentRelationState(
        following: following ?? this.following,
        muted: muted ?? this.muted,
      );
}

class AgentRelationNotifier
    extends AutoDisposeFamilyNotifier<AgentRelationState, String> {
  SocialApi get _api => ref.read(socialApiProvider);

  @override
  AgentRelationState build(String agentId) => const AgentRelationState();

  Future<void> toggleFollow() async {
    final prev = state;
    final next = !prev.following;
    state = state.copyWith(following: next);
    try {
      if (next) {
        await _api.follow(arg);
      } else {
        await _api.unfollow(arg);
      }
    } catch (_) {
      state = prev; // rollback
    }
  }

  Future<void> toggleMute() async {
    final prev = state;
    final next = !prev.muted;
    state = state.copyWith(muted: next);
    try {
      if (next) {
        await _api.mute(arg);
      } else {
        await _api.unmute(arg);
      }
    } catch (_) {
      state = prev; // rollback
    }
  }
}

final agentRelationProvider = AutoDisposeNotifierProviderFamily<
    AgentRelationNotifier, AgentRelationState, String>(
  AgentRelationNotifier.new,
);
