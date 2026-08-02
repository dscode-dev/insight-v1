import 'package:flutter/material.dart';

import '../shared/extensions/build_context_x.dart';
import '../theme/radii.dart';
import '../theme/spacing.dart';

class InsightSegment {
  const InsightSegment({
    required this.label,
    required this.value,
    this.icon,
  });

  final String label;
  final Object value;
  final IconData? icon;
}

class InsightSegmentedTabs<T> extends StatelessWidget {
  const InsightSegmentedTabs({
    super.key,
    required this.value,
    required this.segments,
    required this.onChanged,
    this.dense = false,
  });

  final T value;
  final List<InsightSegment> segments;
  final ValueChanged<T> onChanged;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(InsightSpacing.xs),
      decoration: BoxDecoration(
        color: context.ds.subtle,
        borderRadius: BorderRadius.circular(InsightRadii.lg),
        border: Border.all(color: context.ds.divider.withValues(alpha: 0.7)),
      ),
      child: Row(
        children: [
          for (final segment in segments)
            Expanded(
              child: _SegmentButton<T>(
                segment: segment,
                selected: segment.value == value,
                dense: dense,
                onTap: () => onChanged(segment.value as T),
              ),
            ),
        ],
      ),
    );
  }
}

class _SegmentButton<T> extends StatelessWidget {
  const _SegmentButton({
    required this.segment,
    required this.selected,
    required this.dense,
    required this.onTap,
  });

  final InsightSegment segment;
  final bool selected;
  final bool dense;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final bg = selected ? context.ds.card : Colors.transparent;
    final color = selected ? context.ds.textHigh : context.ds.textMid;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(InsightRadii.md),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          curve: Curves.easeOutCubic,
          height: dense ? 36 : 42,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: bg,
            borderRadius: BorderRadius.circular(InsightRadii.md),
            boxShadow: selected
                ? [
                    BoxShadow(
                      color: Colors.black
                          .withValues(alpha: context.isDark ? 0.22 : 0.08),
                      blurRadius: 14,
                      offset: const Offset(0, 6),
                    ),
                  ]
                : null,
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (segment.icon != null) ...[
                Icon(segment.icon, size: 16, color: color),
                const SizedBox(width: InsightSpacing.sm),
              ],
              Text(
                segment.label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.tt.labelLarge?.copyWith(
                  color: color,
                  fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class InsightTabBar extends StatelessWidget {
  const InsightTabBar({
    super.key,
    required this.tabs,
    this.isScrollable = false,
  });

  final List<Widget> tabs;
  final bool isScrollable;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: InsightSpacing.lg),
      padding: const EdgeInsets.all(InsightSpacing.xs),
      decoration: BoxDecoration(
        color: context.ds.subtle,
        borderRadius: BorderRadius.circular(InsightRadii.lg),
        border: Border.all(color: context.ds.divider.withValues(alpha: 0.7)),
      ),
      child: TabBar(
        tabs: tabs,
        isScrollable: isScrollable,
        labelColor: context.ds.textHigh,
        unselectedLabelColor: context.ds.textMid,
        indicatorSize: TabBarIndicatorSize.tab,
        dividerColor: Colors.transparent,
        splashBorderRadius: BorderRadius.circular(InsightRadii.md),
        indicator: BoxDecoration(
          color: context.ds.card,
          borderRadius: BorderRadius.circular(InsightRadii.md),
        ),
      ),
    );
  }
}
