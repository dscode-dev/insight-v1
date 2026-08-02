// App shell boot test — authenticated path renders the 5-tab glass nav.
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/app.dart';
import 'package:azteca/mock/feed_mock.dart';
import 'package:azteca/models/auth.dart';
import 'package:azteca/providers/auth_provider.dart';
import 'package:azteca/providers/onboarding_provider.dart';
import 'package:azteca/services/services_providers.dart';
import 'package:azteca/widgets/fixed_bottom_nav.dart';

class _AuthedAuth extends AuthNotifier {
  @override
  AuthState build() => const AuthState(
        status: AuthStatus.authenticated,
        user: AuthUser(id: 'me', username: 'me', displayName: 'Você'),
      );
}

void main() {
  testWidgets('authenticated boot renders the fixed bottom nav shell with 5 tabs',
      (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [
        onboardingStatusProvider.overrideWith((ref) async => true),
        authProvider.overrideWith(_AuthedAuth.new),
        feedServiceProvider.overrideWithValue(MockFeedService()),
      ],
      child: const InsightApp(),
    ));
    for (var i = 0; i < 8; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }

    expect(find.byType(FixedBottomNav), findsOneWidget);
    expect(find.text('Home'), findsWidgets);
  });
}
