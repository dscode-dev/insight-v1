import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../models/feed.dart';
import '../../../providers/interaction_provider.dart';
import '../../../providers/reaction_provider.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/format/count.dart';

/// Production interaction bar (AZTECA-SOCIAL-A): **Like · Comment · Boost ·
/// Save**. Share is removed (not part of V1).
///
/// - Like: optimistic toggle via the Social like API (rolls back on failure).
/// - Comment: opens the thread; the count is the backend value (no local count).
/// - Boost: first-class boost entity (POST/DELETE /v1/posts/{id}/boost),
///   optimistic with a visible pending state; the backend owns ranking.
/// - Save: private bookmark (POST/DELETE /v1/posts/{id}/save), optimistic +
///   pending. Separate from Like.
///
/// All four share equal-width touch cells for perfect alignment. When `postId`
/// is null (e.g. sponsored placeholders) Like stays a local toggle and
/// Boost/Save are disabled (no server target) rather than faked.
class PostActions extends HookConsumerWidget {
  const PostActions({
    super.key,
    required this.reactions,
    required this.likedByMe,
    this.postId,
    this.onReply,
  });

  final FeedReactions reactions;
  final bool likedByMe;
  final String? postId;
  final VoidCallback? onReply;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final hasServer = postId != null && postId!.isNotEmpty;

    // ---- Like ----
    final bool liked;
    final int likeCount;
    final VoidCallback onLike;
    if (hasServer) {
      final notifier = ref.read(reactionNotifierProvider(postId!).notifier);
      final state = ref.watch(reactionNotifierProvider(postId!));
      useEffect(() {
        Future.microtask(() => notifier
            .hydrate(ReactionState(liked: likedByMe, count: reactions.likes)));
        return null;
      }, [likedByMe, reactions.likes]);
      liked = state.liked;
      likeCount = state.count;
      onLike = notifier.toggle;
    } else {
      final localLiked = useState<bool>(likedByMe);
      final localCount = useState<int>(reactions.likes);
      liked = localLiked.value;
      likeCount = localCount.value;
      onLike = () {
        localLiked.value = !localLiked.value;
        localCount.value += localLiked.value ? 1 : -1;
      };
    }

    // ---- Boost + Save (server only) ----
    BoostState? boost;
    SaveState? save;
    VoidCallback? onBoost;
    VoidCallback? onSave;
    if (hasServer) {
      final snapshot = ref.watch(interactionSnapshotsProvider)[postId!];
      boost = ref.watch(boostNotifierProvider(postId!));
      save = ref.watch(saveNotifierProvider(postId!));
      final boostNotifier = ref.read(boostNotifierProvider(postId!).notifier);
      final saveNotifier = ref.read(saveNotifierProvider(postId!).notifier);
      useEffect(() {
        if (snapshot != null) {
          saveNotifier.hydrate(snapshot.saved);
          boostNotifier.hydrate(
            boosted: snapshot.boosted,
            count: snapshot.boostCount,
          );
        }
        return null;
      }, [snapshot?.saved, snapshot?.boosted, snapshot?.boostCount]);
      onBoost = boostNotifier.toggle;
      onSave = saveNotifier.toggle;
    }

    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: SizedBox(
        width: double.infinity,
        child: Row(
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _Action(
                  icon: liked ? Icons.favorite : Icons.favorite_outline,
                  semanticLabel: liked ? 'Descurtir' : 'Curtir',
                  count: likeCount,
                  color: liked ? context.ds.confidenceLow : context.ds.textMid,
                  onTap: onLike,
                ),
                const SizedBox(width: 12),
                _Action(
                  icon: Icons.mode_comment_outlined,
                  semanticLabel: 'Comentar',
                  count: reactions.replies, // backend value — never local
                  color: context.ds.textMid,
                  onTap: onReply,
                ),
                const SizedBox(width: 12),
                _Action(
                  icon: (boost?.boosted ?? false)
                      ? Icons.rocket_launch
                      : Icons.rocket_launch_outlined,
                  semanticLabel:
                      (boost?.boosted ?? false) ? 'Remover boost' : 'Boost',
                  count: boost?.count ?? 0,
                  color: (boost?.boosted ?? false)
                      ? context.ds.signal
                      : context.ds.textMid,
                  pending: boost?.pending ?? false,
                  onTap: onBoost,
                ),
              ],
            ),
            const Spacer(),
            _Action(
              icon: (save?.saved ?? false)
                  ? Icons.bookmark_rounded
                  : Icons.bookmark_border_rounded,
              semanticLabel:
                  (save?.saved ?? false) ? 'Remover dos salvos' : 'Salvar',
              count: 0,
              color: (save?.saved ?? false)
                  ? context.ds.signal
                  : context.ds.textMid,
              pending: save?.pending ?? false,
              onTap: onSave,
              alignment: Alignment.centerRight,
            ),
          ],
        ),
      ),
    );
  }
}

class _Action extends StatelessWidget {
  const _Action({
    required this.icon,
    required this.semanticLabel,
    required this.count,
    required this.color,
    this.onTap,
    this.pending = false,
    this.alignment = Alignment.centerLeft,
  });

  final IconData icon;
  final String semanticLabel;
  final int count;
  final Color color;
  final VoidCallback? onTap;
  final bool pending;
  final AlignmentGeometry alignment;

  @override
  Widget build(BuildContext context) {
    final enabled = onTap != null && !pending;
    return Semantics(
      button: true,
      enabled: enabled,
      label: count > 0 ? '$semanticLabel, $count' : semanticLabel,
      child: InkResponse(
        onTap: enabled ? onTap : null,
        radius: 24,
        child: Container(
          // Equal, generous touch target across all four actions.
          constraints: const BoxConstraints(minHeight: 44, minWidth: 44),
          alignment: alignment,
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (pending)
                SizedBox(
                  width: 18,
                  height: 18,
                  child: Padding(
                    padding: const EdgeInsets.all(2),
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      valueColor: AlwaysStoppedAnimation(color),
                    ),
                  ),
                )
              else
                Icon(icon, size: 18, color: color),
              if (count > 0) ...[
                const SizedBox(width: 6),
                Text(
                  formatCount(count),
                  style: context.tt.bodySmall?.copyWith(
                    color: color,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
