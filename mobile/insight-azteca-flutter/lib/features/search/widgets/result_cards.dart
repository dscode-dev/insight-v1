// FEATURE-SEARCH-V1 Stage 3 — typed result cards (one per entity_type).
//
// No generic Map-based card. Each renders ONLY real backend fields, at the
// current Azteca density (compact, no giant cards). Navigation uses the
// Gateway-provided deep_link exclusively — the client never composes routes.

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/spacing.dart';
import '../model/search_models.dart';
import '../navigation/deep_link.dart';

/// Dispatches a card to its typed renderer by entity_type. Wraps in a tap target
/// that navigates via deep_link when navigable (honest no-op for competitions).
class SearchResultCard extends StatelessWidget {
  const SearchResultCard({super.key, required this.card, this.onBeforeNavigate});
  final SearchCard card;

  /// Lets the hub persist its state (query/tab/scroll) before pushing a detail.
  final VoidCallback? onBeforeNavigate;

  @override
  Widget build(BuildContext context) {
    final navigable = deepLinkIsNavigable(card.deepLink);
    final child = switch (card.entityType) {
      'user' => _UserCard(card.asUser()),
      'agent' => _AgentCard(card.asAgent()),
      'community' => _CommunityCard(card.asCommunity()),
      'competition' => _CompetitionCard(card.asCompetition()),
      'match' => _MatchCard(card.asMatch()),
      'post' => _PostCard(card.asPost()),
      _ => const SizedBox.shrink(),
    };
    return Semantics(
      button: navigable,
      child: InkWell(
        onTap: navigable
            ? () {
                onBeforeNavigate?.call();
                context.push(card.deepLink!);
              }
            : null, // competitions: informative, not navigable
        child: Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: InsightSpacing.lg, vertical: InsightSpacing.sm),
          child: child,
        ),
      ),
    );
  }
}

Color _accent(BuildContext context, String hex) {
  final v = int.tryParse(hex.replaceFirst('#', 'ff'), radix: 16);
  return v != null ? Color(v) : context.ds.signal;
}

class _Avatar extends StatelessWidget {
  const _Avatar({this.url, required this.fallback, required this.color, this.icon});
  final String? url;
  final String fallback;
  final Color color;
  final IconData? icon;
  @override
  Widget build(BuildContext context) {
    final has = url != null && url!.isNotEmpty;
    return CircleAvatar(
      radius: 20,
      backgroundColor: color.withValues(alpha: 0.18),
      backgroundImage: has ? NetworkImage(url!) : null,
      child: has
          ? null
          : (icon != null
              ? Icon(icon, size: 18, color: color)
              : Text(fallback, style: context.tt.labelMedium?.copyWith(color: color))),
    );
  }
}

class _UserCard extends StatelessWidget {
  const _UserCard(this.u);
  final UserHit u;
  @override
  Widget build(BuildContext context) {
    return Row(children: [
      _Avatar(url: u.avatarUrl, fallback: u.initials, color: _accent(context, u.accentColor)),
      const SizedBox(width: InsightSpacing.md),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(u.displayName, style: context.tt.bodyMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
          Row(children: [
            Flexible(child: Text('@${u.username}',
                style: context.tt.bodySmall?.copyWith(color: context.ds.textLow),
                maxLines: 1, overflow: TextOverflow.ellipsis)),
            if (u.mutual) ...[
              const SizedBox(width: 6),
              Text('Segue você', style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
            ],
          ]),
        ]),
      ),
      if (u.tier.isNotEmpty)
        Text(u.tier, style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
    ]);
  }
}

class _AgentCard extends StatelessWidget {
  const _AgentCard(this.a);
  final AgentHit a;
  @override
  Widget build(BuildContext context) {
    return Row(children: [
      _Avatar(url: a.avatar.isEmpty ? null : a.avatar, fallback: '', color: context.ds.signal, icon: Icons.smart_toy_outlined),
      const SizedBox(width: InsightSpacing.md),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Flexible(child: Text(a.name, style: context.tt.bodyMedium, maxLines: 1, overflow: TextOverflow.ellipsis)),
            if (a.verified) ...[
              const SizedBox(width: 4),
              Icon(Icons.verified, size: 14, color: context.ds.signal),
            ],
          ]),
          if (a.bio.isNotEmpty)
            Text(a.bio, style: context.tt.bodySmall?.copyWith(color: context.ds.textLow),
                maxLines: 1, overflow: TextOverflow.ellipsis),
        ]),
      ),
      Text('Agente', style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
    ]);
  }
}

