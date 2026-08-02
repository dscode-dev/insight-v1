// Step 1 of the WhatsApp-style auth flow.
//
// Layout inspired by WhatsApp's "Verify your phone number" screen:
//   * Small Insight wordmark/logo at the top.
//   * Centered headline "Confirme seu número" + a paragraph of context.
//   * Country tile (Brazil + flag + +55) — display-only in V1 since the
//     product is BR-locked; styled as a tappable row so the disabled
//     state reads "selected" rather than dead.
//   * Phone input with live BR formatting (XX) XXXXX-XXXX as the user
//     types — feels native + reduces typos on hand-off to the OTP
//     screen.
//   * "Continuar" CTA anchored to the bottom safe-area so the keyboard
//     never covers it.
//   * Small legal-style footnote below the CTA explaining what
//     "Continuar" implies.
//
// Validation: same backend-driven story — we only do a digits-length
// sanity check locally before the round-trip; `phonenumbers` server-side
// is the source of truth.
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

class PhoneEntryScreen extends HookConsumerWidget {
  const PhoneEntryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final controller = useTextEditingController();
    final submitting = useState<bool>(false);
    final digits = useState<int>(0);
    // Auth-A.1: errors + transitions come from the Gateway phone-verification
    // flow now, not the legacy OTP notifier.
    final error = ref.watch(authFlowProvider.select((s) => s.errorMessage));

    // React to flow transitions. Guarded by isCurrent so the screen pushed on
    // top (OTP) owns its own transitions and we don't double-navigate.
    ref.listen(authFlowProvider.select((s) => s.status), (_, next) {
      if (!(ModalRoute.of(context)?.isCurrent ?? false)) return;
      switch (next) {
        case AuthFlowStatus.codeSent:
          submitting.value = false;
          unawaited(context.push(R.authOtp));
        case AuthFlowStatus.registrationRequired:
          // Android instant verification of a brand-new phone — straight to
          // the username step (no OTP screen needed).
          submitting.value = false;
          unawaited(context.push(R.authUsername));
        case AuthFlowStatus.error:
          submitting.value = false;
        case AuthFlowStatus.idle:
        case AuthFlowStatus.sendingCode:
        case AuthFlowStatus.verifying:
          break;
      }
    });

    // Keep a live counter of digits typed so the CTA enables/disables
    // without rebuilding the whole field.
    useEffect(() {
      void onChange() {
        digits.value = controller.text.replaceAll(RegExp(r'\D'), '').length;
      }

      controller.addListener(onChange);
      return () => controller.removeListener(onChange);
    }, [controller]);

    // BR mobile numbers: 11 digits (2 DDD + 9 subscriber). We unlock the
    // CTA at 10 to allow landlines / older formats; the backend has the
    // strict validator.
    final canSubmit = digits.value >= 10 && !submitting.value;

    Future<void> submit() async {
      if (!canSubmit) return;
      submitting.value = true;
      final digitsOnly = controller.text.replaceAll(RegExp(r'\D'), '');
      // Always send +55-prefixed form. Server defaults to BR but
      // explicit is safer for the day we ship a country picker.
      final phone = '+55$digitsOnly';
      // Auth-A.1: kick off Gateway phone verification. Navigation + error
      // display are driven by the flow-status listener above (codeSent →
      // push OTP; registrationRequired → push username; error → re-enable).
      await ref.read(authFlowProvider.notifier).startPhoneVerification(phone);
    }

