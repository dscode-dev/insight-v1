// MatchContextResponse — Sprint 6.2 Part 4.
//
// Wire shape of `GET /v1/context/match/{id}` (Gateway → Atlas). Atlas
// returns DESCRIPTIVE context — never predictive bets. Every section is
// optional because Atlas may not have inference for a match (no quorum
// of sources, family paused, etc.). The UI renders an EmptyState when
// the response is fully empty rather than fabricating data.
//
// Distinct from `match_context.dart` which holds the local UI model for
// the dashboard-card reading; this file is the raw Gateway DTO.
//
// JSON example:
// {
//   "summary": "Equilíbrio ofensivo nas últimas 4 atuações.",
//   "signals": [
//     { "label": "Pressão visitante", "body": "…", "confidence": 0.62 }
//   ],
//   "tendencies": [
//     { "label": "Casa em casa", "value": "5V · 2E · 1D" }
//   ],
//   "community": { "active_users": 132, "leaning": "balanced" }
// }

class MatchContextResponse {
  const MatchContextResponse({
    this.summary,
    this.signals = const [],
    this.tendencies = const [],
    this.community,
  });

  factory MatchContextResponse.fromJson(Map<String, dynamic> json) {
    return MatchContextResponse(
      summary: json['summary'] as String?,
      signals: (json['signals'] as List? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(MatchContextSignal.fromJson)
          .toList(growable: false),
      tendencies: (json['tendencies'] as List? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(MatchContextTendency.fromJson)
          .toList(growable: false),
      community: json['community'] is Map<String, dynamic>
          ? MatchContextCommunity.fromJson(
              json['community'] as Map<String, dynamic>,
            )
          : null,
    );
  }

  final String? summary;
  final List<MatchContextSignal> signals;
  final List<MatchContextTendency> tendencies;
  final MatchContextCommunity? community;

  bool get isEmpty =>
      (summary == null || summary!.isEmpty) &&
      signals.isEmpty &&
      tendencies.isEmpty &&
      community == null;
}

class MatchContextSignal {
  const MatchContextSignal({
    required this.label,
    required this.body,
    this.confidence,
  });

  factory MatchContextSignal.fromJson(Map<String, dynamic> j) {
    return MatchContextSignal(
      label: (j['label'] ?? '').toString(),
      body: (j['body'] ?? '').toString(),
      confidence: (j['confidence'] as num?)?.toDouble(),
    );
  }

  final String label;
  final String body;
  final double? confidence;
}

class MatchContextTendency {
  const MatchContextTendency({required this.label, required this.value});

  factory MatchContextTendency.fromJson(Map<String, dynamic> j) {
    return MatchContextTendency(
      label: (j['label'] ?? '').toString(),
      value: (j['value'] ?? '').toString(),
    );
  }

  final String label;
  final String value;
}

class MatchContextCommunity {
  const MatchContextCommunity({this.activeUsers = 0, this.leaning = 'balanced'});

  factory MatchContextCommunity.fromJson(Map<String, dynamic> j) {
    return MatchContextCommunity(
      activeUsers: (j['active_users'] as num?)?.toInt() ?? 0,
      leaning: (j['leaning'] ?? 'balanced').toString(),
    );
  }

  final int activeUsers;
  final String leaning;
}
