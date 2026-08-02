import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../providers/nav_visibility_provider.dart';
import '../shared/extensions/build_context_x.dart';
import '../theme/icon_sizing.dart';
import '../theme/motion.dart';
import 'avatar.dart';

/// Single navigation destination in the floating bottom bar.
///
/// When [avatarUrl] or [avatarInitials] is set the slot renders a
/// circular avatar instead of the icon — used by the Profile tab so
/// the user sees themselves in the nav.
class FloatingNavDestination {
  const FloatingNavDestination({
    required this.icon,
    required this.activeIcon,
    required this.label,
    this.avatarUrl,
    this.avatarInitials,
    this.avatarColorHex,
  });

  final IconData icon;
  final IconData activeIcon;
  final String label;
  final String? avatarUrl;
  final String? avatarInitials;
  final String? avatarColorHex;

  bool get hasAvatar =>
      (avatarUrl != null && avatarUrl!.isNotEmpty) ||
      (avatarInitials != null && avatarInitials!.isNotEmpty);
}

/// iOS-26 "Liquid Glass" floating bottom navigation.
///
/// Structure (matches Threads / Instagram / Apple News+ on iOS 26):
///   * A single floating pill, inset from all edges, that the page
///     content scrolls physically behind (the shell uses `extendBody`
///     + a `Stack`).
///   * The pill is real glass: `ClipRRect` → `BackdropFilter` gaussian
///     blur → a thin frosted fill + a hairline refraction border, so
///     the content underneath shows through.
///   * Each item is an `AnimatedContainer` (250ms, easeInOutCubic).
///     The SELECTED item expands horizontally into a soft highlight
///     capsule that reveals the colored icon + its label; the others
///     collapse to a bare icon. Every slot animates its own
///     width/padding, so the selection glides between tabs.
class FloatingBottomNav extends ConsumerWidget {
  const FloatingBottomNav({
    super.key,
    required this.destinations,
    required this.currentIndex,
    required this.onSelect,
  });

  final List<FloatingNavDestination> destinations;
  final int currentIndex;
  final ValueChanged<int> onSelect;

  // iOS-26 proportions.
  static const double _radius = 30;
  static const double _barHeight = 64;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final visible = ref.watch(navVisibilityProvider);
    final bottomInset = MediaQuery.of(context).viewPadding.bottom;
    final showLabels = MediaQuery.sizeOf(context).width >= 320;

    return AnimatedSlide(
      duration: InsightMotion.standard,
      curve: InsightMotion.emphasized,
      offset: visible ? Offset.zero : const Offset(0, 1.6),
      child: IgnorePointer(
        ignoring: !visible,
        child: Padding(
          // Floats inset from the screen edges.
          padding: EdgeInsets.fromLTRB(
            20,
            0,
            20,
            (bottomInset > 0 ? bottomInset : 16) + 14,
          ),
          child: _GlassBar(
            height: _barHeight,
            radius: _radius,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                for (var i = 0; i < destinations.length; i++)
                  _NavItem(
                    destination: destinations[i],
                    active: i == currentIndex,
                    showLabel: showLabels,
                    onTap: () {
                      HapticFeedback.selectionClick();
                      onSelect(i);
                    },
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// The translucent glass pill: blur + frosted fill + refraction edge.
class _GlassBar extends StatelessWidget {
  const _GlassBar({
    required this.child,
    required this.height,
    required this.radius,
  });

  final Widget child;
  final double height;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final isDark = context.isDark;
    final br = BorderRadius.circular(radius);
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: br,
        boxShadow: [
          // One soft drop — the glass floats, it doesn't slam.
          BoxShadow(
            color: Colors.black.withValues(alpha: isDark ? 0.18 : 0.08),
            blurRadius: 20,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: br,
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
          child: Container(
            height: height,
            padding: const EdgeInsets.symmetric(horizontal: 8),
            decoration: BoxDecoration(
              borderRadius: br,
              // Frosted acrylic — the bar is mostly the blurred content
              // behind it; the fill only lifts contrast a touch.
              color: Colors.white.withValues(alpha: isDark ? 0.15 : 0.55),
              // Hairline refraction edge — the light-bend rim of glass.
              border: Border.all(
                color: Colors.white.withValues(alpha: isDark ? 0.25 : 0.45),
                width: 0.5,
              ),
            ),
            // Top specular sheen — "mirror" highlight on the upper edge.
            child: Stack(
              children: [
                Positioned(
                  left: 16,
                  right: 16,
                  top: 0,
                  child: Container(
                    height: 1,
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        colors: [
                          Colors.white.withValues(alpha: 0),
                          Colors.white.withValues(alpha: isDark ? 0.5 : 0.8),
                          Colors.white.withValues(alpha: 0),
                        ],
                      ),
                    ),
                  ),
                ),
                Center(child: child),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// One nav slot. Collapsed = bare icon; selected = highlight capsule
/// that expands to reveal the colored icon + label.
class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.destination,
    required this.active,
    required this.showLabel,
    required this.onTap,
  });

  final FloatingNavDestination destination;
  final bool active;
  final bool showLabel;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final isDark = context.isDark;
    final revealLabel = active && showLabel;

    return Semantics(
      label: destination.label,
      selected: active,
      button: true,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeInOutCubic,
          height: 48,
          padding: EdgeInsets.symmetric(horizontal: active ? 18 : 14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(24),
            // Soft highlight fill under the selected item only.
            color: active
                ? Colors.white.withValues(alpha: isDark ? 0.20 : 0.35)
                : Colors.transparent,
            border: active
                ? Border.all(
                    color: Colors.white.withValues(alpha: isDark ? 0.22 : 0.5),
                    width: 0.5,
                  )
                : null,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              _NavIcon(destination: destination, active: active),
              // AnimatedSize collapses the label to 0 width when
              // inactive, so the capsule grows/shrinks smoothly.
              AnimatedSize(
                duration: const Duration(milliseconds: 250),
                curve: Curves.easeInOutCubic,
                child: revealLabel
                    ? Padding(
                        padding: const EdgeInsets.only(left: 8),
                        child: Text(
                          destination.label,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          softWrap: false,
                          style: context.tt.labelMedium?.copyWith(
                            color: ds.textHigh,
                            fontWeight: FontWeight.w700,
                            letterSpacing: -0.1,
                          ),
                        ),
                      )
                    : const SizedBox.shrink(),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NavIcon extends StatelessWidget {
  const _NavIcon({required this.destination, required this.active});

  final FloatingNavDestination destination;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;

    if (destination.hasAvatar) {
      return AnimatedContainer(
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeInOutCubic,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(
            color:
                active ? ds.signal.withValues(alpha: 0.9) : Colors.transparent,
            width: 2,
          ),
        ),
        child: InsightAvatar(
          initials: destination.avatarInitials ?? '·',
          colorHex: destination.avatarColorHex ?? '#5BA8FF',
          avatarUrl: destination.avatarUrl,
          size: InsightIconSize.nav + 2,
        ),
      );
    }

    return AnimatedSwitcher(
      duration: InsightMotion.quick,
      transitionBuilder: (child, animation) => FadeTransition(
        opacity: animation,
        child: ScaleTransition(
          scale: Tween<double>(begin: 0.85, end: 1).animate(animation),
          child: child,
        ),
      ),
      child: Icon(
        active ? destination.activeIcon : destination.icon,
        key: ValueKey('${destination.label}-$active'),
        size: InsightIconSize.nav + (active ? 2 : 0),
        // Colored when active (the "reveal the colored icon" beat),
        // tonally quiet otherwise.
        color: active ? ds.signal : ds.textMid,
      ),
    );
  }
}
