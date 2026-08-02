// Post image upload — Sprint 6.2 Part 2.
//
// Each post image is uploaded INDEPENDENTLY via:
//   POST /v1/feed/uploads  multipart/form-data: file=<bytes>
//     → { "url": "https://...", "id": "<uuid>" }
//
// Why per-image (not one batch upload):
//   * The composer carousel can show per-image progress + per-image
//     retry without canceling the whole post.
//   * The server can return a stable URL/id as soon as bytes are
//     persisted, even before the post itself is published.
//
// The composer collects every returned URL and includes the list in
// the eventual POST /v1/feed/posts payload (Sprint 8.1 backend work).
// Until that endpoint lands, the upload still succeeds independently
// — the post is published optimistically with the image URLs.
//
// Mock impl: never used in production builds (api_mode=gateway).
import 'package:dio/dio.dart';
import 'package:http_parser/http_parser.dart';
import 'package:image_picker/image_picker.dart';

class PostUploadResult {
  const PostUploadResult({required this.url, required this.id});
  final String url;
  final String id;
}

abstract class PostUploadService {
  /// Upload one image. `onProgress` is a 0..1 fraction; emitted at
  /// most every ~50 ms while bytes are in flight. Throws on failure;
  /// the composer translates the error to a user message + offers
  /// retry per-image.
  Future<PostUploadResult> upload(
    XFile file, {
    void Function(double fraction)? onProgress,
  });
}

class GatewayPostUploadService implements PostUploadService {
  GatewayPostUploadService(this._dio);
  final Dio _dio;

  @override
  Future<PostUploadResult> upload(
    XFile file, {
    void Function(double fraction)? onProgress,
  }) async {
    final mime = file.mimeType ?? _guessMime(file.path);
    final multipart = await MultipartFile.fromFile(
      file.path,
      filename: file.name,
      contentType: MediaType.parse(mime),
    );
    final form = FormData.fromMap({'file': multipart});
    final r = await _dio.post<Map<String, dynamic>>(
      '/v1/feed/uploads',
      data: form,
      options: Options(contentType: 'multipart/form-data'),
      onSendProgress: (sent, total) {
        if (total > 0 && onProgress != null) {
          onProgress(sent / total);
        }
      },
    );
    final body = r.data ?? const {};
    final url = body['url'];
    final id = body['id'];
    if (url is! String || url.isEmpty || id is! String || id.isEmpty) {
      throw const FormatException(
        'post upload: missing url/id in response',
      );
    }
    return PostUploadResult(url: url, id: id);
  }

  String _guessMime(String path) {
    final lower = path.toLowerCase();
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.webp')) return 'image/webp';
    return 'image/jpeg';
  }
}

/// Dev mode only. Returns a deterministic URL after a fake delay so
/// the carousel + progress UI can be exercised without a backend.
class MockPostUploadService implements PostUploadService {
  int _counter = 0;
  @override
  Future<PostUploadResult> upload(
    XFile file, {
    void Function(double fraction)? onProgress,
  }) async {
    final steps = 8;
    for (var i = 1; i <= steps; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 80));
      onProgress?.call(i / steps);
    }
    _counter++;
    return PostUploadResult(
      url: 'https://placehold.co/640?text=post-img-$_counter',
      id: 'mock-${_counter.toString().padLeft(4, '0')}',
    );
  }
}
