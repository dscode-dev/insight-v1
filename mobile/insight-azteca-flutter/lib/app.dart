import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:responsive_framework/responsive_framework.dart';

import 'providers/realtime_provider.dart';
import 'providers/settings_provider.dart';
import 'routing/router.dart';
import 'shared/strings/pt_br.dart';
import 'theme/theme.dart';

/// Root MaterialApp. ProviderScope is mounted in `main.dart` so this
/// widget can `watch` providers safely.
class InsightApp extends ConsumerWidget {
  const InsightApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    final themeMode = ref.watch(themeModeProvider);
    // Mount the realtime coordinator once at app root — its `ref.listen`
    // wiring needs to outlive every screen so feed prepends + match
    // events keep dispatching even when Home is off-screen.
    ref.watch(realtimeCoordinatorProvider);

    return MaterialApp.router(
      title: S.appName,
      debugShowCheckedModeBanner: false,
      routerConfig: router,

      theme: insightTheme(Brightness.light),
      darkTheme: insightTheme(Brightness.dark),
      themeMode: themeMode,

      builder: (context, child) => _DismissKeyboard(
        child: ResponsiveBreakpoints.builder(
          breakpoints: const [
            Breakpoint(start: 0, end: 480, name: MOBILE),
            Breakpoint(start: 481, end: 800, name: TABLET),
            Breakpoint(start: 801, end: 1920, name: DESKTOP),
          ],
          child: child ?? const SizedBox.shrink(),
        ),
      ),
    );
  }
}

/// App-wide keyboard dismissal (Azteca-X Part 5).
///
/// A single translucent tap target at the app root: tapping anywhere that
/// isn't an interactive child unfocuses the active editable, closing the
/// keyboard. `onTap` only fires when no child gesture (button, field, list)
/// claims the tap, so it never steals interactions — no per-screen unfocus
/// hacks. Scroll-to-dismiss + navigation-dismiss are handled at the list /
/// router level (ScrollViewKeyboardDismissBehavior.onDrag + route-change
/// unfocus).
class _DismissKeyboard extends StatelessWidget {
  const _DismissKeyboard({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.translucent,
      excludeFromSemantics: true,
      onTap: () {
        final focus = FocusManager.instance.primaryFocus;
        if (focus != null && focus.hasFocus) focus.unfocus();
      },
      child: child,
    );
  }
}
