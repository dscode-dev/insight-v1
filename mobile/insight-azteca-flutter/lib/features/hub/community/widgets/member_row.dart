// FEATURE-COMMUNITIES-V1 Stage 3 — member row (real public profile fields).
import 'package:flutter/material.dart';

import '../../../../shared/extensions/build_context_x.dart';
import '../../../../theme/spacing.dart';
import '../../../../widgets/avatar.dart';
import '../model/community_models.dart';

class MemberRow extends StatelessWidget {
  const MemberRow({super.key, required this.member, this.onTap});
  final CommunityMember member;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      onTap: onTap,
      leading: InsightAvatar(initials: member.initials, colorHex: member.accentColor, size: 36),
      title: Text(member.displayName, style: context.tt.titleMedium),
      subtitle: Text('@${member.username}',
          style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
      trailing: _RoleBadge(role: member.role),
    );
  }
}

class _RoleBadge extends StatelessWidget {
  const _RoleBadge({required this.role});
  final String role;

  @override
  Widget build(BuildContext context) {
    // Role is DISPLAY only — a badge, never an authorization decision.
    if (role == 'member') return const SizedBox.shrink();
    final label = switch (role) {
      'owner' => 'Dono',
      'admin' => 'Admin',
      'moderator' => 'Moderador',
      _ => role,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: InsightSpacing.md, vertical: InsightSpacing.xs),
      decoration: BoxDecoration(
        color: context.ds.subtle,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: context.ds.divider),
      ),
      child: Text(label, style: context.tt.labelSmall?.copyWith(color: context.ds.textMid)),
    );
  }
}
