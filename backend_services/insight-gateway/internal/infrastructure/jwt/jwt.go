// Package jwt implements the auth.TokenCodec port.
//
// Three token kinds, distinguished by the `typ` claim:
//   - access       — sent on every authenticated request (15min TTL)
//   - refresh      — sent only to /v1/auth/refresh (30d TTL)
//   - registration — issued by /otp/verify when the phone has no user;
//     consumed by /register (10min TTL). Carries
//     `phone_e164` instead of `sub`.
//
// Algorithm: HS256 for V1. Production should rotate to RS256 once a
// KMS-backed key store is in place (out of scope for the migration).
package jwt

import (
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"

	insightauth "github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

type Config struct {
	SigningKey      string
	Issuer          string
	Audience        string
	AccessTTL       time.Duration
	RefreshTTL      time.Duration
	RegistrationTTL time.Duration
}

type Codec struct {
	cfg Config
	key []byte
}

func New(cfg Config) *Codec {
	return &Codec{cfg: cfg, key: []byte(cfg.SigningKey)}
}

const (
	typeAccess       = "access"
	typeRefresh      = "refresh"
	typeRegistration = "registration"
)

// ---- IssueX ----

func (c *Codec) IssueAccess(userID uuid.UUID, now time.Time) (string, time.Duration, error) {
	return c.issueWithSub(userID, now, c.cfg.AccessTTL, typeAccess)
}

func (c *Codec) IssueRefresh(userID uuid.UUID, now time.Time) (string, time.Duration, error) {
	return c.issueWithSub(userID, now, c.cfg.RefreshTTL, typeRefresh)
}

func (c *Codec) IssueRegistration(phoneE164 string, now time.Time) (string, time.Duration, error) {
	exp := now.Add(c.cfg.RegistrationTTL)
	claims := jwt.MapClaims{
		"iss":        c.cfg.Issuer,
		"aud":        c.cfg.Audience,
		"phone_e164": phoneE164,
		"iat":        now.Unix(),
		"nbf":        now.Unix(),
		"exp":        exp.Unix(),
		"jti":        uuid.NewString(),
		"typ":        typeRegistration,
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	signed, err := tok.SignedString(c.key)
	if err != nil {
		return "", 0, fmt.Errorf("sign registration token: %w", err)
	}
	return signed, c.cfg.RegistrationTTL, nil
}

func (c *Codec) issueWithSub(userID uuid.UUID, now time.Time, ttl time.Duration, typ string) (string, time.Duration, error) {
	exp := now.Add(ttl)
	claims := jwt.MapClaims{
		"iss": c.cfg.Issuer,
		"aud": c.cfg.Audience,
		"sub": userID.String(),
		"iat": now.Unix(),
		"nbf": now.Unix(),
		"exp": exp.Unix(),
		"jti": uuid.NewString(),
		"typ": typ,
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	signed, err := tok.SignedString(c.key)
	if err != nil {
		return "", 0, fmt.Errorf("sign %s token: %w", typ, err)
	}
	return signed, ttl, nil
}

// ---- DecodeX ----

func (c *Codec) DecodeAccess(token string) (uuid.UUID, error) {
	return c.decodeWithSub(token, typeAccess, insightauth.ErrInvalidCredentials)
}

func (c *Codec) DecodeRefresh(token string) (uuid.UUID, error) {
	return c.decodeWithSub(token, typeRefresh, insightauth.ErrInvalidCredentials)
}

func (c *Codec) DecodeRegistration(token string) (string, error) {
	claims, err := c.parse(token)
	if err != nil {
		return "", insightauth.ErrInvalidRegistrationToken
	}
	if claims["typ"] != typeRegistration {
		return "", insightauth.ErrInvalidRegistrationToken
	}
	phone, _ := claims["phone_e164"].(string)
	if phone == "" {
		return "", insightauth.ErrInvalidRegistrationToken
	}
	return phone, nil
}

func (c *Codec) decodeWithSub(token, expectedType string, onErr error) (uuid.UUID, error) {
	claims, err := c.parse(token)
	if err != nil {
		return uuid.Nil, onErr
	}
	if claims["typ"] != expectedType {
		return uuid.Nil, onErr
	}
	sub, _ := claims["sub"].(string)
	id, err := uuid.Parse(sub)
	if err != nil {
		return uuid.Nil, onErr
	}
	return id, nil
}

func (c *Codec) parse(token string) (jwt.MapClaims, error) {
	parsed, err := jwt.Parse(token, func(t *jwt.Token) (interface{}, error) {
		if t.Method != jwt.SigningMethodHS256 {
			return nil, errors.New("unexpected alg")
		}
		return c.key, nil
	}, jwt.WithIssuer(c.cfg.Issuer), jwt.WithAudience(c.cfg.Audience), jwt.WithExpirationRequired())
	if err != nil || !parsed.Valid {
		return nil, err
	}
	claims, ok := parsed.Claims.(jwt.MapClaims)
	if !ok {
		return nil, errors.New("unexpected claims type")
	}
	return claims, nil
}
