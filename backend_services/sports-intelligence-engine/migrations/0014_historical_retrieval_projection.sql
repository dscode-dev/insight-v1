-- 0014 — A projeção operacional de recuperação histórica (PR-06.4)
--
-- POR QUE UMA MIGRATION NOVA E NÃO UMA EDIÇÃO DA 0013. O aplicador guarda o
-- SHA-256 de cada migration aplicada e RECUSA seguir quando o arquivo muda
-- depois. O caminho de volta é sempre uma migration nova.
--
-- O QUE ELA RESOLVE, E O QUE ELA DELIBERADAMENTE NÃO RESOLVE.
--
-- Os PRs 06.1, 06.2 e 06.3 produziram três oráculos exatos. Eles estão certos e
-- são caros — mas o custo NÃO está onde parecia. Foi medido:
--
--     estado exato       p50 ~= 33,5 ms   sobre ~47 candidatos
--     trajetória exata   p50 ~= 364,2 ms  sobre ~47 candidatos
--
-- Quarenta e sete distâncias sobre quinze eixos não custam trinta e três
-- milissegundos. O que custa é IR BUSCAR as representações: baixar objetos
-- Parquet do MinIO, abrir, projetar colunas, materializar linhas. O cálculo é
-- barato; a AQUISIÇÃO é cara.
--
-- Esta migration existe para mover os candidatos para perto do cálculo.
--
-- POR QUE NÃO HÁ `vector` NEM HNSW AQUI. Houve. Uma versão anterior desta
-- migration criava `vector(58)`, `vector(174)` e dois índices HNSW, e o
-- experimento de viabilidade foi executado até o fim. O resultado foi negativo
-- e útil, e está registrado em `docs/retrieval/ANN_FEASIBILITY_EXPERIMENT_V1.md`:
--
--     o CandidateUniverse é PEQUENO POR CONSTRUÇÃO — uma competição num
--     instante EXATO da grade —, e o planejador do PostgreSQL só escolhe
--     HNSW a partir de alguns milhares de candidatos. Abaixo disso ele
--     prefere B-tree mais ordenação, e está certo: mil candidatos são
--     ordenados em 0,35 ms.
--
-- Guardar um vetor de aproximação que a produção nunca consulta seria pagar
-- 240 e 704 bytes por linha, mais dois grafos HNSW, para nada. A extensão
-- também sai: nenhuma feature de produção da V1 depende dela.
--
-- A INVARIANTE QUE O ESQUEMA EXISTE PARA SUSTENTAR:
--
--     a projeção é DERIVADA, e a autoridade continua sendo o dataset
--
-- Nada aqui é fonte primária. Se a projeção e o dataset normalizado
-- divergirem, o dataset ganha e a projeção é reconstruída — e é por isso que
-- cada linha carrega o digesto da linha de origem: para que a divergência seja
-- DETECTÁVEL em vez de opinável.
--
-- O PAYLOAD É `float64`, E ISSO NÃO É NEGOCIÁVEL. `D_state` e `D_trajectory`
-- são definidas sobre os números do dataset normalizado; qualquer perda de
-- precisão aqui produziria uma distância PARECIDA com a do oráculo, e parecida
-- é o pior resultado possível — passaria despercebida. Por isso `bytea` em
-- `binary64` little-endian, e por isso o teste de ida e volta é bit a bit.
--
-- AS LINHAS ESTÃO NO BANCO, E ISSO NÃO CONTRADIZ O ADR-0037. A 0012 e a 0013
-- mantêm as linhas normalizadas fora do PostgreSQL porque elas são o CONJUNTO
-- DE DADOS: cento e cinco colunas por linha, lidas em varredura colunar. Esta
-- tabela é outra coisa — uma projeção de RECUPERAÇÃO, de acesso pontual por
-- competição e instante, cujo propósito é justamente não varrer.

