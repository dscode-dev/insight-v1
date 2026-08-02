// AZTECA-SEARCH-UX-RESTORE — Explore com Search composta dentro dela.
//
// Explore NÃO é sinônimo de Search: a superfície principal é a experiência de
// descoberta APROVADA (hero Radar + grid Descobrir + buscas recentes reais); a
// busca real da FEATURE-SEARCH-V1 é uma capacidade dentro dela.
//
//   query vazia   → _DiscoveryContent  (composição aprovada restaurada)
//   query válida  → _SearchResultsContent (tabs por capabilities + resultados)
//
// TUDO da FEATURE-SEARCH-V1 preservado: SearchController (debounce 300ms,
// CancelToken, epoch out-of-order, cursores por categoria, dedupe), capabilities
// backend-driven (sem Teams/Players), estados explícitos (partial ≠ success),
// histórico do Gateway, deep links validados, cards tipados.
//
// A antiga seção "Tendências" era trending FABRICADO (linhas hardcoded) e NÃO
// foi reintroduzida — o slot da hierarquia é ocupado pelas buscas recentes REAIS.

import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../routing/routes.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../theme/radii.dart';
import '../../theme/spacing.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/error_state.dart';
import '../../widgets/offline_state.dart';
import 'model/search_models.dart';
import 'state/search_controller.dart';
import 'state/search_providers.dart';
import 'state/search_state.dart';
import 'widgets/result_cards.dart';
import 'widgets/search_history.dart';

class SearchScreen extends HookConsumerWidget {
  const SearchScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = useTextEditingController();
    final query = useState('');
    final activeTab = useState(SearchCategory.all);

    void setQuery(String q) {
      query.value = q;
      for (final cat in SearchCategory.values) {
        ref.read(searchControllerProvider(cat).notifier).onQueryChanged(q);
      }
    }

    void submitQuery(String q) {
      controller.text = q;
      controller.selection = TextSelection.collapsed(offset: q.length);
      query.value = q;
      for (final cat in SearchCategory.values) {
        ref.read(searchControllerProvider(cat).notifier).submit(q);
      }
    }

    final searching = query.value.trim().length >= 2;

