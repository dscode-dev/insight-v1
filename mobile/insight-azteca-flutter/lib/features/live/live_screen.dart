import 'package:flutter/material.dart';

import '../../core/feature_gate.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../providers/live_provider.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../shared/strings/pt_br.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/error_state.dart';
import '../../widgets/search_action.dart';
import 'widgets/live_filters.dart';
import 'widgets/live_match_row.dart';
import 'widgets/live_skeleton.dart';

class LiveScreen extends ConsumerWidget {
  const LiveScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(liveMatchesProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text(S.navLive),
        actions: const [SearchAction()],
      ),
      body: Column(
        children: [
          const LiveFiltersBar(),
          Divider(height: 1, thickness: 0.6, color: context.ds.divider),
          Expanded(
            child: RefreshIndicator(
              color: context.ds.signal,
              backgroundColor: context.ds.card,
              onRefresh: () async => ref.invalidate(liveMatchesProvider),
              child: async.when(
                loading: () => ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  children: const [LiveScreenSkeleton()],
                ),
                error: (e, _) => isFeatureUnavailable(e)
                    ? const FeatureUnavailableView(message: 'Ao vivo em breve')
                    : ListView(
                        children: [
                          ErrorState(
                            title: 'Sem conexão com a Live',
                            description:
                                'Não consegui buscar os jogos. Toque pra tentar de novo.',
                            onRetry: () => ref.invalidate(liveMatchesProvider),
                          ),
                        ],
                      ),
                data: (matches) {
                  if (matches.isEmpty) {
                    return const SingleChildScrollView(
                      physics: AlwaysScrollableScrollPhysics(),
                      child: EmptyState(
                        title: 'Nenhuma partida agora',
                        description:
                            'Mude o filtro acima ou aguarde os próximos jogos.',
                      ),
                    );
                  }
                  return ListView.separated(
                    physics: const AlwaysScrollableScrollPhysics(),
                    itemCount: matches.length,
                    separatorBuilder: (_, __) => Divider(
                      height: 1,
                      thickness: 0.6,
                      color: context.ds.divider,
                    ),
                    itemBuilder: (_, i) => LiveMatchRow(match: matches[i]),
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
