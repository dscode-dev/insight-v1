package proxy

import "testing"

func TestParseFlag(t *testing.T) {
	cases := []struct {
		raw      string
		wantMode RolloutMode
		wantPct  int
	}{
		{"", RolloutOff, 0},
		{"off", RolloutOff, 0},
		{"OFF", RolloutOff, 0},
		{"false", RolloutOff, 0},
		{"0", RolloutOff, 0},
		{"shadow", RolloutShadow, 0},
		{"SHADOW", RolloutShadow, 0},
		{"1", RolloutPercent, 1},
		{"50", RolloutPercent, 50},
		{"100", RolloutPercent, 100},
		// Invalid → default to off (forgiving by design)
		{"101", RolloutOff, 0},
		{"-1", RolloutOff, 0},
		{"abc", RolloutOff, 0},
		{"true", RolloutOff, 0}, // not a synonym; must be explicit
	}
	for _, c := range cases {
		t.Run(c.raw, func(t *testing.T) {
			f := ParseFlag(c.raw)
			if f.Mode != c.wantMode {
				t.Fatalf("mode: got %v want %v", f.Mode, c.wantMode)
			}
			if f.Percent != c.wantPct {
				t.Fatalf("percent: got %d want %d", f.Percent, c.wantPct)
			}
		})
	}
}

func TestFlag_String(t *testing.T) {
	cases := []struct {
		flag Flag
		want string
	}{
		{Flag{Mode: RolloutOff}, "off"},
		{Flag{Mode: RolloutShadow}, "shadow"},
		{Flag{Mode: RolloutPercent, Percent: 50}, "50"},
		{Flag{Mode: RolloutPercent, Percent: 100}, "100"},
	}
	for _, c := range cases {
		t.Run(c.want, func(t *testing.T) {
			if got := c.flag.String(); got != c.want {
				t.Fatalf("got %q want %q", got, c.want)
			}
		})
	}
}
