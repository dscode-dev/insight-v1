import 'package:flutter/material.dart';

import '../../../models/feed.dart';
import '../feed/feed_item_renderer.dart';

/// A single feed item.
///
/// AZTECA-FEED-A: the Feed is **content-type agnostic** — it no longer switches
/// on `post.kind`. It delegates to the [FeedRenderers] registry, which resolves
/// the right [FeedItemRenderer] for the item. New content types are added by
/// registering a renderer; the Feed itself never changes.
class FeedItem extends StatelessWidget {
  const FeedItem({super.key, required this.post, this.onOpenMatch});

  final FeedPost post;
  final ValueChanged<String>? onOpenMatch;

  @override
  Widget build(BuildContext context) {
    return FeedRenderers.instance
        .render(context, post, onOpenMatch: onOpenMatch);
  }
}
