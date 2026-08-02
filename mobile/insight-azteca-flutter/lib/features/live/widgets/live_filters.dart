import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../models/live.dart';
import '../../../providers/live_provider.dart';
import '../../../shared/extensions/build_context_x.dart';

class LiveFiltersBar extends ConsumerWidget {
  const LiveFiltersBar({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final active = ref.watch(liveFilterProvider).status;

    return SizedBox(
      height: 44,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        children: [
          for (final s in LiveStatusFilter.values)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
              child: _Chip(
                label: s.labelPtBr,
                selected: s == active,
                onTap: () => ref.read(liveFilterProvider.notifier).state =
                    LiveFilter(status: s),
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
