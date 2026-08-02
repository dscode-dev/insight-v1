/// Icon sizing tokens.
///
/// Material's default `IconTheme.of(context).size` is too coarse for
/// the dense social-feed layouts here — different surfaces need
/// different anchor sizes. Keep them named so the call sites read
/// intentionally instead of sprinkling magic numbers.
class InsightIconSize {
  const InsightIconSize._();

  /// Inline glyph beside body copy (intelligence pills, status dots
  /// next to text). 14dp keeps it the visual weight of an emoji.
  static const double inline = 14;

  /// Bottom-nav + AppBar action icons. 22dp reads slightly smaller
  /// than Material's 24 default, which makes the floating glass nav
  /// feel less utilitarian.
  static const double nav = 22;

  /// Compose FAB glyph + post action buttons. 18dp paired with the
  /// label keeps the pill compact.
  static const double action = 18;

  /// Big standalone glyphs — empty-state illustrations, sponsored
  /// badge icon. Used sparingly.
  static const double feature = 28;
}
