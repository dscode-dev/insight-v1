/// A football competition shown in the Home Featured Competitions Rail.
///
/// The source of truth is insight-social (`GET /v1/competitions/highlights`
/// via the Gateway). The backend owns `featured`, `priority` and
/// `display_order` — the client NEVER decides ordering or emphasis. Unknown
/// fields in the payload are ignored, so the backend model can grow without a
/// breaking change here.
class Competition {
  const Competition({
    required this.id,
    required this.name,
    required this.slug,
    required this.featured,
    required this.priority,
    required this.displayOrder,
    required this.active,
    this.country,
    this.continent,
    this.type,
    this.icon,
  });

  factory Competition.fromJson(Map<String, dynamic> json) {
    int asInt(Object? v, int fallback) =>
        v is int ? v : (v is num ? v.toInt() : (int.tryParse('$v') ?? fallback));
    bool asBool(Object? v, bool fallback) =>
        v is bool ? v : (v == null ? fallback : '$v' == 'true');
    String? asStr(Object? v) {
      if (v == null) return null;
      final s = '$v'.trim();
      return s.isEmpty ? null : s;
    }

    return Competition(
      id: '${json['id'] ?? json['slug'] ?? ''}',
      name: '${json['name'] ?? ''}',
      slug: '${json['slug'] ?? json['id'] ?? ''}',
      country: asStr(json['country']),
      continent: asStr(json['continent']),
      type: asStr(json['type']),
      featured: asBool(json['featured'], false),
      priority: asInt(json['priority'], 100),
      displayOrder: asInt(json['display_order'], 100),
      icon: asStr(json['icon']),
      active: asBool(json['active'], true),
    );
  }

  final String id;
  final String name;
  final String slug;
  final String? country;
  final String? continent;
  final String? type;
  final bool featured;
  final int priority;
  final int displayOrder;
  final String? icon;
  final bool active;
}
