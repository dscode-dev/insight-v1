// Sprint A — Discussion thread screen.
//
// Layout (top → bottom):
//   * AppBar with community handle in subtitle (taps back to Hub)
//   * Header card: title + body + author chip + counts
//   * Replies list (chronological, oldest at top)
//   * Sticky reply composer pinned to the bottom inset
//
// Keyboard handling: the composer sits inside SafeArea + listens to
// MediaQuery.viewInsets so it floats above the IME instead of being
// covered. The replies list auto-scrolls to the bottom whenever a
// reply is appended (optimistic OR persisted) so the user sees their
// message land.
import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';
import 'package:intl/intl.dart';

import '../../models/discussion_thread.dart';
import '../../providers/discussion_thread_provider.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../theme/radii.dart';
import '../../theme/spacing.dart';
import '../../widgets/avatar.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/error_state.dart';

const _maxReplyChars = 16384;

class DiscussionThreadScreen extends HookConsumerWidget {
  const DiscussionThreadScreen({super.key, required this.discussionId});
  final String discussionId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detailAsync = ref.watch(discussionDetailProvider(discussionId));
    final thread = ref.watch(discussionThreadNotifierProvider(discussionId));
    final notifier =
        ref.read(discussionThreadNotifierProvider(discussionId).notifier);

    final scrollController = useScrollController();
    final composerController = useTextEditingController();
    final composerLength = useState(0);

    // Sync composer counter with controller.
    useEffect(() {
      void onChange() => composerLength.value = composerController.text.length;
      composerController.addListener(onChange);
      return () => composerController.removeListener(onChange);
    }, [composerController]);