    return Scaffold(
      appBar: AppBar(title: const Text('Explorar')),
      body: Column(
        children: [
          // Campo no corpo, posição e paddings da composição aprovada — fixo no
          // topo para que a troca Discovery↔Results não cause salto de layout.
          Padding(
            padding: const EdgeInsets.fromLTRB(
              InsightSpacing.xl,
              InsightSpacing.sm,
              InsightSpacing.xl,
              InsightSpacing.md,
            ),
            child: _ExploreSearchField(
              controller: controller,
              query: query.value,
              onChanged: setQuery,
              onClear: () {
                controller.clear();
                setQuery('');
              },
            ),
          ),
          Expanded(
            child: searching
                ? _SearchResultsContent(activeTab: activeTab)
                : _DiscoveryContent(onSelectRecent: submitQuery),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Campo de busca — estilo APROVADO (filled, radius lg, prefixo, hint, limpar).
// Comportamento (debounce/cancel/out-of-order) permanece no SearchController.
// ---------------------------------------------------------------------------

class _ExploreSearchField extends StatelessWidget {
  const _ExploreSearchField({
    required this.controller,
    required this.query,
    required this.onChanged,
    required this.onClear,
  });
  final TextEditingController controller;
  final String query;
  final ValueChanged<String> onChanged;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      onChanged: onChanged,
      autofocus: false,
      textInputAction: TextInputAction.search,
      style: context.tt.bodyLarge,
      decoration: InputDecoration(
        prefixIcon: const Icon(Icons.search_rounded),
        suffixIcon: query.isEmpty
            ? null
            : Semantics(
                button: true,
                label: 'Limpar pesquisa',
                child: IconButton(
                  icon: const Icon(Icons.close_rounded),
                  tooltip: 'Limpar',
                  onPressed: onClear,
                ),
              ),
        hintText: 'Buscar partidas, clubes, agentes…',
        filled: true,
        fillColor: context.ds.subtle,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(InsightRadii.lg),
          borderSide: BorderSide(color: context.ds.divider),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(InsightRadii.lg),
          borderSide: BorderSide(color: context.ds.divider),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(InsightRadii.lg),
          borderSide: BorderSide(color: context.ds.signal, width: 1.4),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// MODO DISCOVERY — a composição aprovada, restaurada.
// Hero Radar + grid "Descobrir" (navegação real) + "Buscas recentes" (dados
// REAIS do Gateway, ocupando o slot da antiga seção fabricada "Tendências").
// ---------------------------------------------------------------------------

class _DiscoveryContent extends StatelessWidget {
  const _DiscoveryContent({required this.onSelectRecent});
  final ValueChanged<String> onSelectRecent;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
      padding: const EdgeInsets.fromLTRB(
        InsightSpacing.xl,
        InsightSpacing.sm,
        InsightSpacing.xl,
        InsightSpacing.xl5,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _HeroCard(
            title: 'Radar da rodada',
            subtitle: 'Sinais, partidas quentes e leituras da comunidade.',
            icon: Icons.radar_rounded,
            onTap: () => context.go(R.radar),
          ),
          const SizedBox(height: InsightSpacing.xl),
          Text('Descobrir', style: context.tt.titleMedium),
          const SizedBox(height: InsightSpacing.md),
          GridView.count(
            crossAxisCount: 2,
            childAspectRatio: 1.12,
            mainAxisSpacing: InsightSpacing.md,
            crossAxisSpacing: InsightSpacing.md,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            children: [
              _DiscoveryCard(
                title: 'Clubes',
                subtitle: 'Comunidades por torcida',
                icon: Icons.shield_outlined,
                onTap: () => context.push(R.hub),
              ),
              _DiscoveryCard(
                title: 'Agentes',
                subtitle: 'Leituras oficiais',
                icon: Icons.smart_toy_outlined,
                onTap: () => context.push(R.agents),
              ),
              _DiscoveryCard(
                title: 'Discussões',
                subtitle: 'Tópicos em movimento',
                icon: Icons.forum_outlined,
                onTap: () => context.push(R.hub),
              ),
              _DiscoveryCard(
                title: 'Sinais',
                subtitle: 'Movimentos e consenso',
                icon: Icons.trending_up_rounded,
                onTap: () => context.go(R.radar),
              ),
            ],
          ),
          const SizedBox(height: InsightSpacing.xl2),
          // Buscas recentes REAIS (Gateway) — seção, nunca a página inteira.
          RecentSearchesSection(onSelect: onSelectRecent),
        ],
      ),
    );
  }
}

class _HeroCard extends StatelessWidget {
  const _HeroCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.onTap,
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: context.ds.card,
      borderRadius: BorderRadius.circular(InsightRadii.lg),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(InsightRadii.lg),
        child: Container(
          padding: const EdgeInsets.all(InsightSpacing.xl),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(InsightRadii.lg),
            border: Border.all(color: context.ds.divider),
          ),
          child: Row(
            children: [
              Icon(icon, color: context.ds.signal, size: 32),
              const SizedBox(width: InsightSpacing.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: context.tt.titleLarge),
                    const SizedBox(height: InsightSpacing.xs),
                    Text(
                      subtitle,
                      style: context.tt.bodyMedium
                          ?.copyWith(color: context.ds.textMid),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded),
            ],
          ),
        ),
      ),
    );
  }
}

class _DiscoveryCard extends StatelessWidget {
  const _DiscoveryCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.onTap,
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: context.ds.subtle,
      borderRadius: BorderRadius.circular(InsightRadii.lg),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(InsightRadii.lg),
        child: Padding(
          padding: const EdgeInsets.all(InsightSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, color: context.ds.signal),
              const Spacer(),
              Text(title, style: context.tt.titleSmall),
              const SizedBox(height: InsightSpacing.xs),
              Text(
                subtitle,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style:
                    context.tt.bodySmall?.copyWith(color: context.ds.textLow),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// MODO SEARCH RESULTS — a FEATURE-SEARCH-V1 intacta, composta na página.
// ---------------------------------------------------------------------------

class _SearchResultsContent extends ConsumerWidget {
  const _SearchResultsContent({required this.activeTab});
  final ValueNotifier<SearchCategory> activeTab;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final caps = ref.watch(searchCapabilitiesProvider);
    return caps.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (_, __) => _ResultsBody(
          caps: SearchCapabilities.fallback, activeTab: activeTab),
      data: (c) => _ResultsBody(caps: c, activeTab: activeTab),
    );
  }
}

class _ResultsBody extends StatelessWidget {
  const _ResultsBody({required this.caps, required this.activeTab});
  final SearchCapabilities caps;
  final ValueNotifier<SearchCategory> activeTab;

