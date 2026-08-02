import 'package:flutter/material.dart';

import 'colors.dart';
import 'radii.dart';
import 'typography.dart';

/// Composes the InsightColors extension into a full Material 3 ThemeData.
///
/// Widgets pull tokens via `context.ds` (see shared/extensions). This file
/// is the only place that knows about Material's ColorScheme / ThemeData
/// types — everything else stays inside our design system vocabulary.
ThemeData insightTheme(Brightness brightness) {
  final c = brightness == Brightness.light ? InsightColors.light : InsightColors.dark;

  final scheme = ColorScheme(
    brightness: brightness,
    primary: c.signal,
    onPrimary: brightness == Brightness.light ? Colors.white : Colors.black,
    secondary: c.signal,
    onSecondary: Colors.white,
    error: c.confidenceLow,
    onError: Colors.white,
    surface: c.card,
    onSurface: c.textHigh,
    surfaceContainerLowest: c.background,
    surfaceContainerLow: c.background,
    surfaceContainer: c.card,
    surfaceContainerHigh: c.subtle,
    surfaceContainerHighest: c.subtle,
    outline: c.divider,
    outlineVariant: c.divider,
  );

  final textTheme = InsightTypography.toTextTheme(
    textHigh: c.textHigh,
    textMid: c.textMid,
  );

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: c.background,
    textTheme: textTheme,
    extensions: <ThemeExtension<dynamic>>[c],
    splashFactory: InkSparkle.splashFactory,

    // Motion layer (Azteca-Y Part 6): one subtle, native-feeling page
    // transition across the app. Flutter reduces these automatically when the
    // OS "reduce motion" accessibility setting is on (MediaQuery.disableAnimations),
    // so no manual reduced-motion handling is needed here.
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {
        TargetPlatform.iOS: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.macOS: FadeForwardsPageTransitionsBuilder(),
        TargetPlatform.android: FadeForwardsPageTransitionsBuilder(),
      },
    ),

    appBarTheme: AppBarTheme(
      backgroundColor: c.background,
      foregroundColor: c.textHigh,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: InsightTypography.title.copyWith(color: c.textHigh),
    ),

    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: c.background,
      indicatorColor: c.signalMuted,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      height: 64,
      labelTextStyle: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.selected)) {
          return InsightTypography.micro.copyWith(color: c.signal);
        }
        return InsightTypography.micro.copyWith(color: c.textLow);
      }),
      iconTheme: WidgetStateProperty.resolveWith((states) {
        if (states.contains(WidgetState.selected)) {
          return IconThemeData(color: c.signal, size: 22);
        }
        return IconThemeData(color: c.textLow, size: 22);
      }),
    ),

    cardTheme: CardThemeData(
      color: c.card,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: const RoundedRectangleBorder(borderRadius: InsightRadii.brLg),
    ),

    dividerTheme: DividerThemeData(
      color: c.divider,
      space: 1,
      thickness: 0.6,
    ),

    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: c.card,
      surfaceTintColor: Colors.transparent,
      modalBackgroundColor: c.card,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: InsightRadii.rXl),
      ),
      showDragHandle: true,
    ),

    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: c.signal,
        foregroundColor: Colors.white,
        minimumSize: const Size(0, 48),
        shape: const RoundedRectangleBorder(borderRadius: InsightRadii.brMd),
        textStyle: InsightTypography.bodyMedium,
      ),
    ),

    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: c.signal,
        minimumSize: const Size(0, 44),
        textStyle: InsightTypography.bodyMedium,
      ),
    ),

    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: c.subtle,
      hintStyle: InsightTypography.body.copyWith(color: c.textLow),
      contentPadding:
          const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      border: const OutlineInputBorder(
        borderRadius: InsightRadii.brMd,
        borderSide: BorderSide.none,
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: InsightRadii.brMd,
        borderSide: BorderSide(color: c.signal, width: 1.2),
      ),
    ),
  );
}
