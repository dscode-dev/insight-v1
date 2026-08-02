// AZTECA-COMPOSER-A — Production Composer.
//
// A full-screen, dedicated creation workspace (NOT a bottom sheet), inspired by
// X / Threads but keeping the Insight identity. It is the single entry point for
// every future content type (media, polls, sports entities, Atlas analysis) —
// those tools are PREPARED here (disabled "Em breve"), never faked.
//
// Layout: top app bar → user identity → large multiline editor → content tools →
// publication settings (type + visibility) → primary Publish CTA.
//
// Persistence: drafts use the existing secure-storage strategy (ComposerDraftStore).
// Backend: text-only posts via POST /v1/posts (socialApiProvider.createPost); the
// publication type + visibility ride in metadata — no client-side business rules.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../core/composer_draft_store.dart';
import '../../../providers/auth_provider.dart';
import '../../../providers/feed_provider.dart';
import '../../../providers/user_profile_provider.dart';
import '../../../services/social_mapping.dart';
import '../../../services/social_service.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/spacing.dart';
import '../../../widgets/avatar.dart';

const int _maxChars = 2000;
const int _warnAt = 200; // remaining chars at which the counter warns

/// One publication type. The backend stores the chosen `id` in post metadata;
/// the client only presents the options (no business logic here).
class _PubType {
  const _PubType(this.id, this.label, this.icon);
  final String id;
  final String label;
  final IconData icon;
}

const _pubTypes = <_PubType>[
  _PubType('opinion', 'Opinião', Icons.chat_bubble_outline_rounded),
  _PubType('analysis', 'Análise', Icons.insights_rounded),
  _PubType('prediction', 'Palpite', Icons.trending_up_rounded),
  _PubType('discussion', 'Discussão', Icons.forum_outlined),
  _PubType('news', 'Notícia', Icons.newspaper_rounded),
  _PubType('question', 'Pergunta', Icons.help_outline_rounded),
];

/// Visibility option. Only `public` is supported by the backend today; the rest
/// are prepared but disabled with an explicit explanation.
class _Visibility {
  const _Visibility(this.id, this.label, this.icon,
      {this.enabled = false, this.note});
  final String id;
  final String label;
  final IconData icon;
  final bool enabled;
  final String? note;
}

const _visibilities = <_Visibility>[
  _Visibility('public', 'Público', Icons.public_rounded, enabled: true),
  _Visibility('followers', 'Seguidores', Icons.group_outlined,
      note: 'Disponível em breve'),
  _Visibility('community', 'Comunidade', Icons.groups_outlined,
      note: 'Disponível em breve'),
  _Visibility('draft', 'Rascunho privado', Icons.lock_outline_rounded,
      note: 'Use "Salvar rascunho" ao sair'),
];

/// Content tools the composer is ARCHITECTURALLY prepared for. Only text (the
/// editor itself) is enabled today; the rest show "Em breve" — never a fake
/// upload or simulated media.
class _Tool {
  const _Tool(this.label, this.icon);
  final String label;
  final IconData icon;
}

const _tools = <_Tool>[
  _Tool('Foto', Icons.image_outlined),
  _Tool('Vídeo', Icons.videocam_outlined),
  _Tool('Enquete', Icons.poll_outlined),
  _Tool('Partida', Icons.sports_soccer_outlined),
  _Tool('Competição', Icons.emoji_events_outlined),
  _Tool('Jogador', Icons.person_outline_rounded),
  _Tool('Time', Icons.shield_outlined),
  _Tool('Análise Atlas', Icons.auto_awesome_outlined),
  _Tool('Local', Icons.place_outlined),
];

class ComposerScreen extends HookConsumerWidget {
  const ComposerScreen({super.key});