  @override
  Widget build(BuildContext context) {
    final tabs = caps.tabs;
    if (!tabs.contains(activeTab.value)) activeTab.value = tabs.first;
    return Column(children: [
      _Tabs(tabs: tabs, active: activeTab),
      const Divider(height: 1),
      Expanded(
        child: AnimatedBuilder(
          animation: activeTab,
          builder: (_, __) => _CategoryResults(category: activeTab.value),
        ),
      ),
    ]);
  }
}

class _Tabs extends StatelessWidget {
  const _Tabs({required this.tabs, required this.active});
  final List<SearchCategory> tabs;
  final ValueNotifier<SearchCategory> active;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 48,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(
            horizontal: InsightSpacing.xl, vertical: InsightSpacing.sm),
        itemCount: tabs.length,
        separatorBuilder: (_, __) => const SizedBox(width: InsightSpacing.sm),
        itemBuilder: (context, i) {
          final cat = tabs[i];
          return AnimatedBuilder(
            animation: active,
            builder: (context, __) {
              final selected = cat == active.value;
              return Semantics(
                selected: selected,
                button: true,
                label: cat.labelPtBr,
                child: ChoiceChip(
                  label: Text(cat.labelPtBr),
                  selected: selected,
                  onSelected: (_) => active.value = cat,
                ),
              );
            },
          );
        },
      ),
    );
  }
}

class _CategoryResults extends ConsumerStatefulWidget {
  const _CategoryResults({required this.category});
  final SearchCategory category;
  @override
  ConsumerState<_CategoryResults> createState() => _CategoryResultsState();
}

class _CategoryResultsState extends ConsumerState<_CategoryResults> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 400) {
        ref.read(searchControllerProvider(widget.category).notifier).loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(searchControllerProvider(widget.category));
    final notifier =
        ref.read(searchControllerProvider(widget.category).notifier);

    Widget results() {
      final count = state.results.length;
      return Semantics(
        liveRegion: true,
        label: '$count resultados',
        child: CustomScrollView(
          controller: _scroll,
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          slivers: [
            if (state.isPartial)
              const SliverToBoxAdapter(child: _PartialBanner()),
            SliverList.separated(
              itemCount: count,
              separatorBuilder: (_, __) =>
                  Divider(height: 1, color: context.ds.divider),
              itemBuilder: (_, i) => SearchResultCard(card: state.results[i]),
            ),
            if (state.phase == SearchPhase.loadingMore)
              const SliverToBoxAdapter(
                child: Padding(
                  padding: EdgeInsets.all(16),
                  child: Center(child: CircularProgressIndicator()),
                ),
              ),
          ],
        ),
      );
    }

    return switch (state.phase) {
      SearchPhase.debouncing || SearchPhase.loading =>
        const Center(child: CircularProgressIndicator()),
      SearchPhase.empty => const EmptyState(
          title: 'Nenhum resultado',
          description: 'Tente outra palavra ou categoria.'),
      SearchPhase.offline =>
        OfflineState(onRetry: () => notifier.submit(state.query)),
      SearchPhase.unauthorized => const EmptyState(
          title: 'Sessão expirada', description: 'Entre novamente para buscar.'),
      SearchPhase.unavailable => ErrorState(
          title: 'Busca indisponível',
          description: 'O serviço de busca está temporariamente fora do ar.',
          onRetry: () => notifier.submit(state.query)),
      SearchPhase.timeout => ErrorState(
          title: 'Tempo esgotado',
          description: 'A busca demorou demais. Tente de novo.',
          onRetry: () => notifier.submit(state.query)),
      SearchPhase.error => ErrorState(
          title: 'Algo deu errado',
          description: 'Não consegui buscar agora.',
          onRetry: () => notifier.submit(state.query)),
      _ => results(),
    };
  }
}

class _PartialBanner extends StatelessWidget {
  const _PartialBanner();
  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: context.ds.subtle,
      padding: const EdgeInsets.symmetric(
          horizontal: InsightSpacing.xl, vertical: InsightSpacing.sm),
      child: Semantics(
        label: 'Algumas categorias estão temporariamente indisponíveis',
        child: Row(children: [
          Icon(Icons.info_outline, size: 15, color: context.ds.textLow),
          const SizedBox(width: InsightSpacing.sm),
          Expanded(
            child: Text('Alguns resultados podem estar incompletos no momento.',
                style:
                    context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
          ),
        ]),
      ),
    );
  }
}
