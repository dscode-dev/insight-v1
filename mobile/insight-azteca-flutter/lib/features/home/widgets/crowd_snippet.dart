import 'package:flutter/material.dart';

import '../../../models/feed.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/format/count.dart';
import '../../../shared/strings/pt_br.dart';

/// One-line collective sentiment — no bars, no chrome.
///
///   Confiança casa 62% · 1,2k pessoas
///   Confiança casa 33% · ↓ 28pp em 10min · 2,2k pessoas
class CrowdSnippet extends StatelessWidget {
  const CrowdSnippet({super.key, required this.data});

  final FeedCrowdSentiment data;

  ({String label, int pct}) _leading() {
    var label = S.confidenceHomeLabel;
    var best = data.homePct;
    if (data.drawPct > best) {
      label = S.confidenceDrawLabel;
      best = data.drawPct;
    }
    if (data.awayPct > best) {
      label = S.confidenceAwayLabel;
      best = data.awayPct;
    }
    return (label: label, pct: (best * 100).round());
  }

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final tt = context.tt;
    final lead = _leading();
    final delta = data.delta;

    final children = <InlineSpan>[
      TextSpan(text: 'Confiança ${lead.label} '),
      TextSpan(
        text: '${lead.pct}%',
        style: TextStyle(
          color: ds.textHigh,
          fontWeight: FontWeight.w600,
          fontFeatures: const [FontFeature.tabularFigures()],
        ),
      ),
    ];

    if (delta != null) {
      final positive = delta.pp >= 0;
      children
        ..add(const TextSpan(text: ' · '))
        ..add(
          TextSpan(
            text: '${positive ? "↑" : "↓"} ${delta.pp.abs()}pp em ${delta.windowMinutes}min',
            style: TextStyle(
              color: positive ? ds.confidenceHigh : ds.confidenceLow,
              fontWeight: FontWeight.w500,
            ),
          ),
        );
    }

    children
      ..add(const TextSpan(text: ' · '))
      ..add(
        TextSpan(
          text: '${formatCount(data.participants)} ${S.peopleLabel}',
          style: TextStyle(
            color: ds.textMid,
            fontFeatures: const [FontFeature.tabularFigures()],
          ),
        ),
      );

    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Text.rich(
        TextSpan(
          style: tt.bodySmall?.copyWith(color: ds.textMid),
          children: children,
        ),
      ),
    );
  }
}
