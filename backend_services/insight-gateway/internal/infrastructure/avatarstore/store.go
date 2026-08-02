// Package avatarstore — object-store client for user avatar uploads.
//
// Sprint C ships against MinIO in lab and any S3-compatible provider
// in prod (R2, S3, GCS via interop endpoint). The minio-go SDK works
// against all of them — config differs only in endpoint + creds.
//
// Wire flow:
//  1. Gateway accepts a multipart upload at POST /v1/users/me/avatar.
//  2. Validates content type + max size.
//  3. PUTs the object under `avatars/<user_id>.<ext>` with a stable
//     key so a re-upload overwrites the previous file (no orphaned
//     historical avatars accumulating).
//  4. Returns the public URL — the BFF then calls social.User.UpdateAvatar
//     to persist it.
//
// We don't issue presigned URLs in Sprint C because Flutter's
// `image_picker` returns a local file we'd have to forward anyway —
// adding presign would mean two round-trips (presign + PUT) where
// the direct multipart upload only takes one.
package avatarstore

import (
	"context"
	"fmt"
	"io"
	"path"
	"strings"

	"github.com/google/uuid"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

type Config struct {
	Endpoint        string // e.g. "minio:9000" (no scheme)
	UseSSL          bool   // true in prod, false against the lab MinIO
	AccessKeyID     string
	SecretAccessKey string
	Bucket          string // "avatars"
	// PublicBaseURL is the URL prefix the BFF surfaces to clients —
	// distinct from Endpoint because in prod we sit behind a CDN
	// (e.g. https://cdn.insight.io/avatars/...) while the server-to-
	// server PUT goes to the origin endpoint.
	PublicBaseURL string
	// MaxObjectBytes guards the multipart upload size at the
	// boundary. Default 5MiB if zero.
	MaxObjectBytes int64
}

type Store struct {
	client *minio.Client
	cfg    Config
}

func New(cfg Config) (*Store, error) {
	if cfg.Endpoint == "" || cfg.Bucket == "" {
		return nil, fmt.Errorf("avatarstore: endpoint + bucket required")
	}
	if strings.TrimSpace(cfg.PublicBaseURL) == "" {
		return nil, fmt.Errorf("avatarstore: public base URL required")
	}
	if cfg.MaxObjectBytes == 0 {
		cfg.MaxObjectBytes = 5 << 20 // 5MiB
	}
	cli, err := minio.New(cfg.Endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(cfg.AccessKeyID, cfg.SecretAccessKey, ""),
		Secure: cfg.UseSSL,
	})
	if err != nil {
		return nil, fmt.Errorf("avatarstore: new minio client: %w", err)
	}
	return &Store{client: cli, cfg: cfg}, nil
}

func (s *Store) EnsureBucket(ctx context.Context) error {
	exists, err := s.client.BucketExists(ctx, s.cfg.Bucket)
	if err != nil {
		return fmt.Errorf("avatarstore: check bucket %s: %w", s.cfg.Bucket, err)
	}
	if exists {
		return nil
	}
	if err := s.client.MakeBucket(ctx, s.cfg.Bucket, minio.MakeBucketOptions{}); err != nil {
		return fmt.Errorf("avatarstore: make bucket %s: %w", s.cfg.Bucket, err)
	}
	return nil
}

// Put uploads the avatar bytes for `userID`, returning the public URL
// to persist on the user row. `contentType` MUST be a vetted image
// MIME (image/jpeg | image/png | image/webp); the handler is
// responsible for the check.
//
// Object key is stable per user (`avatars/<uuid>.<ext>`) so the new
// upload overwrites the previous one — clients don't accumulate
// orphan images.
func (s *Store) Put(ctx context.Context, userID uuid.UUID, contentType string, body io.Reader, size int64) (string, error) {
	if size > s.cfg.MaxObjectBytes {
		return "", fmt.Errorf("avatarstore: object %d bytes exceeds cap %d", size, s.cfg.MaxObjectBytes)
	}
	ext := extensionFor(contentType)
	if ext == "" {
		return "", fmt.Errorf("avatarstore: unsupported content type %q", contentType)
	}
	key := path.Join("avatars", userID.String()+ext)

	_, err := s.client.PutObject(ctx, s.cfg.Bucket, key, body, size, minio.PutObjectOptions{
		ContentType:  contentType,
		CacheControl: "public, max-age=86400", // 1d at the edge — avatars rarely change
	})
	if err != nil {
		return "", fmt.Errorf("avatarstore: put %s: %w", key, err)
	}

	// Public URL is `<PublicBaseURL>/<key>` with the bucket either
	// embedded in PublicBaseURL or stripped by a CDN rewrite.
	base := strings.TrimRight(s.cfg.PublicBaseURL, "/")
	return base + "/" + key, nil
}

// extensionFor maps the allow-listed content types to a dotted
// extension. Anything outside the list returns "" so the caller
// errors before issuing a PUT.
func extensionFor(contentType string) string {
	switch contentType {
	case "image/jpeg":
		return ".jpg"
	case "image/png":
		return ".png"
	case "image/webp":
		return ".webp"
	default:
		return ""
	}
}
