import 'package:flutter/painting.dart';

/// AZTECA-IDENTITY-A — avatar cache invalidation.
///
/// The Gateway stores avatars at a STABLE per-user object key
/// (`avatars/<uuid>.<ext>`), so a re-upload returns the SAME URL. Flutter's
/// image cache keys on that URL, so without an explicit eviction every
/// `Image.network` keeps painting the OLD bytes after a new upload. Evicting the
/// URL forces the next resolve to fetch fresh bytes — the avatar then updates
/// everywhere (profile, feed, comments, replies) as those widgets rebuild, with
/// no app restart and no manual refresh.
Future<void> evictAvatarFromCache(String? url) async {
  if (url == null || url.isEmpty) return;
  final provider = NetworkImage(url);
  // Removes the live + pending entries from the global ImageCache.
  await provider.evict();
}
