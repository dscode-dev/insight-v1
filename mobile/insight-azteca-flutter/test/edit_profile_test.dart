// AZTECA-PROFILE-B — Edit Profile screen: real form, hydrates authoritative
// value, unsupported fields are NOT fake-enabled inputs, save is dirty-gated.
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/features/profile/edit_profile_screen.dart';
import 'package:azteca/models/auth.dart';
import 'package:azteca/providers/auth_provider.dart';
import 'package:azteca/theme/theme.dart';

class _AuthedAuth extends AuthNotifier {
  @override
  AuthState build() => const AuthState(
        status: AuthStatus.authenticated,
        user: AuthUser(id: 'me', username: 'lucas', displayName: 'Lucas Scout'),
      );
}

Future<void> _pump(WidgetTester tester) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [authProvider.overrideWith(_AuthedAuth.new)],
    child: MaterialApp(
      theme: insightTheme(Brightness.light),
      home: const EditProfileScreen(),
    ),
  ));
  await tester.pump();
}

void main() {
  testWidgets('opens a real edit form (not the avatar picker) hydrated with the current name',
      (tester) async {
    await _pump(tester);
    expect(find.text('Editar perfil'), findsOneWidget);
    // The authoritative display name is hydrated into the editable field.
    expect(find.widgetWithText(TextField, 'Lucas Scout'), findsOneWidget);
    // Username shown read-only (not an editable input).
    expect(find.text('@lucas'), findsOneWidget);
  });

  testWidgets('unsupported fields are shown as deferred, NOT fake-enabled inputs',
      (tester) async {
    await _pump(tester);
    // Exactly ONE editable TextField (display name). Bio/team/location are not inputs.
    expect(find.byType(TextField), findsOneWidget);
    expect(find.text('Bio'), findsOneWidget);
    expect(find.text('Time favorito'), findsOneWidget);
    expect(find.text('Localização'), findsOneWidget);
    expect(find.text('Em breve'), findsWidgets); // deferred markers present
  });

  testWidgets('Save is disabled until the name is dirty', (tester) async {
    await _pump(tester);
    TextButton save() =>
        tester.widget<TextButton>(find.widgetWithText(TextButton, 'Salvar'));
    expect(save().onPressed, isNull); // not dirty → disabled

    await tester.enterText(find.byType(TextField), 'Lucas Tático');
    await tester.pump();
    expect(save().onPressed, isNotNull); // dirty + valid → enabled

    await tester.enterText(find.byType(TextField), '   ');
    await tester.pump();
    expect(save().onPressed, isNull); // empty → disabled again
  });
}
