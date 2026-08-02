import 'dart:io';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../services/avatar_service.dart';

import '../../core/avatar_cache.dart';
import '../../core/user_facing_error.dart';
import '../../models/auth.dart';
import '../../models/profile.dart';
import '../../providers/auth_provider.dart';
import '../../providers/feed_provider.dart';
import '../../providers/profile_provider.dart';
import '../../providers/user_profile_provider.dart';
import '../../routing/routes.dart';
import '../../services/services_providers.dart';
import '../../services/social_service.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../shared/strings/pt_br.dart';
import '../../theme/spacing.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/error_state.dart';
import '../../providers/profile_ui_provider.dart';
import '../../widgets/section_header.dart';
import '../home/widgets/feed_item.dart';
import '../insights/model/insight_metrics.dart';
import '../insights/widgets/insight_primitives.dart';
import 'widgets/badges_row.dart';
import 'widgets/profile_actions.dart';
import 'widgets/profile_completeness.dart';
import 'widgets/profile_skeleton.dart';
import 'widgets/profile_tabs_scaffold.dart';
import 'widgets/sports_profile_header.dart';

/// Profile root.
///
/// Layout: one continuous profile scroll. The identity header scrolls with the
/// selected tab content, while the tab selector pins near the top and supports
/// both tap and horizontal swipe.
class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authProvider.select((s) => s.user));
    final async = ref.watch(profileBundleProvider);
    final sectionIndex = ref.watch(profileSectionIndexProvider('me'));

    return Scaffold(
      appBar: AppBar(
        title: const Text(S.navProfile),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: 'Configurações',
            onPressed: () => context.push('${R.profile}/settings'),
          ),
          IconButton(
            icon: const Icon(Icons.logout_rounded),
            tooltip: S.profileLogout,
            onPressed: () => _confirmLogout(context, ref),
          ),
        ],
      ),
      body: async.when(
        loading: () => RefreshIndicator(
          color: context.ds.signal,
          backgroundColor: context.ds.card,
          onRefresh: () async => ref.invalidate(profileBundleProvider),
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            children: [
              _Header(identity: _profileIdentityFor(user: user)),
              const ProfileBodySkeleton(),
            ],
          ),
        ),
        error: (e, _) => RefreshIndicator(
          color: context.ds.signal,
          backgroundColor: context.ds.card,
          onRefresh: () async => ref.invalidate(profileBundleProvider),
          child: ListView(
            children: [
              _Header(identity: _profileIdentityFor(user: user)),
              ErrorState(
                title: 'Perfil indisponível',
                description:
                    'Não consegui carregar suas estatísticas. Tente de novo.',
                onRetry: () => ref.invalidate(profileBundleProvider),
              ),
            ],
          ),
        ),
        data: (bundle) {
          final sp = (user != null)
              ? ref.watch(sportsProfileProvider(user.id)).valueOrNull
              : null;
          final identity = _profileIdentityFor(
            user: user,
            stats: bundle.stats,
            sportsProfile: sp,
          );
          return ProfileTabsScaffold(
            labels: kProfileTabs,
            initialIndex: sectionIndex.clamp(0, kProfileTabs.length - 1),
            onIndexChanged: (i) =>
                ref.read(profileSectionIndexProvider('me').notifier).state = i,
            header: _Header(identity: identity),
            children: [
              _ActivityTab(
                userId: user?.id ?? '',
                identity: identity,
              ),
              const _PlaceholderTab(
                title: 'Suas comunidades',
                description:
                    'Comunidades que você segue aparecem aqui. Encontre uma na aba Hub.',
              ),
              _StatisticsTab(bundle: bundle, userId: user?.id ?? ''),
            ],
          );
        },
      ),
    );
  }

  Future<void> _confirmLogout(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text(S.profileLogoutConfirmTitle),
        content: const Text(S.profileLogoutConfirmDescription),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text(S.profileLogoutCancel),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text(S.profileLogout),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await ref.read(authProvider.notifier).logout();
    }
  }
}

