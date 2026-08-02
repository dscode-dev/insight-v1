import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../models/live.dart';
import '../../models/match_context_response.dart';
import '../../core/user_facing_error.dart';
import '../../providers/live_provider.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../shared/format/relative_time.dart';
import '../../shared/strings/pt_br.dart';
import '../../theme/spacing.dart';
import '../../widgets/empty_state.dart';
import '../../widgets/error_state.dart';
import '../../widgets/insight_tabs.dart';
import '../../widgets/match_context_card.dart';
import 'match_context_derive.dart';

/// Full-screen match detail.
///
/// Stage 5.2 layout: the dashboard-style "pressure timeline + odds
/// movement" cards are replaced by a single `MatchContextCard` at the
/// top of the Resumo tab. The card carries the same information in
/// social language — directional signals + probability triple — without
/// sparklines or %-delta chips.
///
/// Tabs:
///   * Resumo   — MatchContextCard derived from MatchDetail
///   * Contexto — Atlas-backed descriptive context (Sprint 6.2 Part 4)
///   * Sinais   — community + agent reads on this match
class MatchDetailScreen extends ConsumerWidget {
  const MatchDetailScreen({super.key, required this.matchId});
  final String matchId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(matchDetailProvider(matchId));

    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: async.maybeWhen(
            data: (d) => Text(
              '${d.summary.home.short} × ${d.summary.away.short}',
            ),
            orElse: () => const Text('Partida'),
          ),
        ),
        body: async.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ErrorState(
            title: S.unknownError,
            description: userFacingErrorMessage(e),
            onRetry: () => ref.invalidate(matchDetailProvider(matchId)),
          ),
          data: (detail) => Column(
            children: [
              const InsightTabBar(
                tabs: [
                  Tab(text: 'Resumo'),
                  Tab(text: 'Contexto'),
                  Tab(text: 'Sinais'),
                ],
              ),
              Expanded(
                child: TabBarView(
                  children: [
                    _ResumoTab(detail: detail),
                    _ContextTab(matchId: matchId),
                    _SinaisTab(signals: detail.signals),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ResumoTab extends StatelessWidget {
  const _ResumoTab({required this.detail});
  final MatchDetail detail;

  @override
  Widget build(BuildContext context) {
    final reading = deriveMatchContextReading(detail);
    final hasSomething =
        reading.probabilities != null || reading.signals.isNotEmpty;
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(
        InsightSpacing.xl,
        InsightSpacing.lg,
        InsightSpacing.xl,
        InsightSpacing.xl3,
      ),
      children: [
        MatchContextCard(summary: detail.summary, reading: reading),
        if (!hasSomething) ...[
          const SizedBox(height: InsightSpacing.xl),
          const EmptyState(
            title: 'Sem leituras ainda',
            description:
                'Quando agentes ou a comunidade começarem a ler essa partida, aparece aqui.',
          ),
        ],
      ],
    );
  }
}

// Sprint 6.2 Part 4 — Contexto tab.
//
// Replaces the "H2H em breve" placeholder. Reads
// `matchContextProvider(matchId)` which calls Gateway →
// `GET /v1/context/match/{matchId}` → Atlas inference engine.
//
// State paths:
//   loading → skeleton (CircularProgressIndicator)
//   error   → ErrorState with Retry (invalidates the provider)
//   data    → if empty: EmptyState with the operator's options;
//             otherwise: summary card + signals + tendencies + community
class _ContextTab extends ConsumerWidget {
  const _ContextTab({required this.matchId});
  final String matchId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(matchContextProvider(matchId));
    return async.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => ErrorState(
        title: 'Não foi possível carregar o contexto',
        description: userFacingErrorMessage(e),
        onRetry: () => ref.invalidate(matchContextProvider(matchId)),
      ),
      data: (ctxResponse) {
        if (ctxResponse.isEmpty) {
          return ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            children: const [
              EmptyState(
                title: 'Sem contexto disponível',
                description:
                    'Atlas ainda não publicou leituras para essa partida. Volte em alguns minutos.',
              ),
            ],
          );
        }
        return ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(
            InsightSpacing.xl,
            InsightSpacing.lg,
            InsightSpacing.xl,
            InsightSpacing.xl3,
          ),
          children: [
            if (ctxResponse.summary != null && ctxResponse.summary!.isNotEmpty)
              const _SectionTitle(label: 'Resumo'),
            if (ctxResponse.summary != null && ctxResponse.summary!.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: InsightSpacing.lg),
                child: Text(
                  ctxResponse.summary!,
                  style: context.tt.bodyLarge,
                ),
              ),
            if (ctxResponse.signals.isNotEmpty) ...[
              const _SectionTitle(label: 'Sinais'),
              ...ctxResponse.signals.map(_ContextSignalRow.new),
              const SizedBox(height: InsightSpacing.lg),
            ],
            if (ctxResponse.tendencies.isNotEmpty) ...[
              const _SectionTitle(label: 'Tendências recentes'),
              ...ctxResponse.tendencies.map(_ContextTendencyRow.new),
              const SizedBox(height: InsightSpacing.lg),
            ],
            if (ctxResponse.community != null) ...[
              const _SectionTitle(label: 'Comunidade'),
              _ContextCommunityRow(community: ctxResponse.community!),
            ],
          ],
        );
      },
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: InsightSpacing.sm),
      child: Text(
        label,
        style: context.tt.labelSmall?.copyWith(
          color: context.ds.textLow,
          letterSpacing: 1.0,
        ),
      ),
    );
  }
}

