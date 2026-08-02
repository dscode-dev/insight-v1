import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../features/notifications/state/unread_controller.dart';
import '../routing/routes.dart';
import '../shared/extensions/build_context_x.dart';

/// Bell icon for AppBar.actions with a small unread badge. Tapping pushes
/// the Notifications overlay.
///
/// FEATURE-NOTIFICATIONS-V1: the badge depends EXCLUSIVELY on the unread
/// controller (the Gateway's authoritative count) — never on the loaded list.
/// It works even if the Notification Center was never opened.
class NotificationsAction extends ConsumerWidget {
  const NotificationsAction({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final unread = ref.watch(unreadControllerProvider);
    return IconButton(
      tooltip: 'Notificações',
      onPressed: () => context.push(R.notifications),
      icon: Stack(
        clipBehavior: Clip.none,
        children: [
          const Icon(Icons.notifications_none_rounded),
          if (unread > 0)
            Positioned(
              top: -2,
              right: -3,
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 5,
                  vertical: 1,
                ),
                decoration: BoxDecoration(
                  color: context.ds.confidenceLow,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: context.ds.background, width: 1.5),
                ),
                constraints: const BoxConstraints(minWidth: 16, minHeight: 16),
                child: Text(
                  unread > 9 ? '9+' : '$unread',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                    height: 1.2,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
