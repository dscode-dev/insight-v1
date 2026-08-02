package auth

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"

	domauth "github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

// Auth-A focused unit tests: provider-backed phone verification reuses the SAME
// login/registration branch as OTP, and refresh tokens are server-side, rotated
// + revocable. Real provider SMS is validated on-device.

// ---- fakes ----

type fakeCreds struct {
	byPhone map[string]*domauth.Credential
	byUser  map[uuid.UUID]*domauth.Credential
	touched int
}

func newFakeCreds() *fakeCreds {
	return &fakeCreds{byPhone: map[string]*domauth.Credential{}, byUser: map[uuid.UUID]*domauth.Credential{}}
}
func (f *fakeCreds) GetByPhone(_ context.Context, p string) (*domauth.Credential, error) {
	if c, ok := f.byPhone[p]; ok {
		return c, nil
	}
	return nil, domauth.ErrCredentialNotFound
}
func (f *fakeCreds) GetByUserID(_ context.Context, id uuid.UUID) (*domauth.Credential, error) {
	if c, ok := f.byUser[id]; ok {
		return c, nil
	}
	return nil, domauth.ErrCredentialNotFound
}
func (f *fakeCreds) GetByUsername(context.Context, string) (*domauth.Credential, error) {
	return nil, domauth.ErrCredentialNotFound
}
func (f *fakeCreds) Insert(_ context.Context, c *domauth.Credential) error {
	f.byPhone[c.PhoneE164] = c
	f.byUser[c.UserID] = c
	return nil
}
func (f *fakeCreds) TouchLastLogin(context.Context, uuid.UUID, time.Time) error {
	f.touched++
	return nil
}

type fakeNormalizer struct{}

func (fakeNormalizer) Normalize(raw string) (string, error) {
	if raw == "" {
		return "", domauth.ErrInvalidPhone
	}
	return raw, nil // tests pass already-E.164 numbers
}

// fakeTokens issues predictable tokens so the test can assert rotation.
type fakeTokens struct {
	n           int
	refreshUser uuid.UUID
}

func (t *fakeTokens) IssueAccess(uuid.UUID, time.Time) (string, time.Duration, error) {
	t.n++
	return "access", 15 * time.Minute, nil
}
func (t *fakeTokens) IssueRefresh(_ uuid.UUID, _ time.Time) (string, time.Duration, error) {
	t.n++
	return "refresh-" + uuid.NewString(), 720 * time.Hour, nil
}
func (t *fakeTokens) IssueRegistration(string, time.Time) (string, time.Duration, error) {
	return "regtoken", 10 * time.Minute, nil
}
func (t *fakeTokens) DecodeAccess(string) (uuid.UUID, error) { return uuid.Nil, nil }
func (t *fakeTokens) DecodeRefresh(string) (uuid.UUID, error) {
	return t.refreshUser, nil
}
func (t *fakeTokens) DecodeRegistration(string) (string, error) { return "+5511999999999", nil }

type fakePhoneProvider struct {
	sendPhone   string
	verifyPhone string
	verifyCode  string
	err         error
}

func (f *fakePhoneProvider) Name() string { return "fake-provider" }
func (f *fakePhoneProvider) SendCode(_ context.Context, phone string) (string, error) {
	f.sendPhone = phone
	return "provider-message-id", f.err
}
func (f *fakePhoneProvider) VerifyCode(_ context.Context, phone, code string) error {
	f.verifyPhone = phone
	f.verifyCode = code
	return f.err
}

type fakeCooldown struct {
	last time.Time
	mark int
}

func (f *fakeCooldown) LastRequestAt(context.Context, string) (time.Time, error) {
	return f.last, nil
}
func (f *fakeCooldown) MarkRequested(_ context.Context, _ string, at time.Time, _ time.Duration) error {
	f.last = at
	f.mark++
	return nil
}

// fakeSessions is an in-memory RefreshSessionStore.
type fakeSessions struct {
	rows map[string]*domauth.RefreshSession
}

func newFakeSessions() *fakeSessions {
	return &fakeSessions{rows: map[string]*domauth.RefreshSession{}}
}
func (s *fakeSessions) Create(_ context.Context, userID uuid.UUID, hash string, exp time.Time) error {
	s.rows[hash] = &domauth.RefreshSession{ID: uuid.New(), UserID: userID, TokenHash: hash, ExpiresAt: exp}
	return nil
}
func (s *fakeSessions) Lookup(_ context.Context, hash string) (*domauth.RefreshSession, error) {
	if r, ok := s.rows[hash]; ok {
		return r, nil
	}
	return nil, domauth.ErrRefreshNotFound
}
func (s *fakeSessions) Revoke(_ context.Context, hash string) error {
	if r, ok := s.rows[hash]; ok && r.RevokedAt == nil {
		now := time.Now()
		r.RevokedAt = &now
	}
	return nil
}
func (s *fakeSessions) RevokeAllForUser(_ context.Context, userID uuid.UUID) (int64, error) {
	var n int64
	for _, r := range s.rows {
		if r.UserID == userID && r.RevokedAt == nil {
			now := time.Now()
			r.RevokedAt = &now
			n++
		}
	}
	return n, nil
}

// fakeTokens needs a settable refresh user; add it via embedding helper.
func (t *fakeTokens) withRefreshUser(id uuid.UUID) *fakeTokens { t.refreshUser = id; return t }

