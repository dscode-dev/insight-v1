import 'package:freezed_annotation/freezed_annotation.dart';

part 'match_context.freezed.dart';
part 'match_context.g.dart';

/// Directional cue for a signal line shown inside [MatchContextCard].
/// Drives the icon (arrow) + tonal accent.
enum SignalDirection {
  @JsonValue('up')
  up,
  @JsonValue('down')
  down,
  @JsonValue('neutral')
  neutral,
}

/// One descriptive signal — *not* a number. Examples from the spec:
///   * "Pressão ofensiva" (direction: up)
///   * "Movimento incomum detectado" (direction: neutral)
///
/// We deliberately keep these as short pt-BR clauses rather than KPI
/// chips. The card is a social read of the match, not a stats panel.
@freezed
class MatchContextSignal with _$MatchContextSignal {
  const factory MatchContextSignal({
    required String label,
    @Default(SignalDirection.neutral) SignalDirection direction,
  }) = _MatchContextSignal;

  factory MatchContextSignal.fromJson(Map<String, dynamic> json) =>
      _$MatchContextSignalFromJson(json);
}

/// Composite probability triple for the 1 / X / 2 read.
///
/// Values are 0..1 and SHOULD sum to ~1; the card normalizes display.
/// We do NOT surface this as betting odds — these are community/agent
/// derived reads of "current state of the match", which is why Atlas
/// guarantees descriptive context only (see atlas/api/routes/context.py).
@freezed
class MatchProbabilities with _$MatchProbabilities {
  const factory MatchProbabilities({
    required double home,
    required double draw,
    required double away,
  }) = _MatchProbabilities;

  factory MatchProbabilities.fromJson(Map<String, dynamic> json) =>
      _$MatchProbabilitiesFromJson(json);
}

/// Full payload powering one [MatchContextCard] render. Bundles signals
/// + probabilities + a derived "leading side" hint the card uses to
/// subtly highlight one of the three probability columns.
@freezed
class MatchContextReading with _$MatchContextReading {
  const factory MatchContextReading({
    required String matchId,
    @Default(<MatchContextSignal>[]) List<MatchContextSignal> signals,
    MatchProbabilities? probabilities,
  }) = _MatchContextReading;

  factory MatchContextReading.fromJson(Map<String, dynamic> json) =>
      _$MatchContextReadingFromJson(json);
}
