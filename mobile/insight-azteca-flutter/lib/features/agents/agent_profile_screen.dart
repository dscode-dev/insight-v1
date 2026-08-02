// Agent profile — Social Foundation (/v1/agents/{id} +
// /v1/agents/{id}/posts). Header (avatar/name/bio + follow/mute) over
// the agent's recent posts, rendered with the SAME feed post card.
import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../providers/agents_provider.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../theme/spacing.dart';
import '../../widgets/avatar.dart';
import '../../widgets/offline_state.dart';
import '../home/widgets/feed_item.dart';
import '../moderation/moderation_ui.dart';

class AgentProfileScreen extends ConsumerWidget {
  const AgentProfileScreen({super.key, required this.agentId});

  final String agentId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(agentProfileProvider(agentId));
    final posts = ref.watch(agentPostsProvider(agentId));
    final agentName = profile.valueOrNull?.name;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Agente'),
        actions: [
          IconButton(
            icon: const Icon(Icons.more_horiz_rounded),
            tooltip: 'Opções',
            // Official agents can be reported but not blocked (Store-A Part 5).
            onPressed: () => showProfileMenu(
              context,
              ref,
              userId: agentId,
              name: (agentName != null && agentName.isNotEmpty)
                  ? agentName
                  : 'agente',
              isAgent: true,
            ),
          ),
        ],
      ),
      body: profile.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => isOfflineError(e)
            ? const OfflineState()
            : Center(
                child: Text('Não foi possível carregar o agente.',
                    style: context.tt.bodyMedium),
              ),
        data: (agent) {
          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(agentProfileProvider(agentId));
              ref.invalidate(agentPostsProvider(agentId));
            },
            child: ListView(
              padding: const EdgeInsets.only(bottom: InsightSpacing.xl),
              children: [
                Padding(
                  padding: const EdgeInsets.all(InsightSpacing.xl),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          InsightAvatar(
                            initials: _initials(agent.name),
                            colorHex: '#5BA8FF',
                            avatarUrl:
                                agent.avatar.isNotEmpty ? agent.avatar : null,
                            size: 56,
                          ),
                          const SizedBox(width: InsightSpacing.md),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Flexible(
                                      child: Text(agent.name,
                                          style: context.tt.titleLarge,
                                          overflow: TextOverflow.ellipsis),
                                    ),
                                    if (agent.verified) ...[
                                      const SizedBox(width: 6),
                                      Icon(Icons.verified_rounded,
                                          size: 18, color: context.ds.signal),
                                    ],
                                  ],
                                ),
                                if (agent.slug.isNotEmpty)
                                  Text('@${agent.slug}',
                                      style: context.tt.labelMedium?.copyWith(
                                          color: context.ds.textLow)),
                              ],
                            ),
                          ),
                        ],
                      ),
                      if (agent.bio.isNotEmpty) ...[
                        const SizedBox(height: InsightSpacing.md),
                        Text(agent.bio, style: context.tt.bodyMedium),
                      ],
                      const SizedBox(height: InsightSpacing.lg),
                      _RelationButtons(agentId: agentId),
                    ],
                  ),
                ),
                Divider(color: context.ds.divider, height: 1),
                posts.when(
                  loading: () => const Padding(
                    padding: EdgeInsets.all(InsightSpacing.xl),
                    child: Center(child: CircularProgressIndicator()),
                  ),
                  error: (_, __) => Padding(
                    padding: const EdgeInsets.all(InsightSpacing.xl),
                    child: Text('Não foi possível carregar as publicações.',
                        style: context.tt.bodyMedium),
                  ),
                  data: (items) {
                    if (items.isEmpty) {
                      return Padding(
                        padding: const EdgeInsets.all(InsightSpacing.xl),
                        child: Text('Nenhuma publicação ainda.',
                            style: context.tt.bodyMedium
                                ?.copyWith(color: context.ds.textLow)),
                      );
                    }
                    return Column(
                      children: [
                        for (final post in items)
                          Padding(
                            padding: const EdgeInsets.symmetric(
                                vertical: InsightSpacing.xs),
                            child: FeedItem(post: post),
                          ),
                      ],
                    );
                  },
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _RelationButtons extends ConsumerWidget {
  const _RelationButtons({required this.agentId});
  final String agentId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rel = ref.watch(agentRelationProvider(agentId));
    final notifier = ref.read(agentRelationProvider(agentId).notifier);
    return Row(
      children: [
        Expanded(
          child: FilledButton(
            onPressed: notifier.toggleFollow,
            style: rel.following
                ? FilledButton.styleFrom(
                    backgroundColor: context.ds.subtle,
                    foregroundColor: context.ds.textHigh,
                  )
                : null,
            child: Text(rel.following ? 'Seguindo' : 'Seguir'),
          ),
        ),
        const SizedBox(width: InsightSpacing.sm),
        OutlinedButton(
          onPressed: notifier.toggleMute,
          child: Text(rel.muted ? 'Reativar' : 'Silenciar'),
        ),
      ],
    );
  }
}

String _initials(String name) {
  final parts = name.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty);
  if (parts.isEmpty) return '·';
  return parts.first.substring(0, 1).toUpperCase();
}
