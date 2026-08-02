import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// A recovered composer draft.
class ComposerDraft {
  const ComposerDraft({
    required this.text,
    required this.typeId,
    required this.savedAt,
  });

  final String text;
  final String typeId;
  final DateTime savedAt;

  bool get isEmpty => text.trim().isEmpty;
}

/// Persists the in-progress Composer draft so text is never lost on an
/// accidental close (AZTECA-COMPOSER-A Stage 6). Uses the same secure-storage
/// strategy as [TokenStorage] (Keychain on iOS / EncryptedSharedPreferences on
/// Android) — no new dependency, no mock storage. A single-slot draft is enough
/// for the V1 single-post composer.
class ComposerDraftStore {
  ComposerDraftStore({FlutterSecureStorage? backend})
      : _store = backend ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
              iOptions: IOSOptions(
                accessibility: KeychainAccessibility.first_unlock,
              ),
            );

  final FlutterSecureStorage _store;

  static const _kDraft = 'insight.composer.draft';

  Future<ComposerDraft?> read() async {
    final raw = await _store.read(key: _kDraft);
    if (raw == null || raw.isEmpty) return null;
    try {
      final map = jsonDecode(raw) as Map<String, dynamic>;
      final text = '${map['text'] ?? ''}';
      if (text.trim().isEmpty) return null;
      return ComposerDraft(
        text: text,
        typeId: '${map['type_id'] ?? 'opinion'}',
        savedAt: DateTime.tryParse('${map['saved_at'] ?? ''}') ?? DateTime.now(),
      );
    } catch (_) {
      // Corrupt draft → drop it silently rather than crash the composer.
      await clear();
      return null;
    }
  }

  Future<void> write({required String text, required String typeId}) async {
    if (text.trim().isEmpty) {
      await clear();
      return;
    }
    await _store.write(
      key: _kDraft,
      value: jsonEncode({
        'text': text,
        'type_id': typeId,
        'saved_at': DateTime.now().toIso8601String(),
      }),
    );
  }

  Future<void> clear() => _store.delete(key: _kDraft);
}
