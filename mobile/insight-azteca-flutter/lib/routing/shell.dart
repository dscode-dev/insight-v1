import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../providers/auth_provider.dart';
import '../providers/nav_visibility_provider.dart';
import '../shared/strings/pt_br.dart';
import '../widgets/fixed_bottom_nav.dart';
import '../widgets/floating_bottom_nav.dart' show FloatingNavDestination;

/// 5-tab shell using `StatefulShellRoute.indexedStack`.
///
/// Tabs (Sprint 2): Home · Ao vivo · Radar · Explorar · Perfil.
/// The bar is floating-glass — it overlays the page content via `Stack`
/// instead of being a Scaffold.bottomNavigationBar so the feed scrolls
/// edge-to-edge underneath.
///
/// Behaviors owned here:
///   * Re-tapping the ACTIVE Home tab at its root broadcasts a refresh
///     tick (Part 5) — HomeScreen refreshes the feed + scrolls to top.
///   * The Profile tab renders the user's avatar when available
///     (Part 10); initials fallback otherwise.
class InsightShell extends ConsumerWidget {
  const InsightShell({super.key, required this.navShell});

  final StatefulNavigationShell navShell;

  void _onTap(WidgetRef ref, int i) {
    if (i == navShell.currentIndex && i == 0) {
      // Already on Home → refresh semantics (Twitter-style).
      ref.read(homeRetapTickProvider.notifier).state++;
    }
    navShell.goBranch(
      i,
      // Tapping the active tab returns to its root.
      initialLocation: i == navShell.currentIndex,
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(
      authProvider.select((s) => s.user),
    );

    final destinations = <FloatingNavDestination>[
      const FloatingNavDestination(
        icon: Icons.home_outlined,
        activeIcon: Icons.home_rounded,
        label: S.navHome,
      ),
      const FloatingNavDestination(
        icon: Icons.sensors_outlined,
        activeIcon: Icons.sensors_rounded,
        label: S.navLive,
      ),
      const FloatingNavDestination(
        icon: Icons.radar_outlined,
        activeIcon: Icons.radar_rounded,
        label: S.navRadar,
      ),
      const FloatingNavDestination(
        icon: Icons.explore_outlined,
        activeIcon: Icons.explore_rounded,
        label: S.navExplore,
      ),
      // Profile renders the avatar when the session has one.
      FloatingNavDestination(
        icon: Icons.person_outline_rounded,
        activeIcon: Icons.person_rounded,
        label: S.navProfile,
        avatarUrl: user?.avatarUrl,
        avatarInitials: _initialsOf(user?.displayName),
        avatarColorHex: user?.accentColor,
      ),
    ];

    // AZTECA-FLUTTER-P0 Stage 3: a FIXED bottom nav anchored via
    // `bottomNavigationBar`. The body is laid out ABOVE the bar (no
    // `extendBody`, no Stack overlay), so content — feed, cards, composer FAB,
    // sheets — can never render behind the nav. Safe-area handled by the bar.
    return Scaffold(
      body: navShell,
      bottomNavigationBar: FixedBottomNav(
        destinations: destinations,
        currentIndex: navShell.currentIndex,
        onSelect: (i) => _onTap(ref, i),
      ),
    );
  }
}

String? _initialsOf(String? displayName) {
  if (displayName == null || displayName.trim().isEmpty) return null;
  final parts = displayName.trim().split(RegExp(r'\s+'));
  final first = parts.first.characters.first;
  final last = parts.length > 1 ? parts.last.characters.first : '';
  return (first + last).toUpperCase();
}
