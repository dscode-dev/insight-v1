-- INTAKE-V1 — a partida passa a morar no banco, não numa pasta.
--
-- O QUE ISSO SUBSTITUI. Até aqui a única forma de uma partida chegar ao
-- Atlas era um arquivo aparecer em validated/{competicao}/{temporada}/
-- {fonte}/fixture/. Um watcher tirava a impressão digital do diretório
-- (contagem de arquivos, bytes, mtime mais recente) e, se mudasse,
-- reconstruía tudo. Esse gatilho não sabe o que mudou, não sabe se era
-- válido, e não tem como responder "deu certo" ou "falhou por isto".
--
-- Somado ao descarte silencioso de linha inválida, o resultado era que
-- ninguém conseguia dizer o que havia dentro do Atlas.
--
-- A IDENTIDADE É A CHAVE PRIMÁRIA, e é isso que torna a ingestão idempotente.
-- `uid` vem de atlas/match_identity.py — (competição, temporada, mandante,
-- visitante, dia UTC) — nunca do id da fonte. Reenviar a mesma partida
-- atualiza a linha; enviá-la por outra fonte encontra a mesma linha. Foi
-- keyear no id da fonte que fez 1.554 partidas serem contadas duas ou três
-- vezes pelo motor de força.
--
-- O REGISTRO INTEIRO FICA EM JSONB, E AS COLUNAS SÃO PROJEÇÕES DELE.
-- Duas razões. A primeira é auditoria: o que foi aceito fica gravado
-- exatamente como chegou, então uma dúvida futura sobre uma partida se
-- responde lendo a linha, não reconstruindo o que o parser talvez tenha
-- feito. A segunda é evolução: acrescentar um campo ao contrato não exige
-- migrar a tabela, e as colunas promovidas são só as que precisam de índice.
CREATE TABLE IF NOT EXISTS atlas.match_record (
    uid              TEXT PRIMARY KEY,
    schema_version   TEXT NOT NULL,

    -- Projeções da identidade. Existem como colunas porque toda consulta
    -- filtra por elas; a verdade continua sendo o `document`.
    competition      VARCHAR(64)  NOT NULL,
    season           VARCHAR(16)  NOT NULL,
    home_club_id     VARCHAR(64)  NOT NULL,
    away_club_id     VARCHAR(64)  NOT NULL,
    kickoff_utc      TIMESTAMPTZ  NOT NULL,

    -- Projeção do resultado, para contar sem abrir o JSON.
    home_goals       SMALLINT     NOT NULL,
    away_goals       SMALLINT     NOT NULL,

    -- Quem mandou, e por qual porta. `ingested_via` separa o que entrou por
    -- API do que entrou por CLI — mesma validação, mesma tabela, e a origem
    -- registrada porque "como isso entrou aqui" é a primeira pergunta quando
    -- um número não fecha.
    source           VARCHAR(64)  NOT NULL,
    source_match_id  TEXT         NOT NULL,
    ingested_via     VARCHAR(16)  NOT NULL,
    ingested_by      TEXT         NOT NULL,
    ingested_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),

    document         JSONB        NOT NULL,

    CONSTRAINT ck_match_record_via
        CHECK (ingested_via IN ('api', 'cli')),
    CONSTRAINT ck_match_record_goals
        CHECK (home_goals >= 0 AND away_goals >= 0),
    -- Um clube não joga contra si mesmo. O contrato já recusa, mas a
    -- restrição aqui é o que impede que uma futura porta de escrita que
    -- esqueça de validar consiga gravar.
    CONSTRAINT ck_match_record_distinct_clubs
        CHECK (home_club_id <> away_club_id)
);

-- A varredura que a reconstrução do corpus faz: tudo, em ordem cronológica.
-- A projeção é walk-forward, então a ordem de leitura é a ordem dos jogos.
CREATE INDEX IF NOT EXISTS ix_match_record_kickoff
    ON atlas.match_record (kickoff_utc, uid);

-- Recorte por competição e temporada, que é como toda consulta de cobertura
-- e todo rebuild parcial pergunta.
CREATE INDEX IF NOT EXISTS ix_match_record_competition_season
    ON atlas.match_record (competition, season, kickoff_utc);

-- "Que partidas deste clube nós temos" — nos dois lados do confronto.
CREATE INDEX IF NOT EXISTS ix_match_record_home_club
    ON atlas.match_record (home_club_id, kickoff_utc);
CREATE INDEX IF NOT EXISTS ix_match_record_away_club
    ON atlas.match_record (away_club_id, kickoff_utc);

--
-- O QUE FOI RECUSADO TAMBÉM É DADO.
--
-- Uma linha inválida hoje desaparece: nenhum erro, nenhum log, nenhuma
-- contagem. Quem enviou não descobre, e quem consulta não sabe que faltou.
-- Guardar a recusa transforma "o Atlas não tem essa partida" de mistério em
-- consulta.
--
-- NÃO tem chave primária pela identidade: um registro recusado pode nem ter
-- identidade válida — frequentemente é exatamente esse o motivo da recusa.
CREATE TABLE IF NOT EXISTS atlas.match_rejection (
    id               BIGSERIAL PRIMARY KEY,
    rejected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingested_via     VARCHAR(16) NOT NULL,
    ingested_by      TEXT        NOT NULL,
    -- Melhor esforço: o que dava para identificar do registro recusado.
    -- Nulo quando nem isso o registro trazia.
    competition      VARCHAR(64),
    season           VARCHAR(16),
    source_match_id  TEXT,
    -- Um erro por campo, como a validação devolve: [{"field":…,"reason":…}].
    errors           JSONB       NOT NULL,
    document         JSONB       NOT NULL,

    CONSTRAINT ck_match_rejection_via
        CHECK (ingested_via IN ('api', 'cli'))
);

CREATE INDEX IF NOT EXISTS ix_match_rejection_recent
    ON atlas.match_rejection (rejected_at DESC);

-- Rollback:
--
-- BEGIN;
-- DROP TABLE IF EXISTS atlas.match_rejection;
-- DROP TABLE IF EXISTS atlas.match_record;
-- COMMIT;
