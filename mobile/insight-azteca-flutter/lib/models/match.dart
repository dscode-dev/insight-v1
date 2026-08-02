import 'package:freezed_annotation/freezed_annotation.dart';

part 'match.freezed.dart';
part 'match.g.dart';

enum MatchState {
  @JsonValue('scheduled')
  scheduled,
  @JsonValue('live')
  live,
  @JsonValue('halftime')
  halftime,
  @JsonValue('finished')
  finished,
}

extension MatchStateX on MatchState {
  bool get isLive => this == MatchState.live || this == MatchState.halftime;
}

@freezed
class MatchScore with _$MatchScore {
  const factory MatchScore({required int home, required int away}) = _MatchScore;
  factory MatchScore.fromJson(Map<String, dynamic> json) =>
      _$MatchScoreFromJson(json);
}

@freezed
class MatchTeam with _$MatchTeam {
  const factory MatchTeam({
    required String short,
    required String name,
    required String crestColor,
  }) = _MatchTeam;

  factory MatchTeam.fromJson(Map<String, dynamic> json) =>
      _$MatchTeamFromJson(json);
}

@freezed
class MatchStatus with _$MatchStatus {
  const factory MatchStatus({
    required MatchState state,
    int? minute,
    String? period,
    MatchScore? score,
    required DateTime kickoff,
  }) = _MatchStatus;

  factory MatchStatus.fromJson(Map<String, dynamic> json) =>
      _$MatchStatusFromJson(json);
}

/// Stage 5b `IntelligencePill` — surfaced inside MatchEmbed.
enum IntelligencePillTone {
  @JsonValue('neutral')
  neutral,
  @JsonValue('signal')
  signal,
  @JsonValue('warning')
  warning,
  @JsonValue('success')
  success,
  @JsonValue('danger')
  danger,
}

@freezed
class IntelligencePill with _$IntelligencePill {
  const factory IntelligencePill({
    required String label,
    required IntelligencePillTone tone,
  }) = _IntelligencePill;

  factory IntelligencePill.fromJson(Map<String, dynamic> json) =>
      _$IntelligencePillFromJson(json);
}

/// Light view of a match used by the Live screen + as the carrier
/// inside FeedPost.match.
@freezed
class MatchSummary with _$MatchSummary {
  const factory MatchSummary({
    required String matchId,
    required String league,
    required MatchTeam home,
    required MatchTeam away,
    required MatchStatus status,
    @Default(<IntelligencePill>[]) List<IntelligencePill> pills,
  }) = _MatchSummary;

  factory MatchSummary.fromJson(Map<String, dynamic> json) =>
      _$MatchSummaryFromJson(json);
}
