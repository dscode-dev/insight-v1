import 'package:flutter/material.dart';

import '../core/logger.dart';
import '../shared/extensions/build_context_x.dart';

/// Circular avatar.
///
/// Sprint C: when `avatarUrl` is non-null and non-empty we render the
/// network image with a tasteful loading placeholder + automatic
/// fall-back to the initials rendering on load errors.
///
/// Deterministic colour comes from the author — we never auto-generate
/// from the name so the design stays stable across renders.
class InsightAvatar extends StatelessWidget {
  const InsightAvatar({
    super.key,
    required this.initials,
    required this.colorHex,
    this.size = 40,
    this.avatarUrl,
  });

  final String initials;
  final String colorHex;
  final double size;

  /// Sprint C — full URL of the uploaded avatar. Null/empty falls
  /// back to the initials rendering.
  final String? avatarUrl;

  Color get _color {
    final raw = colorHex.replaceFirst('#', '');
    final v = int.tryParse(raw, radix: 16) ?? 0;
    return Color(0xFF000000 | (v & 0xFFFFFF));
  }

  @override
  Widget build(BuildContext context) {
    final hasNetwork = avatarUrl != null && avatarUrl!.isNotEmpty;
    if (hasNetwork) {
      return ClipOval(
        child: Image.network(
          avatarUrl!,
          width: size,
          height: size,
          fit: BoxFit.cover,
          // Show the initials placeholder while the bytes stream in —
          // avoids the jarring empty circle.
          frameBuilder: (context, child, frame, _) {
            if (frame == null) return _initialsFallback(context);
            return child;
          },
          errorBuilder: (_, error, ___) {
            final uri = Uri.tryParse(avatarUrl!);
            L.w(
              'avatar',
              'avatar.image.failed',
              data: {
                'url_host': uri?.host ?? 'invalid',
                'size': size,
                'reason': error.toString(),
              },
            );
            return _initialsFallback(context);
          },
        ),
      );
    }
    return _initialsFallback(context);
  }

  Widget _initialsFallback(BuildContext context) {
    final fg = ThemeData.estimateBrightnessForColor(_color) == Brightness.light
        ? context.ds.textHigh
        : Colors.white;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(color: _color, shape: BoxShape.circle),
      child: Text(
        initials.toUpperCase(),
        style: TextStyle(
          color: fg,
          fontSize: size * 0.36,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.2,
        ),
      ),
    );
  }
}
