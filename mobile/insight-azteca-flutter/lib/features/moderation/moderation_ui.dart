// Store-A — shared UGC-safety UI: the post/profile 3-dot menu, the report
// reason picker, and the post-report confirmation (with offer to block + hide).
//
// Report flow is ≤3 taps: open menu (1) → "Denunciar" (2) → pick a reason (3,
// submits). Blocking hides content immediately (optimistic via
// blockedUsersProvider); reporting offers to also block the author and/or hide
// the post locally.

import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../providers/moderation_provider.dart';
import '../../services/moderation_service.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../theme/spacing.dart';
import '../../widgets/insight_bottom_sheet.dart';

/// Three-dot menu button for a feed post. Official-agent authors can be
/// reported but NOT blocked (Store-A Part 5).
class PostMenuButton extends ConsumerWidget {
  const PostMenuButton({
    super.key,
    required this.postId,
    required this.authorId,
    required this.authorName,
    required this.authorIsAgent,
  });

  final String postId;
  final String authorId;
  final String authorName;
  final bool authorIsAgent;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return IconButton(
      icon: Icon(Icons.more_horiz_rounded, size: 20, color: context.ds.textLow),
      visualDensity: VisualDensity.compact,
      padding: EdgeInsets.zero,
      constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
      tooltip: 'Opções',
      onPressed: () => showPostMenu(
        context,
        ref,
        postId: postId,
        authorId: authorId,
        authorName: authorName,
        authorIsAgent: authorIsAgent,
      ),
    );
  }
}

/// Opens the post options sheet: report / block author / hide.
Future<void> showPostMenu(
  BuildContext context,
  WidgetRef ref, {
  required String postId,
  required String authorId,
  required String authorName,
  required bool authorIsAgent,
}) async {
  await showInsightBottomSheet<void>(
    context: context,
    builder: (sheetCtx) => InsightBottomSheet(
      title: 'Opções da publicação',
      children: [
        InsightSheetAction(
          icon: Icons.flag_outlined,
          title: 'Denunciar publicação',
          onTap: () {
            Navigator.of(sheetCtx).pop();
            showReportReasons(
              context,
              ref,
              target: ReportTarget.post,
              targetId: postId,
              authorId: authorId,
              authorName: authorName,
              authorIsAgent: authorIsAgent,
              offerHidePost: postId,
            );
          },
        ),
        if (!authorIsAgent)
          InsightSheetAction(
            icon: Icons.block_outlined,
            title: 'Bloquear $authorName',
            destructive: true,
            onTap: () {
              Navigator.of(sheetCtx).pop();
              _confirmBlock(context, ref, authorId, authorName);
            },
          ),
        InsightSheetAction(
          icon: Icons.visibility_off_outlined,
          title: 'Ocultar esta publicação',
          onTap: () {
            Navigator.of(sheetCtx).pop();
            ref.read(hiddenPostsProvider.notifier).hide(postId);
          },
        ),
      ],
    ),
  );
}

/// Profile options sheet (Store-A Part 5): report + block. Official agents can
/// be reported but NOT blocked ([isAgent] = true hides the block action).
Future<void> showProfileMenu(
  BuildContext context,
  WidgetRef ref, {
  required String userId,
  required String name,
  required bool isAgent,
}) async {
  await showInsightBottomSheet<void>(
    context: context,
    builder: (sheetCtx) => InsightBottomSheet(
      title: 'Opções do perfil',
      children: [
        InsightSheetAction(
          icon: Icons.flag_outlined,
          title: isAgent ? 'Denunciar conteúdo' : 'Denunciar $name',
          onTap: () {
            Navigator.of(sheetCtx).pop();
            showReportReasons(
              context,
              ref,
              target: ReportTarget.user,
              targetId: userId,
              authorId: userId,
              authorName: name,
              authorIsAgent: isAgent,
            );
          },
        ),
        if (!isAgent)
          InsightSheetAction(
            icon: Icons.block_outlined,
            title: 'Bloquear $name',
            destructive: true,
            onTap: () {
              Navigator.of(sheetCtx).pop();
              _confirmBlock(context, ref, userId, name);
            },
          ),
      ],
    ),
  );
}