  /// Opens the composer as a full-screen modal (slide-up). Returns true when a
  /// post was published.
  static Future<bool?> open(BuildContext context) {
    return Navigator.of(context, rootNavigator: true).push<bool>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => const ComposerScreen(),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = useTextEditingController();
    final focusNode = useFocusNode();
    useListenable(focusNode);
    final type = useState<_PubType>(_pubTypes.first);
    final visibility = useState<_Visibility>(_visibilities.first);
    final length = useState<int>(0);
    final publishing = useState<bool>(false);
    final errorText = useState<String?>(null);
    final draftRecovered = useState<bool>(false);
    final published = useState<bool>(false);
    final store = useMemoized(ComposerDraftStore.new);
    final saveTimer = useRef<Timer?>(null);

    // Load any recovered draft + wire change → counter + debounced autosave.
    useEffect(() {
      void onChange() {
        length.value = controller.text.length;
        if (errorText.value != null) errorText.value = null;
        saveTimer.value?.cancel();
        saveTimer.value = Timer(const Duration(milliseconds: 600), () {
          store.write(text: controller.text, typeId: type.value.id);
        });
      }

      controller.addListener(onChange);

      () async {
        final draft = await store.read();
        if (draft != null && !context.mounted) return;
        if (draft != null) {
          controller.text = draft.text;
          controller.selection =
              TextSelection.collapsed(offset: draft.text.length);
          length.value = draft.text.length;
          type.value = _pubTypes.firstWhere(
            (t) => t.id == draft.typeId,
            orElse: () => _pubTypes.first,
          );
          draftRecovered.value = true;
        }
        // Defer focus until after the open animation to avoid keyboard jitter.
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (context.mounted) focusNode.requestFocus();
        });
      }();

      return () {
        saveTimer.value?.cancel();
        controller.removeListener(onChange);
      };
    }, [controller]);

    final user = ref.watch(authProvider.select((s) => s.user));
    final remaining = _maxChars - length.value;
    final overLimit = remaining < 0;
    final empty = controller.text.trim().isEmpty;
    final canPublish = !empty && !overLimit && !publishing.value;

    Future<void> discardDraft() async {
      controller.clear();
      length.value = 0;
      draftRecovered.value = false;
      await store.clear();
    }

    Future<void> submit() async {
      if (publishing.value) return;
      final body = controller.text.trim();
      if (body.isEmpty) {
        errorText.value = 'Escreva algo para publicar.';
        return;
      }
      if (body.length > _maxChars) {
        errorText.value =
            'Texto muito longo. Remova ${body.length - _maxChars} caractere(s).';
        return;
      }
      publishing.value = true;
      errorText.value = null;
      unawaited(HapticFeedback.selectionClick());
      try {
        final created = await ref.read(socialApiProvider).createPost(
              content: body,
              metadata: {
                'kind': type.value.id,
                'publication_type': type.value.id,
              },
              visibility: visibility.value.id,
            );
        final post = postToFeedPost(
          created,
          authorName: user?.displayName ?? 'Você',
        );
        ref.read(feedProvider.notifier).prepend(post);
        // AZTECA-POSTS-B: reconcile the owner's Activity surface so the freshly
        // persisted post is discoverable in Profile▸Atividades independent of feed
        // ranking (Activity reads the real GET /v1/users/{id}/posts).
        final myId = user?.id;
        if (myId != null && myId.isNotEmpty) {
          ref.invalidate(userPostsProvider(myId));
        }
        published.value = true;
        await store.clear();
        if (context.mounted) Navigator.of(context).pop(true);
      } catch (_) {
        // Backend unavailable → keep the draft + surface a clear, specific
        // inline error (no generic snackbar). The text is preserved.
        errorText.value =
            'Não foi possível publicar agora. Verifique sua conexão e tente novamente.';
        publishing.value = false;
      }
    }

    Future<bool> confirmExit() async {
      if (published.value || controller.text.trim().isEmpty) return true;
      final choice = await _showExitSheet(context);
      switch (choice) {
        case _ExitChoice.save:
          await store.write(text: controller.text, typeId: type.value.id);
          return true;
        case _ExitChoice.discard:
          await store.clear();
          return true;
        case _ExitChoice.keepEditing:
        case null:
          return false;
      }
    }

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        if (await confirmExit() && context.mounted) {
          Navigator.of(context).pop();
        }
      },
      child: Scaffold(
        appBar: AppBar(
          leading: IconButton(
            icon: const Icon(Icons.close_rounded),
            tooltip: 'Fechar',
            onPressed: publishing.value
                ? null
                : () async {
                    if (await confirmExit() && context.mounted) {
                      Navigator.of(context).pop();
                    }
                  },
          ),
          titleSpacing: 0,
          title: Text('Nova publicação', style: context.tt.titleMedium),
          actions: [
            Padding(
              padding: const EdgeInsets.only(right: InsightSpacing.md),
              child: _PublishButton(
                enabled: canPublish,
                publishing: publishing.value,
                onPressed: submit,
              ),
            ),
          ],
          bottom: PreferredSize(
            preferredSize: const Size.fromHeight(0.5),
            child: Divider(
              height: 0.5,
              thickness: 0.5,
              color: context.ds.divider,
            ),
          ),
        ),
        body: SafeArea(
          child: Column(
            children: [
              if (draftRecovered.value) _DraftBanner(onDiscard: discardDraft),
              // Scrollable creation area — identity + type + editor grow here.
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(
                    InsightSpacing.xl,
                    InsightSpacing.md,
                    InsightSpacing.xl,
                    InsightSpacing.md,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _Identity(
                        displayName: user?.displayName ?? 'Você',
                        accentColor: user?.accentColor ?? '#5BA8FF',
                        avatarUrl: user?.avatarUrl,
                        visibility: visibility.value,
                        onTapVisibility: () async {
                          final picked = await _showVisibilitySheet(
                              context, visibility.value);
                          if (picked != null) visibility.value = picked;
                        },
                      ),
                      const SizedBox(height: InsightSpacing.lg),
                      _TypeSelector(
                        value: type.value,
                        enabled: !publishing.value,
                        onChanged: (t) {
                          type.value = t;
                          store.write(text: controller.text, typeId: t.id);
                        },
                      ),
                      const SizedBox(height: InsightSpacing.lg),
                      AnimatedContainer(
                        duration: const Duration(milliseconds: 180),
                        curve: Curves.easeOutCubic,
                        decoration: BoxDecoration(
                          color: context.ds.subtle.withValues(alpha: 0.42),
                          borderRadius: BorderRadius.circular(22),
                          border: Border.all(
                            color: focusNode.hasFocus
                                ? context.ds.signal.withValues(alpha: 0.42)
                                : context.ds.divider,
                            width: focusNode.hasFocus ? 1.2 : 0.8,
                          ),
                        ),
                        child: Semantics(
                          label: 'Editor de texto da publicação',
                          textField: true,
                          child: TextField(
                            controller: controller,
                            focusNode: focusNode,
                            maxLength: null,
                            maxLines: null,
                            minLines: 7,
                            autocorrect: true,
                            enableInteractiveSelection: true,
                            textCapitalization: TextCapitalization.sentences,
                            keyboardType: TextInputType.multiline,
                            textInputAction: TextInputAction.newline,
                            cursorColor: context.ds.signal,
                            cursorWidth: 2,
                            cursorRadius: const Radius.circular(2),
                            style: context.tt.bodyLarge?.copyWith(height: 1.48),
                            decoration: InputDecoration(
                              hintText: 'O que você está pensando?',
                              hintStyle: context.tt.bodyLarge?.copyWith(
                                color: context.ds.textLow,
                                height: 1.48,
                              ),
                              border: InputBorder.none,
                              enabledBorder: InputBorder.none,
                              focusedBorder: InputBorder.none,
                              isDense: false,
                              contentPadding: const EdgeInsets.fromLTRB(
                                InsightSpacing.lg,
                                InsightSpacing.md,
                                InsightSpacing.lg,
                                InsightSpacing.md,
                              ),
                              counterText: '',
                            ),
                          ),
                        ),
                      ),
                      if (errorText.value != null) ...[
                        const SizedBox(height: InsightSpacing.md),
                        _ValidationMessage(text: errorText.value!),
                      ],
                    ],
                  ),
                ),
              ),
              // Bottom workspace bar — content tools + counter. Sits above the
              // keyboard; the whole Scaffold resizes for keyboard avoidance.
              _BottomBar(
                length: length.value,
                remaining: remaining,
                overLimit: overLimit,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// --------------------------------------------------------------------------
// Header / Publish
// --------------------------------------------------------------------------

class _PublishButton extends StatelessWidget {
  const _PublishButton({
    required this.enabled,
    required this.publishing,
    required this.onPressed,
  });

  final bool enabled;
  final bool publishing;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      enabled: enabled,
      label: 'Publicar',
      child: SizedBox(
        height: 38,
        child: FilledButton(
          onPressed: enabled ? onPressed : null,
          style: FilledButton.styleFrom(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            textStyle:
                context.tt.labelLarge?.copyWith(fontWeight: FontWeight.w700),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(20),
            ),
          ),
          child: publishing
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2.2,
                    valueColor: AlwaysStoppedAnimation(Colors.white),
                  ),
                )
              : const Text('Publicar'),
        ),
      ),
    );
  }
}