    // Auto-scroll on new messages.
    final lastLen = useRef(thread.messages.length);
    useEffect(() {
      if (thread.messages.length > lastLen.value) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (scrollController.hasClients) {
            scrollController.animateTo(
              scrollController.position.maxScrollExtent,
              duration: const Duration(milliseconds: 200),
              curve: Curves.easeOut,
            );
          }
        });
      }
      lastLen.value = thread.messages.length;
      return null;
    }, [thread.messages.length]);

    Future<void> submitReply() async {
      final body = composerController.text;
      if (body.trim().isEmpty || thread.isPosting) return;
      final ok = await notifier.postReply(body);
      if (ok) {
        composerController.clear();
        composerLength.value = 0;
      } else if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Não consegui enviar sua resposta')),
        );
      }
    }

    return Scaffold(
      appBar: AppBar(
        title: detailAsync.when(
          loading: () => const Text('Discussão'),
          error: (_, __) => const Text('Discussão'),
          data: (d) => Text(d?.communityHandle ?? 'Discussão'),
        ),
      ),
      body: detailAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ErrorState(
          title: 'Discussão indisponível',
          description: 'Não consegui carregar essa thread.',
          onRetry: () => ref.invalidate(discussionDetailProvider(discussionId)),
        ),
        data: (detail) {
          if (detail == null) {
            return const EmptyState(
              title: 'Discussão não encontrada',
              description: 'Pode ter sido removida.',
            );
          }
          return Column(
            children: [
              Expanded(
                child: RefreshIndicator(
                  color: context.ds.signal,
                  backgroundColor: context.ds.card,
                  onRefresh: () async {
                    ref.invalidate(discussionDetailProvider(discussionId));
                    await notifier.loadInitial();
                  },
                  child: ListView(
                    controller: scrollController,
                    physics: const AlwaysScrollableScrollPhysics(),
                    padding: const EdgeInsets.only(bottom: 120),
                    children: [
                      _Header(detail: detail),
                      const _Divider(),
                      if (thread.isLoadingInitial)
                        const Padding(
                          padding: EdgeInsets.symmetric(vertical: 24),
                          child: Center(child: CircularProgressIndicator()),
                        )
                      else if (thread.loadError != null && thread.messages.isEmpty)
                        ErrorState(
                          title: 'Respostas indisponíveis',
                          description: 'Tente puxar para atualizar.',
                          onRetry: notifier.loadInitial,
                        )
                      else if (thread.messages.isEmpty)
                        const EmptyState(
                          title: 'Ainda sem respostas',
                          description: 'Seja o primeiro a responder.',
                        )
                      else ...[
                        ...thread.messages.map((m) => _MessageRow(message: m)),
                        if (thread.hasMore) ...[
                          const SizedBox(height: 12),
                          Center(
                            child: TextButton(
                              onPressed: thread.isLoadingMore
                                  ? null
                                  : notifier.loadMore,
                              child: Text(
                                thread.isLoadingMore
                                    ? 'Carregando…'
                                    : 'Ver mais',
                              ),
                            ),
                          ),
                        ],
                      ],
                    ],
                  ),
                ),
              ),
              _ReplyComposer(
                controller: composerController,
                length: composerLength.value,
                posting: thread.isPosting,
                onSubmit: submitReply,
              ),
            ],
          );
        },
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.detail});
  final DiscussionDetail detail;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
      child: Container(
        padding: const EdgeInsets.all(InsightSpacing.lg),
        decoration: BoxDecoration(
          color: context.ds.card,
          borderRadius: InsightRadii.brLg,
          border: Border.all(color: context.ds.divider),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                InsightAvatar(
                  initials: detail.authorInitials ?? '??',
                  colorHex: detail.authorAccent ?? '#5BA8FF',
                  size: 36,
                ),
                const SizedBox(width: InsightSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        detail.authorDisplayName ?? 'Autor',
                        style: context.tt.titleMedium,
                      ),
                      if (detail.communityName != null)
                        Text(
                          detail.communityName!,
                          style: context.tt.labelSmall
                              ?.copyWith(color: context.ds.textLow),
                        ),
                    ],
                  ),
                ),
                Text(
                  DateFormat('dd/MM HH:mm').format(detail.createdAt.toLocal()),
                  style: context.tt.labelSmall
                      ?.copyWith(color: context.ds.textLow),
                ),
              ],
            ),
            const SizedBox(height: InsightSpacing.lg),
            Text(detail.title, style: context.tt.titleLarge),
            const SizedBox(height: 8),
            Text(
              detail.body,
              style: context.tt.bodyMedium?.copyWith(color: context.ds.textMid),
            ),
            const SizedBox(height: InsightSpacing.lg),
            Row(
              children: [
                Icon(Icons.mode_comment_outlined,
                    size: 14, color: context.ds.textLow),
                const SizedBox(width: 4),
                Text(
                  '${detail.replyCount} respostas',
                  style: context.tt.labelSmall
                      ?.copyWith(color: context.ds.textMid),
                ),
                const SizedBox(width: InsightSpacing.lg),
                Icon(Icons.favorite_outline,
                    size: 14, color: context.ds.textLow),
                const SizedBox(width: 4),
                Text(
                  '${detail.reactionCount} curtidas',
                  style: context.tt.labelSmall
                      ?.copyWith(color: context.ds.textMid),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _MessageRow extends StatelessWidget {
  const _MessageRow({required this.message});
  final DiscussionMessage message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 10, 20, 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InsightAvatar(
            initials: message.authorInitials ?? '??',
            colorHex: message.authorAccent ?? '#5BA8FF',
            size: 32,
          ),
          const SizedBox(width: InsightSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        message.authorDisplayName ?? 'Membro',
                        style: context.tt.titleSmall,
                      ),
                    ),
                    Text(
                      DateFormat('HH:mm').format(message.ts.toLocal()),
                      style: context.tt.labelSmall
                          ?.copyWith(color: context.ds.textLow),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  message.body,
                  style: context.tt.bodyMedium
                      ?.copyWith(color: context.ds.textMid),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Divider extends StatelessWidget {
  const _Divider();
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 4),
      child: Divider(height: 1, thickness: 0.6, color: context.ds.divider),
    );
  }
}

class _ReplyComposer extends StatelessWidget {
  const _ReplyComposer({
    required this.controller,
    required this.length,
    required this.posting,
    required this.onSubmit,
  });

  final TextEditingController controller;
  final int length;
  final bool posting;
  final Future<void> Function() onSubmit;

  @override
  Widget build(BuildContext context) {
    final canSend = length > 0 && length <= _maxReplyChars && !posting;
    return SafeArea(
      top: false,
      child: Container(
        decoration: BoxDecoration(
          color: context.ds.card,
          border: Border(top: BorderSide(color: context.ds.divider)),
        ),
        padding: EdgeInsets.fromLTRB(
          InsightSpacing.lg,
          InsightSpacing.md,
          InsightSpacing.md,
          InsightSpacing.md + MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                maxLines: 4,
                minLines: 1,
                textInputAction: TextInputAction.newline,
                maxLength: _maxReplyChars,
                decoration: InputDecoration(
                  hintText: 'Responder…',
                  counterText: '',
                  isDense: true,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(22),
                    borderSide: BorderSide(color: context.ds.divider),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(22),
                    borderSide: BorderSide(color: context.ds.divider),
                  ),
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 10,
                  ),
                ),
              ),
            ),
            const SizedBox(width: InsightSpacing.sm),
            _SendButton(enabled: canSend, busy: posting, onTap: onSubmit),
          ],
        ),
      ),
    );
  }
}

class _SendButton extends StatelessWidget {
  const _SendButton({
    required this.enabled,
    required this.busy,
    required this.onTap,
  });
  final bool enabled;
  final bool busy;
  final Future<void> Function() onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: enabled ? context.ds.signal : context.ds.subtle,
      shape: const CircleBorder(),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: enabled ? () async => onTap() : null,
        child: SizedBox(
          width: 40,
          height: 40,
          child: busy
              ? const Padding(
                  padding: EdgeInsets.all(10),
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Colors.white,
                  ),
                )
              : Icon(
                  Icons.send_rounded,
                  size: 18,
                  color: enabled ? Colors.white : context.ds.textLow,
                ),
        ),
      ),
    );
  }
}
