// Post comment thread (Social Foundation / AZTECA-SOCIAL-A).
//
// Loads a post + its comments (GET /v1/posts/{id}/comments) and adds
// comments/replies (POST /v1/posts/{id}/comments, depth ≤ 2). Resolves REAL
// author identities (display name, @username, avatar) from the backend so the
// thread never renders generic "Usuário" placeholders — all identity data
// comes from getUser / getAgent.
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/social.dart';
import 'feed_provider.dart';
import '../services/social_service.dart';

/// Resolved, backend-sourced identity for a post/comment author. Built from
/// getUser (users) or getAgent (agents). Never a hardcoded placeholder.
class AuthorIdentity {
  const AuthorIdentity({
    required this.displayName,
    required this.username,
    required this.initials,
    required this.accentColor,
    required this.isAgent,
    this.avatarUrl,
  });

  factory AuthorIdentity.fromUser(SocialUserDto u) => AuthorIdentity(
        displayName:
            u.displayName.isNotEmpty ? u.displayName : '@${u.username}',
        username: u.username,
        initials:
            u.initials.isNotEmpty ? u.initials : _initialsOf(u.displayName),
        accentColor: u.accentColor,
        isAgent: false,
        avatarUrl: u.avatarUrl.isEmpty ? null : u.avatarUrl,
      );

  factory AuthorIdentity.fromAgent(AgentProfileDto a) => AuthorIdentity(
        displayName: a.name,
        username: a.slug,
        initials: _initialsOf(a.name),
        accentColor: '#7C6CFF',
        isAgent: true,
        avatarUrl: a.avatar.isEmpty ? null : a.avatar,
      );

  /// Last-resort, NON-generic fallback (used only if a profile fetch fails).
  /// Deliberately avoids the word "Usuário".
  factory AuthorIdentity.fallback({required bool isAgent}) => AuthorIdentity(
        displayName: isAgent ? 'Agente Insight' : 'Membro da comunidade',
        username: '',
        initials: isAgent ? 'AI' : 'MC',
        accentColor: isAgent ? '#7C6CFF' : '#5BA8FF',
        isAgent: isAgent,
      );

  final String displayName;
  final String username; // '' when unknown
  final String initials;
  final String accentColor;
  final bool isAgent;
  final String? avatarUrl;

  static String _initialsOf(String name) {
    final parts = name.trim().split(RegExp(r'\s+'));
    if (parts.isEmpty || parts.first.isEmpty) return '·';
    if (parts.length == 1) {
      return parts.first
          .substring(0, parts.first.length.clamp(0, 2))
          .toUpperCase();
    }
    return (parts.first[0] + parts.last[0]).toUpperCase();
  }
}

class PostThreadState {
  const PostThreadState({
    required this.post,
    required this.comments,
    required this.identities,
    this.sending = false,
  });

  final SocialPostDto post;
  final List<SocialCommentDto> comments;

  /// authorId → resolved identity (post author + every commenter).
  final Map<String, AuthorIdentity> identities;
  final bool sending;

  PostThreadState copyWith({
    SocialPostDto? post,
    List<SocialCommentDto>? comments,
    Map<String, AuthorIdentity>? identities,
    bool? sending,
  }) =>
      PostThreadState(
        post: post ?? this.post,
        comments: comments ?? this.comments,
        identities: identities ?? this.identities,
        sending: sending ?? this.sending,
      );

  /// Real comment count (backend-derived from the loaded comments — never a
  /// local counter; the list only grows from server-confirmed creates).
  int get commentCount => comments.length;

  AuthorIdentity identityFor(String authorId, String authorType) =>
      identities[authorId] ??
      AuthorIdentity.fallback(isAgent: authorType == 'agent');

  /// Top-level comments (depth 1), each with its replies (depth 2) grouped
  /// under it — preserves the ≤2 nesting the backend enforces.
  List<({SocialCommentDto comment, List<SocialCommentDto> replies})>
      get threaded {
    final roots = comments.where((c) => c.parentId.isEmpty).toList()
      ..sort((a, b) => a.createdAt.compareTo(b.createdAt));
    return roots.map((root) {
      final replies = comments.where((c) => c.parentId == root.id).toList()
        ..sort((a, b) => a.createdAt.compareTo(b.createdAt));
      return (comment: root, replies: replies);
    }).toList(growable: false);
  }
}

class PostThreadNotifier
    extends AutoDisposeFamilyAsyncNotifier<PostThreadState, String> {
  SocialApi get _api => ref.read(socialApiProvider);

  @override
  Future<PostThreadState> build(String postId) async {
    final post = await _api.getPost(postId);
    final comments = await _api.listComments(postId);
    final identities = await _resolveIdentities(post, comments);
    return PostThreadState(
        post: post, comments: comments, identities: identities);
  }

  /// Resolve every distinct author (post + comments) to a real identity. Runs
  /// fetches in parallel and tolerates individual failures (falls back to a
  /// non-generic identity rather than failing the whole thread).
  Future<Map<String, AuthorIdentity>> _resolveIdentities(
    SocialPostDto post,
    List<SocialCommentDto> comments, {
    Map<String, AuthorIdentity>? known,
  }) async {
    final wanted = <String, String>{post.authorId: post.authorType};
    for (final c in comments) {
      wanted[c.authorId] = c.authorType;
    }
    final out = <String, AuthorIdentity>{...?known};
    await Future.wait(wanted.entries.map((e) async {
      if (out.containsKey(e.key) || e.key.isEmpty) return;
      try {
        if (e.value == 'agent') {
          out[e.key] = AuthorIdentity.fromAgent(await _api.getAgent(e.key));
        } else {
          out[e.key] = AuthorIdentity.fromUser(await _api.getUser(e.key));
        }
      } catch (_) {
        out[e.key] = AuthorIdentity.fallback(isAgent: e.value == 'agent');
      }
    }));
    return out;
  }

  /// Add a top-level comment ([parentId] null) or a reply ([parentId] set,
  /// depth 2). Inserts the server-confirmed comment on success; surfaces the
  /// error otherwise (no faked persistence).
  Future<bool> addComment(String content, {String? parentId}) async {
    final current = state.valueOrNull;
    if (current == null || content.trim().isEmpty) return false;
    state = AsyncValue.data(current.copyWith(sending: true));
    try {
      final created = await _api.createComment(
        postId: arg,
        parentId: parentId,
        content: content.trim(),
      );
      final refreshedPost = await _api.getPost(arg);
      final comments = [...current.comments, created];
      // Ensure the new author has a resolved identity (usually the caller).
      final identities = await _resolveIdentities(
        refreshedPost,
        comments,
        known: current.identities,
      );
      ref
          .read(feedProvider.notifier)
          .setCommentCount(arg, refreshedPost.commentCount);
      state = AsyncValue.data(
        current.copyWith(
          post: refreshedPost,
          comments: comments,
          identities: identities,
          sending: false,
        ),
      );
      return true;
    } catch (_) {
      state = AsyncValue.data(current.copyWith(sending: false));
      return false;
    }
  }
}

final postThreadProvider = AutoDisposeAsyncNotifierProviderFamily<
    PostThreadNotifier, PostThreadState, String>(PostThreadNotifier.new);
