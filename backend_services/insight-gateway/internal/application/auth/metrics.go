package auth

// Metrics records the auth-domain counters required by Auth-A Part 10:
//
//	auth_phone_provider_requests_total
//	auth_phone_provider_verifications_total
//	auth_registrations_total
//	auth_logins_total
//	auth_refresh_total
//
// The interface lives here (application layer) so the service has no Prometheus
// dependency; the concrete implementation is infrastructure/authmetrics. A nil
// Metrics disables instrumentation (the service guards every call), which keeps
// unit tests free of a registry.
type Metrics interface {
	// PhoneProviderRequest records a provider-backed OTP request attempt.
	PhoneProviderRequest(provider string, success bool)
	// PhoneProviderVerification records a provider-backed OTP verify attempt.
	PhoneProviderVerification(provider string, success bool)
	// Login records a successful Insight login.
	Login()
	// Registration records a completed registration (CompleteRegistration).
	Registration()
	// Refresh records a successful access/refresh-token rotation.
	Refresh()
}
