import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../models/radar.dart';
import '../../../providers/radar_provider.dart';
import '../../../shared/extensions/build_context_x.dart';

/// Timeframe chips for the radar. Mirrors the visual language of
/// LiveFiltersBar so users move between tabs without re-learning.
class RadarFiltersBar extends ConsumerWidget {
  const RadarFiltersBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final active = ref.watch(radarTimeframeProvider);

    return SizedBox(
      height: 44,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        children: [
          for (final t in RadarTimeframe.values)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
              child: _Chip(
                label: t.labelPtBr,
                selected: t == active,
                onTap: () =>
                    ref.read(radarTimeframeProvider.notifier).state = t,
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
