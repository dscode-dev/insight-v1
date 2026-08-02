import 'package:flutter/material.dart';

import '../shared/extensions/build_context_x.dart';

/// Quiet section header for Radar / Hub / Profile sections. Uppercase
/// micro type — never competes with feed content.
class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, this.trailing});
  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 24, 20, 8),
      child: Row(
        children: [
          Expanded(
            child: Text(
              title.toUpperCase(),
              style: context.tt.labelSmall?.copyWith(
                color: context.ds.textMid,
                letterSpacing: 0.6,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}
