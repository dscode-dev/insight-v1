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
