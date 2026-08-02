// AZTECA-PROFILE-A — Settings, reorganized into calm, grouped sections.
//
// Visual language inspired by the *organization* of iOS Settings (grouped
// soft cards, leading icon, title, optional subtitle, chevron) — not a copy.
// Business logic is unchanged: theme (themeModeProvider), notification/locale
// preferences (PreferencesNotifier → one PUT per change), legal sheets, and
// logout (authProvider) all behave exactly as before.
import 'package:flutter/material.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../core/legal.dart';
import '../../models/preferences.dart';
import '../../providers/auth_provider.dart' show authProvider;
import '../../providers/preferences_provider.dart';
import '../../providers/settings_provider.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../shared/strings/pt_br.dart';
import '../../theme/spacing.dart';
import '../../widgets/insight_bottom_sheet.dart';

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(themeModeProvider);
    final prefsAsync = ref.watch(preferencesNotifierProvider);
    final notifier = ref.read(preferencesNotifierProvider.notifier);
    final user = ref.watch(authProvider.select((s) => s.user));

    return Scaffold(
      appBar: AppBar(title: const Text('Configurações')),
      body: ListView(
        // Stage 6 — preserve scroll position across visits.
        key: const PageStorageKey('settings_scroll'),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.only(bottom: InsightSpacing.xl3),
        children: [
          // -------- Conta --------
          _Group(
            title: 'Conta',
            children: [
              _SettingsTile(
                icon: Icons.alternate_email_rounded,
                title: 'Nome de usuário',
                subtitle: (user?.username.isNotEmpty ?? false)
                    ? '@${user!.username}'
                    : '—',
              ),
              if (user?.phoneE164 != null && user!.phoneE164!.isNotEmpty)
                _SettingsTile(
                  icon: Icons.phone_iphone_rounded,
                  title: 'Telefone',
                  subtitle: user.phoneE164!,
                ),
            ],
          ),

          // -------- Aplicativo (LOCAL — device-only, not synced) --------
          _Group(
            title: 'Aplicativo',
            footnote: 'O tema é salvo apenas neste dispositivo.',
            children: [
              _SettingsTile(
                icon: Icons.brightness_auto_outlined,
                title: 'Seguir o sistema',
                subtitle: 'Acompanha o tema do dispositivo',
                trailing: _check(context, mode == ThemeMode.system),
                onTap: () =>
                    ref.read(themeModeProvider.notifier).set(ThemeMode.system),
              ),
              _SettingsTile(
                icon: Icons.light_mode_outlined,
                title: 'Claro',
                subtitle: 'Fundo branco, contraste alto',
                trailing: _check(context, mode == ThemeMode.light),
                onTap: () =>
                    ref.read(themeModeProvider.notifier).set(ThemeMode.light),
              ),
              _SettingsTile(
                icon: Icons.dark_mode_outlined,
                title: 'Escuro',
                subtitle: 'Fundo carvão, descansa a vista',
                trailing: _check(context, mode == ThemeMode.dark),
                onTap: () =>
                    ref.read(themeModeProvider.notifier).set(ThemeMode.dark),
              ),
            ],
          ),

          // -------- Cache (LOCAL — device-only) --------
          _Group(
            title: 'Cache',
            footnote: 'Itens locais. Não afetam seus dados na conta.',
            children: [
              _SettingsTile(
                icon: Icons.image_outlined,
                title: 'Limpar cache de imagens',
                subtitle: 'Recarrega avatares e capas na próxima abertura',
                onTap: () {
                  PaintingBinding.instance.imageCache.clear();
                  PaintingBinding.instance.imageCache.clearLiveImages();
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Cache de imagens limpo.')),
                  );
                },
              ),
            ],
          ),

          // -------- Notificações --------
          prefsAsync.when(
            loading: () => const _Group(
              title: 'Notificações',
              children: [_TileLoading()],
            ),
            error: (e, _) => _Group(
              title: 'Notificações',
              children: [
                _TileError(
                    onRetry: () => ref.invalidate(preferencesNotifierProvider)),
              ],
            ),
            data: (prefs) => _Group(
              title: 'Notificações',
              children: [
                _SwitchTile(
                  icon: Icons.notifications_outlined,
                  title: 'Push',
                  subtitle: 'Partidas e sinais que você segue',
                  value: prefs.pushEnabled,
                  onChanged: notifier.setPushEnabled,
                ),
                _SwitchTile(
                  icon: Icons.mail_outline_rounded,
                  title: 'E-mail',
                  subtitle: 'Resumo das suas comunidades',
                  value: prefs.emailEnabled,
                  onChanged: notifier.setEmailEnabled,
                ),
                _SettingsTile(
                  icon: Icons.schedule_outlined,
                  title: 'Frequência do resumo',
                  subtitle: DigestFrequency.labelPtBr(prefs.digestFrequency),
                  onTap: () => _pickDigestFrequency(context, prefs, notifier),
                ),
              ],
            ),
          ),

          // -------- Idioma --------
          prefsAsync.maybeWhen(
            data: (prefs) => _Group(
              title: 'Idioma',
              footnote:
                  'A tradução completa das telas chega em uma próxima versão. Sua escolha já é salva.',
              children: [
                for (final code in SupportedLocales.all)
                  _SettingsTile(
                    icon: Icons.translate_rounded,
                    title: SupportedLocales.label(code),
                    trailing: _check(context, prefs.locale == code),
                    onTap: () => notifier.setLocale(code),
                  ),
              ],
            ),
            orElse: () => const SizedBox.shrink(),
          ),

          // -------- Esportes (prepared; no backend yet — honestly disabled) --
          const _Group(
            title: 'Esportes',
            children: [
              _SettingsTile(
                icon: Icons.shield_outlined,
                title: 'Time favorito',
                subtitle: 'Escolha o time que representa você',
                enabled: false,
                trailing: _Badge(text: 'Em breve'),
              ),
              _SettingsTile(
                icon: Icons.emoji_events_outlined,
                title: 'Competições que sigo',
                subtitle: 'Personalize seu radar esportivo',
                enabled: false,
                trailing: _Badge(text: 'Em breve'),
              ),
            ],
          ),

          // -------- Privacidade --------
          _Group(
            title: 'Privacidade',
            children: [
              _SettingsTile(
                icon: Icons.privacy_tip_outlined,
                title: 'Política de Privacidade',
                subtitle: 'Versão $kPrivacyVersion · $kLegalEffectiveDate',
                onTap: () => showPrivacyPolicy(context),
              ),
              const _SettingsTile(
                icon: Icons.block_rounded,
                title: 'Contas bloqueadas',
                subtitle: 'Gerencie quem você bloqueou',
                enabled: false,
                trailing: _Badge(text: 'Em breve'),
              ),
              const _SettingsTile(
                icon: Icons.fingerprint_rounded,
                title: 'Login biométrico',
                subtitle: 'Face ID · Touch ID · Passkey',
                enabled: false,
                trailing: _Badge(text: 'Em breve'),
              ),
            ],
          ),

          // -------- Suporte --------
          _Group(
            title: 'Suporte',
            children: [
              _SettingsTile(
                icon: Icons.policy_rounded,
                title: 'Central legal',
                subtitle: 'Termos, Privacidade e Segurança UGC',
                onTap: () => showLegalCenter(context),
              ),
              _SettingsTile(
                icon: Icons.description_outlined,
                title: 'Termos de Uso',
                subtitle: 'Versão $kTermsVersion · $kLegalEffectiveDate',
                onTap: () => showTermsOfUse(context),
              ),
              _SettingsTile(
                icon: Icons.shield_outlined,
                title: 'Política de Segurança UGC',
                subtitle: 'Versão $kUgcPolicyVersion · $kLegalEffectiveDate',
                onTap: () => showUgcSafetyPolicy(context),
              ),
            ],
          ),

          // -------- Sobre --------
          const _Group(
            title: 'Sobre',
            children: [
              _SettingsTile(
                icon: Icons.info_outline_rounded,
                title: 'Versão',
                subtitle: '0.1.0+1',
              ),
              _SettingsTile(
                icon: Icons.favorite_outline_rounded,
                title: 'Insight',
                subtitle: 'AllBlue-Labs · 2026',
              ),
            ],
          ),

          // -------- Sessão --------
          _Group(
            title: 'Sessão',
            children: [
              _SettingsTile(
                icon: Icons.logout_rounded,
                title: S.profileLogout,
                destructive: true,
                onTap: () => _confirmLogout(context, ref),
              ),
            ],
          ),
        ],
      ),
    );
  }

  static Widget _check(BuildContext context, bool on) => on
      ? Icon(Icons.check_rounded, color: context.ds.signal, size: 20)
      : const SizedBox(width: 20);

  Future<void> _pickDigestFrequency(
    BuildContext context,
    UserPreferences current,
    PreferencesNotifier notifier,
  ) async {
    final chosen = await showInsightBottomSheet<String>(
      context: context,
      builder: (_) => InsightBottomSheet(
        title: 'Frequência do resumo',
        subtitle: 'Escolha como quer receber o digest das comunidades.',
        children: [
          RadioGroup<String>(
            groupValue: current.digestFrequency,
            onChanged: (v) => Navigator.of(context).pop(v),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (final f in DigestFrequency.all)
                  RadioListTile<String>(
                    title: Text(DigestFrequency.labelPtBr(f)),
                    value: f,
                  ),
              ],
            ),
          ),
        ],
      ),
    );
    if (chosen != null && chosen != current.digestFrequency) {
      await notifier.setDigestFrequency(chosen);
    }
  }

  Future<void> _confirmLogout(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text(S.profileLogoutConfirmTitle),
        content: const Text(S.profileLogoutConfirmDescription),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text(S.profileLogoutCancel),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text(S.profileLogout),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await ref.read(authProvider.notifier).logout();
    }
  }
}

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------

