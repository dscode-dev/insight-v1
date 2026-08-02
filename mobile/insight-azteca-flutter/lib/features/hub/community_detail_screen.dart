// FEATURE-COMMUNITIES-V1 Stage 3 — CommunityDetailScreen (EVOLVED, not
// replaced). Same route (/hub/community/:id) and the APPROVED header card
// identity are preserved; the body gains capability-driven sections
// (Sobre / Discussões / Membros / Estatísticas / Administração) that share the
// ONE aggregate context and load independently so a failing section never
// takes down the screen. The header is loaded once and never re-fetched on tab
// switch; each tab keeps its own state.
//
// UI authorization is driven EXCLUSIVELY by capabilities from the Gateway —
// never `if (role == owner)`. Deep links come from the Gateway and are
// validated before navigation.

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../shared/extensions/build_context_x.dart';
import '../../shared/format/count.dart';
import '../../theme/radii.dart';
import '../../theme/spacing.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/error_state.dart';
import '../../widgets/insight_tabs.dart';
import 'community/model/community_models.dart';
import 'community/navigation/community_deep_link.dart';
import 'community/state/community_providers.dart';
import 'community/widgets/discussion_card.dart';
import 'community/widgets/member_row.dart';

class CommunityDetailScreen extends ConsumerWidget {
  const CommunityDetailScreen({super.key, required this.communityId});
  final String communityId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(communityDetailProvider(communityId));

    return Scaffold(
      appBar: AppBar(
        title: Text(state.detail?.name ?? 'Comunidade'),
      ),
      body: switch (state.phase) {
        Loadable.loading => const Center(child: CircularProgressIndicator()),
        Loadable.error => ListView(children: [
            ErrorState(
              title: 'Comunidade indisponível',
              description: 'Não consegui carregar essa comunidade agora.',
              onRetry: () => ref.read(communityDetailProvider(communityId).notifier).load(),
            ),
          ]),
        Loadable.ready => _Body(communityId: communityId, detail: state.detail!, busy: state.membershipBusy),
      },
    );
  }
}

class _Body extends ConsumerWidget {
  const _Body({required this.communityId, required this.detail, required this.busy});
  final String communityId;
  final CommunityDetail detail;
  final bool busy;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Tabs are capability-driven: Administração appears only when the Gateway
    // says can_view_admin_panel — never inferred from role.
    final tabs = <(_TabKind, String)>[
      (_TabKind.about, 'Sobre'),
      (_TabKind.discussions, 'Discussões'),
      (_TabKind.members, 'Membros'),
      (_TabKind.stats, 'Estatísticas'),
      if (detail.capabilities.canViewAdminPanel) (_TabKind.admin, 'Administração'),
    ];

    return DefaultTabController(
      length: tabs.length,
      child: Column(
        children: [
          _Header(communityId: communityId, detail: detail, busy: busy),
          if (detail.partial) const _PartialBanner(),
          InsightTabBar(isScrollable: true, tabs: [for (final t in tabs) Tab(text: t.$2)]),
          const SizedBox(height: InsightSpacing.sm),
          Expanded(
            child: TabBarView(
              children: [
                for (final t in tabs)
                  switch (t.$1) {
                    _TabKind.about => _AboutTab(detail: detail),
                    _TabKind.discussions => _DiscussionsTab(communityId: communityId),
                    _TabKind.members => _MembersTab(communityId: communityId),
                    _TabKind.stats => _StatsTab(detail: detail),
                    _TabKind.admin => _AdminTab(communityId: communityId, detail: detail),
                  },
              ],
            ),
          ),
        ],
      ),
    );
  }
}

enum _TabKind { about, discussions, members, stats, admin }

// ---------------------------------------------------------------------------
// Header — preserves the APPROVED card identity (accent square + name + handle
// + presence + description), plus a capability-driven membership action.
// ---------------------------------------------------------------------------

class _Header extends ConsumerWidget {
  const _Header({required this.communityId, required this.detail, required this.busy});
  final String communityId;
  final CommunityDetail detail;
  final bool busy;

