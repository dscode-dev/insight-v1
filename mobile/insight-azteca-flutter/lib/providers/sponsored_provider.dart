import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/feed.dart';

/// Architecture-only Sponsored Intelligence Post injector.
///
/// Provides a small in-memory list of sponsored posts the feed renderer
/// can splice in between organic items. The real implementation will
/// fetch from an ad-mediation service (Gateway proxy) and apply rules
/// like "never two sponsored in a row" + "max one per 6 organic items"
/// — those rules live in [interleaveWithSponsored] below so we can test
/// them in isolation today.
///
/// Spec compliance:
///   * No banners / popups — splicing only.
///   * No betting CTAs in the sample copy.
///   * Discreet "Patrocinado" label rendered by SponsoredPost.
final sponsoredPostsProvider = Provider<List<FeedPost>>((_) => _samples());

/// Splices sponsored posts into a list of organic items.
///
/// Algorithm:
///   * `frequency` controls insertion cadence (default 6 — every 6th
///     organic slot a sponsored post sits below it).
///   * `available` is consumed round-robin so the same sponsor doesn't
///     show up twice in a session unless we exhaust the pool.
///
/// The function is pure so tests can lock the cadence + ordering.
List<FeedPost> interleaveWithSponsored({
  required List<FeedPost> organic,
  required List<FeedPost> sponsored,
  int frequency = 6,
}) {
  if (sponsored.isEmpty || organic.isEmpty) return organic;
  final out = <FeedPost>[];
  var sponsoredIdx = 0;
  for (var i = 0; i < organic.length; i++) {
    out.add(organic[i]);
    if ((i + 1) % frequency == 0 && i + 1 < organic.length) {
      out.add(sponsored[sponsoredIdx % sponsored.length]);
      sponsoredIdx += 1;
    }
  }
  return out;
}

List<FeedPost> _samples() {
  final now = DateTime.now();
  return [
    FeedPost(
      id: 'sponsored_1',
      kind: FeedPostKind.sponsoredIntelligence,
      author: const FeedAuthor(
        id: 'sponsor_konohalabs',
        displayName: 'Konoha Labs',
        username: 'konohalabs',
        initials: 'KL',
        accentColor: '#5BA8FF',
        // isSystem is `false` on purpose — sponsored content is shown
        // as authored content, with the brand as author. The lateral
        // stripe identifying agent/system posts must NOT appear here.
        isSystem: false,
        tier: 'sponsor',
      ),
      body:
          'Estudo do Konoha Labs: como leituras coletivas de pressão antecipam '
          'mudanças táticas em mais de 60% dos jogos de eliminatória. '
          'Compartilhamos o estudo aberto no nosso blog.',
      sponsor: const FeedSponsorMeta(
        name: 'Konoha Labs',
        href: 'https://blog.konohalabs.com/leitura-coletiva',
      ),
      ts: now.subtract(const Duration(minutes: 35)),
    ),
  ];
}
