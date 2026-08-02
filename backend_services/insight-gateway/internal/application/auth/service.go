// Package auth bundles the 4 OTP-auth use cases as methods on a
// single Service. Service is the only public type — everything is
// constructed once at boot via NewService and re-used per request.
//
// Methods:
//   - RequestOtp           — POST /v1/auth/otp/request
//   - VerifyOtp            — POST /v1/auth/otp/verify
//   - CompleteRegistration — POST /v1/auth/register
//   - Refresh              — POST /v1/auth/refresh
package auth

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/rs/zerolog"

	domauth "github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

// Config holds the knobs the OTP flow needs. Loaded from
// internal/config.Settings at boot.
type Config struct {
	OtpCodeLength      int
	OtpTTL             time.Duration
	OtpMaxAttempts     int
	OtpResendCooldown  time.Duration
	SmsMessageTemplate string // "Seu código Insight é {code}. ..."
}

type Service struct {
	cfg         Config
	credentials domauth.CredentialRepo
	challenges  domauth.OtpChallengeRepo
	cooldown    domauth.CooldownStore
	codes       domauth.CodeHasher
	codeGen     codeGenerator
	phone       domauth.PhoneNormalizer
	phoneAuth   domauth.PhoneAuthProvider
	sms         domauth.SmsProvider
	tokens      domauth.TokenCodec
	users       domauth.UserCreator
	sessions    domauth.RefreshSessionStore
	metrics     Metrics
	now         func() time.Time
}

// codeGenerator is satisfied by infrastructure/otp.Codec but kept
// as a private interface so Service doesn't depend on the package.
type codeGenerator interface {
	Generate() (string, error)
}

type Deps struct {
	Credentials domauth.CredentialRepo
	Challenges  domauth.OtpChallengeRepo
	Cooldown    domauth.CooldownStore
	Codes       domauth.CodeHasher
	CodeGen     codeGenerator
	Phone       domauth.PhoneNormalizer
	PhoneAuth   domauth.PhoneAuthProvider
	SMS         domauth.SmsProvider
	Tokens      domauth.TokenCodec
	Users       domauth.UserCreator
	Sessions    domauth.RefreshSessionStore
	Metrics     Metrics
}

func NewService(cfg Config, deps Deps) *Service {
	return &Service{
		cfg:         cfg,
		credentials: deps.Credentials,
		challenges:  deps.Challenges,
		cooldown:    deps.Cooldown,
		codes:       deps.Codes,
		codeGen:     deps.CodeGen,
		phone:       deps.Phone,
		phoneAuth:   deps.PhoneAuth,
		sms:         deps.SMS,
		tokens:      deps.Tokens,
		users:       deps.Users,
		sessions:    deps.Sessions,
		metrics:     deps.Metrics,
		now:         time.Now,
	}
}

// ---- RequestOtp ----

type RequestOtpInput struct {
	RawPhone string
}

