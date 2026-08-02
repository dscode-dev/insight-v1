// AZTECA-PROFILE-A — the shared Sports Identity header.
//
// One header, used by BOTH the logged-in profile and any public profile. It
// never knows where it was opened from: callers build a [ProfileIdentity] from
// whatever source they have (AuthUser + stats, or a SocialUserDto) and pass an
// `actions` slot (owner actions vs. follow/message/report). Fields the backend
// doesn't provide yet (location, favorite team, followers, communities) are
// optional and simply omitted — no placeholders, no mock data, ready to light
// up the moment the backend returns them.
import 'package:flutter/material.dart';

import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/spacing.dart';
import '../../../widgets/avatar.dart';

/// A platform-agnostic sports identity. Only [displayName]/[username]/
/// [accentColor]/[reputation] are guaranteed; the rest render when present.
class ProfileIdentity {
  const ProfileIdentity({
    required this.displayName,
    required this.username,
    required this.initials,
    required this.accentColor,
    required this.reputation,
    this.role = 'supporter',
    this.avatarUrl,
    this.location,
    this.favoriteTeam,
    this.followers,
    this.following,
    this.communities,
    this.posts,
    this.signals,
  });

  final String displayName;
  final String username;
  final String initials;
  final String accentColor;
  final int reputation; // 0..100

  /// Sports role. V1 only ever emits `supporter`; future roles (player, coach,
  /// scout, analyst, referee, club) render through [SportsRole] without a redesign.
  final String role;
  final String? avatarUrl;
  final String? location;
  final String? favoriteTeam;
  final int? followers;
  final int? following;
  final int? communities;
  final int? posts;
  final int? signals;

  /// Level derived from reputation — a presentation of real data, not a
  /// fabricated field. 5 tiers across 0..100.
  ProfileLevel get level => ProfileLevel.fromReputation(reputation);
}

/// Sports role rendering (Stage 4). Only `supporter` is active in V1; the rest
/// are prepared so future producers can set `role` and the UI renders correctly.
class SportsRole {
  const SportsRole(this.id, this.label, this.icon);
  final String id;
  final String label;
  final IconData icon;

  static const _byId = <String, SportsRole>{
    'supporter':
        SportsRole('supporter', 'Torcedor', Icons.sports_soccer_rounded),
    'player': SportsRole('player', 'Jogador', Icons.directions_run_rounded),
    'coach': SportsRole('coach', 'Treinador', Icons.sports_rounded),
    'scout': SportsRole('scout', 'Olheiro', Icons.travel_explore_rounded),
    'analyst': SportsRole('analyst', 'Analista', Icons.query_stats_rounded),
    'referee': SportsRole('referee', 'Árbitro', Icons.sports_score_rounded),
    'club': SportsRole('club', 'Clube', Icons.shield_rounded),
  };

  static SportsRole resolve(String id) => _byId[id] ?? _byId['supporter']!;
}

class ProfileLevel {
  const ProfileLevel(this.tier, this.label);
  final int tier; // 1..5
  final String label;

  static ProfileLevel fromReputation(int reputation) {
    final r = reputation.clamp(0, 100);
    if (r >= 80) return const ProfileLevel(5, 'Lenda');
    if (r >= 60) return const ProfileLevel(4, 'Craque');
    if (r >= 40) return const ProfileLevel(3, 'Analista');
    if (r >= 20) return const ProfileLevel(2, 'Torcedor');
    return const ProfileLevel(1, 'Estreante');
  }
}

/// The Sports Identity header (Stage 2). Clear hierarchy, no oversized cards,
/// no heavy borders — avatar + names on top, an optional context line, a quiet
/// metrics strip, then the caller's action row.
class SportsProfileHeader extends StatelessWidget {
  const SportsProfileHeader({
    super.key,
    required this.identity,
    required this.actions,
    this.onEditAvatar,
  });

  final ProfileIdentity identity;

  /// Owner actions (Edit / Settings) or public actions (Follow / Message /
  /// More) — the header doesn't care which.
  final Widget actions;

