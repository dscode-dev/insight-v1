// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'match_context.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$MatchContextSignalImpl _$$MatchContextSignalImplFromJson(
        Map<String, dynamic> json) =>
    _$MatchContextSignalImpl(
      label: json['label'] as String,
      direction:
          $enumDecodeNullable(_$SignalDirectionEnumMap, json['direction']) ??
              SignalDirection.neutral,
    );

Map<String, dynamic> _$$MatchContextSignalImplToJson(
        _$MatchContextSignalImpl instance) =>
    <String, dynamic>{
      'label': instance.label,
      'direction': _$SignalDirectionEnumMap[instance.direction]!,
    };

const _$SignalDirectionEnumMap = {
  SignalDirection.up: 'up',
  SignalDirection.down: 'down',
  SignalDirection.neutral: 'neutral',
};

_$MatchProbabilitiesImpl _$$MatchProbabilitiesImplFromJson(
        Map<String, dynamic> json) =>
    _$MatchProbabilitiesImpl(
      home: (json['home'] as num).toDouble(),
      draw: (json['draw'] as num).toDouble(),
      away: (json['away'] as num).toDouble(),
    );

Map<String, dynamic> _$$MatchProbabilitiesImplToJson(
        _$MatchProbabilitiesImpl instance) =>
    <String, dynamic>{
      'home': instance.home,
      'draw': instance.draw,
      'away': instance.away,
    };

_$MatchContextReadingImpl _$$MatchContextReadingImplFromJson(
        Map<String, dynamic> json) =>
    _$MatchContextReadingImpl(
      matchId: json['match_id'] as String,
      signals: (json['signals'] as List<dynamic>?)
              ?.map(
                  (e) => MatchContextSignal.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const <MatchContextSignal>[],
      probabilities: json['probabilities'] == null
          ? null
          : MatchProbabilities.fromJson(
              json['probabilities'] as Map<String, dynamic>),
    );

Map<String, dynamic> _$$MatchContextReadingImplToJson(
        _$MatchContextReadingImpl instance) =>
    <String, dynamic>{
      'match_id': instance.matchId,
      'signals': instance.signals.map((e) => e.toJson()).toList(),
      if (instance.probabilities?.toJson() case final value?)
        'probabilities': value,
    };
