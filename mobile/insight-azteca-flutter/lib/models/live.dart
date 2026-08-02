import 'package:freezed_annotation/freezed_annotation.dart';

import 'match.dart';

part 'live.freezed.dart';
part 'live.g.dart';

/// Filter for the Live screen — competition + status combo.
@freezed
class LiveFilter with _$LiveFilter {
  const factory LiveFilter({
    String? competitionId,
    @Default(LiveStatusFilter.all) LiveStatusFilter status,
  }) = _LiveFilter;

  factory LiveFilter.fromJson(Map<String, dynamic> json) =>
      _$LiveFilterFromJson(json);
}

enum LiveStatusFilter {
  @JsonValue('all')
  all,
  @JsonValue('live')
  live,
  @JsonValue('today')
  today,
  @JsonValue('upcoming')
  upcoming,
}

extension LiveStatusFilterX on LiveStatusFilter {
  String get labelPtBr {
    switch (this) {
      case LiveStatusFilter.all:
        return 'Tudo';
      case LiveStatusFilter.live:
        return 'Ao vivo';
      case LiveStatusFilter.today:
        return 'Hoje';
      case LiveStatusFilter.upcoming:
        return 'Em breve';
    }
  }
}

/// Live match enriched with momentum + pressure for the Live row.
@freezed
class LiveMatch with _$LiveMatch {
  const factory LiveMatch({
    required MatchSummary summary,
    /// -1..1 — negative favours away, positive favours home.
    required double momentum,
    /// 0..1 — current pressure intensity (composite).
    required double pressure,
  }) = _LiveMatch;

  factory LiveMatch.fromJson(Map<String, dynamic> json) =>
      _$LiveMatchFromJson(json);
}

/// Single timeline point for a match — used by sparkline charts.
@freezed
class TimelinePoint with _$TimelinePoint {
  const factory TimelinePoint({
    required DateTime ts,
    required double value,
  }) = _TimelinePoint;

  factory TimelinePoint.fromJson(Map<String, dynamic> json) =>
      _$TimelinePointFromJson(json);
}

/// Per-selection odds tick — 1 / X / 2 at a given timestamp.
@freezed
class OddsPoint with _$OddsPoint {
  const factory OddsPoint({
    required DateTime ts,
    required double home,
    required double draw,
    required double away,
  }) = _OddsPoint;

  factory OddsPoint.fromJson(Map<String, dynamic> json) =>
      _$OddsPointFromJson(json);
}

/// Lightweight signal entry as shown inside the Match Detail "Signals"
/// list. Distinct from FeedPost — this is the per-match read.
@freezed
class MatchSignal with _$MatchSignal {
  const factory MatchSignal({
    required String id,
    required String source, // model | expert | community
    required String label,
    required String body,
    required DateTime ts,
  }) = _MatchSignal;

  factory MatchSignal.fromJson(Map<String, dynamic> json) =>
      _$MatchSignalFromJson(json);
}

@freezed
class MatchDetail with _$MatchDetail {
  const factory MatchDetail({
    required MatchSummary summary,
    @Default(<OddsPoint>[]) List<OddsPoint> oddsTimeline,
    @Default(<TimelinePoint>[]) List<TimelinePoint> pressureTimeline,
    @Default(<MatchSignal>[]) List<MatchSignal> signals,
  }) = _MatchDetail;

  factory MatchDetail.fromJson(Map<String, dynamic> json) =>
      _$MatchDetailFromJson(json);
}