-- ======================================== a projeção ==
--
-- A LINHAGEM MORA NA VERSÃO, E NÃO NA LINHA. Cada linha projetada pertence a
-- uma versão, e é a versão que carrega as amarras. Repeti-las por linha
-- multiplicaria o mesmo texto por centenas de milhares de tuplas e permitiria
-- que duas linhas da mesma versão discordassem sobre a própria origem.
CREATE TABLE historical_retrieval_projections (
    id                  uuid PRIMARY KEY,
    name                text NOT NULL,
    kind                text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT hrp_nome_nao_vazio CHECK (length(btrim(name)) > 0),
    CONSTRAINT hrp_tipo_valido CHECK (kind IN ('STATE', 'TRAJECTORY')),
    CONSTRAINT hrp_nome_tipo_unico UNIQUE (name, kind)
);

CREATE TABLE historical_retrieval_projection_versions (
    id                              uuid PRIMARY KEY,
    projection_id                   uuid NOT NULL
        REFERENCES historical_retrieval_projections (id) ON DELETE RESTRICT,
    version                         integer NOT NULL,
    kind                            text NOT NULL,
    status                          text NOT NULL,

    -- ---- as amarras da origem -----------------------------------------
    source_dataset_version_id       uuid NOT NULL
        REFERENCES normalized_feature_dataset_versions (id) ON DELETE RESTRICT,
    source_dataset_version          text NOT NULL,
    source_reference_fingerprint    text NOT NULL,
    normalization_plan_fingerprint  text NOT NULL,
    artifact_set_fingerprint        text NOT NULL,
    candidate_policy_fingerprint    text NOT NULL,
    exact_payload_encoding          text NOT NULL,

    -- ---- só na trajetória: as três políticas do PR-06.3 ----------------
    trajectory_window_fingerprint   text NOT NULL DEFAULT '',
    trajectory_profile_fingerprint  text NOT NULL DEFAULT '',
    trajectory_coverage_fingerprint text NOT NULL DEFAULT '',

    -- ---- a forma do payload --------------------------------------------
    axis_count                      integer NOT NULL,
    horizons                        integer[] NOT NULL DEFAULT '{}',

    -- ---- o conteúdo -----------------------------------------------------
    row_count                       bigint NOT NULL DEFAULT 0,
    -- A IMPRESSÃO SEMÂNTICA, e ela NÃO cobre nada de físico: nem o `id` desta
    -- linha, nem a ordem de inserção, nem o carimbo. Duas construções do mesmo
    -- conteúdo colidem aqui, e é isso que torna a projeção verificável.
    content_fingerprint             text NOT NULL DEFAULT '',
    fingerprint                     text NOT NULL DEFAULT '',

    created_at                      timestamptz NOT NULL DEFAULT now(),
    published_at                    timestamptz,

    CONSTRAINT hrpv_versao_unica UNIQUE (projection_id, version),
    CONSTRAINT hrpv_versao_positiva CHECK (version > 0),
    CONSTRAINT hrpv_tipo_valido CHECK (kind IN ('STATE', 'TRAJECTORY')),
    CONSTRAINT hrpv_status_valido CHECK (
        status IN ('DRAFT', 'BUILDING', 'VALIDATING', 'READY', 'FAILED', 'SUPERSEDED')
    ),
    CONSTRAINT hrpv_eixos_positivos CHECK (axis_count > 0),
    -- READY EXIGE IMPRESSÃO. Publicar sem ela tornaria a validação impossível
    -- de refazer, e a projeção deixaria de ser auditável contra a origem.
    CONSTRAINT hrpv_ready_tem_impressao CHECK (
        status <> 'READY'
        OR (length(content_fingerprint) > 0 AND length(fingerprint) > 0)
    ),
    -- TRAJETÓRIA EXIGE AS TRÊS POLÍTICAS DO PR-06.3. Sem elas, uma projeção
    -- construída sob outros horizontes seria servida a uma query que espera
    -- 1/3/5, e os deslocamentos mediriam outros intervalos.
    CONSTRAINT hrpv_trajetoria_tem_politica CHECK (
        kind <> 'TRAJECTORY'
        OR (
            length(trajectory_window_fingerprint) > 0
            AND length(trajectory_profile_fingerprint) > 0
            AND length(trajectory_coverage_fingerprint) > 0
            AND cardinality(horizons) > 0
        )
    )
);

