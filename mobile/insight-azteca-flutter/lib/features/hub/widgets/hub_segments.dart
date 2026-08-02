import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../models/hub.dart';
import '../../../providers/hub_provider.dart';
import '../../../shared/extensions/build_context_x.dart';

/// Segment chips at the top of the Hub. Matches the visual rhythm of
/// LiveFiltersBar / RadarFiltersBar so the user moves between tabs without
/// re-learning.
class HubSegmentsBar extends ConsumerWidget {
  const HubSegmentsBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final active = ref.watch(hubSegmentProvider);

    return SizedBox(
      height: 44,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        children: [
          for (final s in HubSegment.values)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
              child: _Chip(
                label: s.labelPtBr,
                selected: s == active,
                onTap: () =>
                    ref.read(hubSegmentProvider.notifier).state = s,
              ),
            ),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({
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
    return InkWell(
      onTap: () {
        HapticFeedback.selectionClick();
        onTap();
      },
      borderRadius: BorderRadius.circular(20),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 120),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
        decoration: BoxDecoration(
          color: selected ? ds.signal : ds.subtle,
          borderRadius: BorderRadius.circular(20),
        ),
        child: Text(
          label,
          style: context.tt.labelSmall?.copyWith(
            color: selected ? Colors.white : ds.textMid,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}
