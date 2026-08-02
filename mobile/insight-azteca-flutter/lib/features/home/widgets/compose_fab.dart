import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_hooks/flutter_hooks.dart';

import '../../../shared/extensions/build_context_x.dart';
import 'composer_screen.dart';

/// Quiet floating compose pill — sits bottom-right, hides when the user
/// scrolls down, returns on scroll-up. Replaces the inline composer row
/// at the top of the feed (which was eating attention from the posts).
///
/// Design notes:
///   * Pill, not circular FAB — softer geometry, less dashboard-y.
///   * Always shows the pencil glyph; the "Postar" word is shown only
///     when we're at/near the top so it greets first-time scroll users
///     without competing with content while they read.
///   * Driven by the same ScrollController as the feed, so coupling is
///     local and the FAB never falls out of sync with the list.
class ComposeFab extends HookWidget {
  const ComposeFab({super.key, required this.scrollController});
  final ScrollController scrollController;

  @override
  Widget build(BuildContext context) {
    // visible: false while the user is scrolling down (reading further).
    final visible = useState(true);
    // expanded: true at the top — shows "Postar" label; collapses to a
    // square icon as soon as the user scrolls past ~40px.
    final expanded = useState(true);

    useEffect(() {
      double last = 0;
      void onScroll() {
        if (!scrollController.hasClients) return;
        final pos = scrollController.position;
        final dy = pos.pixels - last;
        // Threshold dampens jitter — micro-scrolls don't toggle.
        if (dy > 6 && visible.value) {
          visible.value = false;
        } else if (dy < -6 && !visible.value) {
          visible.value = true;
        }
        expanded.value = pos.pixels < 40;
        last = pos.pixels;
      }

      scrollController.addListener(onScroll);
      return () => scrollController.removeListener(onScroll);
    }, [scrollController]);

    return AnimatedSlide(
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOutCubic,
      offset: visible.value ? Offset.zero : const Offset(0, 1.4),
      child: IgnorePointer(
        ignoring: !visible.value,
        child: Material(
          color: context.ds.signal,
          elevation: 4,
          shadowColor: context.ds.signal.withValues(alpha: 0.35),
          borderRadius: BorderRadius.circular(28),
          child: InkWell(
            borderRadius: BorderRadius.circular(28),
            onTap: () {
              HapticFeedback.lightImpact();
              ComposerScreen.open(context);
            },
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 220),
              curve: Curves.easeOutCubic,
              padding: EdgeInsets.symmetric(
                horizontal: expanded.value ? 18 : 14,
                vertical: 12,
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.edit_rounded,
                    color: Colors.white,
                    size: 18,
                  ),
                  AnimatedSize(
                    duration: const Duration(milliseconds: 200),
                    curve: Curves.easeOutCubic,
                    child: expanded.value
                        ? Padding(
                            padding: const EdgeInsets.only(left: 8),
                            child: Text(
                              'Postar',
                              style: context.tt.labelSmall?.copyWith(
                                color: Colors.white,
                                fontWeight: FontWeight.w700,
                                letterSpacing: 0.2,
                              ),
                            ),
                          )
                        : const SizedBox.shrink(),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
