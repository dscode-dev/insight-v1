// Post comment thread — Social Foundation / AZTECA-SOCIAL-A.
//
// Shows a post + its comments (GET /v1/posts/{id}/comments) and lets the user
// comment / reply (depth ≤ 2). Production qualities: REAL author identity from
// the backend (never "Usuário"), real comment counter, reply context (avatar +
// name + quoted excerpt), and a collapsible reply tree so deep chains stay
// readable.
import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../models/social.dart';
import '../../providers/post_thread_provider.dart';
import '../../routing/routes.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../shared/format/relative_time.dart';
import '../../theme/spacing.dart';
import '../../widgets/avatar.dart';
import '../../widgets/offline_state.dart';

/// Stage 7 — every author avatar in the thread navigates to the SAME unified
/// profile (agents → agent profile, everyone else → public Sports Profile).
/// Never a placeholder.
void _openAuthor(BuildContext context, String authorId, String authorType) {
  if (authorId.isEmpty) return;
  if (authorType == 'agent') {
    context.push(R.agentProfileFor(authorId));
  } else {
    context.push(R.userProfileFor(authorId));
  }
}

class PostThreadScreen extends HookConsumerWidget {
  const PostThreadScreen({super.key, required this.postId});

  final String postId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final asyncState = ref.watch(postThreadProvider(postId));
    final controller = useTextEditingController();
    final replyTo = useState<SocialCommentDto?>(null);
    final focusNode = useFocusNode();

    Future<void> send() async {
      final text = controller.text.trim();
      if (text.isEmpty) return;
      final ok = await ref
          .read(postThreadProvider(postId).notifier)
          .addComment(text, parentId: replyTo.value?.id);
      if (ok) {
        controller.clear();
        replyTo.value = null;
      } else if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Não foi possível comentar agora.')),
        );
      }
    }

    final state = asyncState.valueOrNull;
    final replyIdentity = (state != null && replyTo.value != null)
        ? state.identityFor(replyTo.value!.authorId, replyTo.value!.authorType)
        : null;

    return Scaffold(
      appBar: AppBar(title: const Text('Publicação')),
      body: Column(
        children: [
          Expanded(
            child: asyncState.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => isOfflineError(e)
                  ? const OfflineState()
                  : Center(
                      child: Padding(
                        padding: const EdgeInsets.all(InsightSpacing.xl),
                        child: Text(
                          'Não foi possível carregar a publicação.',
                          style: context.tt.bodyMedium,
                          textAlign: TextAlign.center,
                        ),
                      ),
                    ),
              data: (state) {
                final threaded = state.threaded;
                final postIdentity = state.identityFor(
                    state.post.authorId, state.post.authorType);
                return ListView(
                  keyboardDismissBehavior:
                      ScrollViewKeyboardDismissBehavior.onDrag,
                  padding: const EdgeInsets.fromLTRB(
                    InsightSpacing.xl,
                    InsightSpacing.lg,
                    InsightSpacing.xl,
                    InsightSpacing.xl,
                  ),
                  children: [
                    _PostHeader(post: state.post, identity: postIdentity),
                    const SizedBox(height: InsightSpacing.lg),
                    _CommentsCount(count: state.commentCount),
                    const SizedBox(height: InsightSpacing.sm),
                    Divider(color: context.ds.divider, height: 1),
                    const SizedBox(height: InsightSpacing.lg),
                    if (threaded.isEmpty)
                      Padding(
                        padding: const EdgeInsets.symmetric(
                          vertical: InsightSpacing.xl,
                        ),
                        child: Text(
                          'Seja o primeiro a comentar.',
                          style: context.tt.bodyMedium
                              ?.copyWith(color: context.ds.textLow),
                          textAlign: TextAlign.center,
                        ),
                      )
                    else
                      for (final node in threaded)
                        _CommentThread(
                          key: ValueKey(node.comment.id),
                          comment: node.comment,
                          replies: node.replies,
                          state: state,
                          onReply: (c) {
                            replyTo.value = c;
                            focusNode.requestFocus();
                          },
                        ),
                  ],
                );
              },
            ),
          ),
          _Composer(
            controller: controller,
            focusNode: focusNode,
            replyingTo: replyTo.value,
            replyingToIdentity: replyIdentity,
            onCancelReply: () => replyTo.value = null,
            sending: asyncState.valueOrNull?.sending ?? false,
            onSend: send,
          ),
        ],
      ),
    );
  }
}

/// Real comment count (backend-derived). Stage 2 — never a local counter.
class _CommentsCount extends StatelessWidget {
  const _CommentsCount({required this.count});
  final int count;