  /// When non-null the avatar shows an edit affordance (owner only).
  final VoidCallback? onEditAvatar;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Padding(
      padding: const EdgeInsets.fromLTRB(InsightSpacing.xl, InsightSpacing.lg,
          InsightSpacing.xl, InsightSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              _Avatar(identity: identity, onEdit: onEditAvatar),
              const SizedBox(width: InsightSpacing.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      identity.displayName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: context.tt.titleLarge
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        if (identity.username.isNotEmpty)
                          Flexible(
                            child: Text('@${identity.username}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: context.tt.bodyMedium
                                    ?.copyWith(color: ds.textMid)),
                          ),
                        const SizedBox(width: 8),
                        _RoleChip(role: SportsRole.resolve(identity.role)),
                      ],
                    ),
                    if (identity.location != null ||
                        identity.favoriteTeam != null) ...[
                      const SizedBox(height: 6),
                      _ContextLine(identity: identity),
                    ],
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: InsightSpacing.lg),
          _MetricsStrip(identity: identity),
          const SizedBox(height: InsightSpacing.lg),
          actions,
        ],
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.identity, this.onEdit});
  final ProfileIdentity identity;
  final VoidCallback? onEdit;

  @override
  Widget build(BuildContext context) {
    final avatar = InsightAvatar(
      initials: identity.initials,
      colorHex: identity.accentColor,
      avatarUrl: identity.avatarUrl,
      size: 72,
    );
    if (onEdit == null) {
      return Semantics(label: 'Foto de ${identity.displayName}', child: avatar);
    }
    return Semantics(
      button: true,
      label: 'Editar foto do perfil',
      child: InkWell(
        onTap: onEdit,
        customBorder: const CircleBorder(),
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            avatar,
            Positioned(
              right: -2,
              bottom: -2,
              child: Container(
                width: 24,
                height: 24,
                decoration: BoxDecoration(
                  color: context.ds.signal,
                  shape: BoxShape.circle,
                  border: Border.all(color: context.ds.background, width: 2),
                ),
                child: const Icon(Icons.camera_alt_rounded,
                    size: 12, color: Colors.white),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Optional "📍 location · 🛡 team" line — only the present parts render.
class _ContextLine extends StatelessWidget {
  const _ContextLine({required this.identity});
  final ProfileIdentity identity;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final style = context.tt.bodySmall?.copyWith(color: ds.textLow);
    final parts = <Widget>[
      if (identity.location != null)
        _IconText(
            icon: Icons.place_outlined, text: identity.location!, style: style),
      if (identity.favoriteTeam != null)
        _IconText(
            icon: Icons.shield_outlined,
            text: identity.favoriteTeam!,
            style: style),
    ];
    return Wrap(
      spacing: InsightSpacing.md,
      runSpacing: 4,
      children: parts,
    );
  }
}

class _IconText extends StatelessWidget {
  const _IconText({required this.icon, required this.text, this.style});
  final IconData icon;
  final String text;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: context.ds.textLow),
        const SizedBox(width: 4),
        Text(text, style: style),
      ],
    );
  }
}

/// Quiet social metrics — Threads/Instagram-style. Only the numbers that
/// should live in the identity header stay here; derived/secondary metrics
/// belong inside the Statistics tab.
class _MetricsStrip extends StatelessWidget {
  const _MetricsStrip({required this.identity});
  final ProfileIdentity identity;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final metrics = <_Metric>[
      if (identity.followers != null)
        _Metric('${identity.followers}', 'Seguidores'),
      _Metric('${identity.reputation}', 'Reputação'),
    ];
    return Row(
      children: [
        for (var i = 0; i < metrics.length; i++) ...[
          if (i > 0) const SizedBox(width: InsightSpacing.xl),
          Semantics(
            label: '${metrics[i].label}: ${metrics[i].value}',
            child: RichText(
              text: TextSpan(
                style: context.tt.bodyMedium?.copyWith(color: ds.textMid),
                children: [
                  TextSpan(
                    text: metrics[i].value,
                    style: TextStyle(
                      color: ds.textHigh,
                      fontWeight: FontWeight.w800,
                      fontFeatures: const [FontFeature.tabularFigures()],
                    ),
                  ),
                  const TextSpan(text: ' '),
                  TextSpan(
                    text: metrics[i].label,
                    style: TextStyle(color: ds.textMid),
                  ),
                ],
              ),
            ),
          ),
        ],
      ],
    );
  }
}

class _Metric {
  const _Metric(this.value, this.label);
  final String value;
  final String label;
}

/// Compact role pill (Stage 4). Subtle — never competes with the identity.
class _RoleChip extends StatelessWidget {
  const _RoleChip({required this.role});
  final SportsRole role;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Semantics(
      label: 'Função: ${role.label}',
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: ds.signal.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(role.icon, size: 12, color: ds.signal),
            const SizedBox(width: 4),
            Text(role.label,
                style: context.tt.labelSmall
                    ?.copyWith(color: ds.signal, fontWeight: FontWeight.w700)),
          ],
        ),
      ),
    );
  }
}
