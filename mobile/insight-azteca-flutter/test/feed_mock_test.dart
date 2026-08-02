import 'package:azteca/mock/feed_mock.dart';
import 'package:azteca/services/feed_service.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final service = MockFeedService();

  test('first page returns newest-first with a next cursor', () async {
    final page = await service.getFeed(const FeedQuery(limit: 3));
    expect(page.items.length, 3);
    for (var i = 1; i < page.items.length; i++) {
      // Strictly descending by ts.
      expect(
        page.items[i - 1].ts.isAfter(page.items[i].ts),
        isTrue,
        reason: 'items must be newest-first',
      );
    }
    expect(page.nextCursor, isNotNull);
  });

  test('second page is strictly older than the first', () async {
    final first = await service.getFeed(const FeedQuery(limit: 3));
    final second = await service.getFeed(
      FeedQuery(cursor: first.nextCursor, limit: 3),
    );
    expect(second.items, isNotEmpty);
    expect(
      second.items.first.ts.isBefore(first.items.last.ts),
      isTrue,
      reason: 'next page must start strictly older than prev page tail',
    );
  });

  test('exhausting all pages eventually nulls the cursor', () async {
    String? cursor;
    var total = 0;
    var safety = 20;
    while (safety-- > 0) {
      final page = await service.getFeed(FeedQuery(cursor: cursor, limit: 4));
      total += page.items.length;
      cursor = page.nextCursor;
      if (cursor == null) break;
    }
    expect(cursor, isNull);
    expect(total, greaterThan(0));
  });
}
