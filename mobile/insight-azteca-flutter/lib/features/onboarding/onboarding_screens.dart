// Onboarding — restored as a lightweight post-login journey.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../providers/onboarding_provider.dart';
import '../../routing/routes.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../theme/spacing.dart';

/// Step ids — kept here so `_StepShell` can compute the progress dots
/// without a hidden ordering rule somewhere else.
enum _OnboardingStep { welcome, about, competitions, teams }

class OnboardingWelcomeScreen extends StatelessWidget {
  const OnboardingWelcomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return _StepShell(
      step: _OnboardingStep.welcome,
      title: 'Insight em poucas leituras',
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Acompanhe futebol com contexto, sinais e discussões organizadas. '
            'A ideia é entender o jogo, não receber palpite.',
            style: context.tt.bodyLarge?.copyWith(color: context.ds.textMid),
          ),
          const SizedBox(height: InsightSpacing.xl3),
          Center(
            child: Container(
              width: 132,
              height: 132,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: RadialGradient(
                  colors: [
                    context.ds.signal.withValues(alpha: 0.14),
                    context.ds.signal.withValues(alpha: 0),
                  ],
                ),
              ),
              child: Image.asset(
                'assets/image/insight-logo-transparent.png',
                width: 104,
                height: 104,
                fit: BoxFit.contain,
              ),
            ),
          ),
        ],
      ),
      nextLabel: 'Começar',
      onNext: (ctx, _) => ctx.go(R.onboardingAbout),
    );
  }
}

class OnboardingAboutScreen extends StatelessWidget {
  const OnboardingAboutScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return _StepShell(
      step: _OnboardingStep.about,
      title: 'Sinais',
      body: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Bullet(
            icon: Icons.insights_outlined,
            label: 'Sinais mostram leituras da comunidade e agentes.',
          ),
          SizedBox(height: InsightSpacing.md),
          _Bullet(
            icon: Icons.query_stats_rounded,
            label: 'Confiança e contexto importam mais que volume bruto.',
          ),
          SizedBox(height: InsightSpacing.md),
          _Bullet(
            icon: Icons.sports_soccer_rounded,
            label: 'Use sinais para ler partidas, clubes e movimentos.',
          ),
        ],
      ),
      nextLabel: 'Avançar',
      onNext: (ctx, _) => ctx.go(R.onboardingCompetitions),
    );
  }
}

class OnboardingCompetitionsScreen extends StatelessWidget {
  const OnboardingCompetitionsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return _StepShell(
      step: _OnboardingStep.competitions,
      title: 'Discussões e clubes',
      body: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Bullet(
            icon: Icons.forum_rounded,
            label: 'Discussões mantêm contexto por assunto, não por ruído.',
          ),
          SizedBox(height: InsightSpacing.md),
          _Bullet(
            icon: Icons.groups_2_rounded,
            label:
                'Clubes e comunidades ajudam você a seguir leituras próximas.',
          ),
          SizedBox(height: InsightSpacing.md),
          _Bullet(
            icon: Icons.report_gmailerrorred_rounded,
            label: 'Denuncie ou bloqueie quando uma conversa sair das regras.',
          ),
        ],
      ),
      nextLabel: 'Avançar',
      onNext: (ctx, _) => ctx.go(R.onboardingTeams),
    );
  }
}

class OnboardingTeamsScreen extends ConsumerWidget {
  const OnboardingTeamsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return _StepShell(
      step: _OnboardingStep.teams,
      title: 'Agentes',
      body: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Bullet(
            icon: Icons.verified_rounded,
            label:
                'Agentes organizam leituras recorrentes e sinais relevantes.',
          ),
          SizedBox(height: InsightSpacing.md),
          _Bullet(
            icon: Icons.person_add_alt_1_rounded,
            label: 'Siga agentes e usuários para moldar sua visão do futebol.',
          ),
          SizedBox(height: InsightSpacing.md),
          _Bullet(
            icon: Icons.home_rounded,
            label: 'Depois disso, seu radar começa no feed principal.',
          ),
        ],
      ),
      nextLabel: 'Concluir',
      onNext: (ctx, refOnPress) async {
        await markOnboardingDone(refOnPress);
        if (ctx.mounted) ctx.go(R.home);
      },
    );
  }
}

// ---------------------------------------------------------------------------
// Shared step scaffold — keeps the four screens visually identical without
// duplicating layout code.
// ---------------------------------------------------------------------------

class _StepShell extends ConsumerWidget {
  const _StepShell({
    required this.step,
    required this.title,
    required this.body,
    required this.nextLabel,
    required this.onNext,
  });

  final _OnboardingStep step;
  final String title;
  final Widget body;
  final String nextLabel;

  /// `WidgetRef` is forwarded so the Finish action can call
  /// `markOnboardingDone(ref)` without re-watching anything itself.
  /// Returns `FutureOr<void>` so screens that only synchronously
  /// navigate (`ctx.go`) don't need to fake an async signature.
  final FutureOr<void> Function(BuildContext context, WidgetRef ref) onNext;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isWelcome = step == _OnboardingStep.welcome;
    return Scaffold(
      appBar: AppBar(
        title: const SizedBox.shrink(),
        backgroundColor: Colors.transparent,
        elevation: 0,
        actions: [
          if (!isWelcome)
            TextButton(
              onPressed: () async {
                // Skip persists the flag too — the operator opted out;
                // we don't punish them with a future re-prompt. The
                // auth gate decides where they actually land.
                await markOnboardingDone(ref);
                if (context.mounted) context.go(R.home);
              },
              child: const Text('Pular'),
            ),
        ],
      ),
      body: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: InsightSpacing.xl,
            vertical: InsightSpacing.lg,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _ProgressDots(activeIndex: step.index),
              const SizedBox(height: InsightSpacing.xl),
              Text(title, style: context.tt.headlineSmall),
              const SizedBox(height: InsightSpacing.lg),
              Expanded(child: SingleChildScrollView(child: body)),
              const SizedBox(height: InsightSpacing.lg),
              SizedBox(
                height: 48,
                child: FilledButton(
                  onPressed: () => onNext(context, ref),
                  child: Text(nextLabel),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ProgressDots extends StatelessWidget {
  const _ProgressDots({required this.activeIndex});
  final int activeIndex;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(_OnboardingStep.values.length, (i) {
        final active = i <= activeIndex;
        return AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          width: active ? 22 : 8,
          height: 8,
          margin: const EdgeInsets.symmetric(horizontal: 4),
          decoration: BoxDecoration(
            color: active ? ds.signal : ds.divider,
            borderRadius: BorderRadius.circular(4),
          ),
        );
      }),
    );
  }
}

class _Bullet extends StatelessWidget {
  const _Bullet({required this.icon, required this.label});
  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 22, color: context.ds.signal),
        const SizedBox(width: InsightSpacing.md),
        Expanded(child: Text(label, style: context.tt.bodyLarge)),
      ],
    );
  }
}
