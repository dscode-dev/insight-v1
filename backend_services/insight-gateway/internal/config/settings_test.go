package config

import "testing"

func TestValidateAuthProviderSupabaseRequiresConfiguration(t *testing.T) {
	tests := []struct {
		name    string
		s       Settings
		wantErr bool
	}{
		{
			name: "supabase configured",
			s: Settings{
				AuthProvider:           "supabase",
				SupabaseURL:            "https://example.supabase.co/rest/v1/",
				SupabasePublishableKey: "publishable-test-key",
			},
		},
		{
			name: "supabase missing url",
			s: Settings{
				AuthProvider:           "supabase",
				SupabasePublishableKey: "publishable-test-key",
			},
			wantErr: true,
		},
		{
			name: "supabase missing key",
			s: Settings{
				AuthProvider: "supabase",
				SupabaseURL:  "https://example.supabase.co",
			},
			wantErr: true,
		},
		{
			name: "supabase invalid url",
			s: Settings{
				AuthProvider:           "supabase",
				SupabaseURL:            "example.supabase.co",
				SupabasePublishableKey: "publishable-test-key",
			},
			wantErr: true,
		},
		{
			name: "firebase standby is not bootable",
			s: Settings{
				AuthProvider: "firebase",
			},
			wantErr: true,
		},
		{
			name: "local allowed",
			s: Settings{
				AuthProvider: "local",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.s.ValidateAuthProvider()
			if tt.wantErr && err == nil {
				t.Fatal("expected error, got nil")
			}
			if !tt.wantErr && err != nil {
				t.Fatalf("expected nil error, got %v", err)
			}
		})
	}
}
