// FEATURE-NOTIFICATIONS-V1 Stage 3 — Notification Center (EVOLVED, not
// replaced). Same route, same approved row identity (icon-in-tinted-square +
// title + relative time + body + unread tint). Only the DATA SOURCE changed:
// items, icon/color, read state and capabilities now come from the Gateway.
//
// Adds: infinite scroll (Gateway cursor + has_more), pull-to-refresh, optimistic
// mark-read/mark-all-read, and independent states (no single isLoading). The
// list is never rebuilt wholesale on a mutation — only the changed item + badge.

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../core/feature_gate.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../shared/format/relative_time.dart';
import '../../theme/spacing.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/error_state.dart';
import '../../widgets/offline_state.dart';
import 'model/notification_models.dart';
import 'state/notification_action_handler.dart';
import 'state/notifications_controller.dart';
import 'state/unread_controller.dart';
import 'widgets/notification_icon.dart';

class NotificationsScreen extends ConsumerStatefulWidget {
  const NotificationsScreen({super.key});
  @override
  ConsumerState<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends ConsumerState<NotificationsScreen> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 400) {
        ref.read(notificationsControllerProvider.notifier).loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(notificationsControllerProvider);
    final notifier = ref.read(notificationsControllerProvider.notifier);
    final unread = ref.watch(unreadControllerProvider);

    final handler = NotificationActionHandler(
      onNavigate: (link) => context.push(link),
      onMarkRead: notifier.markRead,
    );

    return Scaffold(
      appBar: AppBar(
        title: const Text('Notificações'),
        actions: [
          if (state.phase != NotifPhase.unavailable && unread > 0)
            Semantics(
              button: true,
              label: 'Marcar todas como lidas',
              child: TextButton(
                onPressed: notifier.markAllRead,
                child: Text('Marcar lidas', style: TextStyle(color: context.ds.signal)),
              ),
            ),
        ],
      ),
      body: switch (state.phase) {
        NotifPhase.unavailable => const FeatureUnavailableView(message: 'Notificações em breve'),
        NotifPhase.initialLoading => const Center(child: CircularProgressIndicator()),
        NotifPhase.offline => OfflineState(onRetry: notifier.load),
        NotifPhase.error => ListView(children: [
            ErrorState(
              title: 'Notificações indisponíveis',
              description: 'Não consegui carregar a caixa agora.',
              onRetry: notifier.load,
            ),
          ]),
        NotifPhase.empty => RefreshIndicator(
            color: context.ds.signal,
            onRefresh: notifier.refresh,
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              children: const [
                EmptyState(
                  title: 'Nada novo por aqui',
                  description: 'Quando algo que você segue se mexer, a gente avisa.',
                ),
              ],
            ),
          ),
        _ => _List(scroll: _scroll, state: state, handler: handler, onRefresh: notifier.refresh),
      },
    );
  }
}

class _List extends StatelessWidget {
  const _List({
    required this.scroll,
    required this.state,
    required this.handler,
    required this.onRefresh,
  });
  final ScrollController scroll;
  final NotificationsState state;
  final NotificationActionHandler handler;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    final count = state.items.length;
    return RefreshIndicator(
      color: context.ds.signal,
      backgroundColor: context.ds.card,
      onRefresh: onRefresh,
      child: Semantics(
        liveRegion: true,
        label: '$count notificações',
        child: CustomScrollView(
          controller: scroll,
          physics: const AlwaysScrollableScrollPhysics(),
          slivers: [
            if (state.partial) const SliverToBoxAdapter(child: _PartialBanner()),
            SliverList.separated(
              itemCount: count,
              separatorBuilder: (_, __) => Divider(height: 1, thickness: 0.6, color: context.ds.divider),
              itemBuilder: (_, i) => _NotificationRow(item: state.items[i], handler: handler),
            ),
            if (state.phase == NotifPhase.loadingMore)
              const SliverToBoxAdapter(
                child: Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator())),
              ),
          ],
        ),
      ),
    );
  }
}

/// The APPROVED row — same visual structure; icon/color now come from the
/// Gateway DTO instead of a client-side enum switch.
class _NotificationRow extends StatelessWidget {
  const _NotificationRow({required this.item, required this.handler});
  final NotificationItem item;
  final NotificationActionHandler handler;

  @override
  Widget build(BuildContext context) {
    final accent = notificationColor(item.color, fallback: context.ds.signal);
    final tappable = handler.canOpen(item);
    return InkWell(
      // Never open a can_open==false item — tappable only when the Gateway
      // granted an action.
      onTap: tappable ? () => handler.handleOpen(item) : null,
      child: Container(
        color: item.read ? null : context.ds.signalMuted.withValues(alpha: 0.35),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                color: accent.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Icon(notificationIcon(item.icon), size: 18, color: accent),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          item.title,
                          style: context.tt.titleMedium?.copyWith(
                            fontWeight: item.read ? FontWeight.w500 : FontWeight.w700,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(relativeTime(item.createdAt),
                          style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
                    ],
                  ),
                  if (item.body.isNotEmpty) ...[
                    const SizedBox(height: 2),
                    Text(item.body, style: context.tt.bodyMedium?.copyWith(color: context.ds.textMid)),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PartialBanner extends StatelessWidget {
  const _PartialBanner();
  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: context.ds.subtle,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: InsightSpacing.sm),
      child: Text('O contador pode estar momentaneamente incompleto.',
          style: context.tt.labelSmall?.copyWith(color: context.ds.textLow)),
    );
  }
}
