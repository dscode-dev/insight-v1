package httpapi

import "testing"

// The slug is not a display field. It is the identifier a competition carries
// out of this table into the app, into Explorer's collection config and into
// Atlas's competition_key — three consumers that never see this validation and
// cannot repair a value it let through.

func strptr(s string) *string { return &s }

func TestSlugAcceptsThePlatformShape(t *testing.T) {
	for _, slug := range []string{
		"premier-league", "laliga", "brasileirao", "champions-league",
		"libertadores", "serie-a", "copa-do-brasil", "mls2",
	} {
		if !slugPattern.MatchString(slug) {
			t.Errorf("slug valido recusado: %q", slug)
		}
	}
}

func TestSlugRejectsWhatBreaksDownstream(t *testing.T) {
	cases := map[string]string{
		"Premier-League":  "maiusculas quebram a comparacao no Explorer",
		"premier league":  "espaco quebra a chave em URL e em config",
		"premier_league":  "underscore diverge da convencao ja em uso",
		"-premier":        "hifen inicial produz chave vazia ao dividir",
		"premier-":        "hifen final idem",
		"premier--league": "hifen duplo produz segmento vazio",
		"":                "vazio nao identifica nada",
		"café":            "acento nao sobrevive a normalizacao inconsistente",
	}
	for slug, why := range cases {
		if slugPattern.MatchString(slug) {
			t.Errorf("slug invalido aceito: %q (%s)", slug, why)
		}
	}
}

func TestCreateRequiresSlugAndName(t *testing.T) {
	if problem := (competitionInput{}).validate(true); problem != "slug_required" {
		t.Errorf("criacao sem slug: %q", problem)
	}
	if problem := (competitionInput{Slug: strptr("x")}).validate(true); problem != "name_required" {
		t.Errorf("criacao sem nome: %q", problem)
	}
}

func TestUpdateDoesNotRequireThemAgain(t *testing.T) {
	// PATCH carries only what changed; demanding slug and name on every edit
	// would make "rename this competition" impossible to express.
	if problem := (competitionInput{Name: strptr("Nome novo")}).validate(false); problem != "" {
		t.Errorf("edicao parcial recusada: %q", problem)
	}
}

func TestLogoIsOptionalButMustBeFetchable(t *testing.T) {
	// Optional: a competition is registrable before anyone has produced
	// artwork. Present-but-wrong is the case worth catching — it renders as a
	// broken image in the app and reports nothing anywhere.
	if problem := (competitionInput{}).validate(false); problem != "" {
		t.Errorf("logo ausente devia ser aceito: %q", problem)
	}
	if problem := (competitionInput{LogoURL: strptr("")}).validate(false); problem != "" {
		t.Errorf("logo vazio devia ser aceito: %q", problem)
	}
	if problem := (competitionInput{LogoURL: strptr("https://cdn.x/a.png")}).validate(false); problem != "" {
		t.Errorf("logo https recusado: %q", problem)
	}
	for _, bad := range []string{"http://cdn.x/a.png", "//cdn.x/a.png", "cdn.x/a.png"} {
		if problem := (competitionInput{LogoURL: strptr(bad)}).validate(false); problem == "" {
			t.Errorf("logo invalido aceito: %q", bad)
		}
	}
}

func TestAccentColorShape(t *testing.T) {
	if problem := (competitionInput{AccentColor: strptr("#5BA8FF")}).validate(false); problem != "" {
		t.Errorf("cor valida recusada: %q", problem)
	}
	for _, bad := range []string{"5BA8FF", "#5BA8F", "#GGGGGG", "blue"} {
		if problem := (competitionInput{AccentColor: strptr(bad)}).validate(false); problem == "" {
			t.Errorf("cor invalida aceita: %q", bad)
		}
	}
}

func TestOperatorFallsBackToIdThenNull(t *testing.T) {
	// `updated_by` answers "who changed the registry". An empty string would
	// record someone with a blank name; NULL records that it is unknown.
	if got := nullableOperator(ConsoleOperator{Username: "darlan"}); got == nil || *got != "darlan" {
		t.Errorf("username deveria ganhar: %v", got)
	}
	if got := nullableOperator(ConsoleOperator{ID: "op-1"}); got == nil || *got != "op-1" {
		t.Errorf("id deveria servir de fallback: %v", got)
	}
	if got := nullableOperator(ConsoleOperator{}); got != nil {
		t.Errorf("sem operador deveria ser NULL, veio %q", *got)
	}
}

func TestTrimmedOrNilTreatsBlankAsAbsent(t *testing.T) {
	// COALESCE($n, coluna) keeps the stored value when the parameter is NULL.
	// A whitespace-only submission from a console form must therefore arrive
	// as NULL, or it would blank the field.
	if trimmedOrNil(nil) != nil {
		t.Error("nil deveria continuar nil")
	}
	if trimmedOrNil(strptr("   ")) != nil {
		t.Error("string em branco deveria virar nil, nao apagar o valor guardado")
	}
	if got := trimmedOrNil(strptr("  LaLiga  ")); got == nil || *got != "LaLiga" {
		t.Errorf("deveria aparar espacos: %v", got)
	}
}
