// AZTECA-PROFILE-A — Public user profile.
//
// Uses the SAME Sports Profile architecture as the logged-in profile: the
// shared [SportsProfileHeader] + pinned profile tabs + swipeable content. The
// only difference is the action row (Follow / Message / More instead of Edit /
// Settings) and that the avatar isn't editable. Data: /v1/users/{id} (+ /posts)
// through the Gateway — backend is the source of truth.
import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../providers/profile_ui_provider.dart';
import '../../providers/user_profile_provider.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../theme/spacing.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/offline_state.dart';
import '../home/widgets/feed_item.dart';
import 'widgets/profile_actions.dart';
import 'widgets/profile_tabs_scaffold.dart';
import 'widgets/sports_profile_header.dart';

class UserProfileScreen extends ConsumerWidget {
  const UserProfileScreen({super.key, required this.userId});

  final String userId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // AZTECA-IDENTITY-B: single enriched payload (identity + grouped stats +
    // versioned avatar + role) — replaces the getUser + stats fragmentation.
    final profile = ref.watch(sportsProfileProvider(userId));
    final sectionIndex = ref.watch(profileSectionIndexProvider(userId));

    return Scaffold(
      appBar: AppBar(title: const Text('Perfil')),
      body: profile.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => isOfflineError(e)
            ? const OfflineState()
            : Center(
                child: Text('Não foi possível carregar o perfil.',
                    style: context.tt.bodyMedium),
              ),
        data: (user) {
          final name =
              user.displayName.isNotEmpty ? user.displayName : 'Usuário';
          final identity = ProfileIdentity(
            displayName: name,
            username: user.username,
            initials: user.initials.isNotEmpty
                ? user.initials
                : name.substring(0, 1).toUpperCase(),
            accentColor: user.accentColor,
            avatarUrl: user.avatarUrl,
            reputation: user.reputation,
            role: user.role,
            followers: user.stats.followers,
            following: user.stats.following,
            communities: user.stats.communities,
            posts: user.stats.posts,
            signals: user.stats.signals,
            favoriteTeam: user.favoriteTeam,
            location: user.location,
          );
          return ProfileTabsScaffold(
            labels: kProfileTabs,
            initialIndex: sectionIndex.clamp(0, kProfileTabs.length - 1),
            onIndexChanged: (i) => ref
                .read(profileSectionIndexProvider(userId).notifier)
                .state = i,
            header: SportsProfileHeader(
              identity: identity,
              actions: PublicProfileActions(
                userId: userId,
                displayName: name,
              ),
            ),
            children: [
              _PostsTab(userId: userId),
              const _EmptyTab(
                title: 'Comunidades',
                description:
                    'As comunidades deste perfil aparecem aqui em breve.',
              ),
              _PublicStatsTab(identity: identity),
            ],
          );
        },
      ),
    );
  }
}

/// The user's posts, rendered with the SAME feed card as everywhere else.
class _PostsTab extends ConsumerWidget {
  const _PostsTab({required this.userId});
  final String userId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final posts = ref.watch(userPostsProvider(userId));
    return RefreshIndicator(
      color: context.ds.signal,
      backgroundColor: context.ds.card,
      onRefresh: () async {
        ref.invalidate(sportsProfileProvider(userId));
        ref.invalidate(userPostsProvider(userId));
      },
      child: posts.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (_, __) => ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            Padding(
              padding: const EdgeInsets.all(InsightSpacing.xl),
              child: Text('Não foi possível carregar as publicações.',
                  style: context.tt.bodyMedium),
            ),
          ],
        ),
        data: (items) {
          if (items.isEmpty) {
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: const [
                EmptyState(
                  title: 'Nenhuma publicação ainda',
                  description: 'As publicações deste perfil aparecem aqui.',
                ),
              ],
            );
          }
          return ListView.builder(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.only(bottom: InsightSpacing.xl),
            itemCount: items.length,
            itemBuilder: (context, i) => Padding(
              key: ValueKey(items[i].id),
              padding: const EdgeInsets.symmetric(vertical: InsightSpacing.xs),
              child: FeedItem(post: items[i]),
            ),
          );
        },
      ),
    );
  }
}

/// Public statistics — secondary/derived profile numbers live here instead of
/// crowding the identity header.
class _PublicStatsTab extends StatelessWidget {
  const _PublicStatsTab({required this.identity});
  final ProfileIdentity identity;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final level = identity.level;
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(InsightSpacing.xl),
      children: [
        _StatRow(label: 'Reputação', value: '${identity.reputation}'),
        if (identity.followers != null) ...[
          Divider(color: ds.divider, height: InsightSpacing.xl),
          _StatRow(label: 'Seguidores', value: '${identity.followers}'),
        ],
        if (identity.following != null) ...[
          Divider(color: ds.divider, height: InsightSpacing.xl),
          _StatRow(label: 'Seguindo', value: '${identity.following}'),
        ],
        if (identity.communities != null) ...[
          Divider(color: ds.divider, height: InsightSpacing.xl),
          _StatRow(label: 'Comunidades', value: '${identity.communities}'),
        ],
        if (identity.posts != null) ...[
          Divider(color: ds.divider, height: InsightSpacing.xl),
          _StatRow(label: 'Publicações', value: '${identity.posts}'),
        ],
        if (identity.signals != null) ...[
          Divider(color: ds.divider, height: InsightSpacing.xl),
          _StatRow(label: 'Sinais', value: '${identity.signals}'),
        ],
        Divider(color: ds.divider, height: InsightSpacing.xl),
        _StatRow(label: 'Nível', value: '${level.tier} · ${level.label}'),
      ],
    );
  }
}

class _StatRow extends StatelessWidget {
  const _StatRow({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: '$label: $value',
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label,
              style: context.tt.bodyLarge?.copyWith(color: context.ds.textMid)),
          Text(value,
              style:
                  context.tt.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

class _EmptyTab extends StatelessWidget {
  const _EmptyTab({required this.title, required this.description});
  final String title;
  final String description;

  @override
  Widget build(BuildContext context) {
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: [EmptyState(title: title, description: description)],
    );
  }
}
