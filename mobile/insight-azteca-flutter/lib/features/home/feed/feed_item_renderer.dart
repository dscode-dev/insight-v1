import 'package:flutter/material.dart';

import '../../../models/feed.dart';
import '../widgets/posts/agent_post.dart';
import '../widgets/posts/community_post.dart';
import '../widgets/posts/discussion_post.dart';
import '../widgets/posts/signal_post.dart';
import '../widgets/posts/sponsored_post.dart';
import '../widgets/posts/system_post.dart';
import 'text_post_renderer.dart';

/// Renderer-based Feed architecture (AZTECA-FEED-A).
///
/// The Feed itself is **content-type agnostic** — it never switches on
/// `FeedPostKind`. It asks the [FeedRenderers] registry for the renderer that
/// can handle an item and asks it to build the widget. New content types
/// (predictions, Atlas analyses, matches, videos, polls, news) are introduced
/// by REGISTERING a new [FeedItemRenderer] — no Feed redesign, no business
/// logic in the Feed.
abstract class FeedItemRenderer {
  const FeedItemRenderer();

  /// Whether this renderer handles the given post.
  bool canRender(FeedPost post);

  Widget render(
    BuildContext context,
    FeedPost post, {
    ValueChanged<String>? onOpenMatch,
  });
}

/// The renderer registry. The ONLY production renderer implemented this sprint
/// is [TextPostRenderer]. Future renderers are documented placeholders — they
/// are intentionally NOT implemented (no fake renderers):
///   PredictionRenderer · AtlasRenderer · MatchRenderer · VideoRenderer ·
///   PollRenderer · NewsRenderer.
/// Until those exist, non-text variants keep their current rich rendering via
/// [_DefaultRenderer] (a transitional delegate, not a new feature).
class FeedRenderers {
  FeedRenderers._();
  static final FeedRenderers instance = FeedRenderers._();

  // Ordered — first `canRender` match wins.
  static const List<FeedItemRenderer> _renderers = <FeedItemRenderer>[
    TextPostRenderer(),
    // Future (NOT implemented): PredictionRenderer(), AtlasRenderer(),
    // MatchRenderer(), VideoRenderer(), PollRenderer(), NewsRenderer().
  ];
  static const FeedItemRenderer _fallback = _DefaultRenderer();

  FeedItemRenderer resolve(FeedPost post) {
    for (final r in _renderers) {
      if (r.canRender(post)) return r;
    }
    return _fallback;
  }

  Widget render(
    BuildContext context,
    FeedPost post, {
    ValueChanged<String>? onOpenMatch,
  }) =>
      resolve(post).render(context, post, onOpenMatch: onOpenMatch);
}

/// Transitional renderer for the rich, already-shipped variants (agent /
/// system / community / discussion / signal / sponsored). Each of these will
/// get a dedicated renderer in a future sprint; until then their existing
/// widgets are preserved (no regression, no fake data).
class _DefaultRenderer extends FeedItemRenderer {
  const _DefaultRenderer();

  @override
  bool canRender(FeedPost post) => true;

  @override
  Widget render(
    BuildContext context,
    FeedPost post, {
    ValueChanged<String>? onOpenMatch,
  }) {
    switch (post.kind) {
      case FeedPostKind.agentInsight:
        return AgentInsightPost(post: post, onOpenMatch: onOpenMatch);
      case FeedPostKind.systemInsight:
      case FeedPostKind.marketMovement:
        return SystemInsightPost(post: post, onOpenMatch: onOpenMatch);
      case FeedPostKind.communitySignal:
        return CommunityPost(post: post, onOpenMatch: onOpenMatch);
      case FeedPostKind.matchDiscussion:
        return DiscussionPost(post: post, onOpenMatch: onOpenMatch);
      case FeedPostKind.signal:
        return SignalPost(post: post, onOpenMatch: onOpenMatch);
      case FeedPostKind.sponsoredIntelligence:
        return SponsoredPost(post: post, onOpenMatch: onOpenMatch);
      case FeedPostKind.userOpinion:
      case FeedPostKind.quickAnalysis:
        // Text posts are handled by TextPostRenderer; reached only if the
        // registry order changes. Delegate to keep behaviour correct.
        return const TextPostRenderer()
            .render(context, post, onOpenMatch: onOpenMatch);
    }
  }
}