class _Header extends ConsumerStatefulWidget {
  const _Header({required this.identity});
  final ProfileIdentity identity;

  @override
  ConsumerState<_Header> createState() => _HeaderState();
}

class _HeaderState extends ConsumerState<_Header> {
  /// Sprint 6.2 — pick → preview dialog → confirm-or-cancel → upload
  /// with retry. Replaces the previous "pick and immediately upload"
  /// flow, which left no way to back out of an accidental selection
  /// and no way to retry a failed upload without re-picking.
  Future<void> _pickAndUpload() async {
    final picker = ImagePicker();
    XFile? picked;
    try {
      picked = await picker.pickImage(
        source: ImageSource.gallery,
        maxWidth: 1024,
        maxHeight: 1024,
        imageQuality: 88,
      );
    } catch (_) {
      _showError('Não consegui abrir a galeria');
      return;
    }
    if (picked == null) return;

    // Preview dialog — the user confirms or cancels before bytes
    // leave the device. The dialog owns the upload state machine
    // (loading / success / retry) so the profile screen stays
    // responsive while a slow upload is in flight.
    if (!mounted) return;
    final newUrl = await showDialog<String?>(
      context: context,
      barrierDismissible: true,
      builder: (_) => _AvatarPreviewDialog(
        file: picked!,
        service: ref.read(avatarServiceProvider),
      ),
    );
    if (newUrl != null && mounted) {
      // Stage 2 — propagate the new avatar EVERYWHERE without a restart:
      // evict the (stable) URL from the image cache so fresh bytes are
      // fetched, update identity, then refresh the surfaces that paint the
      // avatar (own profile bundle + the feed). Comments/replies re-resolve
      // identity on next open against the now-evicted cache.
      final oldUrl = ref.read(authProvider).user?.avatarUrl;
      await evictAvatarFromCache(oldUrl);
      await evictAvatarFromCache(newUrl);
      ref.read(authProvider.notifier).updateAvatar(newUrl);
      ref.invalidate(profileBundleProvider);
      ref.invalidate(feedProvider);
      if (oldUrl != null || newUrl.isNotEmpty) {
        final myId = ref.read(authProvider).user?.id;
        if (myId != null) ref.invalidate(sportsProfileProvider(myId));
      }
    }
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  @override
  Widget build(BuildContext context) {
    return SportsProfileHeader(
      identity: widget.identity,
      onEditAvatar: _pickAndUpload,
      actions: OwnerProfileActions(
        // AZTECA-PROFILE-B: the Edit button now opens the real Edit Profile
        // screen (was misrouted directly to the avatar picker). The avatar tap
        // on the header remains a quick shortcut.
        onEdit: () => context.push(R.editProfile),
        onSettings: () => context.push('${R.profile}/settings'),
      ),
    );
  }
}

ProfileIdentity _profileIdentityFor({
  required AuthUser? user,
  UserStats? stats,
  SportsProfileDto? sportsProfile,
}) {
  final name = user?.displayName ?? 'Você';
  return ProfileIdentity(
    displayName: name,
    username: user?.username ?? '',
    initials: _initialsFor(name),
    accentColor: user?.accentColor ?? '#5BA8FF',
    // Prefer the locally-updated avatar (reflects an in-session upload
    // immediately); fall back to the server's versioned URL.
    avatarUrl: user?.avatarUrl ?? sportsProfile?.avatarUrl,
    reputation: sportsProfile?.reputation ?? stats?.reputation ?? 0,
    role: sportsProfile?.role ?? 'supporter',
    followers: sportsProfile?.stats.followers,
    following: sportsProfile?.stats.following,
    communities: sportsProfile?.stats.communities,
    posts: sportsProfile?.stats.posts ?? stats?.posts,
    signals: sportsProfile?.stats.signals ?? stats?.signals,
    favoriteTeam: sportsProfile?.favoriteTeam,
    location: sportsProfile?.location,
  );
}

String _initialsFor(String name) {
  final parts = name.trim().split(RegExp(r'\s+'));
  if (parts.isEmpty || parts.first.isEmpty) return 'EU';
  if (parts.length == 1) {
    return parts.first
        .substring(0, parts.first.length.clamp(0, 2))
        .toUpperCase();
  }
  return (parts.first[0] + parts.last[0]).toUpperCase();
}

/// Statistics tab (Stage 5) — the logged-in user's real metrics + badges.
/// Statistics — AZTECA-INSIGHTS-A.
///
/// Renders ONLY backend-authoritative totals from the real sports-profile
/// contract (`GET /v1/users/{id}/sports-profile`, SQL-counted server-side),
/// presented with the shared intelligence primitives. Notably it NO LONGER shows
/// "precisão" (`UserStats.accuracy`): that field exists only in the stub-backed
/// `/v1/profile/me/bundle` projection and has no real backend source — rendering
/// it was fabricating a metric. These are lifetime aggregates with no timestamp
/// in the contract, so freshness stays `unknown` (no chip) rather than guessed,
/// and there is deliberately NO sparkline/delta: a single scalar is not a series
/// and there is no baseline to compare against.
class _StatisticsTab extends ConsumerWidget {
  const _StatisticsTab({required this.bundle, required this.userId});
  final ProfileBundle bundle;
  final String userId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sp = ref.watch(sportsProfileProvider(userId));
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.only(bottom: 32),
      children: [
        sp.when(
          loading: () => const Padding(
            padding: EdgeInsets.all(InsightSpacing.xl),
            child: Center(child: CircularProgressIndicator()),
          ),
          error: (_, __) => Padding(
            padding: const EdgeInsets.all(InsightSpacing.xl),
            child: ErrorState(
              title: 'Métricas indisponíveis',
              description: 'Não consegui carregar suas estatísticas. Tente de novo.',
              onRetry: () => ref.invalidate(sportsProfileProvider(userId)),
            ),
          ),
          data: (p) => _RealMetrics(profile: p),
        ),
        if (bundle.badges.isNotEmpty) ...[
          const SectionHeader(title: 'Conquistas'),
          BadgesRow(badges: bundle.badges),
        ],
      ],
    );
  }
}

