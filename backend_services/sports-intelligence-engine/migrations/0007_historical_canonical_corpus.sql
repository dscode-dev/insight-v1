-- 0007 — Corpus histórico publicado (PR-04.3)
--
-- O QUE ESTA MIGRATION ACRESCENTA, e por que nada dela é derivável.
--
-- Ela acrescenta a PUBLICAÇÃO. As tabelas anteriores respondem «quais fatos
-- canônicos existem»; estas respondem «quais fatos formam o corpus 1.0», que
-- é uma pergunta diferente e sem resposta nas outras:
--
--   * o registro canônico é GLOBAL e cresce depois da publicação;
--   * um `Match` construído por um build de PESQUISA está lá e não pertence
--     ao corpus comercial;
--   * a mesma partida entra em três versões com FAMÍLIAS diferentes em cada.
--
-- Derivar por data seria pior: bastaria alguém corrigir um fato para a versão
-- publicada mudar de conteúdo sem mudar de nome.
--
-- O FATO NÃO É DUPLICADO. `historical_canonical_members` aponta para
-- `matches`; ela não copia a partida. Duplicá-la faria a mesma partida existir
-- cinco vezes com cinco ids — exatamente o que a resolução de identidade
-- passou três PRs impedindo.
--
-- DUAS IMPRESSÕES, E O SCHEMA AS SEPARA:
--   `corpus_fingerprint`  o CONTEÚDO semântico. Não muda entre duas
--                         publicações idênticas — sem carimbo de tempo dentro.
--   `manifest_sha256`     os BYTES do documento. Muda, e é outra pergunta.
--
-- IMUTABILIDADE POR CONSTRAINT E NÃO POR CONVENÇÃO. Uma versão em `READY`
-- exige impressão e manifesto; uma em `SUPERSEDED` exige a sucessora; e o
-- único `UPDATE` do caminho normal é a transição de estado, condicional ao
-- estado anterior — como toda transição desta base desde o PR-02.

-- ================================================ identidade lógica ==

CREATE TABLE historical_canonical_datasets (
    id                  uuid PRIMARY KEY,
    name                text NOT NULL,
    description         text,
    created_at          timestamptz NOT NULL,
    created_by          text NOT NULL,
    created_by_kind     text NOT NULL,

    -- O NOME É ÚNICO NO BANCO e não numa consulta-antes-de-inserir: duas
    -- requisições simultâneas passariam as duas pela consulta. Quem arbitra
    -- é o índice.
    CONSTRAINT historical_canonical_datasets_nome_unico UNIQUE (name),
    -- Ele vira caminho no object store e chave de manifesto.
    CONSTRAINT historical_canonical_datasets_nome_valido CHECK (
        length(btrim(name)) > 0
        AND name !~ '[[:space:]/]'
    ),
    CONSTRAINT historical_canonical_datasets_ator CHECK (
        length(btrim(created_by)) > 0
    )
);

-- ==================================================== versões ==

