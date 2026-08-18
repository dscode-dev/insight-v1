-- 0008 — Composição multi-build e metadado da impressão (PR-04.3.1)
--
-- POR QUE UMA MIGRATION NOVA E NÃO UMA EDIÇÃO DA 0007. O aplicador guarda o
-- SHA-256 de cada migration aplicada e RECUSA seguir quando o arquivo muda
-- depois — porque nesse ponto o banco e o repositório discordam em silêncio.
-- Editar a 0007 quebraria todo ambiente que já a aplicou. O caminho de volta
-- é sempre uma migration nova.
--
-- O QUE ELA CORRIGE. A 0007 guardava UM `build_run_id` e UMA
-- `quality_assessment_id` por membro do corpus, e a composição escolhia qual —
-- na prática, a do build mais recente, via `DISTINCT ON`. Quando dois builds
-- produzem a MESMA partida — duas temporadas construídas em execuções
-- diferentes, ou um reprocessamento que confirma o anterior — guardar um só
-- apaga metade da linhagem, e a metade apagada era tão verdadeira quanto a
-- que ficou.
--
-- NENHUM BUILD VENCE. A pertinência passa a ter uma tabela-filha com UMA linha
-- por contribuição, e o membro guarda a UNIÃO das famílias. As duas coisas são
-- diferentes e as duas importam:
--
--   `historical_canonical_members.included_families`     o que o corpus publica
--   `historical_canonical_member_builds.included_families` o que cada build trouxe
--
-- A IMPRESSÃO GANHA NOME. `corpus_fingerprint` deixou de ser XOR-fold e passou
-- a ser SHA-256 sobre serialização ordenada. As duas são hex de 64 caracteres
-- e são INCOMPARÁVEIS; sem gravar qual construção produziu cada uma, comparar
-- duas versões diria «corpus diferente» sem explicação nenhuma.

-- ================================================ contribuições por membro ==

CREATE TABLE historical_canonical_member_builds (
    version_id              uuid NOT NULL,
    match_id                uuid NOT NULL,
    build_run_id            uuid NOT NULL REFERENCES canonical_build_runs (id),
    -- A avaliação daquele build. Ela é POR CONTRIBUIÇÃO e não por membro:
    -- dois builds sobre a mesma partida foram autorizados por avaliações
    -- diferentes, e as duas precisam sobreviver para que «por que esta
    -- partida está no corpus» tenha as duas respostas que de fato tem.
    quality_assessment_id   uuid NOT NULL
                            REFERENCES match_quality_assessments (id),
    -- A PARCELA daquele build, e não a união. Um build de pesquisa que trouxe
    -- ODDS e um comercial que não trouxe contribuem coisas diferentes para o
    -- mesmo membro, e o manifesto precisa poder dizer isso.
    included_families       text[] NOT NULL,

    PRIMARY KEY (version_id, match_id, build_run_id),
    FOREIGN KEY (version_id, match_id)
        REFERENCES historical_canonical_members (version_id, match_id)
        ON DELETE CASCADE,
    CONSTRAINT hcmb_familias_nao_vazias CHECK (
        array_length(included_families, 1) >= 1
    )
);

-- A TRAVESSIA PARA FRENTE, agora completa: «deste build saíram quais partidas,
-- em quais corpus». Sem este índice ela é varredura da tabela inteira.
CREATE INDEX hcmb_build_idx
    ON historical_canonical_member_builds (build_run_id);

-- ============================ a pertinência para de eleger um build vencedor ==

-- OS DADOS EXISTENTES MIGRAM ANTES DE AS COLUNAS SUMIREM. Um `DROP COLUMN`
-- direto descartaria a linhagem que a 0007 gravou — e ela é correta, só
-- incompleta: era uma contribuição, e continua sendo uma.
INSERT INTO historical_canonical_member_builds (
    version_id, match_id, build_run_id, quality_assessment_id, included_families
)
SELECT version_id, match_id, build_run_id, quality_assessment_id, included_families
FROM historical_canonical_members
ON CONFLICT DO NOTHING;

ALTER TABLE historical_canonical_members
    DROP COLUMN build_run_id,
    DROP COLUMN quality_assessment_id;

-- ==================================================== nome da construção ==

ALTER TABLE historical_canonical_manifests
    ADD COLUMN fingerprint_algorithm text NOT NULL
        DEFAULT 'canonical-sha256-v1',
    ADD COLUMN fingerprint_schema_version text NOT NULL DEFAULT '1.0';

-- O DEFAULT É PARA A COLUNA NASCER PREENCHIDA, e não para o código omitir o
-- valor: quem grava um manifesto informa qual construção usou. Se um dia
-- houver `canonical-sha256-v2`, uma linha sem valor explícito seria rotulada
-- v1 por acidente — e duas impressões incomparáveis passariam por comparáveis.
ALTER TABLE historical_canonical_manifests
    ALTER COLUMN fingerprint_algorithm DROP DEFAULT,
    ALTER COLUMN fingerprint_schema_version DROP DEFAULT;

CREATE INDEX hcmf_algoritmo_idx
    ON historical_canonical_manifests (fingerprint_algorithm);