/// Own-profile Activity — AZTECA-POSTS-B.
///
/// Now reads the OWNER's REAL persisted posts via `userPostsProvider` (GET
/// /v1/users/{id}/posts), the same authoritative endpoint + canonical `FeedItem`
/// renderer the public profile uses — instead of the previously-stubbed
/// `/v1/profile/me/bundle` activity projection. This makes a freshly-created
/// post reliably discoverable here independent of feed ranking (the composer
/// invalidates `userPostsProvider(myId)` on success). Real loading/empty/error/
/// refresh + stable item keys.
/// Backend-authoritative profile metrics rendered with the shared intelligence
/// primitives (AZTECA-INSIGHTS-A). Every value here is SQL-counted server-side in
/// `GET /v1/users/{id}/sports-profile` — none is derived from a paginated client
/// list, and none carries a fabricated delta/trend (there is no baseline or
/// series in the contract).
class _RealMetrics extends StatelessWidget {
  const _RealMetrics({required this.profile});
  final SportsProfileDto profile;

  @override
  Widget build(BuildContext context) {
    final s = profile.stats;
    final cards = <MetricValue>[
      MetricValue(label: 'Publicações', value: s.posts),
      MetricValue(label: 'Sinais', value: s.signals),
      MetricValue(label: 'Seguidores', value: s.followers),
      MetricValue(label: 'Seguindo', value: s.following),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(
              InsightSpacing.xl, InsightSpacing.md, InsightSpacing.xl, InsightSpacing.sm),
          child: GridView.count(
            crossAxisCount: 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            crossAxisSpacing: InsightSpacing.sm,
            mainAxisSpacing: InsightSpacing.sm,
            childAspectRatio: 2.6,
            children: [for (final m in cards) InsightMetricCard(metric: m, dense: true)],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: InsightSpacing.xl),
          child: Column(
            children: [
              MetricValueRow(
                metric: MetricValue(label: 'Reputação', value: profile.reputation),
              ),
              MetricValueRow(
                metric: MetricValue(label: 'Comunidades', value: s.communities),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ActivityTab extends ConsumerWidget {
  const _ActivityTab({
    required this.userId,
    required this.identity,
  });
  final String userId;
  final ProfileIdentity identity;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final posts = ref.watch(userPostsProvider(userId));
    return RefreshIndicator(
      color: context.ds.signal,
      backgroundColor: context.ds.card,
      onRefresh: () async {
        ref.invalidate(userPostsProvider(userId));
        ref.invalidate(profileBundleProvider);
      },
      child: posts.when(
        loading: () => ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            ProfileCompletenessCard(identity: identity),
            const Padding(
              padding: EdgeInsets.all(InsightSpacing.xl),
              child: Center(child: CircularProgressIndicator()),
            ),
          ],
        ),
        error: (_, __) => ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            ProfileCompletenessCard(identity: identity),
            ErrorState(
              title: 'Publicações indisponíveis',
              description: 'Não consegui carregar suas publicações. Tente de novo.',
              onRetry: () => ref.invalidate(userPostsProvider(userId)),
            ),
          ],
        ),
        data: (items) => ListView.builder(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.only(bottom: 32),
          // header + (posts | empty state)
          itemCount: 1 + (items.isEmpty ? 1 : items.length),
          itemBuilder: (context, i) {
            if (i == 0) return ProfileCompletenessCard(identity: identity);
            if (items.isEmpty) {
              return const EmptyState(
                title: 'Sem publicações ainda',
                description: 'Suas publicações aparecem aqui assim que você posta.',
              );
            }
            final post = items[i - 1];
            return Padding(
              key: ValueKey(post.id),
              padding: const EdgeInsets.symmetric(vertical: InsightSpacing.xs),
              child: FeedItem(post: post),
            );
          },
        ),
      ),
    );
  }
}

class _PlaceholderTab extends StatelessWidget {
  const _PlaceholderTab({required this.title, required this.description});
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

// ---------------------------------------------------------------------------
// Avatar preview dialog — Sprint 6.2 Part 1.
//
// State machine:
//   ready     — initial; user sees the cropped preview + [Cancel][Send]
//   uploading — spinner over the preview; both buttons disabled
//   error     — preview + the failure reason + [Cancel][Try again]
//
// On success the dialog pops with the new avatar URL; the caller
// pushes it into AuthState. On cancel the dialog pops with null and
// the original avatar stays.
// ---------------------------------------------------------------------------

class _AvatarPreviewDialog extends StatefulWidget {
  const _AvatarPreviewDialog({required this.file, required this.service});

