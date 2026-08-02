// AZTECA-INSIGHTS-A — primitives: accessibility + honest rendering.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/features/insights/model/insight_metrics.dart';
import 'package:azteca/features/insights/widgets/insight_primitives.dart';
import 'package:azteca/theme/theme.dart';

Future<void> _pump(WidgetTester tester, Widget child) async {
  await tester.pumpWidget(MaterialApp(
    theme: insightTheme(Brightness.light),
    home: Scaffold(body: Center(child: child)),
  ));
  await tester.pump();
}

void main() {
  testWidgets('scalar metric renders label + value with a semantic sentence',
      (tester) async {
    await _pump(tester, const InsightMetricCard(
      metric: MetricValue(label: 'Publicações', value: 12),
    ));
    expect(find.text('Publicações'), findsOneWidget);
    expect(find.text('12'), findsOneWidget);
    expect(
      tester.getSemantics(find.byType(InsightMetricCard)).label,
      contains('Publicações: 12'),
    );
  });

  testWidgets('delta shows icon + TEXT (never colour alone) for up and down',
      (tester) async {
    await _pump(tester, const DeltaIndicator(
      delta: MetricDelta(label: 'Pressão', current: 108, previous: 100),
    ));
    // Text carries the meaning, not just the colour.
    expect(find.textContaining('+8'), findsOneWidget);
    expect(find.byIcon(Icons.arrow_upward_rounded), findsOneWidget);

    await _pump(tester, const DeltaIndicator(
      delta: MetricDelta(label: 'Pressão', current: 90, previous: 100),
    ));
    expect(find.textContaining('-10'), findsOneWidget);
    expect(find.byIcon(Icons.arrow_downward_rounded), findsOneWidget);
  });

  testWidgets('unknown direction renders NO directional arrow', (tester) async {
    await _pump(tester, const DirectionIndicator(direction: MetricDirection.unknown));
    expect(find.byIcon(Icons.arrow_upward_rounded), findsNothing);
    expect(find.byIcon(Icons.arrow_downward_rounded), findsNothing);
    expect(find.text('sem referência'), findsOneWidget);
  });

  testWidgets('probability renders bounded % and is visually distinct from confidence',
      (tester) async {
    await _pump(tester, const ProbabilityBar(
      metric: ProbabilityMetric(
        label: 'Vitória A',
        probability: 0.64,
        confidence: ConfidenceMetric(score: 0.82),
      ),
    ));
    // Probability = continuous bar + % text.
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(find.textContaining('64'), findsOneWidget);
    // Confidence = separate segmented indicator with its own word.
    expect(find.byType(ConfidenceIndicator), findsOneWidget);
    expect(find.text('Alta'), findsOneWidget);
    expect(find.text('Confiança'), findsOneWidget);
  });

  testWidgets('comparison with nothing to compare renders an honest dash',
      (tester) async {
    await _pump(tester, const ComparisonBar(
      metric: ComparisonMetric(
        label: 'Pressão', leftLabel: 'A', rightLabel: 'B',
        leftValue: 0, rightValue: 0,
      ),
    ));
    expect(find.text('—'), findsOneWidget);
  });

  testWidgets('unknown freshness renders nothing (never invented)', (tester) async {
    await _pump(tester, const FreshnessIndicator(freshness: MetricFreshness.unknown));
    expect(find.byType(Icon), findsNothing);
  });

  testWidgets('explanation renders product language + evidence summary',
      (tester) async {
    await _pump(tester, const InsightExplanationCard(
      explanation: InsightExplanation(
        summary: 'Pressão de mercado subiu após movimento sustentado.',
        evidenceSummary: 'Baseado em 12 partidas semelhantes',
        source: InsightSource.market,
      ),
    ));
    expect(find.textContaining('Pressão de mercado subiu'), findsOneWidget);
    expect(find.text('Baseado em 12 partidas semelhantes'), findsOneWidget);
    expect(find.text('Movimento de mercado'), findsOneWidget);
  });
}