  @override
  Widget build(BuildContext context) {
    final label = count == 0
        ? 'Sem comentários'
        : count == 1
            ? '1 comentário'
            : '$count comentários';
    return Semantics(
      header: true,
      child: Text(
        label,
        style: context.tt.labelLarge
            ?.copyWith(color: context.ds.textMid, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _PostHeader extends StatelessWidget {
  const _PostHeader({required this.post, required this.identity});
  final SocialPostDto post;
  final AuthorIdentity identity;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(
          button: true,
          label: 'Abrir perfil de ${identity.displayName}',
          child: GestureDetector(
            onTap: () => _openAuthor(context, post.authorId, post.authorType),
            child: InsightAvatar(
              avatarUrl: identity.avatarUrl,
              initials: identity.initials,
              colorHex: identity.accentColor,
              size: 44,
            ),
          ),
        ),
        const SizedBox(width: InsightSpacing.md),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _IdentityLine(identity: identity, ts: post.createdAt),
              const SizedBox(height: 4),
              Text(post.content,
                  style: context.tt.bodyLarge?.copyWith(height: 1.4)),
            ],
          ),
        ),
      ],
    );
  }
}

/// Name (emphasis) · @username (secondary) · timestamp (low) — shared by the
/// post header and each comment.
class _IdentityLine extends StatelessWidget {
  const _IdentityLine({
    required this.identity,
    required this.ts,
    this.compact = false,
  });
  final AuthorIdentity identity;
  final DateTime ts;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.baseline,
      textBaseline: TextBaseline.alphabetic,
      children: [
        Flexible(
          child: Text(
            identity.displayName,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: (compact ? context.tt.labelLarge : context.tt.titleSmall)
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
        ),
        if (identity.username.isNotEmpty) ...[
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              '@${identity.username}',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: context.tt.bodySmall?.copyWith(color: ds.textMid),
            ),
          ),
        ],
        const SizedBox(width: 6),
        Text('· ${relativeTime(ts)}',
            style: context.tt.labelSmall?.copyWith(color: ds.textLow)),
      ],
    );
  }
}

/// A top-level comment + its (collapsible) replies. Stage 7: deep chains stay
/// readable — replies are collapsed behind a counter and expanded on demand.
class _CommentThread extends HookWidget {
  const _CommentThread({
    super.key,
    required this.comment,
    required this.replies,
    required this.state,
    required this.onReply,
  });

  final SocialCommentDto comment;
  final List<SocialCommentDto> replies;
  final PostThreadState state;
  final ValueChanged<SocialCommentDto> onReply;

  @override
  Widget build(BuildContext context) {
    final expanded = useState<bool>(false);
    return Padding(
      padding: const EdgeInsets.only(bottom: InsightSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _CommentTile(
            comment: comment,
            identity: state.identityFor(comment.authorId, comment.authorType),
            onReply: () => onReply(comment),
          ),
          if (replies.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(left: 38, top: InsightSpacing.xs),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _RepliesToggle(
                    count: replies.length,
                    expanded: expanded.value,
                    onTap: () => expanded.value = !expanded.value,
                  ),
                  if (expanded.value)
                    for (final r in replies)
                      Padding(
                        key: ValueKey(r.id),
                        padding: const EdgeInsets.only(top: InsightSpacing.sm),
                        // Replies are depth 2 — capped by the backend, so no
                        // further nesting (avoids infinite vertical trees).
                        child: _CommentTile(
                          comment: r,
                          identity: state.identityFor(r.authorId, r.authorType),
                          onReply: null,
                          compact: true,
                        ),
                      ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _RepliesToggle extends StatelessWidget {
  const _RepliesToggle({
    required this.count,
    required this.expanded,
    required this.onTap,
  });
  final int count;
  final bool expanded;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final label = expanded
        ? 'Ocultar respostas'
        : (count == 1 ? 'Ver 1 resposta' : 'Ver $count respostas');
    return Semantics(
      button: true,
      label: label,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 4),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                expanded
                    ? Icons.expand_less_rounded
                    : Icons.expand_more_rounded,
                size: 16,
                color: ds.signal,
              ),
              const SizedBox(width: 4),
              Text(label,
                  style: context.tt.labelSmall?.copyWith(
                      color: ds.signal, fontWeight: FontWeight.w700)),
            ],
          ),
        ),
      ),
    );
  }
}

