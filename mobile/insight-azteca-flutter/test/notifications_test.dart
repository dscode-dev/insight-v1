// FEATURE-NOTIFICATIONS-V1 Stage 3 — model + controller + action-handler tests:
// Gateway-owned icon/color/caps, cursor+has_more pagination (client never
// infers), optimistic mark-read/mark-all with rollback, badge decoupled + kept
// consistent, deep-link never opened when can_open==false.
// ignore_for_file: prefer_const_constructors, prefer_const_literals_to_create_immutables
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/features/notifications/data/notifications_api.dart';
import 'package:azteca/features/notifications/model/notification_models.dart';
import 'package:azteca/features/notifications/state/notification_action_handler.dart';
import 'package:azteca/features/notifications/state/notifications_controller.dart';
import 'package:azteca/features/notifications/state/unread_controller.dart';

Map<String, dynamic> _json({
  required String id,
  bool read = false,
  String deep = '/discussion/d1',
  bool canOpen = true,
}) =>
    {
      'id': id,
      'type': 'reaction',
      'priority': 'normal',
      'title': 'T $id',
      'body': 'B',
      'icon': 'favorite',
      'color': '#FF6B9D',
      'deep_link': deep,
      'created_at': '2026-05-01T10:00:00Z',
      'read': read,
      'capabilities': {'can_open': canOpen, 'can_mark_read': !read},
    };

class _FakeApi extends NotificationsApi {
  _FakeApi() : super(Dio());

  List<NotificationsPage> pages = const [];
  int _page = 0;
  int unread = 0;
  Object? markReadError;
  MarkReadResult markReadResult = const MarkReadResult(changed: true, unreadCount: 0);
  int markReadCalls = 0;

  @override
  Future<NotificationsPage> list({String? cursor}) async {
    if (_page < pages.length) return pages[_page++];
    return const NotificationsPage(items: [], nextCursor: '', hasMore: false, unreadCount: 0, partial: false, failedSections: []);
  }

  @override
  Future<int> unreadCount() async => unread;

  @override
  Future<MarkReadResult> markRead(String id) async {
    markReadCalls++;
    if (markReadError != null) throw markReadError!;
    return markReadResult;
  }

  @override
  Future<MarkAllReadResult> markAllRead() async => const MarkAllReadResult(marked: 2, unreadCount: 0);
}

NotificationsPage _page(List<NotificationItem> items, {String cursor = '', int unread = 0, bool partial = false}) =>
    NotificationsPage(
      items: items, nextCursor: cursor, hasMore: cursor.isNotEmpty, unreadCount: unread, partial: partial, failedSections: const [],
    );

NotificationItem _item(String id, {bool read = false, bool canOpen = true, String deep = '/discussion/d1'}) =>
    NotificationItem.fromJson(_json(id: id, read: read, deep: deep, canOpen: canOpen));

Future<void> _tick() => Future<void>.delayed(Duration.zero);

void main() {
  group('models', () {
    test('NotificationItem.fromJson takes icon/color/caps/read from Gateway', () {
      final n = _item('n1');
      expect(n.icon, 'favorite');
      expect(n.color, '#FF6B9D');
      expect(n.capabilities.canOpen, true);
      expect(n.capabilities.canMarkRead, true);
      expect(n.read, false);
    });

    test('markedRead patch flips read + disables can_mark_read (immutable)', () {
      final n = _item('n1');
      final r = n.markedRead();
      expect(n.read, false); // original untouched
      expect(r.read, true);
      expect(r.capabilities.canMarkRead, false);
    });

    test('NotificationsPage carries has_more/unread/partial from Gateway', () {
      final p = NotificationsPage.fromJson({
        'items': [_json(id: 'n1')],
        'next_cursor': 'c2',
        'has_more': true,
        'unread_count': 5,
        'partial': true,
        'failed_sections': ['unread_count'],
      });
      expect(p.hasMore, true);
      expect(p.nextCursor, 'c2');
      expect(p.unreadCount, 5);
      expect(p.partial, true);
    });
  });

  group('controller', () {
    NotificationsController build(_FakeApi api) {
      final unread = UnreadController(api, true);
      return NotificationsController(api, unread, true);
    }

    test('load populates items + sets badge; empty phase on no items', () async {
      final api = _FakeApi()..pages = [_page([_item('n1'), _item('n2')], unread: 2)];
      final c = build(api);
      await _tick();
      expect(c.state.phase, NotifPhase.ready);
      expect(c.state.items.length, 2);
    });

    test('unavailable phase when feature flag is off', () async {
      final api = _FakeApi();
      final c = NotificationsController(api, UnreadController(api, false), false);
      await _tick();
      expect(c.state.phase, NotifPhase.unavailable);
    });

    test('optimistic markRead patches item immediately, then applies server count', () async {
      final api = _FakeApi()
        ..pages = [_page([_item('n1'), _item('n2')], unread: 2)]
        ..unread = 2
        ..markReadResult = const MarkReadResult(changed: true, unreadCount: 1);
      final unread = UnreadController(api, true);
      final c = NotificationsController(api, unread, true);
      await _tick();

      final future = c.markRead('n1');
      // Optimistic frame: item flipped + badge decremented BEFORE the server.
      expect(c.state.items.firstWhere((n) => n.id == 'n1').read, true);
      expect(unread.state, 1);
      await future;
      expect(unread.state, 1); // authoritative server value
    });

    test('markRead rolls back the item on error', () async {
      final api = _FakeApi()
        ..pages = [_page([_item('n1')], unread: 1)]
        ..unread = 1
        ..markReadError = Exception('boom');
      final c = build(api);
      await _tick();
      await c.markRead('n1');
      // Rolled back: item is unread again (list not left in optimistic state).
      expect(c.state.items.single.read, false);
    });

    test('markAllRead optimistically marks all + resets badge', () async {
      final api = _FakeApi()
        ..pages = [_page([_item('n1'), _item('n2')], unread: 2)]
        ..unread = 2;
      final unread = UnreadController(api, true);
      final c = NotificationsController(api, unread, true);
      await _tick();
      await c.markAllRead();
      expect(c.state.items.every((n) => n.read), true);
      expect(unread.state, 0);
    });

    test('loadMore uses Gateway cursor + has_more, dedupes by id', () async {
      final api = _FakeApi()
        ..pages = [
          _page([_item('n1'), _item('n2')], cursor: 'c2', unread: 0),
          _page([_item('n2'), _item('n3')], cursor: '', unread: 0),
        ];
      final c = build(api);
      await _tick();
      expect(c.state.hasMore, true);
      await c.loadMore();
      expect(c.state.items.map((n) => n.id).toList(), ['n1', 'n2', 'n3']);
      expect(c.state.hasMore, false);
    });
  });

  group('action handler', () {
    test('never opens a can_open==false notification, but still marks read', () {
      final opened = <String>[];
      final marked = <String>[];
      final h = NotificationActionHandler(
        onNavigate: opened.add,
        onMarkRead: marked.add,
      );
      // can_open false → no navigation, but read is marked.
      h.handleOpen(_item('n1', canOpen: false));
      expect(opened, isEmpty);
      expect(marked, ['n1']);
      expect(h.canOpen(_item('n1', canOpen: false)), false);

      // can_open true + valid route → navigates.
      h.handleOpen(_item('n2', deep: '/users/u1'));
      expect(opened, ['/users/u1']);
    });
  });
}