  Color _accent() {
    final hex = detail.accentColor.replaceFirst('#', '');
    return Color(int.parse('FF$hex', radix: 16));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accent = _accent();
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
      child: Container(
        padding: const EdgeInsets.all(InsightSpacing.lg),
        decoration: BoxDecoration(
          color: context.ds.card,
          borderRadius: InsightRadii.brLg,
          border: Border.all(color: context.ds.divider),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 48,
                  height: 48,
                  decoration: BoxDecoration(color: accent, borderRadius: BorderRadius.circular(12)),
                ),
                const SizedBox(width: InsightSpacing.lg),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(detail.name, style: context.tt.titleLarge),
                      const SizedBox(height: 2),
                      Text('@${detail.slug}',
                          style: context.tt.bodyMedium?.copyWith(color: context.ds.textMid)),
                      const SizedBox(height: 8),
                      Row(children: [
                        Icon(Icons.people_alt_outlined, size: 14, color: context.ds.textLow),
                        const SizedBox(width: 4),
                        Text('${formatCount(detail.memberCount)} membros',
                            style: context.tt.labelSmall?.copyWith(color: context.ds.textMid)),
                        if (detail.onlineCount > 0) ...[
                          const SizedBox(width: 10),
                          Icon(Icons.circle, size: 8, color: context.ds.signal),
                          const SizedBox(width: 4),
                          Text('${formatCount(detail.onlineCount)} ativos',
                              style: context.tt.labelSmall?.copyWith(color: context.ds.textMid)),
                        ],
                      ]),
                    ],
                  ),
                ),
              ],
            ),
            if (detail.description.isNotEmpty) ...[
              const SizedBox(height: InsightSpacing.md),
              Text(detail.description,
                  style: context.tt.bodyMedium?.copyWith(color: context.ds.textMid)),
            ],
            _MembershipAction(communityId: communityId, caps: detail.capabilities, busy: busy),
          ],
        ),
      ),
    );
  }
}

/// The Join/Leave affordance — rendered ONLY from capabilities (never role).
/// Owner has neither (can't leave without transfer) → no button.
class _MembershipAction extends ConsumerWidget {
  const _MembershipAction({required this.communityId, required this.caps, required this.busy});
  final String communityId;
  final CommunityCapabilities caps;
  final bool busy;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (!caps.canJoin && !caps.canLeave) return const SizedBox.shrink();
    final notifier = ref.read(communityDetailProvider(communityId).notifier);
    final isJoin = caps.canJoin;

    return Padding(
      padding: const EdgeInsets.only(top: InsightSpacing.lg),
      child: SizedBox(
        width: double.infinity,
        child: isJoin
            ? FilledButton.icon(
                onPressed: busy ? null : notifier.join,
                icon: busy
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.add_rounded, size: 18),
                label: Text(busy ? 'Entrando…' : 'Entrar'),
              )
            : OutlinedButton.icon(
                onPressed: busy ? null : notifier.leave,
                icon: busy
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.logout_rounded, size: 18),
                label: Text(busy ? 'Saindo…' : 'Sair'),
              ),
      ),
    );
  }
}

class _PartialBanner extends StatelessWidget {
  const _PartialBanner();
  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: context.ds.subtle,
      padding: const EdgeInsets.symmetric(horizontal: InsightSpacing.xl, vertical: InsightSpacing.sm),
      child: Text('Alguns dados podem estar incompletos no momento.',
          style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
    );
  }
}

// ---------------------------------------------------------------------------
// Sobre
// ---------------------------------------------------------------------------

class _AboutTab extends StatelessWidget {
  const _AboutTab({required this.detail});
  final CommunityDetail detail;

