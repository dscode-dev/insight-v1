// AZTECA-PROFILE-A — the action rows for the shared Sports Profile header.
//
// Owner vs. public actions are the ONLY thing that differs between the
// logged-in profile and a public one, so they live in small dedicated widgets
// that drop into the header's `actions` slot. Owner-only controls (Edit /
// Settings) never appear on someone else's profile, and Follow/Report/More
// never appear on your own.
import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../providers/user_profile_provider.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/spacing.dart';
import '../../moderation/moderation_ui.dart';

/// Owner actions: Edit profile + Settings. Both route to REAL destinations
/// (the avatar editor and the Settings screen) — no placeholders.
class OwnerProfileActions extends StatelessWidget {
  const OwnerProfileActions({
    super.key,
    required this.onEdit,
    required this.onSettings,
  });

  final VoidCallback onEdit;
  final VoidCallback onSettings;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Semantics(
            button: true,
            label: 'Editar perfil',
            child: FilledButton.tonalIcon(
              onPressed: onEdit,
              icon: const Icon(Icons.edit_outlined, size: 18),
              label: const Text('Editar perfil'),
              style: FilledButton.styleFrom(
                minimumSize: const Size.fromHeight(44),
              ),
            ),
          ),
        ),
        const SizedBox(width: InsightSpacing.sm),
        Semantics(
          button: true,
          label: 'Configurações',
          child: OutlinedButton(
            onPressed: onSettings,
            style: OutlinedButton.styleFrom(
              minimumSize: const Size(44, 44),
              padding: const EdgeInsets.symmetric(horizontal: 14),
            ),
            child: const Icon(Icons.settings_outlined, size: 20),
          ),
        ),
      ],
    );
  }
}

/// Public actions: Follow/Unfollow + Message (disabled, prepared) + More
/// (report / block / mute via the shared moderation menu).
class PublicProfileActions extends ConsumerWidget {
  const PublicProfileActions({
    super.key,
    required this.userId,
    required this.displayName,
  });

  final String userId;
  final String displayName;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rel = ref.watch(userRelationProvider(userId));
    final notifier = ref.read(userRelationProvider(userId).notifier);
    final following = rel.following;

    return Row(
      children: [
        Expanded(
          child: Semantics(
            button: true,
            label: following ? 'Deixar de seguir' : 'Seguir',
            child: FilledButton(
              onPressed: notifier.toggleFollow,
              style: following
                  ? FilledButton.styleFrom(
                      backgroundColor: context.ds.subtle,
                      foregroundColor: context.ds.textHigh,
                      minimumSize: const Size.fromHeight(44),
                    )
                  : FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(44),
                    ),
              child: Text(following ? 'Seguindo' : 'Seguir'),
            ),
          ),
        ),
        const SizedBox(width: InsightSpacing.sm),
        // Message — prepared, intentionally disabled (no DM backend in V1).
        Semantics(
          button: true,
          enabled: false,
          label: 'Mensagem — em breve',
          child: OutlinedButton(
            onPressed: null,
            style: OutlinedButton.styleFrom(
              minimumSize: const Size(44, 44),
              padding: const EdgeInsets.symmetric(horizontal: 14),
            ),
            child: const Icon(Icons.mail_outline_rounded, size: 20),
          ),
        ),
        const SizedBox(width: InsightSpacing.sm),
        Semantics(
          button: true,
          label: 'Mais opções',
          child: OutlinedButton(
            onPressed: () => showProfileMenu(
              context,
              ref,
              userId: userId,
              name: displayName.isNotEmpty ? displayName : 'usuário',
              isAgent: false,
            ),
            style: OutlinedButton.styleFrom(
              minimumSize: const Size(44, 44),
              padding: const EdgeInsets.symmetric(horizontal: 14),
            ),
            child: const Icon(Icons.more_horiz_rounded, size: 20),
          ),
        ),
      ],
    );
  }
}
