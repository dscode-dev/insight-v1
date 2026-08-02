import 'package:flutter/material.dart';

import '../../core/feature_gate.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../providers/radar_provider.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../shared/strings/pt_br.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/error_state.dart';
import '../../widgets/search_action.dart';
import '../../widgets/section_header.dart';
import 'widgets/community_signal_row.dart';
import 'widgets/movement_row.dart';
import 'widgets/radar_filters.dart';
import 'widgets/radar_skeleton.dart';
import 'widgets/trending_card.dart';

class RadarScreen extends ConsumerWidget {
  const RadarScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(radarBundleProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text(S.navRadar),
        actions: const [SearchAction()],
      ),
      body: Column(
        children: [
          const RadarFiltersBar(),
          Divider(height: 1, thickness: 0.6, color: context.ds.divider),
          Expanded(
            child: RefreshIndicator(
              color: context.ds.signal,
              backgroundColor: context.ds.card,
              onRefresh: () async => ref.invalidate(radarBundleProvider),
              child: async.when(
                loading: () => const RadarScreenSkeleton(),
                error: (e, _) => isFeatureUnavailable(e)
                    ? const FeatureUnavailableView(message: 'Radar em breve')
                    : ListView(
                        children: [
                          ErrorState(
                            title: 'Radar fora do ar',
                            description:
                                'Não consegui carregar os movimentos agora. Tente de novo.',
                            onRetry: () => ref.invalidate(radarBundleProvider),
                          ),
                        ],
                      ),
                data: (bundle) {
                  if (bundle.trending.isEmpty &&
                      bundle.movements.isEmpty &&
                      bundle.signals.isEmpty) {
                    return const SingleChildScrollView(
                      physics: AlwaysScrollableScrollPhysics(),
                      child: EmptyState(
                        title: 'Radar quieto nessa janela',
                        description:
                            'Mude o intervalo acima ou aguarde o mercado se mexer.',
                      ),
                    );
                  }
                  return ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: [
                      const SectionHeader(title: 'Em alta agora'),
                      SizedBox(
                        height: 132,
                        child: ListView.separated(
                          scrollDirection: Axis.horizontal,
                          padding:
                              const EdgeInsets.symmetric(horizontal: 20),
                          itemCount: bundle.trending.length,
                          separatorBuilder: (_, __) =>
                              const SizedBox(width: 10),
                          itemBuilder: (_, i) =>
                              TrendingMatchCard(match: bundle.trending[i]),
                        ),
                      ),
                      const SectionHeader(title: 'Sinais do mercado'),
                      if (bundle.movements.isEmpty)
                        const _SectionEmpty(
                          message: 'Nenhum sinal nessa janela.',
                        )
                      else
                        ...bundle.movements
                            .map((m) => MovementRow(movement: m)),
                      const SectionHeader(title: 'Sinais da comunidade'),
                      if (bundle.signals.isEmpty)
                        const _SectionEmpty(
                          message: 'Sem sinais novos por aqui ainda.',
                        )
                      else
                        ...bundle.signals
                            .map((s) => CommunitySignalRow(signal: s)),
                      const SizedBox(height: 32),
                    ],
                  );
                },
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Small inline empty for individual sections (not a full-screen state).
class _SectionEmpty extends StatelessWidget {
  const _SectionEmpty({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
      child: Text(
        message,
        style: context.tt.bodySmall?.copyWith(color: context.ds.textLow),
      ),
    );
  }
}