CREATE TABLE historical_canonical_dataset_versions (
    id                  uuid PRIMARY KEY,
    dataset_id          uuid NOT NULL
                        REFERENCES historical_canonical_datasets (id),
    version_major       integer NOT NULL,
    version_minor       integer NOT NULL,
    usage_scope         text NOT NULL,
    status              text NOT NULL,
    -- A impressão SEMÂNTICA. `NULL` até a composição terminar: uma versão em
    -- DRAFT não tem conteúdo para imprimir.
    corpus_fingerprint  text,
    manifest_id         uuid,
    match_count         integer NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL,
    created_by          text NOT NULL,
    created_by_kind     text NOT NULL,
    completed_at        timestamptz,
    failure_reason      text,
    superseded_by       uuid REFERENCES historical_canonical_dataset_versions (id),
    -- As execuções e políticas que compuseram, com as impressões delas. Em
    -- `jsonb` porque a pergunta que se faz é «mostre a linhagem desta versão»
    -- e não «filtre versões por impressão de política»; a travessia POR
    -- BUILD tem tabela própria, logo abaixo.
    inputs              jsonb NOT NULL DEFAULT '{}'::jsonb,
    scope               jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- «1.0» PRECISA SIGNIFICAR UM CONTEÚDO SÓ, PARA SEMPRE. Aceitar a segunda
    -- faria dois corpus atenderem pelo mesmo nome, e todo resultado citando
    -- «1.0» ficaria ambíguo retroativamente.
    CONSTRAINT hcdv_versao_unica UNIQUE (dataset_id, version_major, version_minor),
    CONSTRAINT hcdv_status CHECK (
        status IN ('DRAFT', 'BUILDING', 'VALIDATING', 'READY', 'FAILED',
                   'SUPERSEDED')
    ),
    CONSTRAINT hcdv_escopo CHECK (usage_scope IN ('RESEARCH', 'COMMERCIAL')),
    -- READY SEM IMPRESSÃO OU SEM MANIFESTO afirmaria estar publicada sem nada
    -- que prove o que publicou.
    CONSTRAINT hcdv_publicada_tem_prova CHECK (
        status NOT IN ('READY', 'SUPERSEDED')
        OR (corpus_fingerprint IS NOT NULL AND manifest_id IS NOT NULL)
    ),
    CONSTRAINT hcdv_terminal_tem_fim CHECK (
        status IN ('DRAFT', 'BUILDING', 'VALIDATING') OR completed_at IS NOT NULL
    ),
    CONSTRAINT hcdv_falha_tem_motivo CHECK (
        status <> 'FAILED' OR length(btrim(coalesce(failure_reason, ''))) > 0
    ),
    -- «FOI SUBSTITUÍDA» SEM A SUCESSORA não permite achar o corpus atual.
    CONSTRAINT hcdv_superada_diz_por_qual CHECK (
        status <> 'SUPERSEDED' OR superseded_by IS NOT NULL
    ),
    CONSTRAINT hcdv_nao_substitui_a_si_mesma CHECK (superseded_by <> id),
    CONSTRAINT hcdv_contagem_nao_negativa CHECK (match_count >= 0),
    CONSTRAINT hcdv_ator CHECK (length(btrim(created_by)) > 0)
);

CREATE INDEX hcdv_dataset_idx
    ON historical_canonical_dataset_versions (dataset_id, created_at DESC);

-- «QUAL É O CORPUS ATUAL DESTE ESCOPO» é a consulta do §72, e ela merece um
-- índice PARCIAL: as versões publicadas são poucas entre as tentativas.
CREATE INDEX hcdv_publicadas_idx
    ON historical_canonical_dataset_versions (dataset_id, usage_scope, completed_at DESC)
    WHERE status = 'READY';

CREATE INDEX hcdv_fingerprint_idx
    ON historical_canonical_dataset_versions (corpus_fingerprint)
    WHERE corpus_fingerprint IS NOT NULL;

-- ============================================ builds que compuseram ==

-- TABELA PRÓPRIA E NÃO COLUNA `text[]`. Uma versão feita de trinta builds cabe
-- num array; o que não cabe é a pergunta INVERSA — «quais versões usaram este
-- build?» —, que num array vira varredura e aqui vira índice.
CREATE TABLE historical_canonical_version_builds (
    version_id      uuid NOT NULL
                    REFERENCES historical_canonical_dataset_versions (id)
                    ON DELETE CASCADE,
    build_run_id    uuid NOT NULL REFERENCES canonical_build_runs (id),

    PRIMARY KEY (version_id, build_run_id)
);

CREATE INDEX hcvb_build_idx
    ON historical_canonical_version_builds (build_run_id);

-- ==================================================== pertinência ==

CREATE TABLE historical_canonical_members (
    version_id              uuid NOT NULL
                            REFERENCES historical_canonical_dataset_versions (id)
                            ON DELETE CASCADE,
    match_id                uuid NOT NULL REFERENCES matches (id),
    competition_id          uuid NOT NULL REFERENCES competitions (id),
    season_id               uuid NOT NULL REFERENCES seasons (id),
    competition_code        text NOT NULL,
    season_label            text NOT NULL,
    -- AS FAMÍLIAS QUE ENTRARAM NESTA VERSÃO. A mesma partida entra na versão
    -- de pesquisa com ODDS e na comercial sem — e é por isso que a coluna
    -- está aqui e não em `matches`.
    included_families       text[] NOT NULL,
    build_run_id            uuid NOT NULL REFERENCES canonical_build_runs (id),
    -- «POR QUE ESTA PARTIDA ESTÁ NO CORPUS» tem de ter resposta sem
    -- arqueologia: a avaliação que a autorizou fecha a travessia até a fusão
    -- e ao arquivo bruto.
    quality_assessment_id   uuid NOT NULL
                            REFERENCES match_quality_assessments (id),
    -- O digest do CONTEÚDO publicado desta partida. Sem ele, dois corpus com
    -- as mesmas partidas e placares DIFERENTES teriam a mesma impressão.
    content_fingerprint     text NOT NULL,

    -- IDEMPOTÊNCIA DA COMPOSIÇÃO: um retry depois de um timeout parcial não
    -- pode duplicar a partida, senão a contagem do manifesto passa a
    -- discordar do conteúdo que ela existe para conferir.
    PRIMARY KEY (version_id, match_id),
    CONSTRAINT hcm_familias_nao_vazias CHECK (
        array_length(included_families, 1) >= 1
    ),
    CONSTRAINT hcm_impressao CHECK (length(content_fingerprint) = 64)
);

