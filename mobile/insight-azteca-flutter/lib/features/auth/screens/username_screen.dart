import 'dart:async';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../core/legal.dart';
import '../../../models/auth.dart';
import '../../../providers/auth_flow_provider.dart';
import '../../../providers/auth_provider.dart';
import '../../../routing/routes.dart';
import '../../../shared/extensions/build_context_x.dart';
import '../../../shared/strings/pt_br.dart';
import '../../../theme/spacing.dart';

/// Step 3 of the WhatsApp-style flow — only reached when verify_otp
/// returned `status: registration_required`.
///
/// Asks for a username (3-32 chars, lowercase + digits + . _ -) and a
/// display name. Submits to /v1/auth/register via the notifier; on
/// success the auth status flips to authenticated and the router
/// redirects to /home.
class UsernameScreen extends HookConsumerWidget {
  const UsernameScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final flow = ref.watch(authFlowProvider);
    final token = flow.registrationToken;
    final phone = flow.phoneE164;

    useEffect(() {
      // Defensive: if the user got here without a registration token,
      // restart the flow.
      if (token == null || phone == null) {
        scheduleMicrotask(() {
          if (context.mounted) context.go(R.authPhone);
        });
      }
      return null;
    }, const []);

    final firstNameCtrl = useTextEditingController();
    final lastNameCtrl = useTextEditingController();
    final usernameCtrl = useTextEditingController();
    final usernameError = useState<String?>(null);
    final displayNameError = useState<String?>(null);
    final termsAccepted = useState<bool>(false);
    final termsError = useState<bool>(false);
    final submitting = useState<bool>(false);
    final error = ref.watch(authProvider.select((s) => s.errorMessage));

    Future<void> submit() async {
      if (submitting.value || token == null || phone == null) return;
      final u = usernameCtrl.text.trim().toLowerCase();
      // Azteca-Y Part 1: first + last name compose the backend `displayName`
      // (the gateway's phone-OTP identity has no separate name fields, so we
      // map to the real contract — no parallel auth flow / no fake fields).
      final first = firstNameCtrl.text.trim();
      final last = lastNameCtrl.text.trim();
      final d = [first, last].where((s) => s.isNotEmpty).join(' ');

      // Local validation matches the backend rules so the user doesn't
      // burn a round-trip on obvious typos.
      usernameError.value = !_validUsername(u)
          ? 'Use 3-32 caracteres: letras, números, . _ -'
          : null;
      displayNameError.value = first.isEmpty ? 'Informe seu nome.' : null;
      // Store-A: block account creation without accepting the Terms.
      termsError.value = !termsAccepted.value;
      if (usernameError.value != null ||
          displayNameError.value != null ||
          termsError.value) {
        return;
      }

      submitting.value = true;
      try {
        await ref.read(authProvider.notifier).completeRegistration(
              CompleteRegistrationRequest(
                registrationToken: token,
                username: u,
                displayName: d,
              ),
              phoneE164: phone,
            );
        ref.read(authFlowProvider.notifier).reset();
        // Router redirect handles the navigation; nothing else to do.
      } catch (_) {
        // Message lives in authProvider.errorMessage.
      } finally {
        if (context.mounted) submitting.value = false;
      }
    }

    if (token == null || phone == null) {
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
          child: AutofillGroup(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(S.authUsernameTitle, style: context.tt.displayLarge),
                const SizedBox(height: InsightSpacing.sm),
                Text(
                  S.authUsernameSubtitle,
                  style: context.tt.bodyMedium
                      ?.copyWith(color: context.ds.textMid),
                ),
                const SizedBox(height: InsightSpacing.xl3),
                TextField(
                  controller: usernameCtrl,
                  inputFormatters: [
                    FilteringTextInputFormatter.allow(
                      RegExp(r'[a-z0-9._\-]'),
                    ),
                    LengthLimitingTextInputFormatter(32),
                  ],
                  autofillHints: const [AutofillHints.username],
                  autocorrect: false,
                  textInputAction: TextInputAction.next,
                  decoration: InputDecoration(
                    labelText: S.authUsernameLabel,
                    prefixText: '@',
                    errorText: usernameError.value,
                  ),
                ),
                const SizedBox(height: InsightSpacing.md),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: TextField(
                        controller: firstNameCtrl,
                        autofillHints: const [AutofillHints.givenName],
                        textCapitalization: TextCapitalization.words,
                        textInputAction: TextInputAction.next,
                        decoration: InputDecoration(
                          labelText: 'Nome',
                          errorText: displayNameError.value,
                        ),
                      ),
                    ),
                    const SizedBox(width: InsightSpacing.md),
                    Expanded(
                      child: TextField(
                        controller: lastNameCtrl,
                        autofillHints: const [AutofillHints.familyName],
                        textCapitalization: TextCapitalization.words,
                        textInputAction: TextInputAction.done,
                        decoration:
                            const InputDecoration(labelText: 'Sobrenome'),
                        onSubmitted: (_) => submit(),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: InsightSpacing.lg),
                _TermsCheckbox(
                  accepted: termsAccepted.value,
                  showError: termsError.value,
                  onChanged: (v) {
                    termsAccepted.value = v;
                    if (v) termsError.value = false;
                  },
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
                      : const Text(S.authUsernameCta),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

bool _validUsername(String u) {
  if (u.length < 3 || u.length > 32) return false;
  return RegExp(r'^[a-z0-9._\-]+$').hasMatch(u);
}

/// Mandatory legal acceptance. All policies open in-app; registration is
/// blocked until [accepted] is true. The Gateway currently persists only
/// `accepted_terms_version`, so privacy/UGC versions remain a documented
/// backend compatibility gap.
class _TermsCheckbox extends StatelessWidget {
  const _TermsCheckbox({
    required this.accepted,
    required this.showError,
    required this.onChanged,
  });

  final bool accepted;
  final bool showError;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final base = context.tt.bodySmall?.copyWith(color: context.ds.textMid);
    final link = base?.copyWith(
      color: context.ds.signal,
      fontWeight: FontWeight.w600,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 28,
              height: 28,
              child: Checkbox(
                value: accepted,
                onChanged: (v) => onChanged(v ?? false),
              ),
            ),
            const SizedBox(width: InsightSpacing.sm),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text.rich(
                  TextSpan(
                    style: base,
                    children: [
                      const TextSpan(text: 'Li e aceito os '),
                      TextSpan(
                        text: 'Termos de Uso',
                        style: link,
                        recognizer: TapGestureRecognizer()
                          ..onTap = () => showTermsOfUse(context),
                      ),
                      const TextSpan(text: ' e a '),
                      TextSpan(
                        text: 'Política de Privacidade',
                        style: link,
                        recognizer: TapGestureRecognizer()
                          ..onTap = () => showPrivacyPolicy(context),
                      ),
                      const TextSpan(text: ' e a '),
                      TextSpan(
                        text: 'Política de Segurança UGC',
                        style: link,
                        recognizer: TapGestureRecognizer()
                          ..onTap = () => showUgcSafetyPolicy(context),
                      ),
                      const TextSpan(text: '.'),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
        if (showError)
          Padding(
            padding: const EdgeInsets.only(left: 8, top: 2),
            child: Text(
              'Você precisa aceitar os Termos, a Privacidade e a Política UGC para criar a conta.',
              style: context.tt.bodySmall
                  ?.copyWith(color: context.ds.confidenceLow),
            ),
          ),
      ],
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
