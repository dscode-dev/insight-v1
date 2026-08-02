import '../models/feed.dart';
import '../services/feed_service.dart';
import 'fixtures/feed_fixtures.dart';

/// Mock feed: cursor pagination, newest-first, deterministic.
///
/// Cursor is the `ts.isoIso8601` of the last item in the previous page.
/// Items strictly older than the cursor go in the next page. Mirrors the
/// Next.js mock provider so screenshots / dev mode behave identically.
class MockFeedService implements FeedService {
  MockFeedService();

  static const Duration _latency = Duration(milliseconds: 240);

  @override
  Future<FeedPage> getFeed([FeedQuery query = const FeedQuery()]) async {
    await Future<void>.delayed(_latency);

    final all = List<FeedPost>.from(kFeedPosts())
      ..sort((a, b) => b.ts.compareTo(a.ts)); // newest first

    int start = 0;
    if (query.cursor != null) {
      final cur = DateTime.tryParse(query.cursor!);
      if (cur != null) {
        start = all.indexWhere((p) => p.ts.isBefore(cur));
        if (start == -1) start = all.length;
      }
    }

    final end = (start + query.limit).clamp(0, all.length);
    final page = all.sublist(start, end);
    final hasMore = end < all.length;
    return FeedPage(
      items: page,
      nextCursor: hasMore && page.isNotEmpty
          ? page.last.ts.toIso8601String()
          : null,
    );
  }
}