class _Identity extends StatelessWidget {
  const _Identity({
    required this.displayName,
    required this.accentColor,
    required this.avatarUrl,
    required this.visibility,
    required this.onTapVisibility,
  });

  final String displayName;
  final String accentColor;
  final String? avatarUrl;
  final _Visibility visibility;
  final VoidCallback onTapVisibility;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        InsightAvatar(
          avatarUrl: avatarUrl,
          initials: _initials(displayName),
          colorHex: accentColor,
          size: 44,
        ),
        const SizedBox(width: InsightSpacing.md),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                displayName,
                style: context.tt.titleSmall
                    ?.copyWith(fontWeight: FontWeight.w700),
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 4),
              // Current visibility chip — tappable to change.
              Semantics(
                button: true,
                label: 'Visibilidade: ${visibility.label}',
                child: InkWell(
                  onTap: onTapVisibility,
                  borderRadius: BorderRadius.circular(20),
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: context.ds.subtle,
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: context.ds.divider, width: 0.8),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(visibility.icon,
                            size: 14, color: context.ds.textMid),
                        const SizedBox(width: 6),
                        Text(
                          visibility.label,
                          style: context.tt.labelSmall
                              ?.copyWith(color: context.ds.textMid),
                        ),
                        const SizedBox(width: 2),
                        Icon(Icons.expand_more_rounded,
                            size: 14, color: context.ds.textLow),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  static String _initials(String name) {
    final parts = name.trim().split(RegExp(r'\s+'));
    if (parts.isEmpty || parts.first.isEmpty) return 'EU';
    if (parts.length == 1) {
      return parts.first
          .substring(0, parts.first.length.clamp(0, 2))
          .toUpperCase();
    }
    return (parts.first[0] + parts.last[0]).toUpperCase();
  }
}

