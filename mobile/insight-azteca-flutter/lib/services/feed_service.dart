import 'package:dio/dio.dart';

import '../models/feed.dart';
import 'gateway_client.dart';

/// Pagination query — mirrors the Next.js `FeedQuery` shape.
class FeedQuery {
  const FeedQuery({this.cursor, this.limit = 6});
  final String? cursor;
  final int limit;
}

abstract class FeedService {
  Future<FeedPage> getFeed([FeedQuery query = const FeedQuery()]);
}

class GatewayFeedService implements FeedService {
  GatewayFeedService(this._dio);
  final Dio _dio;

  @override
  Future<FeedPage> getFeed([FeedQuery query = const FeedQuery()]) async {
    final body = await _dio.getJson('/v1/feed', query: {
      if (query.cursor != null) 'cursor': query.cursor,
      'limit': query.limit,
    });
    return FeedPage.fromJson(body);
  }
}