func (s *Service) RequestOtp(ctx context.Context, in RequestOtpInput) error {
	phone, err := s.phone.Normalize(in.RawPhone)
	if err != nil {
		return err
	}

	// Cooldown — bounded SMS-bombing of a victim's phone.
	last, err := s.cooldown.LastRequestAt(ctx, phone)
	if err != nil {
		return fmt.Errorf("cooldown lookup: %w", err)
	}
	now := s.now()
	if !last.IsZero() && now.Sub(last) < s.cfg.OtpResendCooldown {
		return domauth.ErrOtpResendCooldown
	}

	if s.phoneAuth != nil {
		started := time.Now()
		logger := zerolog.Ctx(ctx)
		logger.Info().
			Str("provider", s.phoneAuth.Name()).
			Msg("auth.provider.request_started")
		msgID, err := s.phoneAuth.SendCode(ctx, phone)
		if s.metrics != nil {
			s.metrics.PhoneProviderRequest(s.phoneAuth.Name(), err == nil)
		}
		if err != nil {
			logger.Warn().
				Str("provider", s.phoneAuth.Name()).
				Dur("duration", time.Since(started)).
				Str("failure_reason", authFailureReason(err)).
				Msg("auth.provider.request_failed")
			return fmt.Errorf("%w: %v", domauth.ErrOtpDispatch, err)
		}
		if err := s.cooldown.MarkRequested(ctx, phone, now, s.cfg.OtpResendCooldown); err != nil {
			logger.Warn().
				Str("provider", s.phoneAuth.Name()).
				Dur("duration", time.Since(started)).
				Str("failure_reason", "cooldown_store_failed").
				Msg("auth.provider.request_failed")
			return fmt.Errorf("mark cooldown: %w", err)
		}
		_ = msgID // support/audit hook for providers that return an upstream id.
		logger.Info().
			Str("provider", s.phoneAuth.Name()).
			Dur("duration", time.Since(started)).
			Msg("auth.provider.request_success")
		return nil
	}

	code, err := s.codeGen.Generate()
	if err != nil {
		return fmt.Errorf("code gen: %w", err)
	}
	hash := s.codes.Hash(code, phone)
	body := renderTemplate(s.cfg.SmsMessageTemplate, code)

	msgID, err := s.sms.SendOtp(ctx, phone, body)
	if err != nil {
		return fmt.Errorf("%w: %v", domauth.ErrOtpDispatch, err)
	}

	var msgIDPtr *string
	if msgID != "" {
		msgIDPtr = &msgID
	}
	ch := &domauth.OtpChallenge{
		ID:                uuid.New(),
		PhoneE164:         phone,
		CodeHash:          hash,
		Provider:          s.sms.Name(),
		ProviderMessageID: msgIDPtr,
		Attempts:          0,
		MaxAttempts:       s.cfg.OtpMaxAttempts,
		CreatedAt:         now,
		ExpiresAt:         now.Add(s.cfg.OtpTTL),
	}
	if err := s.challenges.Insert(ctx, ch); err != nil {
		return fmt.Errorf("insert challenge: %w", err)
	}

	// Mark cooldown AFTER the insert so a failed insert doesn't lock
	// out a retry. TTL = cooldown window so expired keys auto-purge.
	if err := s.cooldown.MarkRequested(ctx, phone, now, s.cfg.OtpResendCooldown); err != nil {
		return fmt.Errorf("mark cooldown: %w", err)
	}

	return nil
}

// ---- VerifyOtp ----

type VerifyOtpInput struct {
	RawPhone string
	Code     string
}

// VerifyOtpResult is the discriminated union of "logged in" vs
// "needs registration":
//   - Tokens != nil       → existing user, login complete
//   - Registration != nil → new phone, client must POST /register
//     with the registration token
type VerifyOtpResult struct {
	Tokens       *IssuedTokens
	Registration *RegistrationHandoff
}

type IssuedTokens struct {
	UserID            uuid.UUID
	AccessToken       string
	AccessTTLSeconds  int
	RefreshToken      string
	RefreshTTLSeconds int
}

type RegistrationHandoff struct {
	RegistrationToken      string
	RegistrationTTLSeconds int
}