  final XFile file;
  final AvatarService service;

  @override
  State<_AvatarPreviewDialog> createState() => _AvatarPreviewDialogState();
}

enum _AvatarUploadPhase { ready, uploading, error }

class _AvatarPreviewDialogState extends State<_AvatarPreviewDialog> {
  _AvatarUploadPhase _phase = _AvatarUploadPhase.ready;
  String? _errorMessage;

  // Translate an upload error into an actionable pt-BR sentence. Top-level +
  // testable (AZTECA-QUALITY-A). Distinguishes invalid image / rejected /
  // service-unavailable / auth / timeout / network so the user never gets a
  // wrong cause. Leaks no infrastructure detail.
  // (See avatarUploadErrorMessage at file end.)

  Future<void> _upload() async {
    setState(() {
      _phase = _AvatarUploadPhase.uploading;
      _errorMessage = null;
    });
    try {
      final url = await widget.service.upload(widget.file);
      if (!mounted) return;
      Navigator.of(context).pop(url);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _phase = _AvatarUploadPhase.error;
        _errorMessage = _humanizeUploadError(e);
      });
    }
  }

  /// Translate the upload error into a pt-BR sentence the user can
  /// act on. Network/timeout errors are common; backend rejections
  /// (file too large, bad mime) get their own messages so the user
  /// doesn't blame the network.
  String _humanizeUploadError(Object err) => avatarUploadErrorMessage(err);

