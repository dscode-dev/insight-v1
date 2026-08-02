import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_mode.dart';
import '../mock/feed_mock.dart';
import 'gateway_client.dart';
import 'auth_service.dart';
import 'avatar_service.dart';
import 'moderation_service.dart';
import 'discussion_service.dart';
import 'feed_service.dart';
import 'hub_service.dart';
import 'live_service.dart';
import 'notifications_service.dart';
import 'post_upload_service.dart';
import 'preferences_service.dart';
import 'profile_service.dart';
import 'radar_service.dart';
import 'reaction_service.dart';
import 'realtime_service.dart';

/// One provider per domain service. Each picks mock vs gateway based on
/// `ApiMode.current` (compile-time `--dart-define`). The rest of the
/// app talks only to these providers; the mock/gateway boundary doesn't
/// leak upward.

final apiModeProvider = Provider<ApiMode>((_) => ApiMode.current);

final authServiceProvider = Provider<AuthService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayAuthService(ref.watch(gatewayDioProvider));
  }
  return MockAuthService();
});

/// Store-A — UGC moderation (report + block). Real Gateway client in live mode;
/// no-op in mock/offline so the demo never hits the network.
final moderationApiProvider = Provider<ModerationApi>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayModerationService(ref.watch(gatewayDioProvider));
  }
  return NoopModerationService();
});

final feedServiceProvider = Provider<FeedService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayFeedService(ref.watch(gatewayDioProvider));
  }
  return MockFeedService();
});

final liveServiceProvider = Provider<LiveService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayLiveService(ref.watch(gatewayDioProvider));
  }
  return MockLiveService();
});

final radarServiceProvider = Provider<RadarService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayRadarService(ref.watch(gatewayDioProvider));
  }
  return MockRadarService();
});

final hubServiceProvider = Provider<HubService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayHubService(ref.watch(gatewayDioProvider));
  }
  return MockHubService();
});

// Sprint A — discussion thread (header + messages + post reply).
final discussionServiceProvider = Provider<DiscussionService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayDiscussionService(ref.watch(gatewayDioProvider));
  }
  return MockDiscussionService();
});

// Sprint B — reactions (like/unlike on Discussions).
final reactionServiceProvider = Provider<ReactionService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayReactionService(ref.watch(gatewayDioProvider));
  }
  return MockReactionService();
});

// Sprint C — avatar upload (profile photo).
final avatarServiceProvider = Provider<AvatarService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayAvatarService(ref.watch(gatewayDioProvider));
  }
  return MockAvatarService();
});

/// Sprint 6.2 Part 2 — post image attachment uploads.
///
/// Composer attaches up to N images by calling `upload()` per-file.
/// Each succeeds independently and returns a stable `{url, id}` the
/// composer threads into the eventual post payload.
final postUploadServiceProvider = Provider<PostUploadService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayPostUploadService(ref.watch(gatewayDioProvider));
  }
  return MockPostUploadService();
});

// Sprint D — user preferences (settings screen).
final preferencesServiceProvider = Provider<PreferencesService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayPreferencesService(ref.watch(gatewayDioProvider));
  }
  return MockPreferencesService();
});

final profileServiceProvider = Provider<ProfileService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayProfileService(ref.watch(gatewayDioProvider));
  }
  return MockProfileService();
});

// Notifications: the mock keeps a session-level cache so "mark all read"
// sticks across navigations. The Gateway impl delegates to the server,
// which is its own source of truth.
final notificationsServiceProvider = Provider<NotificationsService>((ref) {
  final mode = ref.watch(apiModeProvider);
  if (mode.isLive) {
    return GatewayNotificationsService(ref.watch(gatewayDioProvider));
  }
  return MockNotificationsService();
});

/// Realtime stream — Gateway SSE in live mode, deterministic timer ticks
/// in mock. The instance is process-scoped: one underlying SSE per app
/// session, multiplexed to many listeners via the broadcast stream
/// returned by `subscribe()`.
final realtimeServiceProvider = Provider<RealtimeService>((ref) {
  final mode = ref.watch(apiModeProvider);
  final service =
      mode.isLive ? GatewayRealtimeService() : MockRealtimeService();
  ref.onDispose(() {
    // Best-effort tear-down when the provider container disposes.
    // ignore: discarded_futures
    service.disconnect();
  });
  return service;
});