CREATE INDEX hrpv_origem_idx
    ON historical_retrieval_projection_versions (source_dataset_version_id, kind);

-- A CONSULTA DE TODA RECUPERAÇÃO INDEXADA: «a projeção READY daquele dataset,
-- daquele tipo». Ela roda uma vez por query e precisa ser pontual.
CREATE INDEX hrpv_prontas_idx
    ON historical_retrieval_projection_versions
    (source_dataset_version_id, kind, published_at DESC)
    WHERE status = 'READY';

-- ======================================== as linhas de ESTADO ==
--
-- O `WHERE` DESTA TABELA É O `CandidateUniverse` DO PR-06.1, e as colunas
-- existem para escrevê-lo por inteiro: competição, fase, minuto, acréscimo,
-- desempate, e a exclusão da própria partida. Um JSON aqui tornaria cada uma
-- dessas igualdades uma expressão, e o planejador deixaria de ter estatística
-- sobre elas.
CREATE TABLE historical_state_projection_rows (
    projection_version_id   uuid NOT NULL
        REFERENCES historical_retrieval_projection_versions (id) ON DELETE CASCADE,

    semantic_key            text NOT NULL,

    competition             text NOT NULL,
    season                  text NOT NULL,
    match_id                text NOT NULL,
    period                  text NOT NULL,
    minute                  integer NOT NULL,
    stoppage                integer NOT NULL,
    tie_break               text NOT NULL,

    -- ---- o payload EXATO: é ele que responde ----------------------------
    -- `float64` little-endian, um valor por eixo canônico, mais um byte de
    -- máscara por eixo. A máscara é o que distingue «zero observado» de
    -- «ausente» — dois estados que o número sozinho não separa.
    exact_values            bytea NOT NULL,
    exact_mask              bytea NOT NULL,
    exact_payload_digest    text NOT NULL,
    usable_axes             integer NOT NULL,
    row_digest              text NOT NULL,
    representation_fingerprint text NOT NULL,

    PRIMARY KEY (projection_version_id, semantic_key),

    CONSTRAINT hspr_eixos_utilizaveis CHECK (usable_axes >= 0),
    CONSTRAINT hspr_minuto CHECK (minute >= 0),
    CONSTRAINT hspr_acrescimo CHECK (stoppage >= 0),
    -- OITO BYTES DE VALOR POR BYTE DE MÁSCARA. Um payload de outro espaço de
    -- eixos decodificaria em silêncio e produziria distância sobre dimensões
    -- que não se correspondem; o esquema recusa antes.
    CONSTRAINT hspr_payload_coerente CHECK (
        octet_length(exact_values) = octet_length(exact_mask) * 8
    ),
    CONSTRAINT hspr_digesto_nao_vazio CHECK (length(exact_payload_digest) > 0)
);

-- O ÍNDICE DO UNIVERSO. A ordem das colunas segue a seletividade: a versão
-- separa builds inteiras, a competição corta em ligas, o instante corta em
-- minutos. É este índice que o planejador usa, e foi medido que ele basta.
CREATE INDEX hspr_universo_idx
    ON historical_state_projection_rows
    (projection_version_id, competition, period, minute, stoppage, tie_break);

-- A exclusão da própria partida é um `<>` sobre esta coluna, em toda consulta.
CREATE INDEX hspr_partida_idx
    ON historical_state_projection_rows (projection_version_id, match_id);

