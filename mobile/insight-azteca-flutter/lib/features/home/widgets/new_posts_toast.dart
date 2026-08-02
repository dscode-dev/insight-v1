import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../providers/feed_provider.dart';
import '../../../shared/extensions/build_context_x.dart';

/// Floating "X novos posts ↑" affordance that slides down from under the
/// AppBar when the pending counter is greater than zero.
///
/// On tap:
///   1. Scrolls the feed back to top.
///   2. Calls FeedNotifier.refresh() (which will swap in the new posts).
///   3. Clears the pending counter.
///
/// Renders nothing when the counter is zero — no slot reserved, no layout
/// shift.
class NewPostsToast extends ConsumerWidget {
  const NewPostsToast({super.key, required this.scrollController});
  final ScrollController scrollController;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final count = ref.watch(pendingNewPostsProvider);

    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 240),
      switchInCurve: Curves.easeOutCubic,
      switchOutCurve: Curves.easeInCubic,
      transitionBuilder: (child, anim) {
        final offset =
            Tween<Offset>(begin: const Offset(0, -0.6), end: Offset.zero)
                .animate(anim);
        return SlideTransition(
          position: offset,
          child: FadeTransition(opacity: anim, child: child),
        );
      },
      child: count == 0
          ? const SizedBox.shrink(key: ValueKey('empty'))
          : Padding(
              key: const ValueKey('pill'),
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Center(
                child: _Pill(
                  count: count,
                  onTap: () async {
                    if (scrollController.hasClients) {
                      await scrollController.animateTo(
                        0,
                        duration: const Duration(milliseconds: 280),
                        curve: Curves.easeOutCubic,
                      );
                    }
                    ref.read(pendingNewPostsProvider.notifier).state = 0;
                    await ref.read(feedProvider.notifier).refresh();
                  },
                ),
              ),
            ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.count, required this.onTap});
  final int count;
  final VoidCallback onTap;

  String get _label =>
      count == 1 ? '1 novo post' : '$count novos posts';

  @override
  Widget build(BuildContext context) {
    return Material(
      color: context.ds.signal,
      borderRadius: BorderRadius.circular(20),
      elevation: 2,
      shadowColor: context.ds.signal.withValues(alpha: 0.3),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.arrow_upward_rounded,
                size: 16,
                color: Colors.white,
              ),
              const SizedBox(width: 6),
              Text(
                _label,
                style: context.tt.labelSmall?.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
