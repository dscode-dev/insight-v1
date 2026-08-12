-- VECTOR-V1 — uma versão de embedding, e o espaço que a torna comparável.
--
-- O QUE SUBSTITUI. `atlas.atlas_vector_memory` guardava DUAS versões por
-- partida (`embedding vector(32)` e `embedding_v2 vector(37)`), sem nada que
-- dissesse qual valia. Medidas contra as 7.261 partidas em produção, a v2
-- tinha 14 dimensões constantes e 2 duplicadas — 21 colunas de informação
-- num vetor de 37.
--
-- A tabela antiga NÃO é apagada aqui. Ela ainda responde à consulta ao vivo
-- enquanto esta não é adotada, e apagá-la na mesma migration que cria a nova
-- deixaria uma janela sem memória vetorial nenhuma.
CREATE TABLE IF NOT EXISTS atlas.match_vector (
    uid          TEXT PRIMARY KEY REFERENCES atlas.match_record(uid) ON DELETE CASCADE,
    version      TEXT        NOT NULL,
    competition  VARCHAR(64) NOT NULL,
    season       VARCHAR(16) NOT NULL,
    kickoff_utc  TIMESTAMPTZ NOT NULL,
    home_club_id VARCHAR(64) NOT NULL,
    away_club_id VARCHAR(64) NOT NULL,
    -- O desfecho. Guardado ao lado do vetor porque é ele que permite MEDIR
    -- se a vizinhança recuperada descreve alguma coisa; não entra no vetor,
    -- e nada no caminho de consulta o lê.
    label        VARCHAR(16) NOT NULL,
    embedding    vector(25)  NOT NULL,
    -- As features antes de padronizar. É o que torna uma resposta
    -- explicável: dá para dizer POR QUE duas partidas se parecem, em vez de
    -- só afirmar que se parecem.
    features     JSONB       NOT NULL,
    built_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ON DELETE CASCADE acima é deliberado: um vetor cuja partida saiu da base é
-- exatamente o resíduo que produziu 134 órfãos na tabela antiga, respondendo
-- a consultas com dados de uma versão anterior do registro de clubes.

CREATE INDEX IF NOT EXISTS ix_match_vector_hnsw
    ON atlas.match_vector USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS ix_match_vector_filtros
    ON atlas.match_vector (competition, season, kickoff_utc);

--
-- O ESPAÇO. Média e desvio por dimensão, gravados.
--
-- Padronizar exige as constantes do CORPUS. Uma consulta ao vivo precisa das
-- MESMAS, ou o vetor da consulta cai num espaço diferente do dos vetores
-- guardados — e a similaridade compara coisas que não estão na mesma régua,
-- sem erro em lugar nenhum e com números plausíveis. Recalcular na hora
-- daria uma resposta diferente a cada partida nova ingerida.
--
CREATE TABLE IF NOT EXISTS atlas.vector_space (
    version      TEXT PRIMARY KEY,
    dimensions   JSONB       NOT NULL,
    means        JSONB       NOT NULL,
    deviations   JSONB       NOT NULL,
    matches      INTEGER     NOT NULL,
    built_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS atlas.match_vector;
-- DROP TABLE IF EXISTS atlas.vector_space;
-- COMMIT;
