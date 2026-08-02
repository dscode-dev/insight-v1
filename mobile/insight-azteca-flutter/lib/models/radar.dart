import 'package:freezed_annotation/freezed_annotation.dart';

import 'match.dart';

part 'radar.freezed.dart';
part 'radar.g.dart';

@freezed
class TrendingMatch with _$TrendingMatch {
  const factory TrendingMatch({
    required MatchSummary summary,
    required String reason,
  }) = _TrendingMatch;

  factory TrendingMatch.fromJson(Map<String, dynamic> json) =>
      _$TrendingMatchFromJson(json);
}

enum MovementDirection {
  @JsonValue('compressing')
  compressing,
  @JsonValue('widening')
  widening,
  @JsonValue('reversal')
  reversal,
}

@freezed
class MarketMovement with _$MarketMovement {
  const factory MarketMovement({
    required String id,
    required String matchId,
    required String matchLabel, // "PAL × FLA"
    required String league,
    required MovementDirection direction,
    required String summary, // "Empate 3.20 → 3.05 em 8 casas"
    required double magnitude, // 0..1
    required DateTime ts,
  }) = _MarketMovement;

  factory MarketMovement.fromJson(Map<String, dynamic> json) =>
      _$MarketMovementFromJson(json);
}

@freezed
class CommunitySignalCard with _$CommunitySignalCard {
  const factory CommunitySignalCard({
    required String id,
    required String authorDisplayName,
    required String authorAccent,
    required String authorInitials,
    required String body,
    required String matchLabel,
    required double confidence,
    required DateTime ts,
  }) = _CommunitySignalCard;

  factory CommunitySignalCard.fromJson(Map<String, dynamic> json) =>
      _$CommunitySignalCardFromJson(json);
}

/// Window of activity considered "recent" for the radar. Drives which
/// movements/signals/trending items the user sees. Chosen on the radar
/// filter bar; the provider passes it down to the service.
enum RadarTimeframe {
  @JsonValue('h1')
  lastHour,
  @JsonValue('today')
  today,
  @JsonValue('d7')
  last7Days,
}

extension RadarTimeframeX on RadarTimeframe {
  String get labelPtBr {
    switch (this) {
      case RadarTimeframe.lastHour:
        return 'Última hora';
      case RadarTimeframe.today:
        return 'Hoje';
      case RadarTimeframe.last7Days:
        return '7 dias';
    }
  }

  Duration get window {
    switch (this) {
      case RadarTimeframe.lastHour:
        return const Duration(hours: 1);
      case RadarTimeframe.today:
        return const Duration(hours: 24);
      case RadarTimeframe.last7Days:
        return const Duration(days: 7);
    }
  }
}

@freezed
class RadarBundle with _$RadarBundle {
  const factory RadarBundle({
    required List<TrendingMatch> trending,
    required List<MarketMovement> movements,
    required List<CommunitySignalCard> signals,
  }) = _RadarBundle;

  factory RadarBundle.fromJson(Map<String, dynamic> json) =>
      _$RadarBundleFromJson(json);
}
