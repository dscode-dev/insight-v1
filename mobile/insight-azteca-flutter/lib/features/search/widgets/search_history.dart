// AZTECA-SEARCH-UX-RESTORE — buscas recentes como SEÇÃO do Discovery.
//
// Histórico REAL do Gateway (fonte única — sem persistência local concorrente).
// Integra a hierarquia da Explore no slot da antiga seção fabricada
// "Tendências": nunca vira a página inteira. Vazio → a seção some (o hero +
// grid continuam dando valor à página); loading/erro → estados discretos que
// não destroem o layout.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/radii.dart';
import '../../../theme/spacing.dart';
import '../state/search_providers.dart';

class RecentSearchesSection extends ConsumerWidget {
  const RecentSearchesSection({super.key, required this.onSelect});
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final history = ref.watch(searchHistoryProvider);
    final actions = ref.read(searchHistoryActionsProvider);

    return history.when(
      loading: () => const SizedBox.shrink(), // discreto: sem spinner intrusivo
      error: (_, __) => const SizedBox.shrink(), // seção some; Discovery permanece
      data: (items) {
        if (items.isEmpty) return const SizedBox.shrink();
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Expanded(
                child: Text('Buscas recentes', style: context.tt.titleMedium),
              ),
              Semantics(
                button: true,
                label: 'Limpar histórico',
                child: TextButton(
                  onPressed: () => actions.clear(),
                  child: const Text('Limpar'),
                ),
              ),
            ]),
            const SizedBox(height: InsightSpacing.xs),
            for (final item in items.take(6))
              _RecentRow(query: item.query, onTap: () => onSelect(item.query)),
          ],
        );
      },
    );
  }
}

/// Linha na densidade visual aprovada da página (card com borda, radius md) —
/// a mesma linguagem das antigas _TrendRow, agora com dados reais.
class _RecentRow extends StatelessWidget {
  const _RecentRow({required this.query, required this.onTap});
  final String query;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: InsightSpacing.sm),
      decoration: BoxDecoration(
        color: context.ds.card,
        borderRadius: BorderRadius.circular(InsightRadii.md),
        border: Border.all(color: context.ds.divider),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(InsightRadii.md),
        child: Padding(
          padding: const EdgeInsets.all(InsightSpacing.lg),
          child: Row(
            children: [
              Icon(Icons.history_rounded, size: 18, color: context.ds.textLow),
              const SizedBox(width: InsightSpacing.md),
              Expanded(
                child: Text(query,
                    style: context.tt.bodyLarge,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis),
              ),
              Icon(Icons.north_west_rounded, size: 14, color: context.ds.textLow),
            ],
          ),
        ),
      ),
    );
  }
}
