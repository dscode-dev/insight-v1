import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Insight typography tokens.
///
/// We name styles by *role*, not by Material's display/headline/body
/// hierarchy, because the design system is read-time-oriented (feed,
/// match context) rather than display-heavy. The Material TextTheme is
/// built underneath so platform widgets that consume `textTheme.bodyLarge`
/// still get sensible defaults.
class InsightTypography {
  const InsightTypography._();

  // Roles
  static TextStyle get display => GoogleFonts.inter(
        fontSize: 28,
        height: 34 / 28,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.2,
      );

  static TextStyle get title => GoogleFonts.inter(
        fontSize: 20,
        height: 26 / 20,
        fontWeight: FontWeight.w600,
        letterSpacing: -0.1,
      );

  static TextStyle get headline => GoogleFonts.inter(
        fontSize: 16,
        height: 22 / 16,
        fontWeight: FontWeight.w600,
      );

  static TextStyle get body => GoogleFonts.inter(
        fontSize: 15,
        height: 22 / 15,
        fontWeight: FontWeight.w400,
      );

  static TextStyle get bodyMedium => GoogleFonts.inter(
        fontSize: 15,
        height: 22 / 15,
        fontWeight: FontWeight.w500,
      );

  static TextStyle get caption => GoogleFonts.inter(
        fontSize: 13,
        height: 18 / 13,
        fontWeight: FontWeight.w400,
      );

  static TextStyle get micro => GoogleFonts.inter(
        fontSize: 11,
        height: 14 / 11,
        fontWeight: FontWeight.w500,
        letterSpacing: 0.4,
      );

  /// Tabular figures for scores, percentages, odds.
  static TextStyle withTabular(TextStyle base) => base.copyWith(
        fontFeatures: const [FontFeature.tabularFigures()],
      );

  /// Builds a Material TextTheme from the role tokens. Used by `theme.dart`.
  static TextTheme toTextTheme({required Color textHigh, required Color textMid}) {
    return TextTheme(
      displayLarge: display.copyWith(color: textHigh),
      headlineMedium: title.copyWith(color: textHigh),
      titleLarge: title.copyWith(color: textHigh),
      titleMedium: headline.copyWith(color: textHigh),
      bodyLarge: body.copyWith(color: textHigh),
      bodyMedium: body.copyWith(color: textHigh),
      bodySmall: caption.copyWith(color: textMid),
      labelSmall: micro.copyWith(color: textMid),
    );
  }
}
