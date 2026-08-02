// Club badge — Sprint 2 (Part 7).
//
// Resolution order:
//   1. local asset map (assets/badges/<slug>.png) — ships with the app
//   2. remote CDN image (when a badgeUrl is provided), memory-cached
//      by Flutter's image cache
//   3. initials-on-crest-color fallback — ALWAYS available, so a
//      failed image can never break the layout
//
// Usage discipline (product rule): live matches, radar, match headers
// and selected trend posts only. Never as decoration everywhere.

import 'package:flutter/material.dart';

import '../clubs/club_registry.dart';
import '../shared/extensions/build_context_x.dart';

class ClubBadge extends StatelessWidget {
  const ClubBadge({
    super.key,
    required this.short,
    required this.crestColor,
    this.name,
    this.badgeUrl,
    this.size = 22,
  });

  /// Short code ("FLA", "PAL") — the fallback initials + a registry key.
  final String short;

  /// Full club name when available — the strongest registry key
  /// ("Manchester City", "Flamengo"). Resolved before [short].
  final String? name;

  /// Stable crest color hex from the model — fallback background.
  final String crestColor;

  /// Optional remote badge URL (CDN). Null/empty skips to fallback.
  final String? badgeUrl;

  final double size;

  Color get _color {
    final raw = crestColor.replaceFirst('#', '');
    final v = int.tryParse(raw, radix: 16) ?? 0x5BA8FF;
    return Color(0xFF000000 | (v & 0xFFFFFF));
  }

  Widget _fallback(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: _color.withValues(alpha: 0.22),
        shape: BoxShape.circle,
        border: Border.all(color: _color.withValues(alpha: 0.55), width: 1),
      ),
      alignment: Alignment.center,
      child: Text(
        short.isEmpty ? '?' : short.characters.first,
        style: context.tt.labelSmall?.copyWith(
          color: _color,
          fontWeight: FontWeight.w800,
          fontSize: size * 0.45,
          height: 1,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // Registry-first: the canonical club identity ships a BUNDLED crest
    // (assets/clubs/<club_id>.png) — no runtime logo API. We try the
    // full name, then the short code.
    final club = ClubRegistry.instance.lookup(name ?? '') ??
        ClubRegistry.instance.lookup(short);
    if (club != null) {
      return ClipOval(
        child: Image.asset(
          club.logoAsset,
          width: size,
          height: size,
          fit: BoxFit.cover,
          errorBuilder: (ctx, _, __) => _fallback(ctx),
        ),
      );
    }
    return _fallback(context);
  }
}
