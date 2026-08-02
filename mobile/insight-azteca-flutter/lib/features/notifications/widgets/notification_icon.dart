// FEATURE-NOTIFICATIONS-V1 Stage 3 — resolve the Gateway-owned icon NAME + hex
// color to concrete Flutter values. The Gateway decides WHICH icon/color a type
// gets; the client only renders. Unknown names fall back to a neutral bell.
import 'package:flutter/material.dart';

const _iconByName = <String, IconData>{
  'person_add': Icons.person_add_alt_1_rounded,
  'reply': Icons.reply_rounded,
  'alternate_email': Icons.alternate_email_rounded,
  'favorite': Icons.favorite_rounded,
  'campaign': Icons.campaign_rounded,
  'notifications': Icons.notifications_rounded,
};

IconData notificationIcon(String name) => _iconByName[name] ?? Icons.notifications_rounded;

Color notificationColor(String hex, {Color fallback = const Color(0xFF5BA8FF)}) {
  var h = hex.replaceFirst('#', '').trim();
  if (h.length == 6) h = 'FF$h';
  final v = int.tryParse(h, radix: 16);
  return v == null ? fallback : Color(v);
}
