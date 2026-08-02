// Launch-flow tests — Sprint 2 (Parts 1 + 15).
//
// The production rule under test:
//   fresh signed-out install → Splash → Login
//   first authenticated run  → Splash → Onboarding
//   onboarded authenticated → Splash → Home

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/app.dart';
import 'package:azteca/features/auth/screens/auth_entry_screen.dart';
import 'package:azteca/features/onboarding/onboarding_screens.dart';
import 'package:azteca/models/auth.dart';
import 'package:azteca/providers/auth_provider.dart';
import 'package:azteca/providers/onboarding_provider.dart';
import 'package:azteca/widgets/fixed_bottom_nav.dart';

class _AnonymousAuth extends AuthNotifier {
  @override
  AuthState build() => const AuthState(status: AuthStatus.anonymous);
}

class _AuthenticatedAuth extends AuthNotifier {
  @override
  AuthState build() => const AuthState(
        status: AuthStatus.authenticated,
        user: AuthUser(id: 'me', username: 'me', displayName: 'Você'),
      );
}

Future<void> _pumpApp(
  WidgetTester tester, {
  required bool onboarded,
  required bool authenticated,
}) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [
      onboardingStatusProvider.overrideWith((ref) async => onboarded),
      authProvider.overrideWith(
        authenticated ? _AuthenticatedAuth.new : _AnonymousAuth.new,
      ),
    ],
    child: const InsightApp(),
  ));
  // Drain redirect + async providers. pumpAndSettle is unusable here
  // (infinite shimmer/pulse animations).
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  testWidgets('fresh signed-out install lands on login, never Home',
      (tester) async {
    await _pumpApp(tester, onboarded: false, authenticated: false);

    expect(find.byType(AuthEntryScreen), findsOneWidget,
        reason: 'onboarding is post-login, not a generic startup intro');
    expect(find.byType(FixedBottomNav), findsNothing,
        reason: 'a fresh install must NEVER jump straight to Home');
  });

  testWidgets('onboarded but signed-out user lands on login', (tester) async {
    await _pumpApp(tester, onboarded: true, authenticated: false);

    // Auth landing is the Auth Entry screen (Azteca-Y.5); "Continuar com
    // telefone" leads into the Gateway phone-verification flow.
    expect(find.byType(AuthEntryScreen), findsOneWidget);
    expect(find.byType(FixedBottomNav), findsNothing);
  });

  testWidgets('first authenticated run lands on onboarding', (tester) async {
    await _pumpApp(tester, onboarded: false, authenticated: true);

    expect(find.byType(OnboardingWelcomeScreen), findsOneWidget);
    expect(find.byType(FixedBottomNav), findsNothing);
    expect(find.byType(AuthEntryScreen), findsNothing);
  });

  testWidgets('authenticated user goes straight to Home', (tester) async {
    await _pumpApp(tester, onboarded: true, authenticated: true);

    expect(find.byType(FixedBottomNav), findsOneWidget);
    expect(find.byType(OnboardingWelcomeScreen), findsNothing);
    expect(find.byType(AuthEntryScreen), findsNothing);
  });
}