// --------------------------------------------------------------------------
// Publication type selector
// --------------------------------------------------------------------------

class _TypeSelector extends StatelessWidget {
  const _TypeSelector({
    required this.value,
    required this.enabled,
    required this.onChanged,
  });

  final _PubType value;
  final bool enabled;
  final ValueChanged<_PubType> onChanged;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Tipo de publicação',
          style: context.tt.labelMedium
              ?.copyWith(color: ds.textLow, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: InsightSpacing.sm),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final t in _pubTypes)
              _TypeChip(
                type: t,
                selected: t.id == value.id,
                enabled: enabled,
                onTap: () => onChanged(t),
              ),
          ],
        ),
      ],
    );
  }
}

class _TypeChip extends StatelessWidget {
  const _TypeChip({
    required this.type,
    required this.selected,
    required this.enabled,
    required this.onTap,
  });

  final _PubType type;
  final bool selected;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final bg = selected ? ds.signal : ds.subtle;
    final fg = selected ? Colors.white : ds.textMid;
    return Semantics(
      button: true,
      selected: selected,
      label: 'Tipo ${type.label}',
      child: IgnorePointer(
        ignoring: !enabled,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(20),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 140),
            curve: Curves.easeOut,
            constraints: const BoxConstraints(minHeight: 38),
            padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 8),
            decoration: BoxDecoration(
              color: bg.withValues(alpha: enabled ? 1 : 0.6),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(
                color: selected ? Colors.transparent : ds.divider,
                width: 0.8,
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(type.icon, size: 15, color: fg),
                const SizedBox(width: 6),
                Text(
                  type.label,
                  style: context.tt.bodySmall
                      ?.copyWith(color: fg, fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// --------------------------------------------------------------------------
// Bottom bar: content tools + counter
// --------------------------------------------------------------------------

class _BottomBar extends StatelessWidget {
  const _BottomBar({
    required this.length,
    required this.remaining,
    required this.overLimit,
  });

  final int length;
  final int remaining;
  final bool overLimit;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Container(
      decoration: BoxDecoration(
        color: context.scheme.surface,
        border: Border(top: BorderSide(color: ds.divider, width: 0.5)),
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Content tools — horizontally scrollable; all "Em breve" today.
            SizedBox(
              height: 52,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(
                  horizontal: InsightSpacing.md,
                  vertical: InsightSpacing.sm,
                ),
                itemCount: _tools.length,
                separatorBuilder: (_, __) => const SizedBox(width: 6),
                itemBuilder: (_, i) => _ToolButton(tool: _tools[i]),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                InsightSpacing.lg,
                0,
                InsightSpacing.lg,
                InsightSpacing.sm,
              ),
              child: Row(
                children: [
                  Text(
                    'Apenas texto disponível',
                    style: context.tt.labelSmall?.copyWith(color: ds.textLow),
                  ),
                  const Spacer(),
                  // Character counter — turns amber/red near + over the limit.
                  Text(
                    '$length/$_maxChars',
                    style: context.tt.labelSmall?.copyWith(
                      color: overLimit
                          ? ds.signal
                          : (remaining <= _warnAt
                              ? const Color(0xFFE0A100)
                              : ds.textLow),
                      fontWeight: remaining <= _warnAt
                          ? FontWeight.w700
                          : FontWeight.w500,
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

class _ToolButton extends StatelessWidget {
  const _ToolButton({required this.tool});

  final _Tool tool;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    // Every tool is prepared but disabled — tapping explains "Em breve" rather
    // than faking a flow.
    return Semantics(
      button: true,
      enabled: false,
      label: '${tool.label} — em breve',
      child: Tooltip(
        message: '${tool.label} — em breve',
        child: InkWell(
          onTap: () {
            ScaffoldMessenger.of(context)
              ..hideCurrentSnackBar()
              ..showSnackBar(
                SnackBar(
                  behavior: SnackBarBehavior.floating,
                  content: Text('${tool.label}: disponível em breve'),
                  duration: const Duration(seconds: 2),
                ),
              );
          },
          borderRadius: BorderRadius.circular(12),
          child: Container(
            constraints: const BoxConstraints(minWidth: 44),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: ds.subtle.withValues(alpha: 0.6),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(tool.icon, size: 18, color: ds.textLow),
                const SizedBox(height: 2),
                Text(
                  tool.label,
                  style: context.tt.labelSmall
                      ?.copyWith(fontSize: 9, height: 1, color: ds.textLow),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// --------------------------------------------------------------------------
// Banners / validation / sheets
// --------------------------------------------------------------------------

class _DraftBanner extends StatelessWidget {
  const _DraftBanner({required this.onDiscard});

  final VoidCallback onDiscard;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Container(
      width: double.infinity,
      color: ds.signal.withValues(alpha: 0.10),
      padding: const EdgeInsets.symmetric(
        horizontal: InsightSpacing.xl,
        vertical: InsightSpacing.sm,
      ),
      child: Row(
        children: [
          Icon(Icons.history_rounded, size: 16, color: ds.signal),
          const SizedBox(width: InsightSpacing.sm),
          Expanded(
            child: Text(
              'Rascunho recuperado',
              style: context.tt.bodySmall?.copyWith(color: ds.textMid),
            ),
          ),
          TextButton(
            onPressed: onDiscard,
            child: const Text('Descartar'),
          ),
        ],
      ),
    );
  }
}

class _ValidationMessage extends StatelessWidget {
  const _ValidationMessage({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Container(
      padding: const EdgeInsets.all(InsightSpacing.md),
      decoration: BoxDecoration(
        color: ds.signal.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ds.signal.withValues(alpha: 0.30)),
      ),
      child: Row(
        children: [
          Icon(Icons.error_outline_rounded, size: 18, color: ds.signal),
          const SizedBox(width: InsightSpacing.sm),
          Expanded(
            child: Text(
              text,
              style: context.tt.bodySmall?.copyWith(color: ds.textHigh),
            ),
          ),
        ],
      ),
    );
  }
}

enum _ExitChoice { save, discard, keepEditing }

Future<_ExitChoice?> _showExitSheet(BuildContext context) {
  return showModalBottomSheet<_ExitChoice>(
    context: context,
    useSafeArea: true,
    showDragHandle: true,
    builder: (ctx) => SafeArea(
      top: false,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              InsightSpacing.xl,
              0,
              InsightSpacing.xl,
              InsightSpacing.sm,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Salvar rascunho?',
                    style: ctx.tt.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w700)),
                const SizedBox(height: InsightSpacing.xs),
                Text(
                  'Você tem texto não publicado. Pode salvá-lo para continuar depois.',
                  style: ctx.tt.bodySmall?.copyWith(color: ctx.ds.textLow),
                ),
              ],
            ),
          ),
          ListTile(
            leading: const Icon(Icons.save_outlined),
            title: const Text('Salvar rascunho'),
            onTap: () => Navigator.of(ctx).pop(_ExitChoice.save),
          ),
          ListTile(
            leading: Icon(Icons.delete_outline_rounded, color: ctx.ds.signal),
            title: Text('Descartar', style: TextStyle(color: ctx.ds.signal)),
            onTap: () => Navigator.of(ctx).pop(_ExitChoice.discard),
          ),
          ListTile(
            leading: const Icon(Icons.edit_outlined),
            title: const Text('Continuar editando'),
            onTap: () => Navigator.of(ctx).pop(_ExitChoice.keepEditing),
          ),
        ],
      ),
    ),
  );
}

Future<_Visibility?> _showVisibilitySheet(
  BuildContext context,
  _Visibility current,
) {
  return showModalBottomSheet<_Visibility>(
    context: context,
    useSafeArea: true,
    showDragHandle: true,
    builder: (ctx) => SafeArea(
      top: false,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              InsightSpacing.xl,
              0,
              InsightSpacing.xl,
              InsightSpacing.sm,
            ),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text('Quem pode ver',
                  style: ctx.tt.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w700)),
            ),
          ),
          for (final v in _visibilities)
            ListTile(
              enabled: v.enabled,
              leading: Icon(v.icon,
                  color: v.enabled ? ctx.ds.textHigh : ctx.ds.textLow),
              title: Text(v.label),
              subtitle: v.note == null ? null : Text(v.note!),
              trailing: v.id == current.id
                  ? Icon(Icons.check_rounded, color: ctx.ds.signal)
                  : null,
              onTap: v.enabled ? () => Navigator.of(ctx).pop(v) : null,
            ),
        ],
      ),
    ),
  );
}