-- ======================================== as linhas de TRAJETÓRIA ==
--
-- A CHAVE SEMÂNTICA É A DA ÂNCORA MAIS A IDENTIDADE DA REPRESENTAÇÃO, porque
-- uma trajetória não é uma linha: é uma âncora e os instantes que ela alcançou.
-- Duas trajetórias sobre a mesma âncora com janelas diferentes são objetos
-- diferentes, e a chave precisa distingui-los.
CREATE TABLE historical_trajectory_projection_rows (
    projection_version_id   uuid NOT NULL
        REFERENCES historical_retrieval_projection_versions (id) ON DELETE CASCADE,

    semantic_key            text NOT NULL,
    anchor_key              text NOT NULL,

    competition             text NOT NULL,
    season                  text NOT NULL,
    match_id                text NOT NULL,
    period                  text NOT NULL,
    minute                  integer NOT NULL,
    stoppage                integer NOT NULL,
    tie_break               text NOT NULL,

    exact_values            bytea NOT NULL,
    exact_mask              bytea NOT NULL,
    exact_payload_digest    text NOT NULL,
    usable_cells            integer NOT NULL,
    usable_horizons         integer NOT NULL,
    anchor_row_digest       text NOT NULL,
    trajectory_fingerprint  text NOT NULL,
    representation_fingerprint text NOT NULL,

    -- ---- a LINHAGEM dos slots -------------------------------------------
    --
    -- UMA TRAJETÓRIA NÃO É UMA LINHA: é uma âncora e os instantes que ela
    -- alcançou. A impressão da trajetória cobre o digesto da linha de origem
    -- de CADA slot — é isso que prova que o `t-5` usado é do mesmo período e
    -- daquela partida.
    --
    -- SEM ESTA COLUNA A PROJEÇÃO NÃO RECONSTRÓI A TRAJETÓRIA. Ela guardaria os
    -- deslocamentos e perderia a prova de onde eles vieram, e a impressão
    -- reconstruída divergiria da do oráculo — que é exatamente o que o gate de
    -- concordância existe para não deixar passar.
    --
    -- `jsonb` E NÃO `bytea` AQUI, e a diferença é o tipo do dado: os
    -- deslocamentos são numéricos e quentes, e por isso são binários; isto é
    -- metadado de linhagem, pequeno (três slots) e auto-descritivo.
    slot_lineage            jsonb NOT NULL DEFAULT '[]'::jsonb,

    PRIMARY KEY (projection_version_id, semantic_key),

    CONSTRAINT htpr_celulas CHECK (usable_cells >= 0),
    CONSTRAINT htpr_horizontes CHECK (usable_horizons >= 0),
    CONSTRAINT htpr_minuto CHECK (minute >= 0),
    CONSTRAINT htpr_acrescimo CHECK (stoppage >= 0),
    CONSTRAINT htpr_payload_coerente CHECK (
        octet_length(exact_values) = octet_length(exact_mask) * 8
    ),
    CONSTRAINT htpr_impressao_nao_vazia CHECK (length(trajectory_fingerprint) > 0)
);

CREATE INDEX htpr_universo_idx
    ON historical_trajectory_projection_rows
    (projection_version_id, competition, period, minute, stoppage, tie_break);

CREATE INDEX htpr_partida_idx
    ON historical_trajectory_projection_rows (projection_version_id, match_id);

-- ======================================== a validação ==
--
-- ELA É UMA TABELA PORQUE É EVIDÊNCIA, e não um log. Antes de uma versão virar
-- READY, o construtor reconfere contagens, impressões e linhagem contra o
-- dataset normalizado; o resultado dessa reconferência é o que autoriza a
-- publicação, e guardá-lo permite responder «por que esta projeção foi
-- publicada» sem reconstruí-la.
CREATE TABLE historical_retrieval_projection_validations (
    id                      uuid PRIMARY KEY,
    projection_version_id   uuid NOT NULL
        REFERENCES historical_retrieval_projection_versions (id) ON DELETE CASCADE,
    validated_at            timestamptz NOT NULL DEFAULT now(),

    rows_expected           bigint NOT NULL,
    rows_found              bigint NOT NULL,
    content_fingerprint     text NOT NULL,
    payload_rows_verified   bigint NOT NULL DEFAULT 0,
    outcome                 text NOT NULL,
    detail                  jsonb NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT hrpva_resultado_valido CHECK (outcome IN ('PASSED', 'FAILED')),
    CONSTRAINT hrpva_contagens CHECK (rows_expected >= 0 AND rows_found >= 0)
);

CREATE INDEX hrpva_versao_idx
    ON historical_retrieval_projection_validations (projection_version_id, validated_at DESC);