    return Scaffold(
      // SafeArea bottom is false so the CTA hugs the home-indicator
      // area on iPhones with a notch — we add bottom padding manually
      // inside the CTA section instead.
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const _BrandHeader(),
            Expanded(
              child: SingleChildScrollView(
                physics: const ClampingScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(
                  InsightSpacing.xl2,
                  InsightSpacing.lg,
                  InsightSpacing.xl2,
                  InsightSpacing.xl,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      S.authPhoneTitle,
                      style: context.tt.displaySmall
                          ?.copyWith(fontWeight: FontWeight.w600),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: InsightSpacing.md),
                    Text(
                      S.authPhoneSubtitle,
                      style: context.tt.bodyMedium
                          ?.copyWith(color: context.ds.textMid, height: 1.4),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: InsightSpacing.xl2),
                    const _CountryTile(),
                    const SizedBox(height: InsightSpacing.md),
                    _PhoneField(
                      controller: controller,
                      onSubmitted: (_) => submit(),
                    ),
                    if (error != null) ...[
                      const SizedBox(height: InsightSpacing.md),
                      _ErrorBanner(message: error),
                    ],
                  ],
                ),
              ),
            ),
            _BottomCta(
              enabled: canSubmit,
              submitting: submitting.value,
              onTap: submit,
            ),
          ],
        ),
      ),
    );
  }
}

// ---- Header ---------------------------------------------------------------

class _BrandHeader extends StatelessWidget {
  const _BrandHeader();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: InsightSpacing.xl),
      child: Column(
        children: [
          // Soft circular halo behind the logo — picks up the brand
          // signal colour without dominating.
          Container(
            width: 72,
            height: 72,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: RadialGradient(
                colors: [
                  context.ds.signal.withValues(alpha: 0.16),
                  context.ds.signal.withValues(alpha: 0),
                ],
              ),
            ),
            alignment: Alignment.center,
            child: Image.asset(
              // Transparent mark — no black square on the auth background.
              'assets/image/insight-logo-transparent.png',
              width: 56,
              height: 56,
              fit: BoxFit.contain,
            ),
          ),
          const SizedBox(height: InsightSpacing.sm),
          Text(
            'Insight',
            style: context.tt.titleLarge?.copyWith(
              fontWeight: FontWeight.w700,
              letterSpacing: 0.2,
            ),
          ),
          const SizedBox(height: 2),
          // Azteca-X Part 2: clear product positioning on first contact.
          Text(
            'Sports Intelligence Platform',
            style: context.tt.bodySmall?.copyWith(
              color: context.ds.textLow,
              letterSpacing: 0.6,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}

// ---- Country tile ---------------------------------------------------------

class _CountryTile extends StatelessWidget {
  const _CountryTile();

  @override
  Widget build(BuildContext context) {
    return InkWell(
      // V1 is BR-locked; the tile is interactive-looking but the picker
      // hasn't shipped. When it does, swap this for the picker route.
      onTap: null,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        height: 56,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        decoration: BoxDecoration(
          color: context.ds.subtle,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: context.ds.divider),
        ),
        child: Row(
          children: [
            const Text('🇧🇷', style: TextStyle(fontSize: 24)),
            const SizedBox(width: InsightSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    S.authPhoneCountryLabel,
                    style: context.tt.labelSmall
                        ?.copyWith(color: context.ds.textLow),
                  ),
                  Text(
                    S.authPhoneCountryBR,
                    style: context.tt.titleMedium
                        ?.copyWith(fontWeight: FontWeight.w500),
                  ),
                ],
              ),
            ),
            Icon(
              Icons.expand_more_rounded,
              color: context.ds.textLow,
              size: 22,
            ),
          ],
        ),
      ),
    );
  }
}

// ---- Phone field ----------------------------------------------------------

