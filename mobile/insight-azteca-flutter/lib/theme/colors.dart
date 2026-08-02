import 'package:flutter/material.dart';

/// Insight design system — colour tokens.
///
/// Two surfaces of colour live here:
///   * `InsightColors` — neutral, semantic, and agent accents per brightness.
///     Pulled by `theme.dart` to build a ColorScheme + ThemeExtension.
///   * `InsightAgentColors` — per-agent stripe colours for AgentInsightPost.
///
/// Decision: not a Threads clone. Semantic colours are *visible*, not muted.
/// Confidence high = a real green, not a sad grey. Premium feel comes from
/// spacing and typography, not desaturation.
class InsightColors extends ThemeExtension<InsightColors> {
  const InsightColors({
    required this.background,
    required this.card,
    required this.subtle,
    required this.textHigh,
    required this.textMid,
    required this.textLow,
    required this.divider,
    required this.signal,
    required this.signalMuted,
    required this.confidenceHigh,
    required this.confidenceMid,
    required this.confidenceLow,
    required this.agent,
  });

  final Color background;
  final Color card;
  final Color subtle;

  final Color textHigh;
  final Color textMid;
  final Color textLow;

  final Color divider;

  final Color signal;
  final Color signalMuted;

  final Color confidenceHigh;
  final Color confidenceMid;
  final Color confidenceLow;

  final InsightAgentColors agent;

  static const InsightColors light = InsightColors(
    background: Color(0xFFFAFBFC),
    card: Color(0xFFFFFFFF),
    subtle: Color(0xFFF2F4F7),
    textHigh: Color(0xFF0D1117),
    textMid: Color(0xFF4B5563),
    textLow: Color(0xFF828C98),
    divider: Color(0x0F0F172A),
    signal: Color(0xFF3884FF),
    signalMuted: Color(0xFFE0EBFF),
    confidenceHigh: Color(0xFF10B981),
    confidenceMid: Color(0xFFF59E0B),
    confidenceLow: Color(0xFFF43F5E),
    agent: InsightAgentColors.light,
  );

  static const InsightColors dark = InsightColors(
    background: Color(0xFF0A0B0E),
    card: Color(0xFF14171C),
    subtle: Color(0xFF1B1F25),
    textHigh: Color(0xFFF5F7FA),
    textMid: Color(0xFFA7B0BD),
    textLow: Color(0xFF6B7280),
    divider: Color(0x14FFFFFF),
    signal: Color(0xFF5BA8FF),
    signalMuted: Color(0x1F5BA8FF),
    confidenceHigh: Color(0xFF34D399),
    confidenceMid: Color(0xFFFBBF24),
    confidenceLow: Color(0xFFFB7185),
    agent: InsightAgentColors.dark,
  );

  @override
  InsightColors copyWith({
    Color? background,
    Color? card,
    Color? subtle,
    Color? textHigh,
    Color? textMid,
    Color? textLow,
    Color? divider,
    Color? signal,
    Color? signalMuted,
    Color? confidenceHigh,
    Color? confidenceMid,
    Color? confidenceLow,
    InsightAgentColors? agent,
  }) {
    return InsightColors(
      background: background ?? this.background,
      card: card ?? this.card,
      subtle: subtle ?? this.subtle,
      textHigh: textHigh ?? this.textHigh,
      textMid: textMid ?? this.textMid,
      textLow: textLow ?? this.textLow,
      divider: divider ?? this.divider,
      signal: signal ?? this.signal,
      signalMuted: signalMuted ?? this.signalMuted,
      confidenceHigh: confidenceHigh ?? this.confidenceHigh,
      confidenceMid: confidenceMid ?? this.confidenceMid,
      confidenceLow: confidenceLow ?? this.confidenceLow,
      agent: agent ?? this.agent,
    );
  }

  @override
  InsightColors lerp(ThemeExtension<InsightColors>? other, double t) {
    if (other is! InsightColors) return this;
    return InsightColors(
      background: Color.lerp(background, other.background, t)!,
      card: Color.lerp(card, other.card, t)!,
      subtle: Color.lerp(subtle, other.subtle, t)!,
      textHigh: Color.lerp(textHigh, other.textHigh, t)!,
      textMid: Color.lerp(textMid, other.textMid, t)!,
      textLow: Color.lerp(textLow, other.textLow, t)!,
      divider: Color.lerp(divider, other.divider, t)!,
      signal: Color.lerp(signal, other.signal, t)!,
      signalMuted: Color.lerp(signalMuted, other.signalMuted, t)!,
      confidenceHigh: Color.lerp(confidenceHigh, other.confidenceHigh, t)!,
      confidenceMid: Color.lerp(confidenceMid, other.confidenceMid, t)!,
      confidenceLow: Color.lerp(confidenceLow, other.confidenceLow, t)!,
      agent: agent.lerp(other.agent, t),
    );
  }
}

/// Per-agent accent colour. Used by `AgentInsightPost` for the lateral
/// stripe so users can identify which agent produced an insight at a glance.
class InsightAgentColors {
  const InsightAgentColors({
    required this.scout,
    required this.pulse,
    required this.momentum,
    required this.stats,
    required this.history,
  });

  final Color scout;
  final Color pulse;
  final Color momentum;
  final Color stats;
  final Color history;

  static const InsightAgentColors light = InsightAgentColors(
    scout: Color(0xFFF59E0B),
    pulse: Color(0xFF3884FF),
    momentum: Color(0xFFF43F5E),
    stats: Color(0xFF10B981),
    history: Color(0xFF94A3B8),
  );

  static const InsightAgentColors dark = InsightAgentColors(
    scout: Color(0xFFFBBF24),
    pulse: Color(0xFF5BA8FF),
    momentum: Color(0xFFFB7185),
    stats: Color(0xFF34D399),
    history: Color(0xFFC8D0DA),
  );

  Color byId(String agentId) {
    switch (agentId) {
      case 'scout':
        return scout;
      case 'pulse':
        return pulse;
      case 'momentum':
        return momentum;
      case 'stats':
        return stats;
      case 'history':
        return history;
      default:
        return history;
    }
  }

  InsightAgentColors lerp(InsightAgentColors other, double t) {
    return InsightAgentColors(
      scout: Color.lerp(scout, other.scout, t)!,
      pulse: Color.lerp(pulse, other.pulse, t)!,
      momentum: Color.lerp(momentum, other.momentum, t)!,
      stats: Color.lerp(stats, other.stats, t)!,
      history: Color.lerp(history, other.history, t)!,
    );
  }
}