-- A travessia PARA FRENTE: «em quais corpus esta partida entrou» (§99).
CREATE INDEX hcm_match_idx ON historical_canonical_members (match_id);

-- A paginação por chave da composição e da materialização — nunca `OFFSET`.
CREATE INDEX hcm_particao_idx
    ON historical_canonical_members (version_id, competition_code, season_label);

-- ======================================================= manifestos ==

CREATE TABLE historical_canonical_manifests (
    id                  uuid PRIMARY KEY,
    version_id          uuid NOT NULL
                        REFERENCES historical_canonical_dataset_versions (id)
                        ON DELETE CASCADE,
    schema_version      text NOT NULL,
    -- O documento inteiro, do jeito que foi serializado. Ele é a descrição
    -- publicada e é IMUTÁVEL: não há `UPDATE` no caminho normal.
    document            jsonb NOT NULL,
    -- As DUAS impressões, lado a lado e nomeadas, porque confundi-las é caro.
    corpus_fingerprint  text NOT NULL,
    manifest_sha256     text NOT NULL,
    object_key          text,
    created_at          timestamptz NOT NULL,

    -- UM MANIFESTO POR VERSÃO. Dois descreveriam o mesmo corpus de duas
    -- formas, e a segunda seria a que ninguém leu.
    CONSTRAINT hcmf_um_por_versao UNIQUE (version_id),
    CONSTRAINT hcmf_impressoes CHECK (
        length(corpus_fingerprint) = 64 AND length(manifest_sha256) = 64
    )
);

-- «QUAIS PUBLICAÇÕES PRODUZIRAM ESTE MESMO CORPUS» (§89). Plural de
-- propósito: duas publicações independentes dos mesmos fatos têm a mesma
-- impressão e ids diferentes.
CREATE INDEX hcmf_fingerprint_idx
    ON historical_canonical_manifests (corpus_fingerprint);

ALTER TABLE historical_canonical_dataset_versions
    ADD CONSTRAINT hcdv_manifest_fk
    FOREIGN KEY (manifest_id) REFERENCES historical_canonical_manifests (id)
    DEFERRABLE INITIALLY DEFERRED;

-- =================================================== objetos escritos ==

-- O PARQUET É REPRESENTAÇÃO E NÃO FONTE DA VERDADE (ADR-0027). Estas linhas
-- existem para conferir e para achar: sem elas, «o corpus 1.0 escreveu quais
-- arquivos» exigiria listar o bucket, e uma versão que falhou no meio
-- deixaria órfãos que ninguém encontra.
CREATE TABLE historical_canonical_objects (
    id                  uuid PRIMARY KEY,
    version_id          uuid NOT NULL
                        REFERENCES historical_canonical_dataset_versions (id)
                        ON DELETE CASCADE,
    object_key          text NOT NULL,
    family              text NOT NULL,
    competition_code    text NOT NULL,
    season_label        text NOT NULL,
    sha256              text NOT NULL,
    size_bytes          bigint NOT NULL,
    row_count           bigint NOT NULL,
    content_type        text NOT NULL,
    created_at          timestamptz NOT NULL,

    CONSTRAINT hco_chave_unica UNIQUE (version_id, object_key),
    CONSTRAINT hco_impressao CHECK (length(sha256) = 64),
    -- UM PARQUET DE ZERO LINHA É INDISTINGUÍVEL, na leitura, de uma partição
    -- que ninguém escreveu — e as duas exigem ações diferentes de quem
    -- investiga um buraco na cobertura. Aqui ele simplesmente não existe.
    CONSTRAINT hco_nao_vazio CHECK (row_count > 0 AND size_bytes > 0)
);

CREATE INDEX hco_version_idx
    ON historical_canonical_objects (version_id, family, competition_code);