class _PhoneField extends StatelessWidget {
  const _PhoneField({required this.controller, required this.onSubmitted});
  final TextEditingController controller;
  final ValueChanged<String> onSubmitted;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Container(
          height: 56,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: context.ds.subtle,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: context.ds.divider),
          ),
          child: Text(
            S.authPhoneCountryDial,
            style:
                context.tt.titleMedium?.copyWith(fontWeight: FontWeight.w600),
          ),
        ),
        const SizedBox(width: InsightSpacing.md),
        Expanded(
          child: SizedBox(
            height: 56,
            child: TextField(
              controller: controller,
              keyboardType: TextInputType.phone,
              autofocus: true,
              autofillHints: const [AutofillHints.telephoneNumber],
              onSubmitted: onSubmitted,
              style:
                  context.tt.titleMedium?.copyWith(fontWeight: FontWeight.w500),
              inputFormatters: [
                FilteringTextInputFormatter.digitsOnly,
                _BrazilianPhoneFormatter(),
                LengthLimitingTextInputFormatter(15),
              ],
              decoration: InputDecoration(
                hintText: S.authPhoneHint,
                filled: true,
                fillColor: context.ds.subtle,
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 14,
                ),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(color: context.ds.divider),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(color: context.ds.divider),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(color: context.ds.signal, width: 1.5),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

// ---- Bottom CTA -----------------------------------------------------------

class _BottomCta extends StatelessWidget {
  const _BottomCta({
    required this.enabled,
    required this.submitting,
    required this.onTap,
  });

  final bool enabled;
  final bool submitting;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: context.ds.background,
        border: Border(top: BorderSide(color: context.ds.divider)),
      ),
      padding: EdgeInsets.fromLTRB(
        InsightSpacing.xl2,
        InsightSpacing.lg,
        InsightSpacing.xl2,
        InsightSpacing.lg + MediaQuery.viewPaddingOf(context).bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            height: 52,
            width: double.infinity,
            child: FilledButton(
              onPressed: enabled ? onTap : null,
              style: FilledButton.styleFrom(
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
              child: submitting
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Text(
                      S.authPhoneCta,
                      style: TextStyle(fontWeight: FontWeight.w600),
                    ),
            ),
          ),
          const SizedBox(height: InsightSpacing.sm),
          Text(
            S.authPhoneFootnote,
            style: context.tt.labelSmall?.copyWith(
              color: context.ds.textLow,
              height: 1.4,
            ),
            textAlign: TextAlign.center,
          ),
        ],
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
        border: Border.all(
          color: context.ds.confidenceLow.withValues(alpha: 0.3),
        ),
      ),
      child: Row(
        children: [
          Icon(Icons.error_outline, size: 18, color: context.ds.confidenceLow),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: context.tt.bodyMedium
                  ?.copyWith(color: context.ds.confidenceLow),
            ),
          ),
        ],
      ),
    );
  }
}

// ---- Phone formatter ------------------------------------------------------

/// Formats raw digits as a Brazilian phone number while the user types:
///
///   1            → "1"
///   11           → "11"
///   112          → "(11) 2"
///   119          → "(11) 9"
///   1199         → "(11) 99"
///   11999        → "(11) 999"
///   119999       → "(11) 9999"
///   1199999      → "(11) 99999"
///   119999999    → "(11) 9999-9999"      (landline; 10 digits)
///   1199999999   → "(11) 99999-9999"     (mobile; 11 digits)
///
/// Cursor handling: the formatter always moves the caret to the end
/// after rewriting — keeps the UX simple. For a richer experience
/// (caret-preserving) a more elaborate `IntlPhoneFormatter` would be
/// the next step.
class _BrazilianPhoneFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final digits = newValue.text.replaceAll(RegExp(r'\D'), '');
    final formatted = _format(digits);
    return TextEditingValue(
      text: formatted,
      selection: TextSelection.collapsed(offset: formatted.length),
    );
  }

  static String _format(String digits) {
    if (digits.isEmpty) return '';
    final buf = StringBuffer();
    // Up to 2 DDD digits inside parens.
    if (digits.length <= 2) {
      buf.write(digits);
      return buf.toString();
    }
    buf.write('(${digits.substring(0, 2)}) ');
    // Subscriber number: split with dash at the right pivot.
    final rest = digits.substring(2);
    if (rest.length <= 4) {
      buf.write(rest);
    } else if (rest.length <= 8) {
      // 4-N format (landlines): "9999-9..." up to "9999-9999"
      buf
        ..write(rest.substring(0, 4))
        ..write('-')
        ..write(rest.substring(4));
    } else {
      // 5-4 format (mobile): "99999-9999"
      buf
        ..write(rest.substring(0, 5))
        ..write('-')
        ..write(rest.substring(5, rest.length.clamp(5, 9)));
    }
    return buf.toString();
  }
}