/// A titled group: quiet uppercase header + a single soft rounded card with the
/// items stacked inside (thin insets between). No heavy borders or shadows.
class _Group extends StatelessWidget {
  const _Group({required this.title, required this.children, this.footnote});

  final String title;
  final List<Widget> children;
  final String? footnote;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(InsightSpacing.xl,
              InsightSpacing.xl, InsightSpacing.xl, InsightSpacing.sm),
          child: Text(
            title.toUpperCase(),
            style: context.tt.labelSmall?.copyWith(
              color: ds.textMid,
              letterSpacing: 0.6,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        Container(
          margin: const EdgeInsets.symmetric(horizontal: InsightSpacing.lg),
          decoration: BoxDecoration(
            color: ds.card,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
                color: ds.divider.withValues(alpha: 0.5), width: 0.6),
          ),
          clipBehavior: Clip.antiAlias,
          child: Column(
            children: [
              for (var i = 0; i < children.length; i++) ...[
                if (i > 0)
                  Padding(
                    padding: const EdgeInsets.only(left: 56),
                    child:
                        Divider(height: 0.6, thickness: 0.6, color: ds.divider),
                  ),
                children[i],
              ],
            ],
          ),
        ),
        if (footnote != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(
                InsightSpacing.xl, InsightSpacing.sm, InsightSpacing.xl, 0),
            child: Text(
              footnote!,
              style: context.tt.bodySmall?.copyWith(color: ds.textLow),
            ),
          ),
      ],
    );
  }
}

