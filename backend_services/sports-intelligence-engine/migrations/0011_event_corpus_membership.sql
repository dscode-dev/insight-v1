-- 0011 — Pertinência de evento no corpus publicado (PR-04.4.2)
--
-- POR QUE UMA MIGRATION NOVA E NÃO UMA EDIÇÃO. O aplicador guarda o SHA-256 de
-- cada migration aplicada e RECUSA seguir quando o arquivo muda depois —
-- porque nesse ponto o banco e o repositório discordam em silêncio. O caminho
-- de volta é sempre uma migration nova.
--
-- O QUE ELA RESOLVE. O PR-04.4.1 construiu eventos canônicos e os gravou no
-- registro; nenhuma versão do corpus os publica. A pergunta que falta responder
-- é «a versão 1.0 contém QUAIS eventos», e ela não se deriva:
--
--   «os eventos da partida que está no corpus»   FALSO das duas pontas
--
--     · uma versão pode publicar a partida SEM eventos — porque não declarou
--       execução de evento nenhuma, ou porque a licença os excluiu do escopo
--       comercial;
--     · o registro canônico é GLOBAL e cresce depois da publicação, então
--       derivar faria uma versão publicada mudar de conteúdo sem mudar de nome.
--
-- Então a pertinência de evento é GRAVADA, evento a evento, e congela junto
-- com a versão.
--
-- O FATO NÃO É DUPLICADO, como no PR-04.3. O `CanonicalMatchEvent` continua
-- sendo um só, no registro; o que existe por versão é uma LINHA DE PERTINÊNCIA
-- que aponta para ele.

-- ==================================== o digest do FATO do evento canônico ==
--
-- ELE EXISTE PARA RECUSAR CONFLITO (PR-04.4.2 §69). A identidade canônica do
-- evento é DERIVADA de `(partida, chave da fonte, revisão)`; duas execuções
-- sobre o mesmo dado produzem o mesmo id E o mesmo fato. Se o fato diverge sob
-- a mesma identidade, alguma coisa muito específica aconteceu — a fonte
-- reescreveu o passado sob a mesma chave, ou o mapeamento mudou de
-- significado. Sem esta coluna, o `ON CONFLICT DO NOTHING` da escrita trata os
-- dois casos igual: fica com o primeiro, em silêncio.
--
-- ELE É O DIGESTO DO FATO, E NÃO DO ESTADO. `status` fica de fora de
-- propósito: `ACTIVE → CORRECTED` é o que o motor SOUBE DEPOIS, não uma
-- mudança no que aconteceu em campo. Com o estado dentro, reprocessar um
-- arquivo cujos eventos já foram corrigidos — o caso mais comum que existe —
-- seria acusado de conflito. E é isso que permite gravar o digest UMA vez, na
-- inserção: a transição de revisão toca `status` e nada mais.
--
-- NULO É «NÃO SEI», e não «igual a qualquer coisa». Eventos gravados antes
-- desta migration não têm digest, e a guarda os deixa passar em vez de
-- inventar uma comparação — mentir sobre o que se sabe é pior que admitir a
-- lacuna.
ALTER TABLE canonical_match_events
    ADD COLUMN content_digest text;

ALTER TABLE canonical_match_events
    ADD CONSTRAINT cme_digest_valido CHECK (
        content_digest IS NULL OR content_digest ~ '^[0-9a-f]{64}$'
    );

-- ==================================== as execuções de evento de uma versão ==
--
-- TABELA PRÓPRIA E NÃO COLUNA `uuid[]`, pela mesma razão de
-- `historical_canonical_version_builds`: a pergunta inversa — «quais versões
-- publicaram esta execução de evento?» — num array vira varredura e aqui vira
-- índice.

CREATE TABLE historical_canonical_version_event_builds (
    version_id      uuid NOT NULL
                    REFERENCES historical_canonical_dataset_versions (id)
                    ON DELETE CASCADE,
    build_run_id    uuid NOT NULL REFERENCES canonical_event_build_runs (id),

    PRIMARY KEY (version_id, build_run_id)
);

CREATE INDEX hcveb_build_idx
    ON historical_canonical_version_event_builds (build_run_id);

-- ============================================== a pertinência de evento ==

CREATE TABLE historical_canonical_event_members (
    version_id          uuid NOT NULL
                        REFERENCES historical_canonical_dataset_versions (id)
                        ON DELETE CASCADE,
    -- A AUTORIDADE É O `CanonicalEventId` (§7). Dois chutes do mesmo jogador
    -- no mesmo minuto são dois eventos; colapsá-los por «mesma partida, mesmo
    -- jogador, mesmo minuto» apagaria um fato que aconteceu.
    event_id            uuid NOT NULL REFERENCES canonical_match_events (id),
    -- A partida a que ele pertence. Ela é REDUNDANTE com o registro e está
    -- aqui de propósito: sem ela, «os eventos desta partida nesta versão» é
    -- uma junção com a tabela de eventos inteira, e com ela é um índice.
    match_id            uuid NOT NULL REFERENCES matches (id),
    -- A PARTIÇÃO, pelo mesmo motivo: contar eventos por competição/temporada
    -- para o manifesto não pode exigir junção com `matches` e `seasons`.
    competition_code    text NOT NULL,
    season_label        text NOT NULL,
    -- O digest do CONTEÚDO publicado. É ele que permite conferir que a versão
    -- publica o conteúdo que ela imprimiu, sem reler evento nenhum.
    content_digest      text NOT NULL,

    -- UMA PERTINÊNCIA POR EVENTO POR VERSÃO (§68). Duas execuções que
    -- produziram o mesmo evento contribuem DUAS linhagens e UMA pertinência —
    -- a chave primária é o que impede a segunda de virar um evento a mais na
    -- contagem do manifesto.
    PRIMARY KEY (version_id, event_id),
    CONSTRAINT hcem_digest CHECK (content_digest ~ '^[0-9a-f]{64}$'),
    -- O EVENTO PERTENCE A UMA PARTIDA QUE ESTÁ NA VERSÃO. Sem isto, um evento
    -- órfão entraria no corpus apontando para uma partida que ele não tem — e
    -- a travessia «versão → evento → partida» quebraria no meio.
    FOREIGN KEY (version_id, match_id)
        REFERENCES historical_canonical_members (version_id, match_id)
        ON DELETE CASCADE
);

CREATE INDEX hcem_match_idx
    ON historical_canonical_event_members (version_id, match_id);

CREATE INDEX hcem_particao_idx
    ON historical_canonical_event_members (version_id, competition_code, season_label);

-- A travessia para frente: «este evento canônico está em quais corpus?»
CREATE INDEX hcem_event_idx ON historical_canonical_event_members (event_id);

-- ================================== as execuções que produziram o evento ==
--
-- PLURAL DE PROPÓSITO (§66, §68). O mesmo evento canônico pode ter sido
-- produzido por duas execuções — a segunda sendo reprocessamento —, e as duas
-- linhagens são igualmente verdadeiras. Guardar uma só apagaria metade da
-- resposta a «de onde veio este evento».

CREATE TABLE historical_canonical_event_member_builds (
    version_id      uuid NOT NULL,
    event_id        uuid NOT NULL,
    build_run_id    uuid NOT NULL REFERENCES canonical_event_build_runs (id),

    PRIMARY KEY (version_id, event_id, build_run_id),
    FOREIGN KEY (version_id, event_id)
        REFERENCES historical_canonical_event_members (version_id, event_id)
        ON DELETE CASCADE
);

CREATE INDEX hcemb_build_idx
    ON historical_canonical_event_member_builds (build_run_id);