class _ContextSignalRow extends StatelessWidget {
  const _ContextSignalRow(this.signal);
  final MatchContextSignal signal;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: InsightSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 6,
            height: 6,
            margin: const EdgeInsets.only(top: 8),
            decoration: BoxDecoration(
              color: context.ds.signal,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: InsightSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(signal.label, style: context.tt.titleMedium),
                    ),
                    if (signal.confidence != null)
                      Text(
                        '${(signal.confidence! * 100).round()}%',
                        style: context.tt.labelSmall
                            ?.copyWith(color: context.ds.textLow),
                      ),
                  ],
                ),
                if (signal.body.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    signal.body,
                    style: context.tt.bodyMedium
                        ?.copyWith(color: context.ds.textMid),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ContextTendencyRow extends StatelessWidget {
  const _ContextTendencyRow(this.tendency);
  final MatchContextTendency tendency;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Expanded(
            child: Text(
              tendency.label,
              style: context.tt.bodyMedium?.copyWith(color: context.ds.textMid),
            ),
          ),
          Text(
            tendency.value,
            style: context.tt.bodyMedium?.copyWith(
              color: context.ds.textHigh,
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
        ],
      ),
    );
  }
}

class _ContextCommunityRow extends StatelessWidget {
  const _ContextCommunityRow({required this.community});
  final MatchContextCommunity community;

  String _leaningLabel() {
    switch (community.leaning) {
      case 'home':
        return 'Inclinação ao mandante';
      case 'away':
        return 'Inclinação ao visitante';
      case 'mixed':
        return 'Divergência entre leituras';
      default:
        return 'Leituras equilibradas';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Icon(Icons.diversity_3_outlined, size: 18, color: context.ds.textMid),
          const SizedBox(width: InsightSpacing.sm),
          Expanded(
            child: Text(
              _leaningLabel(),
              style: context.tt.bodyMedium,
            ),
          ),
          Text(
            '${community.activeUsers} ativos',
            style: context.tt.labelSmall?.copyWith(color: context.ds.textLow),
          ),
        ],
      ),
    );
  }
}

class _SinaisTab extends StatelessWidget {
  const _SinaisTab({required this.signals});
  final List<MatchSignal> signals;

  @override
  Widget build(BuildContext context) {
    if (signals.isEmpty) {
      return ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: const [
          EmptyState(
            title: 'Sem sinais ainda',
            description: 'Quando alguém ler a partida, aparece aqui.',
          ),
        ],
      );
    }
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      children: [
        ...signals.map((s) => _SignalRow(signal: s)),
        const SizedBox(height: 32),
      ],
    );
  }
}

class _SignalRow extends StatelessWidget {
  const _SignalRow({required this.signal});
  final MatchSignal signal;

  Color _sourceColor(BuildContext c) {
    switch (signal.source) {
      case 'model':
        return c.ds.signal;
      case 'expert':
        return c.ds.confidenceMid;
      case 'community':
        return c.ds.confidenceHigh;
      default:
        return c.ds.textLow;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 6,
            height: 6,
            margin: const EdgeInsets.only(top: 8),
            decoration: BoxDecoration(
              color: _sourceColor(context),
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(signal.label, style: context.tt.titleMedium),
                    const Spacer(),
                    Text(
                      relativeTime(signal.ts),
                      style: context.tt.labelSmall
                          ?.copyWith(color: context.ds.textLow),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  signal.body,
                  style: context.tt.bodyMedium
                      ?.copyWith(color: context.ds.textMid),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