  @override
  Widget build(BuildContext context) {
    final busy = _phase == _AvatarUploadPhase.uploading;
    return Dialog(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 360),
        child: Padding(
          padding: const EdgeInsets.all(InsightSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('Pré-visualização', style: context.tt.titleMedium),
              const SizedBox(height: InsightSpacing.lg),
              AspectRatio(
                aspectRatio: 1,
                child: ClipOval(
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      Image.file(
                        File(widget.file.path),
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) => Container(
                          color: context.ds.subtle,
                          child:
                              const Icon(Icons.broken_image_outlined, size: 40),
                        ),
                      ),
                      if (busy)
                        const ColoredBox(
                          color: Color(0x66000000),
                          child: Center(
                            child: CircularProgressIndicator(strokeWidth: 2.5),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
              if (_phase == _AvatarUploadPhase.error &&
                  _errorMessage != null) ...[
                const SizedBox(height: InsightSpacing.md),
                Text(
                  _errorMessage!,
                  textAlign: TextAlign.center,
                  style:
                      context.tt.bodySmall?.copyWith(color: context.ds.signal),
                ),
              ],
              const SizedBox(height: InsightSpacing.xl),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed:
                          busy ? null : () => Navigator.of(context).pop(null),
                      child: const Text('Cancelar'),
                    ),
                  ),
                  const SizedBox(width: InsightSpacing.md),
                  Expanded(
                    flex: 2,
                    child: FilledButton(
                      onPressed: busy ? null : _upload,
                      child: Text(
                        _phase == _AvatarUploadPhase.error
                            ? 'Tentar de novo'
                            : 'Enviar foto',
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Maps an avatar-upload error to an actionable pt-BR message (AZTECA-QUALITY-A).
///
/// Honest, distinct causes — invalid image vs rejected vs service-unavailable vs
/// auth vs timeout vs network — so the user is never told the wrong thing. Never
/// exposes hostnames, bucket names, tokens or stack traces.
String avatarUploadErrorMessage(Object err) {
  final raw = err.toString().toLowerCase();
  if (raw.contains('timeout')) return 'Tempo esgotado. Tente de novo.';
  if (raw.contains('413') || raw.contains('too large')) {
    return 'Imagem grande demais. Escolha outra.';
  }
  if (raw.contains('415') || raw.contains('unsupported')) {
    return 'Formato não aceito. Exporte como JPG, PNG ou WebP.';
  }
  // Avatar storage configured-but-unavailable. The Gateway returns a normalized
  // 503 CAPABILITY_UNAVAILABLE (detail avatar_storage_unavailable) instead of a
  // misleading 404 — surface an honest "temporarily unavailable", distinct from
  // an invalid image.
  if (raw.contains('503') ||
      raw.contains('avatar_storage_unavailable') ||
      raw.contains('capability_unavailable')) {
    return 'Envio de foto indisponível no momento. Tente novamente mais tarde.';
  }
  if (raw.contains('401') || raw.contains('unauthorized')) {
    return 'Sua sessão expirou. Entre novamente para atualizar a foto.';
  }
  // Legacy 404 (pre-fix Gateways where the route was skipped) — treat like a
  // transient service issue, never blame the user.
  if (raw.contains('404')) {
    return 'Não foi possível atualizar sua foto agora. Tente novamente em alguns instantes.';
  }
  if (raw.contains('connection') || raw.contains('network')) {
    return 'Verifique sua conexão e tente novamente.';
  }
  return userFacingErrorMessage(err);
}
