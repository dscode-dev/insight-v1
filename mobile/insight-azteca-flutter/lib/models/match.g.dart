// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'match.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$MatchScoreImpl _$$MatchScoreImplFromJson(Map<String, dynamic> json) =>
    _$MatchScoreImpl(
      home: (json['home'] as num).toInt(),
      away: (json['away'] as num).toInt(),
    );

Map<String, dynamic> _$$MatchScoreImplToJson(_$MatchScoreImpl instance) =>
    <String, dynamic>{
      'home': instance.home,
      'away': instance.away,
    };

_$MatchTeamImpl _$$MatchTeamImplFromJson(Map<String, dynamic> json) =>
    _$MatchTeamImpl(
      short: json['short'] as String,
      name: json['name'] as String,
      crestColor: json['crest_color'] as String,
    );

Map<String, dynamic> _$$MatchTeamImplToJson(_$MatchTeamImpl instance) =>
    <String, dynamic>{
      'short': instance.short,
      'name': instance.name,
      'crest_color': instance.crestColor,
    };

_$MatchStatusImpl _$$MatchStatusImplFromJson(Map<String, dynamic> json) =>
    _$MatchStatusImpl(
      state: $enumDecode(_$MatchStateEnumMap, json['state']),
      minute: (json['minute'] as num?)?.toInt(),
      period: json['period'] as String?,
      score: json['score'] == null
          ? null
          : MatchScore.fromJson(json['score'] as Map<String, dynamic>),
      kickoff: DateTime.parse(json['kickoff'] as String),
    );

Map<String, dynamic> _$$MatchStatusImplToJson(_$MatchStatusImpl instance) =>
    <String, dynamic>{
      'state': _$MatchStateEnumMap[instance.state]!,
      if (instance.minute case final value?) 'minute': value,
      if (instance.period case final value?) 'period': value,
      if (instance.score?.toJson() case final value?) 'score': value,
      'kickoff': instance.kickoff.toIso8601String(),
    };

const _$MatchStateEnumMap = {
  MatchState.scheduled: 'scheduled',
  MatchState.live: 'live',
  MatchState.halftime: 'halftime',
  MatchState.finished: 'finished',
};

_$IntelligencePillImpl _$$IntelligencePillImplFromJson(
        Map<String, dynamic> json) =>
    _$IntelligencePillImpl(
      label: json['label'] as String,
      tone: $enumDecode(_$IntelligencePillToneEnumMap, json['tone']),
    );

Map<String, dynamic> _$$IntelligencePillImplToJson(
        _$IntelligencePillImpl instance) =>
    <String, dynamic>{
      'label': instance.label,
      'tone': _$IntelligencePillToneEnumMap[instance.tone]!,
    };

const _$IntelligencePillToneEnumMap = {
  IntelligencePillTone.neutral: 'neutral',
  IntelligencePillTone.signal: 'signal',
  IntelligencePillTone.warning: 'warning',
  IntelligencePillTone.success: 'success',
  IntelligencePillTone.danger: 'danger',
};

_$MatchSummaryImpl _$$MatchSummaryImplFromJson(Map<String, dynamic> json) =>
    _$MatchSummaryImpl(
      matchId: json['match_id'] as String,
      league: json['league'] as String,
      home: MatchTeam.fromJson(json['home'] as Map<String, dynamic>),
      away: MatchTeam.fromJson(json['away'] as Map<String, dynamic>),
      status: MatchStatus.fromJson(json['status'] as Map<String, dynamic>),
      pills: (json['pills'] as List<dynamic>?)
              ?.map((e) => IntelligencePill.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const <IntelligencePill>[],
    );

Map<String, dynamic> _$$MatchSummaryImplToJson(_$MatchSummaryImpl instance) =>
    <String, dynamic>{
      'match_id': instance.matchId,
      'league': instance.league,
      'home': instance.home.toJson(),
      'away': instance.away.toJson(),
      'status': instance.status.toJson(),
      'pills': instance.pills.map((e) => e.toJson()).toList(),
    };
