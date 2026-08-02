// Auth method entry (Azteca-Y.5 Part 2).
//
// The landing screen of the auth flow: the operator chooses how to continue.
// Today only "Continuar com telefone" is active (phone-OTP is the gateway's
// identity). Biometrics / Passkeys are shown as a disabled "em breve" section —
// VISUAL PREPARATION ONLY for the future Auth-A sprint (no provider SDK, no
// WebAuthn, no backend). Routes/providers/contracts are untouched: selecting
// phone simply navigates to the existing R.authPhone screen.
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../routing/routes.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../theme/spacing.dart';

class AuthEntryScreen extends StatelessWidget {
  const AuthEntryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: InsightSpacing.xl2,
            vertical: InsightSpacing.xl2,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Spacer(flex: 3),
              // Brand block — logo halo + wordmark + tagline.
              Center(
                child: Column(
                  children: [
                    Container(
                      width: 96,
                      height: 96,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        gradient: RadialGradient(
                          colors: [
                            ds.signal.withValues(alpha: 0.20),
                            ds.signal.withValues(alpha: 0),
                          ],
                        ),
                      ),
                      child: Image.asset(
                        'assets/image/insight-logo-transparent.png',
                        width: 68,
                        height: 68,
                        fit: BoxFit.contain,
                      ),
                    ),
                    const SizedBox(height: InsightSpacing.lg),
                    Text(
                      'Insight',
                      style: context.tt.displaySmall?.copyWith(
                        fontWeight: FontWeight.w800,
                        letterSpacing: -0.5,
                      ),
                    ),
                    const SizedBox(height: InsightSpacing.xs),
                    Text(
                      'Inteligência social esportiva',
                      style: context.tt.titleSmall?.copyWith(
                        color: ds.textMid,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: InsightSpacing.xl3),
              // Value props — give the screen substance and set expectations.
              const _FeatureRow(
                icon: Icons.bolt_rounded,
                label: 'Sinais e leituras de jogo em tempo real',
              ),
              const SizedBox(height: InsightSpacing.md),
              const _FeatureRow(
                icon: Icons.forum_rounded,
                label: 'Discussões e comunidades de clubes',
              ),
              const SizedBox(height: InsightSpacing.md),
              const _FeatureRow(
                icon: Icons.smart_toy_rounded,
                label: 'Agentes de inteligência esportiva',
              ),
              const Spacer(flex: 3),
              // Primary CTA — full-width, tall, unmistakable.
              SizedBox(
                height: 54,
                child: FilledButton.icon(
                  onPressed: () => context.go(R.authPhone),
                  icon: const Icon(Icons.smartphone_rounded, size: 20),
                  style: FilledButton.styleFrom(
                    textStyle: context.tt.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(16),
                    ),
                  ),
                  label: const Text('Continuar com telefone'),
                ),
              ),
              const SizedBox(height: InsightSpacing.md),
              // Privacy reassurance with a lock glyph.
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.lock_outline_rounded, size: 14, color: ds.textLow),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(
                      'Usamos seu telefone apenas para proteger o acesso à conta.',
                      textAlign: TextAlign.center,
                      style: context.tt.bodySmall?.copyWith(
                        color: ds.textLow,
                        height: 1.3,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: InsightSpacing.sm),
            ],
          ),
        ),
      ),
    );
  }
}

/// A single value-proposition row on the login screen: a tinted icon tile and
/// a short label, giving the screen production substance.
class _FeatureRow extends StatelessWidget {
  const _FeatureRow({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Row(
      children: [
        Container(
          width: 38,
          height: 38,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: ds.signal.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(11),
          ),
          child: Icon(icon, size: 20, color: ds.signal),
        ),
        const SizedBox(width: InsightSpacing.md),
        Expanded(
          child: Text(
            label,
            style: context.tt.bodyMedium?.copyWith(
              color: ds.textHigh,
              fontWeight: FontWeight.w500,
            ),
          ),
        ),
      ],
    );
  }
}
