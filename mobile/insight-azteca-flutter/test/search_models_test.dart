// FEATURE-SEARCH-V1 Stage 3 — models: capabilities→tabs, no teams/players,
// trending honesty, typed card decode, dedupe key, deep-link honesty.
// ignore_for_file: prefer_const_literals_to_create_immutables, inference_failure_on_instance_creation, inference_failure_on_collection_literal
import 'package:flutter_test/flutter_test.dart';
import 'package:azteca/features/search/model/search_models.dart';
import 'package:azteca/features/search/navigation/deep_link.dart';

void main() {
  group('capabilities drive tabs (never hardcoded)', () {
    test('enabled 6 → tabs = All + 6; teams/players excluded; trending unavailable', () {
      final caps = SearchCapabilities.fromJson({
        'enabled': ['users', 'agents', 'communities', 'competitions', 'matches', 'posts'],
        'blocked': {'teams': 'BLOCKED_BY_DOMAIN', 'players': 'BLOCKED_BY_DOMAIN'},
        'temporarily_unavailable': [],
        'trending': 'UNAVAILABLE',
      });
      expect(caps.tabs.first, SearchCategory.all);
      expect(caps.tabs.length, 7);
      // Teams/Players are not valid categories and never appear as tabs.
      expect(caps.tabs.map((t) => t.wire), isNot(contains('teams')));
      expect(caps.tabs.map((t) => t.wire), isNot(contains('players')));
      expect(caps.trendingAvailable, isFalse);
      expect(caps.blocked.containsKey('teams'), isTrue);
    });

    test('unknown wire categories are ignored (forward-compat)', () {
      final caps = SearchCapabilities.fromJson({
        'enabled': ['users', 'teams', 'players', 'zzz'],
      });
      // Only real client categories survive; teams/players/zzz dropped.
      expect(caps.enabled, [SearchCategory.users]);
    });

    test('shrunk capabilities → fewer tabs', () {
      final caps = SearchCapabilities.fromJson({'enabled': ['users', 'posts']});
      expect(caps.tabs, [SearchCategory.all, SearchCategory.users, SearchCategory.posts]);
    });
  });

  group('typed card decode (no generic Map card)', () {
    test('user card real fields + mutual', () {
      final c = SearchCard.fromJson({
        'entity_type': 'user', 'entity_id': 'u1', 'deep_link': '/users/u1',
        'data': {'id': 'u1', 'username': 'neymar', 'display_name': 'Ney',
          'initials': 'NE', 'reputation': 87, 'tier': 'pro', 'followers': 10,
          'is_following': true, 'follows_viewer': true, 'mutual': true},
      });
      expect(c.key, 'user:u1');
      final u = c.asUser();
      expect(u.username, 'neymar');
      expect(u.mutual, isTrue);
      expect(u.reputation, 87);
    });

    test('match card keeps teams as CONTEXT (no team entity)', () {
      final c = SearchCard.fromJson({
        'entity_type': 'match', 'entity_id': 'm1', 'deep_link': '/live/match/m1',
        'data': {'match_id': 'm1', 'competition_name': 'Brasileirão',
          'home_team': {'name': 'Flamengo', 'short': 'FLA'},
          'away_team': {'name': 'Palmeiras', 'short': 'PAL'},
          'kickoff_ts': '2026-01-01T00:00:00Z', 'state': 'scheduled'},
      });
      final m = c.asMatch();
      expect(m.home.name, 'Flamengo'); // context string, not a Team id
      expect(c.entityType, 'match');   // never "team"
    });
  });

  group('deep-link honesty (validated against real routes)', () {
    test('supported links are navigable', () {
      for (final l in ['/users/x', '/agents/x', '/hub/community/x', '/live/match/x', '/post/x']) {
        expect(deepLinkIsNavigable(l), isTrue, reason: l);
      }
    });
    test('null (competition) and unknown routes are NOT navigable', () {
      expect(deepLinkIsNavigable(null), isFalse);
      expect(deepLinkIsNavigable(''), isFalse);
      expect(deepLinkIsNavigable('/teams/x'), isFalse);   // no such route
      expect(deepLinkIsNavigable('/players/x'), isFalse);
      expect(deepLinkIsNavigable('/competition/x'), isFalse);
    });
  });

  group('All result parsing (per-category cursors + partial)', () {
    test('partial + failed categories + per-category cursors', () {
      final r = SearchAllResult.fromJson({
        'items': [
          {'entity_type': 'user', 'entity_id': 'u1', 'normalized_score': 1.0, 'data': {}},
        ],
        'cursors': {'users': 'cur-u', 'posts': 'cur-p'},
        'partial': true,
        'failed_categories': ['communities'],
      });
      expect(r.partial, isTrue);
      expect(r.failedCategories, ['communities']);
      expect(r.cursors['users'], 'cur-u');
      expect(r.items.first.score, 1.0);
    });
  });
}
