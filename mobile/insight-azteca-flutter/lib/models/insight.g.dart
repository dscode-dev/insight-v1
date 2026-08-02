// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'insight.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$AgentInsightImpl _$$AgentInsightImplFromJson(Map<String, dynamic> json) =>
    _$AgentInsightImpl(
      insightId: json['insight_id'] as String,
      agentId: $enumDecode(_$AgentIdEnumMap, json['agent_id']),
      insightKind: $enumDecode(_$AgentInsightKindEnumMap, json['insight_kind']),
      matchId: json['match_id'] as String,
      headline: json['headline'] as String,
      body: json['body'] as String? ?? '',
      confidence: (json['confidence'] as num).toDouble(),
      minute: (json['minute'] as num?)?.toInt(),
      refs:
          (json['refs'] as List<dynamic>?)?.map((e) => e as String).toList() ??
              const <String>[],
      metrics:
          json['metrics'] as Map<String, dynamic>? ?? const <String, dynamic>{},
      createdAt: DateTime.parse(json['created_at'] as String),
    );

Map<String, dynamic> _$$AgentInsightImplToJson(_$AgentInsightImpl instance) =>
    <String, dynamic>{
      'insight_id': instance.insightId,
      'agent_id': _$AgentIdEnumMap[instance.agentId]!,
      'insight_kind': _$AgentInsightKindEnumMap[instance.insightKind]!,
      'match_id': instance.matchId,
      'headline': instance.headline,
      'body': instance.body,
      'confidence': instance.confidence,
      if (instance.minute case final value?) 'minute': value,
      'refs': instance.refs,
      'metrics': instance.metrics,
      'created_at': instance.createdAt.toIso8601String(),
    };

const _$AgentIdEnumMap = {
  AgentId.scout: 'scout',
  AgentId.pulse: 'pulse',
  AgentId.momentum: 'momentum',
  AgentId.stats: 'stats',
  AgentId.history: 'history',
};

const _$AgentInsightKindEnumMap = {
  AgentInsightKind.tacticalShift: 'tactical_shift',
  AgentInsightKind.pressingPattern: 'pressing_pattern',
  AgentInsightKind.sentimentSwing: 'sentiment_swing',
  AgentInsightKind.crowdPolarisation: 'crowd_polarisation',
  AgentInsightKind.momentumShift: 'momentum_shift',
  AgentInsightKind.shotPressureReversal: 'shot_pressure_reversal',
  AgentInsightKind.thresholdCross: 'threshold_cross',
  AgentInsightKind.rollingAnomaly: 'rolling_anomaly',
  AgentInsightKind.historicalContext: 'historical_context',
  AgentInsightKind.rareEvent: 'rare_event',
};
