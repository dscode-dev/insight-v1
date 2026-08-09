package config

import (
	"reflect"
	"testing"
)

func TestPublisherIsDisabledWithoutSocialByDefault(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test")
	t.Setenv("NEXUS_PUBLISHER_ENABLED", "")
	t.Setenv("NEXUS_SOCIAL_GRPC_ADDR", "")

	settings, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if settings.PublisherEnabled {
		t.Fatal("publisher must be disabled by default")
	}
	if settings.SocialGrpcAddr != "" {
		t.Fatalf("social address = %q, want empty", settings.SocialGrpcAddr)
	}
}

func TestProviderRuntimeDefaultsAreDisabledAndOrdered(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test")

	settings, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if settings.EnableOpenAI || settings.EnableAnthropic || settings.EnableGemini {
		t.Fatal("private providers must require explicit enable flags")
	}
	if settings.DefaultProvider != "anthropic" {
		t.Fatalf("default provider = %q", settings.DefaultProvider)
	}
	want := []string{"anthropic", "openai", "gemini"}
	if !reflect.DeepEqual(settings.ProviderOrder, want) {
		t.Fatalf("provider order = %v, want %v", settings.ProviderOrder, want)
	}
}

func TestProviderRuntimeAcceptsGenericModelsAliasesAndOrder(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test")
	t.Setenv("OPENAI_MODEL", "gpt-test")
	t.Setenv("ANTHROPIC_MODEL", "claude-test")
	t.Setenv("GEMINI_MODEL", "gemini-test")
	t.Setenv("NEXUS_ENABLE_OPENAI", "true")
	t.Setenv("NEXUS_PROVIDER_ORDER", "gemini,gpt,claude")
	t.Setenv("NEXUS_DEFAULT_PROVIDER", "gemini")

	settings, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if settings.OpenAIModel != "gpt-test" ||
		settings.AnthropicModel != "claude-test" ||
		settings.GeminiModel != "gemini-test" {
		t.Fatalf("unexpected models: %+v", settings)
	}
	if !settings.EnableOpenAI || settings.EnableAnthropic || settings.EnableGemini {
		t.Fatal("provider enable flags were not applied independently")
	}
	want := []string{"gemini", "openai", "anthropic"}
	if !reflect.DeepEqual(settings.ProviderOrder, want) {
		t.Fatalf("provider order = %v, want %v", settings.ProviderOrder, want)
	}
}

func TestPublisherCanBeEnabledWithExplicitSocialAddress(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test")
	t.Setenv("NEXUS_PUBLISHER_ENABLED", "true")
	t.Setenv("NEXUS_SOCIAL_GRPC_ADDR", "dns:///insight-social:50051")
	// A publisher needs somewhere to generate from; see
	// TestPublisherWithoutProviderIsRejected for why this is now required.
	t.Setenv("NEXUS_ENABLE_ANTHROPIC", "true")

	settings, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if !settings.PublisherEnabled {
		t.Fatal("publisher must honor explicit enablement")
	}
	if settings.SocialGrpcAddr != "dns:///insight-social:50051" {
		t.Fatalf("unexpected social address %q", settings.SocialGrpcAddr)
	}
}

// A publisher with no provider hits ErrAllProvidersFailed on every draft and
// opens a ticket for each one. Refusing at boot turns a slow flood of tickets
// into one clear message.
func TestPublisherWithoutProviderIsRejected(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test")
	t.Setenv("NEXUS_PUBLISHER_ENABLED", "true")
	t.Setenv("NEXUS_SOCIAL_GRPC_ADDR", "dns:///insight-social:50051")

	if _, err := Load(); err == nil {
		t.Fatal("publisher with zero providers must not boot")
	}
}

func TestPublisherWithoutSocialAddressIsRejected(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test")
	t.Setenv("NEXUS_PUBLISHER_ENABLED", "true")
	t.Setenv("NEXUS_ENABLE_ANTHROPIC", "true")

	if _, err := Load(); err == nil {
		t.Fatal("publisher without a Social address must not boot")
	}
}

// The publisher off is the current production state and must stay bootable
// with nothing else configured — the validation is about the publisher, not
// a new set of required variables.
func TestPublisherDisabledNeedsNoProviders(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test")

	settings, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if settings.PublisherEnabled {
		t.Fatal("publisher must default to off")
	}
}

// MinIdle below the handler's worst case lets a second consumer reclaim an
// in-flight trend and publish the same agent post twice. Unset, it is raised
// rather than refused, so the default configuration still boots.
func TestClaimerMinIdleIsRaisedToHandlerWorstCase(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test")
	t.Setenv("NEXUS_PUBLISHER_ENABLED", "true")
	t.Setenv("NEXUS_SOCIAL_GRPC_ADDR", "dns:///insight-social:50051")
	t.Setenv("NEXUS_ENABLE_ANTHROPIC", "true")
	t.Setenv("NEXUS_LLM_TIMEOUT", "60")

	settings, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	want := 60 * len(settings.ProviderOrder)
	if settings.ClaimerMinIdleSec != want {
		t.Fatalf("ClaimerMinIdleSec = %d, want %d", settings.ClaimerMinIdleSec, want)
	}
	if !settings.ClaimerMinIdleDerived {
		t.Fatal("the raise must be recorded so the boot log can report it")
	}
}

// Explicitly choosing an unsafe value is refused, not silently corrected:
// someone typed that number and needs to know why it cannot stand.
func TestExplicitlyUnsafeClaimerMinIdleIsRejected(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test")
	t.Setenv("NEXUS_PUBLISHER_ENABLED", "true")
	t.Setenv("NEXUS_SOCIAL_GRPC_ADDR", "dns:///insight-social:50051")
	t.Setenv("NEXUS_ENABLE_ANTHROPIC", "true")
	t.Setenv("NEXUS_LLM_TIMEOUT", "60")
	t.Setenv("NEXUS_CLAIMER_MIN_IDLE", "30")

	if _, err := Load(); err == nil {
		t.Fatal("an explicitly unsafe MinIdle must not boot")
	}
}

// With the publisher off there is no LLM call in the handler, so the long
// floor would only slow pending recovery down for no reason.
func TestClaimerMinIdleUntouchedWhenPublisherIsOff(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test")

	settings, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if settings.ClaimerMinIdleSec != 30 {
		t.Fatalf("ClaimerMinIdleSec = %d, want the 30s default", settings.ClaimerMinIdleSec)
	}
}

func TestControlPlaneTokenIsRead(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test")
	t.Setenv("NEXUS_CONTROL_PLANE_TOKEN", "  s3cret  ")

	settings, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	// Trimmed: a token pasted with a trailing newline in a .env would
	// otherwise never match the one the Control Plane sends.
	if settings.ControlPlaneToken != "s3cret" {
		t.Fatalf("ControlPlaneToken = %q", settings.ControlPlaneToken)
	}
}