func (s *Service) VerifyOtp(ctx context.Context, in VerifyOtpInput) (*VerifyOtpResult, error) {
	phone, err := s.phone.Normalize(in.RawPhone)
	if err != nil {
		return nil, err
	}

	if s.phoneAuth != nil {
		started := time.Now()
		logger := zerolog.Ctx(ctx)
		logger.Info().
			Str("provider", s.phoneAuth.Name()).
			Msg("auth.provider.verify_started")
		err := s.phoneAuth.VerifyCode(ctx, phone, in.Code)
		if s.metrics != nil {
			s.metrics.PhoneProviderVerification(s.phoneAuth.Name(), err == nil)
		}
		if err != nil {
			logger.Warn().
				Str("provider", s.phoneAuth.Name()).
				Dur("duration", time.Since(started)).
				Str("failure_reason", authFailureReason(err)).
				Msg("auth.provider.verify_failed")
			if errors.Is(err, domauth.ErrPhoneProviderNotConfigured) {
				return nil, err
			}
			return nil, domauth.ErrOtpInvalid
		}
		result, err := s.resolvePhone(ctx, phone, s.now())
		if err != nil {
			logger.Warn().
				Str("provider", s.phoneAuth.Name()).
				Dur("duration", time.Since(started)).
				Str("failure_reason", authFailureReason(err)).
				Msg("auth.provider.verify_failed")
			return nil, err
		}
		logger.Info().
			Str("provider", s.phoneAuth.Name()).
			Dur("duration", time.Since(started)).
			Msg("auth.provider.verify_success")
		return result, nil
	}

	ch, err := s.challenges.FreshestUnconsumed(ctx, phone)
	if err != nil {
		if errors.Is(err, domauth.ErrChallengeNotFound) {
			// Don't disclose whether the phone has ever been issued
			// an OTP — same error for "no challenge" and "wrong code".
			return nil, domauth.ErrOtpInvalid
		}
		return nil, fmt.Errorf("load challenge: %w", err)
	}

	now := s.now()
	if ch.IsExhausted() {
		return nil, domauth.ErrOtpExhausted
	}
	if ch.IsExpired(now) {
		return nil, domauth.ErrOtpExpired
	}

	// Always increment attempts before comparing — a wrong code still
	// counts toward the cap.
	if err := s.challenges.IncrementAttempts(ctx, ch.ID); err != nil {
		return nil, fmt.Errorf("increment attempts: %w", err)
	}

	if !s.codes.Verify(in.Code, ch.CodeHash, phone) {
		return nil, domauth.ErrOtpInvalid
	}

	if err := s.challenges.MarkConsumed(ctx, ch.ID, now); err != nil {
		return nil, fmt.Errorf("mark consumed: %w", err)
	}

	// Existing user? → login path. New phone? → registration handoff.
	return s.resolvePhone(ctx, phone, now)
}

// resolvePhone is the shared tail of every phone-verified flow: an existing
// credential logs in (access+refresh); a new phone gets a registration handoff.
// Keeping ONE branch guarantees providers do not become parallel auth systems.
func (s *Service) resolvePhone(ctx context.Context, phone string, now time.Time) (*VerifyOtpResult, error) {
	cred, err := s.credentials.GetByPhone(ctx, phone)
	if err != nil && !errors.Is(err, domauth.ErrCredentialNotFound) {
		return nil, fmt.Errorf("load credential: %w", err)
	}
	if cred != nil {
		if err := s.credentials.TouchLastLogin(ctx, cred.ID, now); err != nil {
			return nil, fmt.Errorf("touch last_login: %w", err)
		}
		tokens, err := s.issueTokens(ctx, cred.UserID, now)
		if err != nil {
			return nil, err
		}
		if s.metrics != nil {
			s.metrics.Login()
		}
		return &VerifyOtpResult{Tokens: tokens}, nil
	}

	regToken, regTTL, err := s.tokens.IssueRegistration(phone, now)
	if err != nil {
		return nil, fmt.Errorf("issue registration token: %w", err)
	}
	return &VerifyOtpResult{
		Registration: &RegistrationHandoff{
			RegistrationToken:      regToken,
			RegistrationTTLSeconds: int(regTTL.Seconds()),
		},
	}, nil
}

// ---- CompleteRegistration ----

type CompleteRegistrationInput struct {
	RegistrationToken        string
	Username                 string
	DisplayName              string
	AccentColor              *string
	AcceptedTermsVersion     string
	AcceptedPrivacyVersion   string
	AcceptedUGCPolicyVersion string
}

