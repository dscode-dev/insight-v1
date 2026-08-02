// Package otp generates + verifies OTP codes.
//
// Storage at rest: HMAC-SHA256(secret, phone+":"+code). The salt by
// phone means two users requesting the same random code don't share
// a hash row — eliminates any cross-phone collision risk and ties
// the hash to its intended target.
package otp

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math/big"
)

// Generator + Hasher in one object so wiring stays simple. Implements
// the auth.CodeHasher port; the Generate method is service-side only.
type Codec struct {
	HMACSecret []byte
	Length     int // 6 in production
}

func New(hmacSecret string, length int) *Codec {
	if length < 4 {
		length = 6
	}
	return &Codec{HMACSecret: []byte(hmacSecret), Length: length}
}

// Generate returns a uniformly-random numeric OTP. Uses crypto/rand
// (not math/rand) — predictable codes break the OTP threat model.
func (c *Codec) Generate() (string, error) {
	upper := int64(1)
	for i := 0; i < c.Length; i++ {
		upper *= 10
	}
	n, err := rand.Int(rand.Reader, big.NewInt(upper))
	if err != nil {
		return "", fmt.Errorf("otp: rand failed: %w", err)
	}
	return fmt.Sprintf("%0*d", c.Length, n.Int64()), nil
}

// Hash satisfies auth.CodeHasher.Hash.
func (c *Codec) Hash(code, phoneE164 string) string {
	m := hmac.New(sha256.New, c.HMACSecret)
	m.Write([]byte(phoneE164))
	m.Write([]byte(":"))
	m.Write([]byte(code))
	return hex.EncodeToString(m.Sum(nil))
}

// Verify satisfies auth.CodeHasher.Verify. Constant-time compare so
// timing leaks of "how many leading bytes match" don't help an
// attacker brute-force.
func (c *Codec) Verify(code, expectedHash, phoneE164 string) bool {
	actual := c.Hash(code, phoneE164)
	return hmac.Equal([]byte(actual), []byte(expectedHash))
}
