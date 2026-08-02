import 'package:flutter/material.dart';

import '../shared/extensions/build_context_x.dart';

/// A lightweight, premium segmented control (AZTECA-PROFILE-A).
///
/// Compact height, a subtle track, a single sliding thumb (no per-segment
/// borders, no heavy shadows). The thumb glides under the active label with a
/// calm easing curve. Built to sit *below* a heavier header without competing
/// with it.
class InsightSegmentedControl extends StatelessWidget {
  const InsightSegmentedControl({
    super.key,
    required this.labels,
    required this.selectedIndex,
    required this.onChanged,
  });

  final List<String> labels;
  final int selectedIndex;
  final ValueChanged<int> onChanged;

  static const double _height = 38;
  static const double _pad = 3;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final n = labels.length;
    final selected = selectedIndex.clamp(0, n - 1);

    return Semantics(
      container: true,
      label: 'Seções do perfil',
      child: Container(
        height: _height,
        padding: const EdgeInsets.all(_pad),
        decoration: BoxDecoration(
          color: ds.subtle,
          borderRadius: BorderRadius.circular(12),
        ),
        child: LayoutBuilder(
          builder: (context, c) {
            final thumbW = c.maxWidth / n;
            return Stack(
              children: [
                // Sliding thumb — the only moving, emphasized element.
                AnimatedAlign(
                  duration: const Duration(milliseconds: 220),
                  curve: Curves.easeOutCubic,
                  alignment: n == 1
                      ? Alignment.center
                      : Alignment(2 * selected / (n - 1) - 1, 0),
                  child: Container(
                    width: thumbW,
                    height: double.infinity,
                    decoration: BoxDecoration(
                      color: ds.card,
                      borderRadius: BorderRadius.circular(9),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withValues(
                              alpha: context.isDark ? 0.20 : 0.05),
                          blurRadius: 6,
                          offset: const Offset(0, 1),
                        ),
                      ],
                    ),
                  ),
                ),
                Row(
                  children: [
                    for (var i = 0; i < n; i++)
                      Expanded(
                        child: _Segment(
                          label: labels[i],
                          selected: i == selected,
                          onTap: () => onChanged(i),
                        ),
                      ),
                  ],
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _Segment extends StatelessWidget {
  const _Segment({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Semantics(
      button: true,
      selected: selected,
      label: label,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: Center(
          child: AnimatedDefaultTextStyle(
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOutCubic,
            style: context.tt.labelLarge!.copyWith(
              color: selected ? ds.textHigh : ds.textMid,
              fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
            ),
            child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
          ),
        ),
      ),
    );
  }
}
