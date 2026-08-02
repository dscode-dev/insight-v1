// Sprint C — Avatar upload service.
//
// POST /v1/users/me/avatar  multipart/form-data: file=<bytes>
//   → { "avatar_url": "https://..." }
//
// The picker layer (image_picker) returns an XFile that carries both
// a path and a MIME type. We forward the MIME verbatim to the BFF so
// the server's allow-list check is the ONLY source of truth (no
// double-validation of supported types).
//
// Mock impl returns a deterministic placeholder URL so the screen can
// be exercised without a running gateway/MinIO.
import 'package:dio/dio.dart';
import 'package:http_parser/http_parser.dart';
import 'package:image_picker/image_picker.dart';

import '../core/logger.dart';

abstract class AvatarService {
  /// Uploads the picked file. Returns the public URL to persist on
  /// AuthUser.avatarUrl.
  Future<String> upload(XFile file);
}

class GatewayAvatarService implements AvatarService {
  GatewayAvatarService(this._dio);
  final Dio _dio;

  @override
  Future<String> upload(XFile file) async {
    final mime = file.mimeType ?? _guessMime(file.path);
    if (!_allowedMime(mime)) {
      L.w('avatar', 'upload_rejected_unsupported_media',
          data: {'mime': mime, 'name': file.name});
      throw UnsupportedError('unsupported_media_type:$mime');
    }
    L.i('avatar', 'upload_started', data: {'mime': mime, 'name': file.name});
    final multipart = await MultipartFile.fromFile(
      file.path,
      filename: file.name,
      contentType: MediaType.parse(mime),
    );
    final form = FormData.fromMap({'file': multipart});
    try {
      final r = await _dio.post<Map<String, dynamic>>(
        '/v1/users/me/avatar',
        data: form,
        options: Options(
          contentType: 'multipart/form-data',
          // Dio's default JSON content-type would break the boundary
          // negotiation; setting contentType above is sufficient.
        ),
      );
      final url = (r.data ?? const {})['avatar_url'];
      if (url is! String || url.isEmpty) {
        throw const FormatException(
            'avatar upload: empty avatar_url in response');
      }
      L.i('avatar', 'upload_success');
      return url;
    } catch (e, st) {
      L.e('avatar', 'upload_failed', error: e, stackTrace: st);
      rethrow;
    }
  }

  String _guessMime(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.webp')) return 'image/webp';
    return 'image/jpeg'; // sensible default for .jpg/.jpeg/HEIC-converted
  }

  bool _allowedMime(String mime) =>
      mime == 'image/jpeg' || mime == 'image/png' || mime == 'image/webp';
}

class MockAvatarService implements AvatarService {
  @override
  Future<String> upload(XFile file) async {
    await Future<void>.delayed(const Duration(milliseconds: 320));
    // Stable per-file path → URL so re-uploads produce the same URL,
    // exercising the "no orphan files" intent in lab.
    return 'https://placehold.co/256?text=Mock';
  }
}
