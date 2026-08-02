import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../../models/feed.dart';
import '../../../../routing/routes.dart';
import '../../../../shared/extensions/build_context_x.dart';
import '../../../../widgets/confidence_meter.dart';
import '../feed_item_shell.dart';
import '../match_embed.dart';
import '../post_actions.dart';
import 'open_author.dart';

/// AI insight variant — lateral stripe matches the agent's accent so the
/// origin is identifiable without chrome. Headline-style body, confidence
/// meter + minute marker, no reply preview (agents don't converse).
class AgentInsightPost extends StatelessWidget {
  const AgentInsightPost({super.key, required this.post, this.onOpenMatch});

  final FeedPost post;
  final ValueChanged<String>? onOpenMatch;

  Color _stripe(BuildContext context) {
    final id = post.agent?.id.name ?? 'history';
    return context.ds.agent.byId(id);
  }

  @override
  Widget build(BuildContext context) {
    final agent = post.agent;
    return FeedItemShell(
      onTapAuthor: openAuthorProfile(context, post),
      onTapPost: () => context.push(R.postThreadFor(post.id)),
      author: post.author,
      ts: post.ts,
      postId: post.id,
      stripeColor: _stripe(context),
      headerDecoration: _AgentBadge(label: agent?.label ?? 'Agente'),
      children: [
        const SizedBox(height: 4),
        // Trend posts (Part 6): optional structured title above the
        // summary body. Plain agent commentary has no title.
        if (agent?.title != null && agent!.title!.isNotEmpty) ...[
          Text(
            agent.title!,
            style:
                context.tt.titleMedium?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 4),
        ],
        Text(post.body, style: context.tt.bodyLarge),
        if (agent != null && agent.highlights.isNotEmpty)
          _Highlights(highlights: agent.highlights),
        if (agent != null && agent.tags.isNotEmpty) _TagsRow(tags: agent.tags),
        if (post.match != null)
          MatchEmbed(
            match: post.match!,
            onTap: onOpenMatch == null
                ? null
                : () => onOpenMatch!(post.match!.matchId),
          ),
        if (agent != null) _AgentFooter(meta: agent),
        PostActions(
          reactions: post.reactions,
          likedByMe: post.likedByMe,
          postId: post.id,
          onReply: () => context.push(R.postThreadFor(post.id)),
        ),
      ],
    );
  }
}

class _AgentBadge extends StatelessWidget {
  const _AgentBadge({required this.label});
  final String label;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: context.ds.subtle,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        label.toUpperCase(),
        style: context.tt.labelSmall?.copyWith(
          color: context.ds.textMid,
          letterSpacing: 0.5,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _AgentFooter extends StatelessWidget {
  const _AgentFooter({required this.meta});
  final FeedAgentMeta meta;

  @override
  Widget build(BuildContext context) {
    final pct = (meta.confidence * 100).round();
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Row(
        children: [
          Expanded(child: ConfidenceMeter(value: meta.confidence)),
          const SizedBox(width: 10),
          Text(
            '$pct%',
            style: context.tt.bodySmall?.copyWith(
              color: context.ds.textHigh,
              fontWeight: FontWeight.w600,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
          if (meta.minute != null) ...[
            const SizedBox(width: 8),
            Text(
              "${meta.minute}'",
              style: context.tt.labelSmall?.copyWith(
                color: context.ds.textLow,
                fontFeatures: const [FontFeature.tabularFigures()],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Compact bullet list of trend highlights — the structured facts the
/// agent surfaced, kept scannable (max 3 rendered).
class _Highlights extends StatelessWidget {
  const _Highlights({required this.highlights});
  final List<String> highlights;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final h in highlights.take(3))
            Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 7),
                    child: Container(
                      width: 4,
                      height: 4,
                      decoration: BoxDecoration(
                        color: context.ds.signal,
                        shape: BoxShape.circle,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      h,
                      style: context.tt.bodyMedium
                          ?.copyWith(color: context.ds.textMid),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

/// Quiet tag chips — context labels (competition, trend family), never
/// loud, capped at 4 so cards stay calm.
class _TagsRow extends StatelessWidget {
  const _TagsRow({required this.tags});
  final List<String> tags;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Wrap(
        spacing: 6,
        runSpacing: 6,
        children: [
          for (final tag in tags.take(4))
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: context.ds.subtle,
                borderRadius: BorderRadius.circular(999),
              ),
              child: Text(
                tag,
                style:
                    context.tt.labelSmall?.copyWith(color: context.ds.textLow),
              ),
            ),
        ],
      ),
    );
  }
}
