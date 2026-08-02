import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../shared/extensions/build_context_x.dart';
import 'avatar.dart';
import 'floating_bottom_nav.dart' show FloatingNavDestination;

/// Fixed bottom navigation — refined (AZTECA-NAVIGATION-A).
///
/// Anchored via `Scaffold.bottomNavigationBar` (never floating). Lightweight,
/// X/Threads-style: **inactive items show the icon only**; the **active item
/// expands into a subtle capsule** revealing its label with a smooth
/// fade + horizontal-expansion (~220ms, no bounce). Active = Insight primary
/// (signal); inactive = neutral. Compact ~62dp height (excluding SafeArea),
/// ≥44×44dp touch targets.
class FixedBottomNav extends StatelessWidget {
  const FixedBottomNav({
    super.key,
    required this.destinations,
    required this.currentIndex,
    required this.onSelect,
  });

  final List<FloatingNavDestination> destinations;
  final int currentIndex;
  final ValueChanged<int> onSelect;

  /// Visual bar height, excluding the SafeArea inset below.
  static const double _barHeight = 62;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: context.scheme.surface,
        border: Border(top: BorderSide(color: context.ds.divider, width: 0.5)),
      ),
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: _barHeight,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              for (var i = 0; i < destinations.length; i++)
                _NavItem(
                  destination: destinations[i],
                  selected: i == currentIndex,
                  onTap: () {
                    if (i != currentIndex) HapticFeedback.selectionClick();
                    onSelect(i);
                  },
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// A single destination. Only the item whose [selected] state changed animates
/// (capsule + label), keeping the bar cheap to rebuild and smooth at 60 FPS.
class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.destination,
    required this.selected,
    required this.onTap,
  });

  final FloatingNavDestination destination;
  final bool selected;
  final VoidCallback onTap;

  static const Duration _anim = Duration(milliseconds: 220);
  static const Curve _curve = Curves.easeOutCubic;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final active = ds.signal; // Insight primary
    final neutral = ds.textLow; // inactive neutral
    final color = selected ? active : neutral;

    final Widget glyph = destination.hasAvatar
        ? InsightAvatar(
            avatarUrl: destination.avatarUrl,
            initials: destination.avatarInitials ?? '',
            colorHex: destination.avatarColorHex ?? '#5BA8FF',
            size: 24,
          )
        : Icon(
            selected ? destination.activeIcon : destination.icon,
            size: 24,
            color: color,
          );

    return Semantics(
      button: true,
      selected: selected,
      label: destination.label,
      child: InkResponse(
        onTap: onTap,
        radius: 40,
        highlightColor: Colors.transparent,
        splashColor: active.withValues(alpha: 0.10),
        child: ConstrainedBox(
          // Guarantee a ≥44×44 touch target even when the item is icon-only.
          constraints: const BoxConstraints(minWidth: 44, minHeight: 44),
          child: Center(
            child: AnimatedContainer(
              duration: _anim,
              curve: _curve,
              padding: EdgeInsets.symmetric(
                horizontal: selected ? 12 : 10,
                vertical: 7,
              ),
              decoration: BoxDecoration(
                // Subtle capsule on the active item only — small radius, light
                // emphasis, no shadow, no floating look.
                color: selected ? active.withValues(alpha: 0.12) : Colors.transparent,
                borderRadius: BorderRadius.circular(14),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  glyph,
                  // Label appears only for the active item, expanding
                  // horizontally (AnimatedSize) + fading in (AnimatedOpacity).
                  AnimatedSize(
                    duration: _anim,
                    curve: _curve,
                    alignment: Alignment.centerLeft,
                    child: selected
                        ? Padding(
                            padding: const EdgeInsets.only(left: 7),
                            child: AnimatedOpacity(
                              duration: _anim,
                              curve: _curve,
                              opacity: 1,
                              child: Text(
                                destination.label,
                                maxLines: 1,
                                overflow: TextOverflow.clip,
                                softWrap: false,
                                style: context.tt.labelMedium?.copyWith(
                                  color: active,
                                  fontWeight: FontWeight.w700,
                                  height: 1,
                                ),
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
