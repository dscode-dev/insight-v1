-- 0003 — Registro canônico futebolístico (PR-01 persistido)
--
-- POR QUE ESTA MIGRATION EXISTE NO PR-03. O PR-01 modelou o domínio
-- futebolístico inteiro — competição, temporada, time, jogador, partida — e
-- deliberadamente não o persistiu: sem uma fonte de dados, tabelas vazias
-- seriam peso sem uso. O PR-02 trouxe os bytes. O PR-03 é o primeiro que
-- precisa CONSULTAR entidades canônicas, porque resolver identidade é
-- justamente encontrar a entidade que já existe.
--
-- Então o registro nasce aqui, e nasce com a forma que a resolução precisa:
-- com colunas normalizadas para busca em massa.
--
-- `normalized_name` É MATERIALIZADA, e não calculada no SQL. Normalizar
-- dentro do banco exigiria uma função equivalente à do Python — remoção de
-- acento, casefold, sufixos societários com a guarda das duas palavras — e as
-- duas divergiriam na primeira mudança. A coluna é escrita pelo mesmo
-- normalizador que a resolução usa, e a versão dele fica gravada ao lado para
-- que uma mudança futura saiba o que reindexar (§66).

-- ============================================================ competições ==

CREATE TABLE competitions (
    id                  uuid PRIMARY KEY,
    code                text NOT NULL,
    name                text NOT NULL,
    region              text NOT NULL,
    competition_type    text NOT NULL,
    active              boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),

    -- O CATÁLOGO É FECHADO (PR-01). A constraint o repete no banco porque
    -- uma sexta competição inserida por um script ganharia resolução sem
    -- nunca ter passado por decisão nenhuma.
    CONSTRAINT competitions_catalogo_fechado CHECK (
        code IN ('PREMIER_LEAGUE', 'LA_LIGA', 'BRA_SERIE_A',
                 'UEFA_CHAMPIONS_LEAGUE', 'CONMEBOL_LIBERTADORES')
    ),
    CONSTRAINT competitions_tipo CHECK (
        competition_type IN ('DOMESTIC_LEAGUE', 'CONTINENTAL_CLUB')
    ),
    CONSTRAINT competitions_codigo_unico UNIQUE (code)
);

-- =============================================================== temporadas ==

CREATE TABLE seasons (
    id                  uuid PRIMARY KEY,
    competition_id      uuid NOT NULL REFERENCES competitions (id) ON DELETE CASCADE,
    label               text NOT NULL,
    normalized_label    text NOT NULL,
    starts_at           timestamptz NOT NULL,
    ends_at             timestamptz NOT NULL,
    regime_code         text NOT NULL,
    regime_from         timestamptz NOT NULL,
    regime_to           timestamptz,
    regulation_version  text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT seasons_janela CHECK (ends_at > starts_at),
    CONSTRAINT seasons_regime CHECK (
        regime_code IN ('DOUBLE_ROUND_ROBIN', 'GROUP_STAGE_KNOCKOUT', 'LEAGUE_PHASE_KNOCKOUT')
    ),
    -- Duas temporadas com o mesmo rótulo na mesma competição seriam a mesma
    -- edição duas vezes — e a resolução escolheria por ordem de leitura.
    CONSTRAINT seasons_rotulo_unico UNIQUE (competition_id, label)
);

-- A CONSULTA DA RESOLUÇÃO DE TEMPORADA: (competição, rótulo normalizado).
CREATE INDEX seasons_busca_idx ON seasons (competition_id, normalized_label);
-- A consulta que desambigua `2024` pela data da partida (§15).
CREATE INDEX seasons_janela_idx ON seasons (competition_id, starts_at, ends_at);

-- ==================================================================== times ==

CREATE TABLE teams (
    id                  uuid PRIMARY KEY,
    canonical_name      text NOT NULL,
    normalized_name     text NOT NULL,
    normalizer_major    integer NOT NULL DEFAULT 1,
    normalizer_minor    integer NOT NULL DEFAULT 0,
    country             text NOT NULL,
    short_name          text,
    active              boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT teams_pais CHECK (length(country) = 2),
    CONSTRAINT teams_nome_nao_vazio CHECK (length(btrim(canonical_name)) > 0)
);

-- A CONSULTA QUENTE: nome normalizado → candidatos. NÃO é UNIQUE, e a
-- ausência é deliberada: dois clubes podem normalizar para a mesma chave —
-- `Sporting` de Portugal e `Sporting` do Kansas, se alguém os registrar
-- assim — e é exatamente esse caso que a resolução precisa VER para mandar
-- para revisão. Um UNIQUE aqui esconderia a colisão no `INSERT`.
CREATE INDEX teams_normalizado_idx ON teams (normalized_name);
CREATE INDEX teams_pais_idx ON teams (country, normalized_name);

-- ================================================================ jogadores ==

CREATE TABLE players (
    id                  uuid PRIMARY KEY,
    canonical_name      text NOT NULL,
    normalized_name     text NOT NULL,
    normalizer_major    integer NOT NULL DEFAULT 1,
    normalizer_minor    integer NOT NULL DEFAULT 0,
    date_of_birth       date,
    nationality         text,
    preferred_foot      text,
    primary_position    text,
    active              boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT players_pe CHECK (preferred_foot IS NULL OR preferred_foot IN ('LEFT', 'RIGHT', 'BOTH')),
    CONSTRAINT players_nome_nao_vazio CHECK (length(btrim(canonical_name)) > 0)
);

