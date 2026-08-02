import 'package:flutter/material.dart';

import '../../theme/colors.dart';

/// Ergonomic accessors so widgets read theme tokens with a single dot.
///
///   context.ds.signal           // InsightColors.signal
///   context.ds.textHigh
///   context.tt.bodyLarge        // TextTheme.bodyLarge
///   context.scheme.primary
extension BuildContextX on BuildContext {
  /// Insight design-system color tokens.
  InsightColors get ds {
    final ext = Theme.of(this).extension<InsightColors>();
    if (ext == null) {
      throw FlutterError(
        'InsightColors not found in ThemeData.extensions. '
        'Did you forget to apply insightTheme()?',
      );
    }
    return ext;
  }

  TextTheme get tt => Theme.of(this).textTheme;
  ColorScheme get scheme => Theme.of(this).colorScheme;
  Brightness get brightness => Theme.of(this).brightness;
  bool get isDark => brightness == Brightness.dark;

  MediaQueryData get mq => MediaQuery.of(this);
  double get screenWidth => mq.size.width;
  double get screenHeight => mq.size.height;
  EdgeInsets get safePadding => mq.padding;
}
