import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../models/hub.dart';
import '../../providers/hub_provider.dart';
import '../../routing/routes.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../shared/strings/pt_br.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/error_state.dart';
import '../../widgets/search_action.dart';
import '../../widgets/section_header.dart';
import 'widgets/community_tile.dart';
import 'widgets/discussion_row.dart';
import 'widgets/hub_segments.dart';
import 'widgets/hub_skeleton.dart';
import 'widgets/tipster_tile.dart';

class HubScreen extends ConsumerWidget {
  const HubScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(hubBundleProvider);
    final segment = ref.watch(hubSegmentProvider);

    return Scaffold(
      appBar: AppBar(
        // AZTECA-FLUTTER-P0 Stage 4: Hub is a pushed route outside the tab bar,
        // so it must always offer a visible way back (the user is never
        // trapped). The leading control pops the stack when possible and falls
        // back to Home otherwise; the OS back gesture also works now that Hub
        // is `push`ed rather than `go`-replaced (see search_screen).
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          tooltip: MaterialLocalizations.of(context).backButtonTooltip,
          onPressed: () =>
              context.canPop() ? context.pop() : context.go(R.home),
        ),
        title: const Text(S.navHub),
        actions: const [SearchAction()],
      ),
      body: Column(
        children: [
          const HubSegmentsBar(),
          Divider(height: 1, thickness: 0.6, color: context.ds.divider),
          Expanded(
            child: RefreshIndicator(
              color: context.ds.signal,
              backgroundColor: context.ds.card,
              onRefresh: () async => ref.invalidate(hubBundleProvider),
              child: async.when(
                loading: () => const HubScreenSkeleton(),
                error: (e, _) => ListView(
                  children: [
                    ErrorState(
                      title: 'Hub indisponível',
                      description:
                          'Não consegui carregar comunidades e tipsters. Tente de novo.',
                      onRetry: () => ref.invalidate(hubBundleProvider),
                    ),
                  ],
                ),
                data: (bundle) {
                  if (bundle.communities.isEmpty &&
                      bundle.tipsters.isEmpty &&
                      bundle.discussions.isEmpty) {
                    return SingleChildScrollView(
                      physics: const AlwaysScrollableScrollPhysics(),
                      child: EmptyState(
                        title: _emptyTitleFor(segment),
                        description: _emptyDescriptionFor(segment),
                      ),
                    );
                  }
                  return ListView(
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: [
                      if (bundle.communities.isNotEmpty) ...[
                        SectionHeader(title: _communityHeaderFor(segment)),
                        SizedBox(
                          height: 124,
                          child: ListView.separated(
                            scrollDirection: Axis.horizontal,
                            padding:
                                const EdgeInsets.symmetric(horizontal: 20),
                            itemCount: bundle.communities.length,
                            separatorBuilder: (_, __) =>
                                const SizedBox(width: 10),
                            itemBuilder: (_, i) => CommunityTile(
                              community: bundle.communities[i],
                            ),
                          ),
                        ),
                      ],
                      if (bundle.tipsters.isNotEmpty) ...[
                        const SectionHeader(title: 'Tipsters em alta'),
                        SizedBox(
                          height: 140,
                          child: ListView.separated(
                            scrollDirection: Axis.horizontal,
                            padding:
                                const EdgeInsets.symmetric(horizontal: 20),
                            itemCount: bundle.tipsters.length,
                            separatorBuilder: (_, __) =>
                                const SizedBox(width: 10),
                            itemBuilder: (_, i) =>
                                TipsterTile(tipster: bundle.tipsters[i]),
                          ),
                        ),
                      ],
                      if (bundle.discussions.isNotEmpty) ...[
                        SectionHeader(title: _discussionHeaderFor(segment)),
                        ...bundle.discussions
                            .map((d) => DiscussionRow(discussion: d)),
                      ],
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

  String _emptyTitleFor(HubSegment s) {
    switch (s) {
      case HubSegment.mine:
        return 'Você ainda não segue ninguém';
      case HubSegment.hot:
        return 'Hub quieto agora';
      case HubSegment.fresh:
        return 'Nada novo por aqui';
    }
  }

  String _emptyDescriptionFor(HubSegment s) {
    switch (s) {
      case HubSegment.mine:
        return 'Siga comunidades e tipsters pra ver o conteúdo deles aqui.';
      case HubSegment.hot:
        return 'Comunidades e discussões aparecem aqui quando esquentam.';
      case HubSegment.fresh:
        return 'Volte daqui a pouco — novas discussões aparecem em tempo real.';
    }
  }

  String _communityHeaderFor(HubSegment s) {
    switch (s) {
      case HubSegment.mine:
        return 'Suas comunidades';
      case HubSegment.hot:
        return 'Comunidades em alta';
      case HubSegment.fresh:
        return 'Novas comunidades';
    }
  }

  String _discussionHeaderFor(HubSegment s) {
    switch (s) {
      case HubSegment.mine:
        return 'Discussões que você segue';
      case HubSegment.hot:
        return 'Discussões mais ativas';
      case HubSegment.fresh:
        return 'Discussões recentes';
    }
  }
}
