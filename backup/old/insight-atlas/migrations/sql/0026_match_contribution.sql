-- COMPOSIÇÃO — uma partida completa montada de várias fontes.
--
-- O PROBLEMA QUE ISTO RESOLVE, E ELE SERIA SILENCIOSO. `match_record` era
-- escrita direto, com `ON CONFLICT (uid) DO UPDATE SET document = EXCLUDED`.
-- Basta cruzar duas fontes para isso destruir dado: o CSV público do
-- Brasileirão traz placar e mercado mas não traz chutes; uma raspagem traz
-- chutes mas não traz mercado. Ingeridas em qualquer ordem, a segunda
-- apagaria o bloco da primeira — sem erro, sem log, com a linha parecendo
-- completa até alguém contar.
--
-- A INVERSÃO. `match_record` deixa de ser escrita e passa a ser DERIVADA.
-- O que se grava é a contribuição de cada fonte, e a partida é a composição
-- delas. Reingerir uma fonte substitui a contribuição dela e só ela.
--
-- MEDIDO ANTES DE CONSTRUIR: as 1.899 partidas de Brasileirão que temos do
-- ESPN encontram todas as 1.899 contrapartidas no CSV público, no mesmo dia,
-- depois de converter o fuso. Duas fontes independentes, identidade em
-- acordo total — é isso que torna a composição possível, e é por isso que
-- toda fonte nova precisa provar alinhamento antes de entrar.
CREATE TABLE IF NOT EXISTS atlas.match_contribution (
    uid              TEXT        NOT NULL,
    -- A fonte é parte da chave. Duas fontes descrevendo a mesma partida são
    -- duas linhas, e nenhuma pisa na outra.
    source           VARCHAR(64) NOT NULL,

    -- Quais blocos esta fonte declara trazer. Guardado como texto ordenado
    -- ('core,market_close') e não como estrutura, porque o que importa aqui
    -- é comparar e mostrar, não navegar.
    profile          TEXT        NOT NULL,

    -- O que ESTA fonte disse, exatamente como chegou. É o que permite
    -- responder "de onde veio o placar desta partida" sem reprocessar nada.
    document         JSONB       NOT NULL,

    -- Projeções da identidade, para inspecionar sem abrir o JSON.
    competition      VARCHAR(64) NOT NULL,
    season           VARCHAR(16) NOT NULL,
    kickoff_utc      TIMESTAMPTZ NOT NULL,

    ingested_via     VARCHAR(16) NOT NULL,
    ingested_by      TEXT        NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (uid, source),
    CONSTRAINT ck_match_contribution_via
        CHECK (ingested_via IN ('api', 'cli'))
);

CREATE INDEX IF NOT EXISTS ix_match_contribution_uid
    ON atlas.match_contribution (uid);
CREATE INDEX IF NOT EXISTS ix_match_contribution_source
    ON atlas.match_contribution (source, ingested_at DESC);

--
-- DESACORDO ENTRE FONTES SOBRE UM FATO.
--
-- Duas fontes podem trazer blocos diferentes sem conflito nenhum — é o caso
-- normal e é o ponto da composição. Conflito é quando duas trazem o MESMO
-- fato com valores diferentes: um placar 2-1 e um 2-2 para a mesma partida
-- significam que uma delas está errada.
--
-- A precedência resolve qual vence, mas o desacordo fica gravado. Uma fonte
-- que discorda com frequência é uma fonte para revisar, e sem registro isso
-- só apareceria quando alguém desconfiasse de um número.
CREATE TABLE IF NOT EXISTS atlas.match_conflict (
    id               BIGSERIAL PRIMARY KEY,
    uid              TEXT        NOT NULL,
    -- O campo em disputa, no caminho do contrato: 'result.home_goals'.
    field            TEXT        NOT NULL,
    winning_source   VARCHAR(64) NOT NULL,
    winning_value    TEXT,
    losing_source    VARCHAR(64) NOT NULL,
    losing_value     TEXT,
    detected_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_match_conflict_uid
    ON atlas.match_conflict (uid);
CREATE INDEX IF NOT EXISTS ix_match_conflict_recent
    ON atlas.match_conflict (detected_at DESC);

-- `match_record` ganha de onde veio cada composição. Não substitui a coluna
-- `source` — aquela passa a dizer qual fonte venceu a precedência, e esta
-- diz quantas contribuíram.
ALTER TABLE atlas.match_record
    ADD COLUMN IF NOT EXISTS contributing_sources INTEGER NOT NULL DEFAULT 1;

-- Rollback:
--
-- BEGIN;
-- ALTER TABLE atlas.match_record DROP COLUMN IF EXISTS contributing_sources;
-- DROP TABLE IF EXISTS atlas.match_conflict;
-- DROP TABLE IF EXISTS atlas.match_contribution;
-- COMMIT;