func newService(creds *fakeCreds, tokens *fakeTokens, sess domauth.RefreshSessionStore) *Service {
	return NewService(Config{}, Deps{
		Credentials: creds,
		Phone:       fakeNormalizer{},
		Tokens:      tokens,
		Sessions:    sess,
	})
}

func newProviderService(creds *fakeCreds, tokens *fakeTokens, provider domauth.PhoneAuthProvider, cooldown domauth.CooldownStore, sess domauth.RefreshSessionStore) *Service {
	return NewService(Config{
		OtpResendCooldown: time.Minute,
	}, Deps{
		Credentials: creds,
		Cooldown:    cooldown,
		Phone:       fakeNormalizer{},
		PhoneAuth:   provider,
		Tokens:      tokens,
		Sessions:    sess,
	})
}

// ---- tests ----

func TestPhoneProvider_RequestAndVerify_UsesInsightSessionBranch(t *testing.T) {
	creds := newFakeCreds()
	uid := uuid.New()
	creds.byPhone["+5511999999999"] = &domauth.Credential{ID: uuid.New(), UserID: uid, PhoneE164: "+5511999999999"}
	sess := newFakeSessions()
	provider := &fakePhoneProvider{}
	cooldown := &fakeCooldown{}
	svc := newProviderService(creds, &fakeTokens{}, provider, cooldown, sess)

	if err := svc.RequestOtp(context.Background(), RequestOtpInput{RawPhone: "+5511999999999"}); err != nil {
		t.Fatalf("RequestOtp: %v", err)
	}
	if provider.sendPhone != "+5511999999999" {
		t.Fatalf("provider got phone %q", provider.sendPhone)
	}
	if cooldown.mark != 1 {
		t.Fatalf("expected cooldown mark, got %d", cooldown.mark)
	}

	res, err := svc.VerifyOtp(context.Background(), VerifyOtpInput{RawPhone: "+5511999999999", Code: "123456"})
	if err != nil {
		t.Fatalf("VerifyOtp: %v", err)
	}
	if provider.verifyPhone != "+5511999999999" || provider.verifyCode != "123456" {
		t.Fatalf("provider verify got phone=%q code=%q", provider.verifyPhone, provider.verifyCode)
	}
	if res.Tokens == nil {
		t.Fatal("expected existing-phone login tokens")
	}
	if len(sess.rows) != 1 {
		t.Fatalf("expected refresh session stored, got %d", len(sess.rows))
	}
}

func TestPhoneProvider_VerifyFailureDoesNotIssueInsightSession(t *testing.T) {
	provider := &fakePhoneProvider{err: domauth.ErrPhoneProviderInvalid}
	svc := newProviderService(newFakeCreds(), &fakeTokens{}, provider, &fakeCooldown{}, newFakeSessions())

	_, err := svc.VerifyOtp(context.Background(), VerifyOtpInput{RawPhone: "+5511999999999", Code: "000000"})
	if !errors.Is(err, domauth.ErrOtpInvalid) {
		t.Fatalf("expected ErrOtpInvalid, got %v", err)
	}
}

func TestRefresh_RotatesAndRevokesOldToken(t *testing.T) {
	creds := newFakeCreds()
	uid := uuid.New()
	creds.byUser[uid] = &domauth.Credential{ID: uuid.New(), UserID: uid, PhoneE164: "+5511999999999"}
	creds.byPhone["+5511999999999"] = creds.byUser[uid]
	sess := newFakeSessions()
	tokens := (&fakeTokens{}).withRefreshUser(uid)
	svc := newService(creds, tokens, sess)

	// Seed a live session as if it had been issued at login.
	first := "refresh-original"
	_ = sess.Create(context.Background(), uid, hashToken(first), time.Now().Add(time.Hour))

	out, err := svc.Refresh(context.Background(), RefreshInput{RefreshToken: first})
	if err != nil {
		t.Fatalf("Refresh: %v", err)
	}
	if out.RefreshToken == first {
		t.Fatal("expected a rotated (new) refresh token")
	}
	// The original must now be revoked → reuse rejected.
	if r := sess.rows[hashToken(first)]; r == nil || r.RevokedAt == nil {
		t.Fatal("expected original refresh session to be revoked after rotation")
	}
	_, err = svc.Refresh(context.Background(), RefreshInput{RefreshToken: first})
	if !errors.Is(err, domauth.ErrRefreshRevoked) {
		t.Fatalf("expected ErrRefreshRevoked on reuse, got %v", err)
	}
}

func TestRefresh_UnknownTokenRejected(t *testing.T) {
	uid := uuid.New()
	tokens := (&fakeTokens{}).withRefreshUser(uid)
	svc := newService(newFakeCreds(), tokens, newFakeSessions())
	_, err := svc.Refresh(context.Background(), RefreshInput{RefreshToken: "never-issued"})
	if !errors.Is(err, domauth.ErrInvalidCredentials) {
		t.Fatalf("expected ErrInvalidCredentials for unknown refresh token, got %v", err)
	}
}

func TestLogout_RevokesSession(t *testing.T) {
	uid := uuid.New()
	sess := newFakeSessions()
	svc := newService(newFakeCreds(), &fakeTokens{}, sess)
	tok := "refresh-logout"
	_ = sess.Create(context.Background(), uid, hashToken(tok), time.Now().Add(time.Hour))

	if err := svc.Logout(context.Background(), tok); err != nil {
		t.Fatalf("Logout: %v", err)
	}
	if r := sess.rows[hashToken(tok)]; r == nil || r.RevokedAt == nil {
		t.Fatal("expected session revoked after logout")
	}
}
