import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/avatar_cache.dart';
import '../../providers/auth_provider.dart';
import '../../providers/feed_provider.dart';
import '../../providers/profile_provider.dart';
import '../../providers/user_profile_provider.dart';
import '../../services/services_providers.dart';
import '../../services/social_service.dart';
import '../../shared/extensions/build_context_x.dart';
import '../../theme/spacing.dart';
import 'profile_screen.dart' show avatarUploadErrorMessage;

/// AZTECA-PROFILE-B — real Edit Profile.
///
/// Replaces the previous misroute where the Edit button opened the avatar picker
/// directly. This is a dedicated route (multiple concerns + keyboard + avatar
/// action justify a screen over a bottom sheet). It edits ONLY fields the backend
/// truly models + owns: **display_name** (the sole writable Core Identity text
/// field). Avatar is one action WITHIN the form — a failure/unavailability there
/// never discards the text edits. Fields the schema does not model (bio, favorite
/// team, location, role) are NOT shown as fake-enabled inputs; they are honestly
/// deferred. Save persists via PATCH /v1/users/me and only clears dirty/pops after
/// authoritative confirmation.
class EditProfileScreen extends ConsumerStatefulWidget {
  const EditProfileScreen({super.key});

  @override
  ConsumerState<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends ConsumerState<EditProfileScreen> {
  late final TextEditingController _name;
  late final String _originalName;
  bool _saving = false;
  bool _avatarBusy = false;
  String? _error; // form-level (display name) error
  String? _avatarError;

  static const int _maxName = 64;

  @override
  void initState() {
    super.initState();
    final user = ref.read(authProvider).user;
    _originalName = user?.displayName ?? '';
    _name = TextEditingController(text: _originalName);
    _name.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  bool get _dirty => _name.text.trim() != _originalName.trim();
  bool get _valid {
    final n = _name.text.trim();
    return n.isNotEmpty && n.runes.length <= _maxName;
  }

  Future<void> _save() async {
    if (_saving) return; // duplicate-submit guard
    final name = _name.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'Digite um nome de exibição.');
      return;
    }
    if (name.runes.length > _maxName) {
      setState(() => _error = 'Nome muito longo (máx. $_maxName).');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final confirmed =
          await ref.read(socialApiProvider).updateDisplayName(name);
      if (!mounted) return;
      // Authoritative success → reconcile identity everywhere.
      ref.read(authProvider.notifier).updateDisplayName(confirmed);
      final myId = ref.read(authProvider).user?.id;
      if (myId != null && myId.isNotEmpty) {
        ref.invalidate(sportsProfileProvider(myId));
        ref.invalidate(userPostsProvider(myId));
      }
      ref.invalidate(profileBundleProvider);
      ref.invalidate(feedProvider); // feed author display name reflects the change
      context.pop(true);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = _humanizeProfileError(e);
      });
    }
  }

  String _humanizeProfileError(Object err) {
    final raw = err.toString().toLowerCase();
    if (raw.contains('display_name_too_long')) {
      return 'Nome muito longo (máx. $_maxName).';
    }
    if (raw.contains('display_name_required')) {
      return 'Digite um nome de exibição.';
    }
    if (raw.contains('409') || raw.contains('taken') || raw.contains('conflict')) {
      return 'Esse nome já está em uso. Tente outro.';
    }
    if (raw.contains('401') || raw.contains('unauthorized')) {
      return 'Sua sessão expirou. Entre novamente.';
    }
    if (raw.contains('timeout')) return 'Tempo esgotado. Tente de novo.';
    if (raw.contains('connection') || raw.contains('network')) {
      return 'Verifique sua conexão e tente novamente.';
    }
    return 'Não foi possível salvar agora. Tente novamente.';
  }

  Future<void> _changeAvatar() async {
    if (_avatarBusy) return;
    setState(() => _avatarError = null);
    final picker = ImagePicker();
    XFile? picked;
    try {
      picked = await picker.pickImage(
        source: ImageSource.gallery,
        maxWidth: 1024,
        maxHeight: 1024,
        imageQuality: 88,
      );
    } catch (_) {
      setState(() => _avatarError = 'Não consegui abrir a galeria.');
      return;
    }
    if (picked == null) return;
    setState(() => _avatarBusy = true);
    try {
      final url = await ref.read(avatarServiceProvider).upload(picked);
      if (!mounted) return;
      final oldUrl = ref.read(authProvider).user?.avatarUrl;
      await evictAvatarFromCache(oldUrl);
      await evictAvatarFromCache(url);
      ref.read(authProvider.notifier).updateAvatar(url);
      final myId = ref.read(authProvider).user?.id;
      if (myId != null) ref.invalidate(sportsProfileProvider(myId));
      ref.invalidate(profileBundleProvider);
      ref.invalidate(feedProvider);
      setState(() => _avatarBusy = false);
    } catch (e) {
      if (!mounted) return;
      // Avatar failure NEVER discards the in-progress text edits.
      setState(() {
        _avatarBusy = false;
        _avatarError = avatarUploadErrorMessage(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = ref.watch(authProvider.select((s) => s.user));
    final canSave = _dirty && _valid && !_saving;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Editar perfil'),
        actions: [
          TextButton(
            onPressed: canSave ? _save : null,
            child: _saving
                ? const SizedBox(
                    width: 18, height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Salvar'),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(InsightSpacing.xl),
        children: [
          // Avatar — one action within the form; never blocks text editing.
          Center(
            child: Column(
              children: [
                GestureDetector(
                  onTap: _avatarBusy ? null : _changeAvatar,
                  child: CircleAvatar(
                    radius: 44,
                    backgroundColor: context.ds.subtle,
                    backgroundImage: (user?.avatarUrl != null &&
                            user!.avatarUrl!.isNotEmpty)
                        ? NetworkImage(user.avatarUrl!)
                        : null,
                    child: (user?.avatarUrl == null || user!.avatarUrl!.isEmpty)
                        ? Text(_initials(user?.displayName ?? ''),
                            style: context.tt.titleLarge)
                        : null,
                  ),
                ),
                const SizedBox(height: InsightSpacing.sm),
                TextButton.icon(
                  onPressed: _avatarBusy ? null : _changeAvatar,
                  icon: _avatarBusy
                      ? const SizedBox(
                          width: 14, height: 14,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.photo_camera_outlined, size: 18),
                  label: Text(_avatarBusy ? 'Enviando…' : 'Alterar foto'),
                ),
                if (_avatarError != null)
                  Padding(
                    padding: const EdgeInsets.only(top: InsightSpacing.xs),
                    child: Text(_avatarError!,
                        textAlign: TextAlign.center,
                        style: context.tt.bodySmall
                            ?.copyWith(color: context.ds.signal)),
                  ),
              ],
            ),
          ),
          const SizedBox(height: InsightSpacing.xl),

          // Display name — the one writable Core Identity text field.
          Text('Nome de exibição', style: context.tt.labelLarge),
          const SizedBox(height: InsightSpacing.sm),
          TextField(
            controller: _name,
            maxLength: _maxName,
            enabled: !_saving,
            textInputAction: TextInputAction.done,
            decoration: InputDecoration(
              hintText: 'Como você aparece no Insight',
              border: const OutlineInputBorder(),
              contentPadding: const EdgeInsets.symmetric(
                  horizontal: InsightSpacing.lg, vertical: InsightSpacing.md),
              errorText: _error,
            ),
          ),

          // Username — real identity, NOT editable in V1 (deep-link + uniqueness
          // safety). Shown read-only for context (honest, not a fake input).
          const SizedBox(height: InsightSpacing.md),
          _ReadOnlyRow(
            label: 'Nome de usuário',
            value: (user?.username.isNotEmpty ?? false) ? '@${user!.username}' : '—',
            note: 'Não editável nesta versão',
          ),

          // Honestly-deferred fields — NOT fake-enabled inputs.
          const SizedBox(height: InsightSpacing.lg),
          Text('Em breve', style: context.tt.labelLarge),
          const SizedBox(height: InsightSpacing.sm),
          const _DeferredRow(
              icon: Icons.notes_outlined, label: 'Bio'),
          const _DeferredRow(
              icon: Icons.shield_outlined, label: 'Time favorito'),
          const _DeferredRow(
              icon: Icons.place_outlined, label: 'Localização'),
          const SizedBox(height: InsightSpacing.sm),
          Text(
            'Esses campos ainda não são armazenados pela plataforma. Chegam em uma próxima versão — não são exibidos como editáveis para não prometer o que ainda não guardamos.',
            style: context.tt.bodySmall?.copyWith(color: context.ds.textLow),
          ),
        ],
      ),
    );
  }

  String _initials(String name) {
    final parts = name.trim().split(RegExp(r'\s+'));
    if (parts.isEmpty || parts.first.isEmpty) return 'EU';
    if (parts.length == 1) {
      return parts.first.substring(0, parts.first.length.clamp(0, 2)).toUpperCase();
    }
    return (parts.first[0] + parts.last[0]).toUpperCase();
  }
}

class _ReadOnlyRow extends StatelessWidget {
  const _ReadOnlyRow({required this.label, required this.value, this.note});
  final String label;
  final String value;
  final String? note;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(InsightSpacing.md),
      decoration: BoxDecoration(
        border: Border.all(color: context.ds.divider),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: context.tt.bodySmall?.copyWith(color: context.ds.textLow)),
                Text(value, style: context.tt.bodyMedium),
              ],
            ),
          ),
          if (note != null)
            Text(note!, style: context.tt.bodySmall?.copyWith(color: context.ds.textLow)),
        ],
      ),
    );
  }
}

class _DeferredRow extends StatelessWidget {
  const _DeferredRow({required this.icon, required this.label});
  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Opacity(
      opacity: 0.55,
      child: Semantics(
        enabled: false,
        label: '$label — em breve, não editável',
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: InsightSpacing.xs),
          child: Row(
            children: [
              Icon(icon, size: 18, color: context.ds.textLow),
              const SizedBox(width: InsightSpacing.sm),
              Text(label, style: context.tt.bodyMedium),
              const Spacer(),
              Text('Em breve',
                  style: context.tt.bodySmall?.copyWith(color: context.ds.textLow)),
            ],
          ),
        ),
      ),
    );
  }
}
