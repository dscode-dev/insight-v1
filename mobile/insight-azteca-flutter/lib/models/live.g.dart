// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'live.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$LiveFilterImpl _$$LiveFilterImplFromJson(Map<String, dynamic> json) =>
    _$LiveFilterImpl(
      competitionId: json['competition_id'] as String?,
      status: $enumDecodeNullable(_$LiveStatusFilterEnumMap, json['status']) ??
          LiveStatusFilter.all,
    );

Map<String, dynamic> _$$LiveFilterImplToJson(_$LiveFilterImpl instance) =>
    <String, dynamic>{
      if (instance.competitionId case final value?) 'competition_id': value,
      'status': _$LiveStatusFilterEnumMap[instance.status]!,
    };

const _$LiveStatusFilterEnumMap = {
  LiveStatusFilter.all: 'all',
  LiveStatusFilter.live: 'live',
  LiveStatusFilter.today: 'today',
  LiveStatusFilter.upcoming: 'upcoming',
};

_$LiveMatchImpl _$$LiveMatchImplFromJson(Map<String, dynamic> json) =>
    _$LiveMatchImpl(
      summary: MatchSummary.fromJson(json['summary'] as Map<String, dynamic>),
      momentum: (json['momentum'] as num).toDouble(),
      pressure: (json['pressure'] as num).toDouble(),
    );

Map<String, dynamic> _$$LiveMatchImplToJson(_$LiveMatchImpl instance) =>
    <String, dynamic>{
      'summary': instance.summary.toJson(),
      'momentum': instance.momentum,
      'pressure': instance.pressure,
    };

_$TimelinePointImpl _$$TimelinePointImplFromJson(Map<String, dynamic> json) =>
    _$TimelinePointImpl(
      ts: DateTime.parse(json['ts'] as String),
      value: (json['value'] as num).toDouble(),
    );

Map<String, dynamic> _$$TimelinePointImplToJson(_$TimelinePointImpl instance) =>
    <String, dynamic>{
      'ts': instance.ts.toIso8601String(),
      'value': instance.value,
    };

_$OddsPointImpl _$$OddsPointImplFromJson(Map<String, dynamic> json) =>
    _$OddsPointImpl(
      ts: DateTime.parse(json['ts'] as String),
      home: (json['home'] as num).toDouble(),
      draw: (json['draw'] as num).toDouble(),
      away: (json['away'] as num).toDouble(),
    );

Map<String, dynamic> _$$OddsPointImplToJson(_$OddsPointImpl instance) =>
    <String, dynamic>{
      'ts': instance.ts.toIso8601String(),
      'home': instance.home,
      'draw': instance.draw,
      'away': instance.away,
    };

_$MatchSignalImpl _$$MatchSignalImplFromJson(Map<String, dynamic> json) =>
    _$MatchSignalImpl(
      id: json['id'] as String,
      source: json['source'] as String,
      label: json['label'] as String,
      body: json['body'] as String,
      ts: DateTime.parse(json['ts'] as String),
    );

Map<String, dynamic> _$$MatchSignalImplToJson(_$MatchSignalImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'source': instance.source,
      'label': instance.label,
      'body': instance.body,
      'ts': instance.ts.toIso8601String(),
    };

_$MatchDetailImpl _$$MatchDetailImplFromJson(Map<String, dynamic> json) =>
    _$MatchDetailImpl(
      summary: MatchSummary.fromJson(json['summary'] as Map<String, dynamic>),
      oddsTimeline: (json['odds_timeline'] as List<dynamic>?)
              ?.map((e) => OddsPoint.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const <OddsPoint>[],
      pressureTimeline: (json['pressure_timeline'] as List<dynamic>?)
              ?.map((e) => TimelinePoint.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const <TimelinePoint>[],
      signals: (json['signals'] as List<dynamic>?)
              ?.map((e) => MatchSignal.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const <MatchSignal>[],
    );

Map<String, dynamic> _$$MatchDetailImplToJson(_$MatchDetailImpl instance) =>
    <String, dynamic>{
      'summary': instance.summary.toJson(),
      'odds_timeline': instance.oddsTimeline.map((e) => e.toJson()).toList(),
      'pressure_timeline':
          instance.pressureTimeline.map((e) => e.toJson()).toList(),
      'signals': instance.signals.map((e) => e.toJson()).toList(),
    };