func (s *Service) CompleteRegistration(ctx context.Context, in CompleteRegistrationInput) (*IssuedTokens, error) {
	// Store-A (App Store / Play): no account is created without explicit
	// acceptance of Terms, Privacy and UGC Safety policy versions.
	if strings.TrimSpace(in.AcceptedTermsVersion) == "" ||
		strings.TrimSpace(in.AcceptedPrivacyVersion) == "" ||
		strings.TrimSpace(in.AcceptedUGCPolicyVersion) == "" {
		return nil, domauth.ErrTermsNotAccepted
	}

	phone, err := s.tokens.DecodeRegistration(in.RegistrationToken)
	if err != nil {
		return nil, domauth.ErrInvalidRegistrationToken
	}

	now := s.now()

	// Defensive: somebody else may have registered with this phone
	// during the ~10min registration token TTL. Take the existing
	// row instead of failing.
	existingByPhone, err := s.credentials.GetByPhone(ctx, phone)
	if err != nil && !errors.Is(err, domauth.ErrCredentialNotFound) {
		return nil, fmt.Errorf("load credential by phone: %w", err)
	}
	if existingByPhone != nil {
		if err := s.credentials.TouchLastLogin(ctx, existingByPhone.ID, now); err != nil {
			return nil, fmt.Errorf("touch last_login: %w", err)
		}
		return s.issueTokens(ctx, existingByPhone.UserID, now)
	}

	// Username collision on our side.
	if existingByUsername, err := s.credentials.GetByUsername(ctx, in.Username); err == nil && existingByUsername != nil {
		return nil, domauth.ErrUsernameTaken
	} else if err != nil && !errors.Is(err, domauth.ErrCredentialNotFound) {
		return nil, fmt.Errorf("load credential by username: %w", err)
	}

	// Social is the source of truth for user identity. Create there first.
	userID, err := s.users.CreateUser(ctx, in.Username, in.DisplayName, in.AccentColor)
	if err != nil {
		if errors.Is(err, domauth.ErrUsernameTaken) {
			return nil, domauth.ErrUsernameTaken
		}
		return nil, fmt.Errorf("social create_user: %w", err)
	}

	cred := &domauth.Credential{
		ID:                       uuid.New(),
		UserID:                   userID,
		PhoneE164:                phone,
		Username:                 in.Username,
		CreatedAt:                now,
		LastLoginAt:              &now,
		AcceptedTermsVersion:     strings.TrimSpace(in.AcceptedTermsVersion),
		AcceptedPrivacyVersion:   strings.TrimSpace(in.AcceptedPrivacyVersion),
		AcceptedUGCPolicyVersion: strings.TrimSpace(in.AcceptedUGCPolicyVersion),
		AcceptedLegalAt:          &now,
	}
	if err := s.credentials.Insert(ctx, cred); err != nil {
		return nil, fmt.Errorf("insert credential: %w", err)
	}

	tokens, err := s.issueTokens(ctx, userID, now)
	if err != nil {
		return nil, err
	}
	if s.metrics != nil {
		s.metrics.Registration()
	}
	return tokens, nil
}

// ---- Refresh (Auth-A Part 7: rotation + revocation) ----

type RefreshInput struct {
	RefreshToken string
}

