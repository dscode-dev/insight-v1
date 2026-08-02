// AZTECA-QUALITY-A — avatar upload error humanization (honest, distinct causes).
import 'package:flutter_test/flutter_test.dart';
import 'package:azteca/features/profile/profile_screen.dart';

void main() {
  group('avatarUploadErrorMessage distinguishes causes', () {
    test('503 / storage-unavailable → temporarily unavailable (not "invalid")',
        () {
      const msg = 'GatewayException(503): avatar_storage_unavailable';
      final out = avatarUploadErrorMessage(msg);
      expect(out, contains('indisponível'));
      expect(out.toLowerCase(), isNot(contains('formato')));
    });
    test('capability_unavailable code maps to the same honest message', () {
      final out = avatarUploadErrorMessage('code: CAPABILITY_UNAVAILABLE');
      expect(out, contains('indisponível'));
    });
    test('415 / unsupported → format guidance', () {
      final out = avatarUploadErrorMessage('unsupported_media_type:image/gif');
      expect(out, contains('Formato'));
    });
    test('413 / too large → size guidance', () {
      expect(avatarUploadErrorMessage('413 too large'), contains('grande'));
    });
    test('timeout → time message', () {
      expect(avatarUploadErrorMessage('DioException timeout'),
          contains('Tempo'));
    });
    test('401 / unauthorized → session message', () {
      expect(avatarUploadErrorMessage('GatewayException(401) unauthorized'),
          contains('sessão'));
    });
    test('network → connection message', () {
      expect(avatarUploadErrorMessage('connection error'),
          contains('conexão'));
    });
    test('no message leaks host/bucket/token/stack', () {
      for (final e in <String>[
        'https://minio.internal:9000 bucket=avatars token=abc.def.ghi',
        '503 avatar_storage_unavailable',
        '#0 someStack (package:foo/bar.dart:1)',
      ]) {
        final out = avatarUploadErrorMessage(e).toLowerCase();
        expect(out, isNot(contains('minio')));
        expect(out, isNot(contains('bucket')));
        expect(out, isNot(contains('token')));
        expect(out, isNot(contains('http')));
        expect(out, isNot(contains('package:')));
      }
    });
  });
}
