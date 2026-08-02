// Agents list — Social Foundation (/v1/agents). The minimum agent
// discovery surface: the official voices, tappable into their profile.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../providers/agents_provider.dart';
import '../../routing/routes.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../theme/spacing.dart';
import '../../widgets/avatar.dart';
import '../../widgets/offline_state.dart';

class AgentsListScreen extends ConsumerWidget {
  const AgentsListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final agents = ref.watch(agentsListProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Agentes')),
      body: agents.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => isOfflineError(e)
            ? const OfflineState()
            : Center(
                child: Text('Não foi possível carregar os agentes.',
                    style: context.tt.bodyMedium),
              ),
        data: (list) {
          if (list.isEmpty) {
            return Center(
              child: Text('Nenhum agente disponível.',
                  style: context.tt.bodyMedium
                      ?.copyWith(color: context.ds.textLow)),
            );
          }
          return RefreshIndicator(
            onRefresh: () async => ref.refresh(agentsListProvider.future),
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(
                vertical: InsightSpacing.md,
              ),
              itemCount: list.length,
              separatorBuilder: (_, __) =>
                  Divider(color: context.ds.divider, height: 1, indent: 72),
              itemBuilder: (context, i) {
                final a = list[i];
                return ListTile(
                  onTap: () => context.push(R.agentProfileFor(a.id)),
                  leading: InsightAvatar(
                    initials: _initials(a.name),
                    colorHex: '#5BA8FF',
                    avatarUrl: a.avatar.isNotEmpty ? a.avatar : null,
                    size: 44,
                  ),
                  title: Row(
                    children: [
                      Flexible(
                        child: Text(a.name,
                            style: context.tt.titleSmall,
                            overflow: TextOverflow.ellipsis),
                      ),
                      if (a.verified) ...[
                        const SizedBox(width: 4),
                        Icon(Icons.verified_rounded,
                            size: 16, color: context.ds.signal),
                      ],
                    ],
                  ),
                  subtitle: a.bio.isNotEmpty
                      ? Text(a.bio,
                          maxLines: 2, overflow: TextOverflow.ellipsis)
                      : null,
                  trailing: const Icon(Icons.chevron_right_rounded),
                );
              },
            ),
          );
        },
      ),
    );
  }
}

String _initials(String name) {
  final parts = name.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty);
  if (parts.isEmpty) return '·';
  return parts.first.substring(0, 1).toUpperCase();
}