/// Reason picker. Tapping a reason submits the report immediately (tap 3) and
/// then shows the confirmation with the option to block/hide.
Future<void> showReportReasons(
  BuildContext context,
  WidgetRef ref, {
  required ReportTarget target,
  required String targetId,
  String? authorId,
  String? authorName,
  bool authorIsAgent = false,
  String? offerHidePost,
}) async {
  await showInsightBottomSheet<void>(
    context: context,
    builder: (sheetCtx) => InsightBottomSheet(
      title: 'Qual é o motivo?',
      subtitle: 'Sua denúncia ajuda a manter a comunidade confiável.',
      children: [
        for (final reason in ReportReason.values)
          ListTile(
            title: Text(reason.label),
            onTap: () async {
              Navigator.of(sheetCtx).pop();
              await _submitAndConfirm(
                context,
                ref,
                target: target,
                targetId: targetId,
                reason: reason,
                authorId: authorId,
                authorName: authorName,
                authorIsAgent: authorIsAgent,
                offerHidePost: offerHidePost,
              );
            },
          ),
      ],
    ),
  );
}

Future<void> _submitAndConfirm(
  BuildContext context,
  WidgetRef ref, {
  required ReportTarget target,
  required String targetId,
  required ReportReason reason,
  String? authorId,
  String? authorName,
  bool authorIsAgent = false,
  String? offerHidePost,
}) async {
  try {
    await submitReport(ref, target: target, targetId: targetId, reason: reason);
  } catch (_) {
    if (context.mounted) {
      _snack(context, 'Não foi possível enviar a denúncia. Tente novamente.');
    }
    return;
  }
  if (!context.mounted) return;

  final canBlock = authorId != null && !authorIsAgent;
  await showInsightBottomSheet<void>(
    context: context,
    builder: (sheetCtx) => InsightBottomSheet(
      title: 'Denúncia enviada',
      subtitle: 'Nossa equipe vai revisar.',
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: InsightSpacing.md),
          child: Row(
            children: [
              Icon(Icons.check_circle, color: sheetCtx.ds.signal),
              const SizedBox(width: InsightSpacing.md),
              Expanded(
                child: Text(
                  'Denúncia enviada. Nossa equipe vai revisar.',
                  style: sheetCtx.tt.bodyLarge,
                ),
              ),
            ],
          ),
        ),
        if (offerHidePost != null)
          InsightSheetAction(
            icon: Icons.visibility_off_outlined,
            title: 'Ocultar esta publicação',
            onTap: () {
              ref.read(hiddenPostsProvider.notifier).hide(offerHidePost);
              Navigator.of(sheetCtx).pop();
            },
          ),
        if (canBlock)
          InsightSheetAction(
            icon: Icons.block_outlined,
            title: 'Bloquear ${authorName ?? 'autor'}',
            destructive: true,
            onTap: () async {
              Navigator.of(sheetCtx).pop();
              await _doBlock(context, ref, authorId, authorName ?? 'autor');
            },
          ),
        InsightSheetAction(
          icon: Icons.done_rounded,
          title: 'Concluir',
          onTap: () => Navigator.of(sheetCtx).pop(),
        ),
      ],
    ),
  );
}

Future<void> _confirmBlock(
  BuildContext context,
  WidgetRef ref,
  String userId,
  String name,
) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text('Bloquear $name?'),
      content: const Text(
        'As publicações e os comentários dessa pessoa somem do seu app. '
        'Você pode desbloquear depois.',
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar')),
        FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Bloquear')),
      ],
    ),
  );
  if (ok == true && context.mounted) {
    await _doBlock(context, ref, userId, name);
  }
}

Future<void> _doBlock(
  BuildContext context,
  WidgetRef ref,
  String userId,
  String name,
) async {
  // Optimistic: content hides immediately; reverts + warns on failure.
  final ok = await ref.read(blockedUsersProvider.notifier).block(userId);
  if (!context.mounted) return;
  _snack(context,
      ok ? '$name foi bloqueado.' : 'Não foi possível bloquear agora.');
}

void _snack(BuildContext context, String msg) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
}