  @override
  Widget build(BuildContext context) {
    final kindLabel = switch (detail.kind) {
      'competition' => 'Competição',
      'topic' => 'Tópico',
      _ => detail.kind,
    };
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(InsightSpacing.xl),
      children: [
        if (detail.description.isNotEmpty) ...[
          Text('Sobre', style: context.tt.titleMedium),
          const SizedBox(height: InsightSpacing.sm),
          Text(detail.description, style: context.tt.bodyMedium?.copyWith(color: context.ds.textMid)),
          const SizedBox(height: InsightSpacing.xl),
        ],
        _InfoRow(label: 'Tipo', value: kindLabel),
        _InfoRow(label: 'Visibilidade', value: detail.privacy == 'public' ? 'Pública' : detail.privacy),
        _InfoRow(label: 'Membros', value: formatCount(detail.memberCount)),
        _InfoRow(label: 'Discussões', value: formatCount(detail.discussionCount)),
      ],
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});
  final String label, value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: InsightSpacing.sm),
      child: Row(
        children: [
          Expanded(child: Text(label, style: context.tt.bodyMedium?.copyWith(color: context.ds.textMid))),
          Text(value, style: context.tt.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Discussões (community feed — Discussions only; own card, never a Post card)
// ---------------------------------------------------------------------------

class _DiscussionsTab extends ConsumerStatefulWidget {
  const _DiscussionsTab({required this.communityId});
  final String communityId;
  @override
  ConsumerState<_DiscussionsTab> createState() => _DiscussionsTabState();
}

class _DiscussionsTabState extends ConsumerState<_DiscussionsTab>
    with AutomaticKeepAliveClientMixin {
  final _scroll = ScrollController();

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 400) {
        ref.read(communityDiscussionsProvider(widget.communityId).notifier).loadMore();
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
    super.build(context);
    final state = ref.watch(communityDiscussionsProvider(widget.communityId));
    final notifier = ref.read(communityDiscussionsProvider(widget.communityId).notifier);

    return switch (state.phase) {
      Loadable.loading => const Center(child: CircularProgressIndicator()),
      Loadable.error => ListView(children: [
          ErrorState(
            title: 'Não foi possível carregar as discussões',
            onRetry: notifier.load,
          ),
        ]),
      Loadable.ready => state.items.isEmpty
          ? ListView(physics: const AlwaysScrollableScrollPhysics(), children: const [
              EmptyState(
                title: 'Sem discussões ainda',
                description: 'Quando alguém abrir um tópico aqui, ele aparece nessa aba.',
              ),
            ])
          : ListView.builder(
              controller: _scroll,
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.symmetric(vertical: InsightSpacing.sm),
              itemCount: state.items.length + (state.loadingMore ? 1 : 0),
              itemBuilder: (context, i) {
                if (i >= state.items.length) {
                  return const Padding(
                    padding: EdgeInsets.all(16),
                    child: Center(child: CircularProgressIndicator()),
                  );
                }
                final d = state.items[i];
                return DiscussionCard(
                  discussion: d,
                  onTap: communityDeepLinkIsNavigable(d.deepLink) ? () => context.push(d.deepLink) : null,
                );
              },
            ),
    };
  }
}

// ---------------------------------------------------------------------------
// Membros (paginated; role filter uses the SAME endpoint)
// ---------------------------------------------------------------------------

class _MembersTab extends ConsumerStatefulWidget {
  const _MembersTab({required this.communityId});
  final String communityId;
  @override
  ConsumerState<_MembersTab> createState() => _MembersTabState();
}

class _MembersTabState extends ConsumerState<_MembersTab> with AutomaticKeepAliveClientMixin {
  final _scroll = ScrollController();

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 400) {
        ref.read(communityMembersProvider(widget.communityId).notifier).loadMore();
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
    super.build(context);
    final state = ref.watch(communityMembersProvider(widget.communityId));
    final notifier = ref.read(communityMembersProvider(widget.communityId).notifier);

    const filters = <(String, String)>[
      ('', 'Todos'),
      ('owner', 'Dono'),
      ('admin', 'Admins'),
      ('moderator', 'Moderadores'),
    ];

    Widget list() {
      return switch (state.phase) {
        Loadable.loading => const Center(child: CircularProgressIndicator()),
        Loadable.error => ListView(children: [
            ErrorState(title: 'Não foi possível carregar os membros', onRetry: notifier.load),
          ]),
        Loadable.ready => state.members.isEmpty
            ? ListView(physics: const AlwaysScrollableScrollPhysics(), children: const [
                EmptyState(title: 'Nenhum membro nessa visão', description: 'Tente outro filtro.'),
              ])
            : ListView.builder(
                controller: _scroll,
                physics: const AlwaysScrollableScrollPhysics(),
                itemCount: state.members.length + (state.loadingMore ? 1 : 0),
                itemBuilder: (context, i) {
                  if (i >= state.members.length) {
                    return const Padding(
                      padding: EdgeInsets.all(16),
                      child: Center(child: CircularProgressIndicator()),
                    );
                  }
                  final m = state.members[i];
                  return MemberRow(
                    member: m,
                    onTap: communityDeepLinkIsNavigable(m.deepLink) ? () => context.push(m.deepLink) : null,
                  );
                },
              ),
      };
    }

    return Column(
      children: [
        SizedBox(
          height: 48,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: InsightSpacing.xl, vertical: InsightSpacing.sm),
            itemCount: filters.length,
            separatorBuilder: (_, __) => const SizedBox(width: InsightSpacing.sm),
            itemBuilder: (context, i) {
              final selected = state.roleFilter == filters[i].$1;
              return ChoiceChip(
                label: Text(filters[i].$2),
                selected: selected,
                onSelected: (_) => notifier.setRoleFilter(filters[i].$1),
              );
            },
          ),
        ),
        Expanded(child: list()),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Estatísticas (real counters + role distribution)
// ---------------------------------------------------------------------------

class _StatsTab extends StatelessWidget {
  const _StatsTab({required this.detail});
  final CommunityDetail detail;

  @override
  Widget build(BuildContext context) {
    final rc = detail.roleCounts;
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(InsightSpacing.xl),
      children: [
        Text('Visão geral', style: context.tt.titleMedium),
        const SizedBox(height: InsightSpacing.md),
        Row(children: [
          _StatCard(label: 'Membros', value: formatCount(detail.memberCount)),
          const SizedBox(width: InsightSpacing.md),
          _StatCard(label: 'Discussões', value: formatCount(detail.discussionCount)),
          const SizedBox(width: InsightSpacing.md),
          _StatCard(label: 'Ativos agora', value: formatCount(detail.onlineCount)),
        ]),
        const SizedBox(height: InsightSpacing.xl),
        Text('Distribuição de papéis', style: context.tt.titleMedium),
        const SizedBox(height: InsightSpacing.md),
        _InfoRow(label: 'Donos', value: formatCount(rc.owner)),
        _InfoRow(label: 'Admins', value: formatCount(rc.admin)),
        _InfoRow(label: 'Moderadores', value: formatCount(rc.moderator)),
        _InfoRow(label: 'Membros', value: formatCount(rc.member)),
      ],
    );
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({required this.label, required this.value});
  final String label, value;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(InsightSpacing.lg),
        decoration: BoxDecoration(
          color: context.ds.card,
          borderRadius: BorderRadius.circular(InsightRadii.md),
          border: Border.all(color: context.ds.divider),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(value, style: context.tt.titleLarge),
            const SizedBox(height: 2),
            Text(label, style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Administração (only when can_view_admin_panel) — real admin OVERVIEW.
// Management mutations have no V1 endpoint yet; this surface shows the real
// role distribution + which management capabilities the viewer holds, without
// fabricating action buttons that do nothing.
// ---------------------------------------------------------------------------

class _AdminTab extends StatelessWidget {
  const _AdminTab({required this.communityId, required this.detail});
  final String communityId;
  final CommunityDetail detail;

  @override
  Widget build(BuildContext context) {
    final caps = detail.capabilities;
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(InsightSpacing.xl),
      children: [
        Text('Painel de administração', style: context.tt.titleMedium),
        const SizedBox(height: InsightSpacing.sm),
        Text('Suas permissões nesta comunidade.',
            style: context.tt.bodySmall?.copyWith(color: context.ds.textMid)),
        const SizedBox(height: InsightSpacing.lg),
        _CapRow(label: 'Gerenciar membros', granted: caps.canManageMembers),
        _CapRow(label: 'Convidar membros', granted: caps.canInviteMembers),
        _CapRow(label: 'Configurações da comunidade', granted: caps.canManageSettings),
        _CapRow(label: 'Remover discussões', granted: caps.canDeleteDiscussion),
        const SizedBox(height: InsightSpacing.xl),
        Text('Composição', style: context.tt.titleMedium),
        const SizedBox(height: InsightSpacing.md),
        _InfoRow(label: 'Donos', value: formatCount(detail.roleCounts.owner)),
        _InfoRow(label: 'Admins', value: formatCount(detail.roleCounts.admin)),
        _InfoRow(label: 'Moderadores', value: formatCount(detail.roleCounts.moderator)),
      ],
    );
  }
}

class _CapRow extends StatelessWidget {
  const _CapRow({required this.label, required this.granted});
  final String label;
  final bool granted;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: InsightSpacing.sm),
      child: Row(
        children: [
          Icon(granted ? Icons.check_circle_outline : Icons.remove_circle_outline,
              size: 18, color: granted ? context.ds.signal : context.ds.textLow),
          const SizedBox(width: InsightSpacing.md),
          Text(label, style: context.tt.bodyMedium?.copyWith(
              color: granted ? context.ds.textHigh : context.ds.textLow)),
        ],
      ),
    );
  }
}