-- HOMÔNIMOS SÃO ESPERADOS E NÃO SÃO ERRO. O índice existe justamente para
-- que a resolução os encontre TODOS — um `UNIQUE` aqui impediria registrar
-- dois `João Silva`, que é o caso real que o PR inteiro trata.
CREATE INDEX players_normalizado_idx ON players (normalized_name);
-- A evidência que separa homônimos (§19, §86). Índice PARCIAL porque a
-- consulta só serve quando a data existe.
CREATE INDEX players_dob_idx ON players (normalized_name, date_of_birth)
    WHERE date_of_birth IS NOT NULL;

CREATE TABLE player_team_tenures (
    id          bigserial PRIMARY KEY,
    player_id   uuid NOT NULL REFERENCES players (id) ON DELETE CASCADE,
    team_id     uuid NOT NULL REFERENCES teams (id) ON DELETE CASCADE,
    valid_from  timestamptz NOT NULL,
    valid_to    timestamptz,

    CONSTRAINT tenures_janela CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

-- A CONSULTA DA EVIDÊNCIA TEMPORAL (§20): o clube do jogador NA DATA.
-- Empréstimo é vínculo simultâneo legítimo, então NÃO há constraint de
-- exclusão entre janelas — proibi-la apagaria um fato real do futebol.
CREATE INDEX tenures_jogador_idx ON player_team_tenures (player_id, valid_from);
CREATE INDEX tenures_time_idx ON player_team_tenures (team_id, valid_from);

-- ================================================================= partidas ==

CREATE TABLE matches (
    id                  uuid PRIMARY KEY,
    competition_id      uuid NOT NULL REFERENCES competitions (id) ON DELETE CASCADE,
    season_id           uuid NOT NULL REFERENCES seasons (id) ON DELETE CASCADE,
    home_team_id        uuid NOT NULL REFERENCES teams (id),
    away_team_id        uuid NOT NULL REFERENCES teams (id),
    scheduled_kickoff   timestamptz NOT NULL,
    actual_kickoff      timestamptz,
    stage_type          text NOT NULL,
    round_number        integer,
    group_label         text,
    regime_code         text NOT NULL,
    regime_from         timestamptz NOT NULL,
    regulation_version  text NOT NULL,
    lifecycle           text NOT NULL,
    neutral_venue       boolean NOT NULL DEFAULT false,
    venue_name          text,
    created_at          timestamptz NOT NULL DEFAULT now(),

    -- Herdado do PR-01: mandante e visitante não podem ser o mesmo clube.
    CONSTRAINT matches_times_distintos CHECK (home_team_id <> away_team_id),
    CONSTRAINT matches_rodada CHECK (round_number IS NULL OR round_number >= 1)
);

-- A CHAVE DE AGRUPAMENTO DA RESOLUÇÃO DE PARTIDA (§22). Ela reduz o espaço
-- de busca de «todas as partidas» para «as deste confronto nesta temporada»,
-- que são uma ou duas. Sem ela, resolver partida varreria a tabela por linha.
--
-- NÃO É UNIQUE: dois jogos do mesmo par na mesma temporada existem — ida e
-- volta de mata-mata, jogo único adiado e remarcado. É exatamente por isso
-- que o resolver pontua por horário em vez de casar por confronto.
CREATE INDEX matches_confronto_idx
    ON matches (season_id, home_team_id, away_team_id, scheduled_kickoff);
CREATE INDEX matches_competicao_idx ON matches (competition_id, season_id, scheduled_kickoff);
CREATE INDEX matches_kickoff_idx ON matches (scheduled_kickoff);

-- ===================================================== resultados (pós-jogo) ==
--
-- SEPARADO DE `matches` (PR-01, decisão central). O placar é informação
-- pós-jogo, e o motor descreve estados anteriores: se o agregado o carregasse,
-- qualquer caminho que descrevesse o minuto 63 poderia lê-lo, e a descrição
-- passaria a conter a resposta. A separação em tabela própria é a mesma
-- decisão, no banco.

CREATE TABLE match_results (
    match_id            uuid PRIMARY KEY REFERENCES matches (id) ON DELETE CASCADE,
    regular_home        integer NOT NULL,
    regular_away        integer NOT NULL,
    extra_home          integer,
    extra_away          integer,
    penalties_home      integer,
    penalties_away      integer,
    recorded_at         timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT results_nao_negativo CHECK (
        regular_home >= 0 AND regular_away >= 0
        AND (extra_home IS NULL OR extra_home >= 0)
        AND (penalties_home IS NULL OR penalties_home >= 0)
    ),
    -- Prorrogação é acumulada e só acontece após empate no tempo normal.
    CONSTRAINT results_prorrogacao_apos_empate CHECK (
        extra_home IS NULL OR regular_home = regular_away
    ),
    CONSTRAINT results_prorrogacao_completa CHECK (
        (extra_home IS NULL) = (extra_away IS NULL)
    ),
    CONSTRAINT results_penaltis_completos CHECK (
        (penalties_home IS NULL) = (penalties_away IS NULL)
    )
);