class _CommunityCard extends StatelessWidget {
  const _CommunityCard(this.c);
  final CommunityHit c;
  @override
  Widget build(BuildContext context) {
    return Row(children: [
      _Avatar(fallback: '', color: _accent(context, c.accentColor), icon: Icons.groups_outlined),
      const SizedBox(width: InsightSpacing.md),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(c.name, style: context.tt.bodyMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
          if (c.topic.isNotEmpty)
            Text(c.topic, style: context.tt.bodySmall?.copyWith(color: context.ds.textLow),
                maxLines: 1, overflow: TextOverflow.ellipsis),
        ]),
      ),
      Text('${c.memberCount} membros', style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
    ]);
  }
}

class _CompetitionCard extends StatelessWidget {
  const _CompetitionCard(this.c);
  final CompetitionHit c;
  @override
  Widget build(BuildContext context) {
    // deep_link is null → non-navigable; render informative, no chevron.
    return Row(children: [
      _Avatar(fallback: '', color: _accent(context, c.accentColor), icon: Icons.emoji_events_outlined),
      const SizedBox(width: InsightSpacing.md),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Flexible(child: Text(c.name, style: context.tt.bodyMedium, maxLines: 1, overflow: TextOverflow.ellipsis)),
            if (c.featured) ...[
              const SizedBox(width: 4),
              Icon(Icons.star, size: 13, color: context.ds.signal),
            ],
          ]),
          if (c.region.isNotEmpty)
            Text(c.region, style: context.tt.bodySmall?.copyWith(color: context.ds.textLow),
                maxLines: 1, overflow: TextOverflow.ellipsis),
        ]),
      ),
      if (c.shortName.isNotEmpty)
        Text(c.shortName, style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
    ]);
  }
}

class _MatchCard extends StatelessWidget {
  const _MatchCard(this.m);
  final MatchHit m;
  @override
  Widget build(BuildContext context) {
    final score = (m.homeScore != null && m.awayScore != null)
        ? '${m.homeScore} - ${m.awayScore}'
        : 'vs';
    return Row(children: [
      Icon(Icons.sports_soccer, size: 22, color: context.ds.textLow),
      const SizedBox(width: InsightSpacing.md),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${m.home.name}  $score  ${m.away.name}',
              style: context.tt.bodyMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
          Text([m.competitionName, if (m.state.isNotEmpty) m.state].join(' · '),
              style: context.tt.bodySmall?.copyWith(color: context.ds.textLow),
              maxLines: 1, overflow: TextOverflow.ellipsis),
        ]),
      ),
    ]);
  }
}

class _PostCard extends StatelessWidget {
  const _PostCard(this.p);
  final PostHit p;
  @override
  Widget build(BuildContext context) {
    // Compact: author + snippet + counts — NOT a full post render (keeps the list light).
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        _Avatar(url: p.authorAvatar.isEmpty ? null : p.authorAvatar, fallback: '',
            color: context.ds.signal,
            icon: p.authorType == 'agent' ? Icons.smart_toy_outlined : Icons.person_outline),
        const SizedBox(width: InsightSpacing.sm),
        Expanded(child: Text(p.authorName, style: context.tt.labelMedium, maxLines: 1, overflow: TextOverflow.ellipsis)),
        if (p.likeCount > 0 || p.commentCount > 0)
          Text('${p.likeCount} · ${p.commentCount}',
              style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
      ]),
      const SizedBox(height: 4),
      // Snippet may carry <b> markers from ts_headline; strip to plain text for
      // the compact card (bold-highlight rendering is a later enhancement).
      Text(p.snippet.replaceAll(RegExp(r'</?b>'), ''),
          style: context.tt.bodySmall, maxLines: 2, overflow: TextOverflow.ellipsis),
    ]);
  }
}