/// A leading rounded-square icon used by every settings item.
class _LeadingIcon extends StatelessWidget {
  const _LeadingIcon({required this.icon, this.tint, this.muted = false});
  final IconData icon;
  final Color? tint;
  final bool muted;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Container(
      width: 32,
      height: 32,
      decoration: BoxDecoration(
        color: (tint ?? ds.signal).withValues(alpha: muted ? 0.06 : 0.12),
        borderRadius: BorderRadius.circular(9),
      ),
      child:
          Icon(icon, size: 18, color: muted ? ds.textLow : (tint ?? ds.signal)),
    );
  }
}

/// A single tappable / informational settings row.
class _SettingsTile extends StatelessWidget {
  const _SettingsTile({
    required this.icon,
    required this.title,
    this.subtitle,
    this.trailing,
    this.onTap,
    this.enabled = true,
    this.destructive = false,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final VoidCallback? onTap;
  final bool enabled;
  final bool destructive;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    final titleColor = !enabled
        ? ds.textLow
        : destructive
            ? ds.signal
            : ds.textHigh;
    final tile = Padding(
      padding: const EdgeInsets.symmetric(
          horizontal: InsightSpacing.md, vertical: 12),
      child: Row(
        children: [
          _LeadingIcon(
            icon: icon,
            tint: destructive ? ds.signal : null,
            muted: !enabled,
          ),
          const SizedBox(width: InsightSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: context.tt.bodyLarge?.copyWith(
                        color: titleColor, fontWeight: FontWeight.w500)),
                if (subtitle != null) ...[
                  const SizedBox(height: 2),
                  Text(subtitle!,
                      style: context.tt.bodySmall?.copyWith(color: ds.textLow)),
                ],
              ],
            ),
          ),
          const SizedBox(width: InsightSpacing.sm),
          trailing ??
              (onTap != null
                  ? Icon(Icons.chevron_right_rounded,
                      color: ds.textLow, size: 22)
                  : const SizedBox.shrink()),
        ],
      ),
    );

    return Semantics(
      button: onTap != null,
      enabled: enabled,
      label: subtitle == null ? title : '$title. $subtitle',
      child: InkWell(
        onTap: enabled ? onTap : null,
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 56),
          child: tile,
        ),
      ),
    );
  }
}

/// A settings row whose trailing control is a switch.
class _SwitchTile extends StatelessWidget {
  const _SwitchTile({
    required this.icon,
    required this.title,
    required this.value,
    required this.onChanged,
    this.subtitle,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final ds = context.ds;
    return Semantics(
      toggled: value,
      label: subtitle == null ? title : '$title. $subtitle',
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 56),
        child: Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: InsightSpacing.md, vertical: 8),
          child: Row(
            children: [
              _LeadingIcon(icon: icon),
              const SizedBox(width: InsightSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title,
                        style: context.tt.bodyLarge?.copyWith(
                            color: ds.textHigh, fontWeight: FontWeight.w500)),
                    if (subtitle != null) ...[
                      const SizedBox(height: 2),
                      Text(subtitle!,
                          style: context.tt.bodySmall
                              ?.copyWith(color: ds.textLow)),
                    ],
                  ],
                ),
              ),
              Switch.adaptive(value: value, onChanged: onChanged),
            ],
          ),
        ),
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({required this.text});
  final String text;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: context.ds.subtle,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(text,
          style: context.tt.labelSmall?.copyWith(color: context.ds.textMid)),
    );
  }
}

class _TileLoading extends StatelessWidget {
  const _TileLoading();
  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.symmetric(vertical: 22),
        child: Center(
          child: SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ),
      );
}

class _TileError extends StatelessWidget {
  const _TileError({required this.onRetry});
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) {
    return _SettingsTile(
      icon: Icons.error_outline_rounded,
      title: 'Não consegui carregar as preferências',
      subtitle: 'Toque para tentar novamente',
      onTap: onRetry,
    );
  }
}