class _CommentTile extends StatelessWidget {
  const _CommentTile({
    required this.comment,
    required this.identity,
    required this.onReply,
    this.compact = false,
  });
  final SocialCommentDto comment;
  final AuthorIdentity identity;
  final VoidCallback? onReply;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      label: 'Comentário de ${identity.displayName}',
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            button: true,
            label: 'Abrir perfil de ${identity.displayName}',
            child: GestureDetector(
              onTap: () =>
                  _openAuthor(context, comment.authorId, comment.authorType),
              child: InsightAvatar(
                avatarUrl: identity.avatarUrl,
                initials: identity.initials,
                colorHex: identity.accentColor,
                size: compact ? 28 : 32,
              ),
            ),
          ),
          const SizedBox(width: InsightSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _IdentityLine(
                    identity: identity, ts: comment.createdAt, compact: true),
                const SizedBox(height: 2),
                Text(comment.content,
                    style: context.tt.bodyMedium?.copyWith(height: 1.35)),
                if (onReply != null)
                  Semantics(
                    button: true,
                    label: 'Responder a ${identity.displayName}',
                    child: TextButton(
                      onPressed: onReply,
                      style: TextButton.styleFrom(
                        padding: EdgeInsets.zero,
                        minimumSize: const Size(0, 32),
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                      child: Text('Responder',
                          style: context.tt.labelSmall
                              ?.copyWith(color: context.ds.signal)),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Composer extends HookWidget {
  const _Composer({
    required this.controller,
    required this.focusNode,
    required this.replyingTo,
    required this.replyingToIdentity,
    required this.onCancelReply,
    required this.sending,
    required this.onSend,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final SocialCommentDto? replyingTo;
  final AuthorIdentity? replyingToIdentity;
  final VoidCallback onCancelReply;
  final bool sending;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    useListenable(focusNode);
    return SafeArea(
      top: false,
      child: Container(
        decoration: BoxDecoration(
          border:
              Border(top: BorderSide(color: context.ds.divider, width: 0.5)),
        ),
        padding: const EdgeInsets.fromLTRB(
          InsightSpacing.lg,
          InsightSpacing.sm,
          InsightSpacing.lg,
          InsightSpacing.sm,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Stage 6 — reply context: who you're answering + a quoted excerpt.
            if (replyingTo != null && replyingToIdentity != null)
              _ReplyContext(
                identity: replyingToIdentity!,
                excerpt: replyingTo!.content,
                onCancel: onCancelReply,
              ),
            AnimatedContainer(
              duration: const Duration(milliseconds: 160),
              curve: Curves.easeOutCubic,
              decoration: BoxDecoration(
                color: context.ds.subtle.withValues(alpha: 0.55),
                borderRadius: BorderRadius.circular(22),
                border: Border.all(
                  color: focusNode.hasFocus
                      ? context.ds.signal.withValues(alpha: 0.40)
                      : context.ds.divider,
                  width: focusNode.hasFocus ? 1.1 : 0.8,
                ),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: controller,
                      focusNode: focusNode,
                      minLines: 1,
                      maxLines: 4,
                      textCapitalization: TextCapitalization.sentences,
                      cursorColor: context.ds.signal,
                      cursorWidth: 2,
                      cursorRadius: const Radius.circular(2),
                      style: context.tt.bodyMedium?.copyWith(height: 1.35),
                      decoration: InputDecoration(
                        hintText: replyingToIdentity == null
                            ? 'Escreva um comentário…'
                            : 'Responder a ${replyingToIdentity!.displayName}…',
                        hintStyle: context.tt.bodyMedium
                            ?.copyWith(color: context.ds.textLow),
                        border: InputBorder.none,
                        enabledBorder: InputBorder.none,
                        focusedBorder: InputBorder.none,
                        isDense: false,
                        contentPadding: const EdgeInsets.fromLTRB(
                          InsightSpacing.md,
                          11,
                          InsightSpacing.sm,
                          11,
                        ),
                      ),
                    ),
                  ),
                  sending
                      ? const Padding(
                          padding: EdgeInsets.all(12),
                          child: SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          ),
                        )
                      : Padding(
                          padding: const EdgeInsets.only(right: 4),
                          child: IconButton(
                            onPressed: onSend,
                            icon: const Icon(Icons.send_rounded),
                            color: context.ds.signal,
                            tooltip: 'Enviar',
                            constraints: const BoxConstraints(
                              minWidth: 44,
                              minHeight: 44,
                            ),
                            style: IconButton.styleFrom(
                              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                            ),
                          ),
                        ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ReplyContext extends StatelessWidget {
  const _ReplyContext({
    required this.identity,
    required this.excerpt,
    required this.onCancel,
  });
  final AuthorIdentity identity;
  final String excerpt;
  final VoidCallback onCancel;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final quoted = excerpt.trim().replaceAll('\n', ' ');
    return Container(
      margin: const EdgeInsets.only(bottom: InsightSpacing.sm),
      padding: const EdgeInsets.fromLTRB(10, 8, 8, 8),
      decoration: BoxDecoration(
        color: ds.subtle,
        borderRadius: BorderRadius.circular(10),
        border: Border(left: BorderSide(color: ds.signal, width: 2.5)),
      ),
      child: Row(
        children: [
          InsightAvatar(
            avatarUrl: identity.avatarUrl,
            initials: identity.initials,
            colorHex: identity.accentColor,
            size: 26,
          ),
          const SizedBox(width: InsightSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Respondendo a ${identity.displayName}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.tt.labelSmall?.copyWith(
                      color: ds.textMid, fontWeight: FontWeight.w700),
                ),
                Text(
                  '“$quoted”',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.tt.bodySmall?.copyWith(color: ds.textLow),
                ),
              ],
            ),
          ),
          Semantics(
            button: true,
            label: 'Cancelar resposta',
            child: IconButton(
              onPressed: onCancel,
              visualDensity: VisualDensity.compact,
              constraints: const BoxConstraints(minWidth: 40, minHeight: 40),
              icon: Icon(Icons.close_rounded, size: 18, color: ds.textMid),
              tooltip: 'Cancelar',
            ),
          ),
        ],
      ),
    );
  }
}
