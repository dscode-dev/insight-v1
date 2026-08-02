import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../providers/nav_visibility_provider.dart';

/// Subscribes a `ScrollController` to the [navVisibilityProvider].
///
/// Scrolling down past the threshold hides the floating nav; scrolling
/// up brings it back. The same threshold (6dp) keeps it in sync with
/// the ComposeFab so they don't fade independently.
///
/// Usage:
///
/// ```dart
/// final controller = useScrollController();
/// useNavScrollListener(ref, controller);
/// ```
void useNavScrollListener(
  WidgetRef ref,
  ScrollController controller, {
  double threshold = 6,
}) {
  useEffect(() {
    double last = 0;
    void onScroll() {
      if (!controller.hasClients) return;
      final pos = controller.position;
      final dy = pos.pixels - last;
      final notifier = ref.read(navVisibilityProvider.notifier);
      // Above the threshold, treat tiny jitter as no-change.
      if (dy > threshold && notifier.state) {
        notifier.state = false;
      } else if (dy < -threshold && !notifier.state) {
        notifier.state = true;
      }
      // Always reveal when the user reaches the top — feels natural to
      // see the nav after a long scroll-back.
      if (pos.pixels <= 4 && !notifier.state) {
        notifier.state = true;
      }
      last = pos.pixels;
    }

    controller.addListener(onScroll);
    return () => controller.removeListener(onScroll);
  }, [controller]);
}
