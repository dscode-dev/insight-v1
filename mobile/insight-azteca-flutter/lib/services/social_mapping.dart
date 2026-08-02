// Social Foundation → UI model mapping.
//
// The app's feed/post cards are built around the legacy `FeedPost`
// model. To migrate to the Social Foundation WITHOUT redesigning the
// UI, every Social DTO is mapped into `FeedPost` here. This is the
// single seam between the wire contract and the renderers — when the
// Gateway DTO evolves, only this file (and models/social.dart) change.

import 'dart:convert';

import 'package:flutter/widgets.dart'; // String.characters extension

import '../models/feed.dart';
import '../models/social.dart';

/// Maps a feed item (post + denormalized author) to a `FeedPost`.
FeedPost feedItemToFeedPost(SocialFeedItemDto item) {
  final post = item.post;
  final isAgent = post.isAgent;
  return FeedPost(
    id: post.id,
    kind: isAgent ? FeedPostKind.agentInsight : FeedPostKind.userOpinion,
    author: _author(
      id: post.authorId,
      name: item.authorName,
      isAgent: isAgent,
      sponsored: item.sponsored,
    ),
    body: post.content,
    agent: isAgent ? _agentMeta(item.authorName, post.metadata) : null,
    reactions: FeedReactions(
      likes: post.likeCount,
      replies: post.commentCount,
    ),
    // Viewer's like state from the Gateway feed DTO — the heart paints
    // correctly on first frame (no false-negatives).
    likedByMe: item.likedByMe,
    ts: post.createdAt.toLocal(),
  );
}

/// Maps a bare post (e.g. the composer's POST /v1/posts response, or a
/// single GET /v1/posts/:id) to a `FeedPost`. [authorName] lets the
/// caller supply the display name the bare post omits.
FeedPost postToFeedPost(SocialPostDto post, {String? authorName}) {
  final isAgent = post.isAgent;
  return FeedPost(
    id: post.id,
    kind: isAgent ? FeedPostKind.agentInsight : FeedPostKind.userOpinion,
    author: _author(
      id: post.authorId,
      name: authorName ?? '',
      isAgent: isAgent,
      sponsored: false,
    ),
    body: post.content,
    agent: isAgent ? _agentMeta(authorName ?? '', post.metadata) : null,
    reactions: FeedReactions(likes: post.likeCount, replies: post.commentCount),
    likedByMe: false,
    ts: post.createdAt.toLocal(),
  );
}

FeedAuthor _author({
  required String id,
  required String name,
  required bool isAgent,
  required bool sponsored,
}) {
  final display = name.trim().isNotEmpty
      ? name.trim()
      : (isAgent ? 'Agente' : 'Usuário');
  return FeedAuthor(
    id: id,
    displayName: display,
    username: null,
    initials: _initials(display),
    accentColor: _accentFor(id.isNotEmpty ? id : display),
    isSystem: isAgent,
  );
}

/// Agent meta from Nexus-published post metadata. The publisher encodes
/// `title` plainly and `highlights`/`tags` as JSON arrays.
FeedAgentMeta _agentMeta(String name, Map<String, String> metadata) {
  return FeedAgentMeta(
    id: _agentIdFor(name, metadata['agent']),
    label: name.trim().isNotEmpty ? name.trim() : 'Agente',
    confidence: 0,
    title: (metadata['title'] ?? '').isNotEmpty ? metadata['title'] : null,
    highlights: _jsonStringList(metadata['highlights']),
    tags: _jsonStringList(metadata['tags']),
  );
}

/// Best-effort visual mapping of the seeded Social agent voices
/// (ninja/pulse/oracle/sentinel/echo) onto the legacy FeedAgentId set.
/// Drives only the icon/accent on the agent card — never behaviour.
FeedAgentId _agentIdFor(String name, String? slug) {
  final key = (slug ?? name).toLowerCase();
  if (key.contains('pulse')) return FeedAgentId.pulse;
  if (key.contains('oracle') || key.contains('history')) {
    return FeedAgentId.history;
  }
  if (key.contains('sentinel') || key.contains('stat')) {
    return FeedAgentId.stats;
  }
  if (key.contains('echo') || key.contains('momentum')) {
    return FeedAgentId.momentum;
  }
  return FeedAgentId.scout; // ninja / market / default
}

List<String> _jsonStringList(String? raw) {
  if (raw == null || raw.isEmpty) return const [];
  try {
    final decoded = jsonDecode(raw);
    if (decoded is List) {
      return decoded.map((e) => e.toString()).toList(growable: false);
    }
  } catch (_) {
    // Not JSON — treat a non-empty scalar as a single entry.
    return [raw];
  }
  return const [];
}

String _initials(String name) {
  final parts = name.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty);
  if (parts.isEmpty) return '·';
  final first = parts.first.characters.first;
  final last = parts.length > 1 ? parts.last.characters.first : '';
  return (first + last).toUpperCase();
}

/// Deterministic accent hex from a stable key, so the same author keeps
/// the same colour across sessions without a server-provided value.
String _accentFor(String key) {
  const palette = [
    '#5BA8FF', '#7C6CFF', '#36C2A6', '#FF7A59',
    '#F2C14E', '#E16BB0', '#4FD1C5', '#9B8CFF',
  ];
  var hash = 0;
  for (final c in key.codeUnits) {
    hash = (hash * 31 + c) & 0x7fffffff;
  }
  return palette[hash % palette.length];
}
