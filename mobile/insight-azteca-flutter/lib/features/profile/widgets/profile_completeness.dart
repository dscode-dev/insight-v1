// AZTECA-IDENTITY-B — Sports Identity completeness (Stage 3).
//
// A DETERMINISTIC score over real profile fields — no AI, no mock values. Each
// item is either present (from the backend) or missing; the percentage is
// simply done/total. Shown only on the owner's profile to nudge enrichment.
import 'package:flutter/material.dart';

import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/spacing.dart';
import 'sports_profile_header.dart';

class CompletenessItem {
  const CompletenessItem(this.label, this.done, this.hint);
  final String label;
  final bool done;
  final String hint;
}

class ProfileCompleteness {
  const ProfileCompleteness(this.items);

  /// Deterministic checklist over ONLY real, user-ACTIONABLE fields
  /// (AZTECA-PROFILE-B, Stage 14). favoriteTeam + location were removed from the
  /// denominator: the users schema does not model them and they are not editable
  /// in V1, so including them permanently penalized every user (100% was
  /// impossible). They return when the backend models + Edit Profile exposes
  /// them. Kept items are all achievable through actions the user can take now:
  /// avatar (Edit Profile), display name (Edit Profile), username (set at
  /// signup), and joining a community.
  factory ProfileCompleteness.of(ProfileIdentity id) => ProfileCompleteness([
        CompletenessItem('Foto de perfil', id.avatarUrl != null,
            'Adicione uma foto para ser reconhecido'),
        CompletenessItem('Nome de exibição', id.displayName.trim().isNotEmpty,
            'Diga como quer ser chamado'),
        CompletenessItem('Nome de usuário', id.username.trim().isNotEmpty,
            'Escolha um @username'),
        CompletenessItem('Comunidades', (id.communities ?? 0) > 0,
            'Participe de pelo menos uma comunidade'),
      ]);

  final List<CompletenessItem> items;

  int get total => items.length;
  int get completed => items.where((i) => i.done).length;
  double get fraction => total == 0 ? 0 : completed / total;
  int get percent => (fraction * 100).round();
  List<CompletenessItem> get missing =>
      items.where((i) => !i.done).toList(growable: false);
}

/// Owner-only completeness card: ring + % + missing items as suggestions.
class ProfileCompletenessCard extends StatelessWidget {
  const ProfileCompletenessCard({super.key, required this.identity});
  final ProfileIdentity identity;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final c = ProfileCompleteness.of(identity);
    if (c.percent >= 100) return const SizedBox.shrink();
    return Semantics(
      container: true,
      label: 'Perfil ${c.percent}% completo',
      child: Container(
        margin: const EdgeInsets.fromLTRB(InsightSpacing.xl, InsightSpacing.sm,
            InsightSpacing.xl, InsightSpacing.sm),
        padding: const EdgeInsets.all(InsightSpacing.lg),
        decoration: BoxDecoration(
          color: ds.subtle,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                SizedBox(
                  width: 40,
                  height: 40,
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      CircularProgressIndicator(
                        value: c.fraction,
                        strokeWidth: 4,
                        backgroundColor: ds.divider,
                        valueColor: AlwaysStoppedAnimation(ds.signal),
                      ),
                      Text('${c.percent}',
                          style: context.tt.labelSmall
                              ?.copyWith(fontWeight: FontWeight.w700)),
                    ],
                  ),
                ),
                const SizedBox(width: InsightSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Complete sua identidade',
                          style: context.tt.titleSmall
                              ?.copyWith(fontWeight: FontWeight.w700)),
                      Text('${c.completed} de ${c.total} itens concluídos',
                          style: context.tt.bodySmall
                              ?.copyWith(color: ds.textLow)),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: InsightSpacing.md),
            for (final m in c.missing)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Row(
                  children: [
                    Icon(Icons.radio_button_unchecked_rounded,
                        size: 16, color: ds.textLow),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text.rich(
                        TextSpan(children: [
                          TextSpan(
                              text: m.label,
                              style: context.tt.bodySmall?.copyWith(
                                  color: ds.textHigh,
                                  fontWeight: FontWeight.w600)),
                          TextSpan(
                              text: ' · ${m.hint}',
                              style: context.tt.bodySmall
                                  ?.copyWith(color: ds.textLow)),
                        ]),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
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