func (s *Service) Refresh(ctx context.Context, in RefreshInput) (*IssuedTokens, error) {
	userID, err := s.tokens.DecodeRefresh(in.RefreshToken)
	if err != nil {
		return nil, domauth.ErrInvalidCredentials
	}
	// Server-side session check: the refresh token must be a live (not
	// revoked, not expired) stored session. This is what makes refresh
	// tokens revocable + detects reuse of a rotated-away token.
	if s.sessions != nil {
		sess, err := s.sessions.Lookup(ctx, hashToken(in.RefreshToken))
		if err != nil {
			if errors.Is(err, domauth.ErrRefreshNotFound) {
				return nil, domauth.ErrInvalidCredentials
			}
			return nil, fmt.Errorf("lookup refresh session: %w", err)
		}
		if sess.RevokedAt != nil || s.now().After(sess.ExpiresAt) {
			return nil, domauth.ErrRefreshRevoked
		}
	}
	cred, err := s.credentials.GetByUserID(ctx, userID)
	if err != nil {
		if errors.Is(err, domauth.ErrCredentialNotFound) {
			return nil, domauth.ErrUserNotFound
		}
		return nil, fmt.Errorf("load credential: %w", err)
	}
	// Rotate: revoke the presented refresh token, then mint a fresh pair.
	if s.sessions != nil {
		if err := s.sessions.Revoke(ctx, hashToken(in.RefreshToken)); err != nil {
			return nil, fmt.Errorf("revoke old refresh: %w", err)
		}
	}
	tokens, err := s.issueTokens(ctx, cred.UserID, s.now())
	if err != nil {
		return nil, err
	}
	if s.metrics != nil {
		s.metrics.Refresh()
	}
	return tokens, nil
}

// Logout revokes the presented refresh token's server-side session. Idempotent.
func (s *Service) Logout(ctx context.Context, refreshToken string) error {
	if s.sessions == nil {
		return nil
	}
	return s.sessions.Revoke(ctx, hashToken(refreshToken))
}

// hashToken is the at-rest representation of a refresh token (we never store
// the raw token). SHA-256 hex is sufficient: refresh tokens are high-entropy
// JWTs, not user passwords.
func hashToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

// ---- helpers ----

func (s *Service) issueTokens(ctx context.Context, userID uuid.UUID, now time.Time) (*IssuedTokens, error) {
	access, accessTTL, err := s.tokens.IssueAccess(userID, now)
	if err != nil {
		return nil, fmt.Errorf("issue access: %w", err)
	}
	refresh, refreshTTL, err := s.tokens.IssueRefresh(userID, now)
	if err != nil {
		return nil, fmt.Errorf("issue refresh: %w", err)
	}
	// Auth-A Part 7: persist the refresh token (hashed) as a revocable,
	// rotatable server-side session. Best-effort store errors fail the issue
	// so we never hand out a refresh token we can't later revoke.
	if s.sessions != nil {
		if err := s.sessions.Create(ctx, userID, hashToken(refresh), now.Add(refreshTTL)); err != nil {
			return nil, fmt.Errorf("store refresh session: %w", err)
		}
	}
	return &IssuedTokens{
		UserID:            userID,
		AccessToken:       access,
		AccessTTLSeconds:  int(accessTTL.Seconds()),
		RefreshToken:      refresh,
		RefreshTTLSeconds: int(refreshTTL.Seconds()),
	}, nil
}

// renderTemplate replaces {code} in the SMS template. Single-token
// template by design — anything more elaborate belongs in a real
// templating engine, which is overkill for one-token OTPs.
func renderTemplate(template, code string) string {
	out := make([]byte, 0, len(template)+8)
	i := 0
	for i < len(template) {
		if i+6 <= len(template) && template[i:i+6] == "{code}" {
			out = append(out, code...)
			i += 6
			continue
		}
		out = append(out, template[i])
		i++
	}
	return string(out)
}

func authFailureReason(err error) string {
	switch {
	case err == nil:
		return ""
	case errors.Is(err, domauth.ErrPhoneProviderNotConfigured):
		return "provider_not_configured"
	case errors.Is(err, domauth.ErrPhoneProviderInvalid):
		return "provider_rejected"
	case errors.Is(err, domauth.ErrOtpResendCooldown):
		return "resend_cooldown"
	case errors.Is(err, domauth.ErrOtpDispatch):
		return "dispatch_failed"
	case errors.Is(err, domauth.ErrOtpInvalid):
		return "invalid_or_expired"
	case errors.Is(err, domauth.ErrInvalidPhone):
		return "invalid_phone"
	case errors.Is(err, domauth.ErrUsernameTaken):
		return "username_taken"
	default:
		return "internal_error"
	}
}
