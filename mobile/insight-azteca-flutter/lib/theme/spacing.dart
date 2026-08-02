/// 4-base spacing scale.
///
/// Use these constants instead of magic numbers. Layouts that mix the
/// scale (8, 12, 16) read consistently across screens.
class InsightSpacing {
  const InsightSpacing._();

  static const double xs2 = 2;
  static const double xs = 4;
  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 20;
  static const double xl2 = 24;
  static const double xl3 = 32;
  static const double xl4 = 40;
  static const double xl5 = 56;

  /// Standard horizontal page padding (feed items, screen content).
  static const double pageHorizontal = xl;

  /// Standard vertical padding inside a feed item.
  static const double feedItemVertical = lg;
}
