// Screenshot harness for the Splash + FloatingBottomNav UI task.
// Run: flutter test test/ui_screenshots --update-goldens
// Goldens land in test/ui_screenshots/goldens/ — used as before/after
// evidence, not as regression gates (real devices add fonts/blur).

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/features/splash/splash_screen.dart';
import 'package:azteca/theme/colors.dart';
import 'package:azteca/widgets/floating_bottom_nav.dart';

const _devices = <String, (Size, double)>{
  'iphone': (Size(390, 844), 3),
  'iphone-pro-max': (Size(430, 932), 3),
  'ipad-11': (Size(834, 1194), 2),
  'ipad-13': (Size(1024, 1366), 2),
};

const _tag = String.fromEnvironment('SHOT_TAG', defaultValue: 'after');

List<FloatingNavDestination> _destinations() => const [
      FloatingNavDestination(
          icon: Icons.home_outlined, activeIcon: Icons.home, label: 'Home'),
      FloatingNavDestination(
          icon: Icons.sensors_outlined, activeIcon: Icons.sensors, label: 'Ao vivo'),
      FloatingNavDestination(
          icon: Icons.radar_outlined, activeIcon: Icons.radar, label: 'Radar'),
      FloatingNavDestination(
          icon: Icons.search_outlined, activeIcon: Icons.search, label: 'Explorar'),
      FloatingNavDestination(
          icon: Icons.person_outline, activeIcon: Icons.person, label: 'Perfil'),
    ];

Future<void> _pumpAt(WidgetTester tester, Size size, double dpr, Widget child) async {
  tester.view.physicalSize = size * dpr;
  tester.view.devicePixelRatio = dpr;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(child);
  // Decode any Image.asset for real (goldens render blank otherwise).
  await tester.runAsync(() async {
    for (final e in find.byType(Image).evaluate()) {
      final img = e.widget as Image;
      await precacheImage(img.image, e);
    }
  });
  // Settle entry animations without pumpAndSettle (loader loops forever).
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

// insightTheme() pulls GoogleFonts (network — unavailable in tests).
// The nav only needs the InsightColors extension for `context.ds`.
ThemeData _testTheme() => ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      extensions: const <ThemeExtension<dynamic>>[InsightColors.dark],
    );

void main() {
  for (final entry in _devices.entries) {
    final (size, dpr) = entry.value;

    testWidgets('splash — ${entry.key}', (tester) async {
      await _pumpAt(
        tester,
        size,
        dpr,
        MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: _testTheme(),
          home: const SplashScreen(),
        ),
      );
      await expectLater(
        find.byType(MaterialApp),
        matchesGoldenFile('goldens/$_tag/splash-${entry.key}.png'),
      );
    });

    testWidgets('bottom nav — ${entry.key}', (tester) async {
      await _pumpAt(
        tester,
        size,
        dpr,
        ProviderScope(
          child: MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: _testTheme(),
            home: Scaffold(
              // Busy backdrop so glass/blur reads in the capture.
              body: Stack(
                children: [
                  Positioned.fill(
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                          colors: [
                            const Color(0xFF101A33),
                            const Color(0xFF0A0E1A),
                            Colors.blueAccent.withValues(alpha: 0.35),
                          ],
                        ),
                      ),
                    ),
                  ),
                  Align(
                    alignment: Alignment.bottomCenter,
                    child: FloatingBottomNav(
                      destinations: _destinations(),
                      currentIndex: 0,
                      onSelect: (_) {},
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
      await expectLater(
        find.byType(MaterialApp),
        matchesGoldenFile('goldens/$_tag/nav-${entry.key}.png'),
      );
    });
  }
}
