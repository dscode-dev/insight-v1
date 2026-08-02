import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../providers/auth_flow_provider.dart';
import '../../../routing/routes.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/strings/pt_br.dart';
import '../../../theme/spacing.dart';

/// Step 2 of the WhatsApp-style flow.
///
/// Shows a 6-digit OTP input and a resend timer. On submit:
///   * status == "ok"                    → notifier already accepted
///     the session; the router redirect flips us to /home automatically.
///   * status == "registration_required" → stash the registration token
///     in authFlowProvider, navigate to /auth/username.
class OtpVerifyScreen extends HookConsumerWidget {
  const OtpVerifyScreen({super.key});

  static const Duration _resendCooldown = Duration(seconds: 60);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final flow = ref.watch(authFlowProvider);
    final phone = flow.phoneE164;

    // Defensive — if the user landed here without a phone in the flow
    // state (deep-link, hot-reload), kick them back to step 1.
    useEffect(() {
      if (phone == null) {
        scheduleMicrotask(() {
          if (context.mounted) context.go(R.authPhone);
        });
      }
      return null;
    }, const []);

    final controller = useTextEditingController();
    final submitting = useState<bool>(false);
    final resendRemaining = useState<int>(_resendCooldown.inSeconds);
    // Auth-A.1: errors + transitions now come from the Gateway phone flow.
    final error = ref.watch(authFlowProvider.select((s) => s.errorMessage));

    // Resend cooldown ticker — 1Hz, stops when the screen unmounts.
    useEffect(() {
      final ticker = Timer.periodic(const Duration(seconds: 1), (_) {
        if (resendRemaining.value > 0) {
          resendRemaining.value = resendRemaining.value - 1;
        }
      });
      return ticker.cancel;
    }, const []);

    // React to flow transitions. isCurrent guards against the (mounted-below)
    // phone screen also firing on the same transition.
    ref.listen(authFlowProvider.select((s) => s.status), (_, next) {
      if (!(ModalRoute.of(context)?.isCurrent ?? false)) return;
      switch (next) {
        case AuthFlowStatus.registrationRequired:
          submitting.value = false;
          unawaited(context.push(R.authUsername));
        case AuthFlowStatus.error:
          submitting.value = false;
        case AuthFlowStatus.idle:
        case AuthFlowStatus.sendingCode:
        case AuthFlowStatus.codeSent:
        case AuthFlowStatus.verifying:
          break;
      }
      // status drives to login via AuthNotifier → router redirect.
    });

    Future<void> submit() async {
      if (submitting.value || phone == null) return;
      final code = controller.text.trim();
      if (code.length < 6) return;
      submitting.value = true;
      // confirmSmsCode verifies through Gateway; Gateway owns provider choice
      // navigation/error handled by the flow-status listener above. Reset the
      // spinner once it settles (on login success the screen is already
      // unmounting, so the mounted guard short-circuits).
      await ref.read(authFlowProvider.notifier).confirmSmsCode(code);
      if (context.mounted) submitting.value = false;
    }

    Future<void> resend() async {
      if (resendRemaining.value > 0 || phone == null) return;
      // Re-issue the SMS through Gateway.
      await ref.read(authFlowProvider.notifier).startPhoneVerification(phone);
      resendRemaining.value = _resendCooldown.inSeconds;
    }

    if (phone == null) {
      return const Scaffold(body: SizedBox.shrink());
    }

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: () => context.pop(),
        ),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(
            horizontal: InsightSpacing.xl2,
            vertical: InsightSpacing.xl3,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(S.authOtpTitle, style: context.tt.displayLarge),
              const SizedBox(height: InsightSpacing.sm),
              Text.rich(
                TextSpan(
                  style: context.tt.bodyMedium
                      ?.copyWith(color: context.ds.textMid),
                  children: [
                    const TextSpan(text: '${S.authOtpSubtitle} '),
                    TextSpan(
                      text: phone,
                      style: TextStyle(
                        color: context.ds.textHigh,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const TextSpan(text: '.'),
                  ],
                ),
              ),
              const SizedBox(height: InsightSpacing.xl3),
              TextField(
                controller: controller,
                keyboardType: TextInputType.number,
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  LengthLimitingTextInputFormatter(6),
                ],
                autofillHints: const [AutofillHints.oneTimeCode],
                style: context.tt.displayLarge?.copyWith(
                  fontFeatures: const [FontFeature.tabularFigures()],
                  letterSpacing: 12,
                ),
                textAlign: TextAlign.center,
                onSubmitted: (_) => submit(),
                decoration: const InputDecoration(
                  counterText: '',
                  hintText: '••••••',
                ),
              ),
              if (error != null) ...[
                const SizedBox(height: InsightSpacing.md),
                _ErrorBanner(message: error),
              ],
              const SizedBox(height: InsightSpacing.xl),
              FilledButton(
                onPressed: submitting.value ? null : submit,
                child: submitting.value
                    ? const SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Text('Confirmar'),
              ),
              const SizedBox(height: InsightSpacing.lg),
              Center(
                child: resendRemaining.value > 0
                    ? Text(
                        '${S.authOtpResendIn} ${resendRemaining.value}s',
                        style: context.tt.bodySmall
                            ?.copyWith(color: context.ds.textLow),
                      )
                    : TextButton(
                        onPressed: resend,
                        child: const Text(S.authOtpResend),
                      ),
              ),
              Center(
                child: TextButton(
                  onPressed: () {
                    ref.read(authFlowProvider.notifier).reset();
                    context.go(R.authPhone);
                  },
                  child: const Text(S.authOtpChangeNumber),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: context.ds.confidenceLow.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        message,
        style: context.tt.bodyMedium?.copyWith(color: context.ds.confidenceLow),
      ),
    );
  }
}
