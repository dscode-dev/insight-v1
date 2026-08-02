// Club badge fallback tests — Sprint 2 (Part 7): a failed/missing
// image must NEVER break the UI; initials always render.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/widgets/club_badge.dart';

Widget _host(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  testWidgets('renders initials fallback when no badge source exists',
      (tester) async {
    await tester.pumpWidget(_host(
      const ClubBadge(short: 'FLA', crestColor: '#E52B2B'),
    ));
    expect(find.text('F'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('empty short still renders a placeholder, never crashes',
      (tester) async {
    await tester.pumpWidget(_host(
      const ClubBadge(short: '', crestColor: 'not-a-color'),
    ));
    expect(find.text('?'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('broken network badge falls back to initials',
      (tester) async {
    await tester.pumpWidget(_host(
      const ClubBadge(
        short: 'PAL',
        crestColor: '#1B9E4B',
        badgeUrl: 'http://invalid.local/badge.png',
      ),
    ));
    // Image.network fails in widget tests (no HTTP) → errorBuilder.
    await tester.pump();
    expect(find.text('P'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
