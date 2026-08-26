-- 0013 — O ajuste causal e o dataset normalizado (PR-05.5.2)
--
-- POR QUE UMA MIGRATION NOVA E NÃO UMA EDIÇÃO DA 0012. O aplicador guarda o
-- SHA-256 de cada migration aplicada e RECUSA seguir quando o arquivo muda
-- depois. O caminho de volta é sempre uma migration nova.
--
-- O QUE ELA RESOLVE. O PR-05.5.1 congelou os números como foram extraídos:
-- gols em gols, xG em xG, cotações em cotações. Eles não são comparáveis entre
-- si — um `xg_home_5m` de 0,4 e um `shots_home_5m` de 4 estão em unidades
-- diferentes, e qualquer distância que os some está somando maçãs com
-- laranjas. Esta migration guarda o que torna a soma legítima: a escala de cada
-- eixo em cada competição, e o dataset reescrito sob ela.
--
-- A INVARIANTE QUE O ESQUEMA EXISTE PARA SUSTENTAR:
--
--     mudar a metade de AVALIAÇÃO não pode mudar NADA do ajuste
--
-- Ela aparece aqui em duas decisões concretas, e as duas são fáceis de errar:
--
--   `reference_fingerprint` É A IMPRESSÃO DA METADE DE REFERÊNCIA, e não a
--   `raw_content_fingerprint` da versão crua. A segunda cobre as duas metades:
--   usá-la como identidade do ajuste faria uma partida acrescentada à
--   avaliação produzir «outro ajuste» sem que número nenhum mudasse.
--
--   `source_raw_content_fingerprint` EXISTE, e é LINHAGEM. Ela responde «de
--   qual dataset cru este ajuste saiu», que é pergunta real — e por isso mora
--   numa coluna própria, fora de tudo que a impressão do conjunto cobre.
--
-- OITO TABELAS, E DUAS DELAS MERECEM JUSTIFICATIVA. O pacote por competição
-- (`normalizer_artifact_bundles`) tem impressão DERIVADA dos artefatos dele; o
-- manifesto (`normalized_feature_dataset_manifests`) espelha o do dataset cru.
-- Nenhuma das duas é redundância: a primeira torna «traga só a escala da
-- Premier League» uma consulta indexada em vez de uma varredura no conjunto
-- inteiro — que é exatamente o caminho da leitura ao vivo do PR-06 —, e a
-- segunda mantém a simetria com a 0012, onde o documento serializado é o que
-- permite reconciliar bucket e banco sem reconstruir nada.
--
-- OS NÚMEROS DO AJUSTE SÃO `numeric`, E NÃO `double precision`. A mediana e o
-- IQR são o insumo de TODA transformação; gravá-los em ponto flutuante faria a
-- escala de uma competição depender do arredondamento do driver. A conversão
-- para `float64` acontece uma vez só, na SAÍDA, e declaradamente (ADR-0040).
--
-- AS LINHAS NORMALIZADAS NÃO ESTÃO AQUI (ADR-0037, e a mesma decisão da 0012).
-- Elas são cento e cinco valores por linha; o banco guarda identidade,
-- políticas, contagens e PONTEIROS.

-- ======================================== o conjunto de artefatos ==
--
-- ELE É A UNIDADE DE PUBLICAÇÃO DO AJUSTE. Um artefato solto não normaliza
-- nada: normalizar uma linha exige o pacote inteiro da competição, e comparar
-- duas linhas exige o mesmo conjunto dos dois lados.

CREATE TABLE normalizer_artifact_sets (
    id                              uuid PRIMARY KEY,
    status                          text NOT NULL,

    -- ============================================== a identidade ==
    --
    -- ESTAS QUATRO SÃO O QUE A IMPRESSÃO DO CONJUNTO COBRE, junto dos pacotes.
    -- Nenhuma delas enxerga a avaliação.
    plan_fingerprint                text NOT NULL,
    split_fingerprint               text NOT NULL,
    reference_end_exclusive         timestamptz NOT NULL,
    reference_fingerprint           text NOT NULL,
    -- A impressão do conjunto, materializada para ser CONSULTADA: «este ajuste
    -- já existe?» é a pergunta que evita reajustar noventa e um mil linhas.
    fingerprint                     text NOT NULL,

    -- ================================================ a linhagem ==
    --
    -- FORA DA IMPRESSÃO, E PERSISTIDA. Linhagem responde «de onde veio»;
    -- identidade responde «é o mesmo ajuste». Confundi-las é o defeito central
    -- que este PR existe para impedir.
    source_version_id               uuid
                                    REFERENCES historical_feature_dataset_versions (id),
    source_raw_content_fingerprint  text,
    reference_rows                  integer NOT NULL DEFAULT 0,

    created_at                      timestamptz NOT NULL,
    created_by                      text NOT NULL,
    created_by_kind                 text NOT NULL,
    completed_at                    timestamptz,
    failure_reason                  text,

    CONSTRAINT nas_status CHECK (
        status IN ('DRAFT', 'BUILDING', 'VALIDATING', 'READY', 'FAILED', 'SUPERSEDED')
    ),
    CONSTRAINT nas_impressoes CHECK (
        plan_fingerprint ~ '^[0-9a-f]{64}$'
        AND split_fingerprint ~ '^[0-9a-f]{64}$'
        AND reference_fingerprint ~ '^[0-9a-f]{64}$'
        AND fingerprint ~ '^[0-9a-f]{64}$'
        AND (source_raw_content_fingerprint IS NULL
             OR source_raw_content_fingerprint ~ '^[0-9a-f]{64}$')
    ),
    CONSTRAINT nas_terminal_tem_fim CHECK (
        status IN ('DRAFT', 'BUILDING', 'VALIDATING') OR completed_at IS NOT NULL
    ),
    CONSTRAINT nas_falha_tem_motivo CHECK (
        status <> 'FAILED' OR length(btrim(coalesce(failure_reason, ''))) > 0
    ),
    CONSTRAINT nas_referencia_nao_negativa CHECK (reference_rows >= 0)
);

-- «ESTE AJUSTE JÁ EXISTE?» — dois ajustes sobre a mesma referência sob o mesmo
-- plano SÃO o mesmo ajuste, e descobrir isso custa uma consulta em vez de
-- recalcular mediana nenhuma.
CREATE INDEX nas_impressao_idx ON normalizer_artifact_sets (fingerprint);

-- «QUE AJUSTES SAÍRAM DESTA VERSÃO CRUA?» — a travessia para frente.
CREATE INDEX nas_origem_idx
    ON normalizer_artifact_sets (source_version_id)
    WHERE source_version_id IS NOT NULL;

-- ================================== o pacote de uma competição ==
--
-- ELE DEPENDE SÓ DA COMPETIÇÃO DELE, e é essa a propriedade do isolamento:
-- mexer na referência da La Liga não muda a impressão do pacote da Premier
-- League — nem por dependência direta, nem por um agregado compartilhado.
--
-- POR QUE ELE É UMA TABELA E NÃO UM `GROUP BY`. Normalizar uma partida da
-- Premier League ao vivo não pode exigir carregar as medianas de todas as
-- ligas do conjunto para depois filtrar. Esta tabela é o que torna «traga só a
-- escala desta liga» um acesso por chave.

CREATE TABLE normalizer_artifact_bundles (
    set_id                  uuid NOT NULL
                            REFERENCES normalizer_artifact_sets (id)
                            ON DELETE CASCADE,
    -- O CÓDIGO da competição, que é o que o Parquet cru grava na partição...
    competition             text NOT NULL,
    -- ...e a IDENTIDADE dela, que é o que o artefato exige. As duas juntas
    -- porque a travessia entre elas é justamente onde um artefato pode acabar
    -- normalizando a liga errada (PR-05.4 §132).
    competition_id          uuid NOT NULL,
    reference_fingerprint   text NOT NULL,
    plan_fingerprint        text NOT NULL,
    fingerprint             text NOT NULL,
    artifact_count          integer NOT NULL DEFAULT 0,
    fitted_count            integer NOT NULL DEFAULT 0,
    insufficient_count      integer NOT NULL DEFAULT 0,
    degenerate_count        integer NOT NULL DEFAULT 0,

    PRIMARY KEY (set_id, competition),
    CONSTRAINT nab_impressoes CHECK (
        reference_fingerprint ~ '^[0-9a-f]{64}$'
        AND plan_fingerprint ~ '^[0-9a-f]{64}$'
        AND fingerprint ~ '^[0-9a-f]{64}$'
    ),
    -- AS CONTAGENS TÊM DE FECHAR. Um pacote que já se contradiz nunca chegaria
    -- a ser conferido, e o banco é o lugar barato de pegar isso.
    CONSTRAINT nab_contagens_fecham CHECK (
        fitted_count + insufficient_count + degenerate_count = artifact_count
    ),
    CONSTRAINT nab_contagens_nao_negativas CHECK (
        artifact_count >= 0 AND fitted_count >= 0
        AND insufficient_count >= 0 AND degenerate_count >= 0
    )
);

-- ===================================== os artefatos, um por eixo ==
--
-- SÓ OS EIXOS `ROBUST` TÊM ARTEFATO. Os `PASS_THROUGH` não têm escala nenhuma
-- para guardar, e inventar uma linha vazia para eles faria a tabela insinuar
-- que houve um ajuste que não houve. Quais eixos são quais está no PLANO, cuja
-- impressão está logo acima.

CREATE TABLE normalizer_fit_artifacts (
    set_id                      uuid NOT NULL,
    competition                 text NOT NULL,
    feature_key                 text NOT NULL,
    -- A IMPRESSÃO DA FEATURE, e não só a chave. Duas versões da mesma feature
    -- têm a mesma chave e escalas diferentes; um artefato que guardasse só o
    -- nome continuaria «válido» depois de a definição mudar.
    feature_version             text NOT NULL,
    feature_fingerprint         text NOT NULL,
    competition_id              uuid NOT NULL,

    normalizer_key              text NOT NULL,
    normalizer_fingerprint      text NOT NULL,
    fit_cutoff                  jsonb NOT NULL DEFAULT '{}'::jsonb,

    status                      text NOT NULL,
    -- OS NÚMEROS, EM `numeric`. Ver o cabeçalho: `double precision` faria a
    -- escala depender do arredondamento do driver.
    median                      numeric,
    q1                          numeric,
    q3                          numeric,
    iqr                         numeric,

    -- A POPULAÇÃO: o total, o disponível e a impressão dela. Os três porque
    -- «mediana de trinta e uma observações» e «mediana de trinta e uma de
    -- noventa e uma mil» são afirmações muito diferentes.
    population_count            integer NOT NULL DEFAULT 0,
    available_count             integer NOT NULL DEFAULT 0,
    population_digest           text NOT NULL DEFAULT '',
    -- A REFERÊNCIA DAQUELA COMPETIÇÃO — e é aqui que a cegueira à avaliação
    -- vira coluna. Se esta fosse a impressão crua global, acrescentar uma
    -- partida à avaliação mudaria a impressão de todo artefato do conjunto.
    source_corpus_fingerprint   text NOT NULL,
    source_space_fingerprint    text NOT NULL,
    fingerprint                 text NOT NULL,
    detail                      text NOT NULL DEFAULT '',

    PRIMARY KEY (set_id, competition, feature_key),
    FOREIGN KEY (set_id, competition)
        REFERENCES normalizer_artifact_bundles (set_id, competition)
        ON DELETE CASCADE,

    CONSTRAINT nfa_status CHECK (
        status IN ('FITTED', 'INSUFFICIENT_SAMPLE', 'DEGENERATE_SCALE')
    ),
    CONSTRAINT nfa_impressoes CHECK (
        feature_fingerprint ~ '^[0-9a-f]{64}$'
        AND normalizer_fingerprint ~ '^[0-9a-f]{64}$'
        AND source_corpus_fingerprint ~ '^[0-9a-f]{64}$'
        AND source_space_fingerprint ~ '^[0-9a-f]{64}$'
        AND fingerprint ~ '^[0-9a-f]{64}$'
    ),
    -- «AJUSTADO» É UMA AFIRMAÇÃO SOBRE OS PARÂMETROS, e não sobre a intenção
    -- de calculá-los.
    CONSTRAINT nfa_ajustado_tem_numeros CHECK (
        status <> 'FITTED'
        OR (median IS NOT NULL AND q1 IS NOT NULL
            AND q3 IS NOT NULL AND iqr IS NOT NULL AND iqr > 0)
    ),
    -- SEM EPSILON, E O BANCO TAMBÉM RECUSA (ADR-0035). Dispersão nula é
    -- `DEGENERATE_SCALE`; um `FITTED` com IQR zero seria uma divisão por zero
    -- esperando o momento de acontecer, e um `FITTED` com IQR minúsculo
    -- inventado seria pior — produziria números enormes que parecem sinal.
    CONSTRAINT nfa_degenerado_tem_iqr_nulo CHECK (
        status <> 'DEGENERATE_SCALE' OR iqr IS NULL OR iqr = 0
    ),
    -- OU A AMOSTRA SERVE, OU O NÚMERO NÃO DEVERIA EXISTIR (PR-05.4 §123).
    CONSTRAINT nfa_insuficiente_nao_publica_mediana CHECK (
        status <> 'INSUFFICIENT_SAMPLE' OR median IS NULL
    ),
    CONSTRAINT nfa_subconjunto CHECK (
        available_count >= 0 AND available_count <= population_count
    )
);

-- «A ESCALA DESTE EIXO NESTA LIGA» — o acesso da leitura ao vivo.
CREATE INDEX nfa_eixo_idx
    ON normalizer_fit_artifacts (competition_id, feature_key, set_id);

-- «ONDE O AJUSTE NÃO ENCONTROU ESCALA» — a pergunta de saúde do ajuste, que é
-- feita depois de um salto nas células indisponíveis de uma construção.
CREATE INDEX nfa_sem_escala_idx
    ON normalizer_fit_artifacts (set_id, status)
    WHERE status <> 'FITTED';

-- ==================================== a identidade do normalizado ==
--
-- ELA APONTA PARA O DATASET CRU, e não para uma versão dele. «O normalizado do
-- match-state-raw» continua verdadeiro quando o cru publica a 1.1; é a VERSÃO
-- normalizada que aponta para a VERSÃO crua.

CREATE TABLE normalized_feature_datasets (
    id                  uuid PRIMARY KEY,
    name                text NOT NULL,
    source_dataset_id   uuid NOT NULL
                        REFERENCES historical_feature_datasets (id),
    description         text,
    created_at          timestamptz NOT NULL,
    created_by          text NOT NULL,
    created_by_kind     text NOT NULL,

    CONSTRAINT nfd_nome_unico UNIQUE (name),
    CONSTRAINT nfd_nome_valido CHECK (
        length(btrim(name)) > 0
        AND position('/' IN name) = 0
        AND position(' ' IN name) = 0
    )
);

-- ============================================= as versões normalizadas ==
--
-- UMA PROJEÇÃO INDEPENDENTE, e não um campo a mais na versão crua. Um mesmo
-- dataset cru alimenta N representações: refinar o plano, ou reajustar sobre
-- uma referência estendida, produz uma representação nova sobre exatamente as
-- mesmas linhas cruas — e o cru não pode mudar de identidade por causa disso.

CREATE TABLE normalized_feature_dataset_versions (
    id                              uuid PRIMARY KEY,
    dataset_id                      uuid NOT NULL
                                    REFERENCES normalized_feature_datasets (id),
    version_major                   integer NOT NULL,
    version_minor                   integer NOT NULL,
    status                          text NOT NULL,

    -- ======================================== a origem, com prova ==
    source_version_id               uuid NOT NULL
                                    REFERENCES historical_feature_dataset_versions (id),
    source_version_major            integer NOT NULL,
    source_version_minor            integer NOT NULL,
    source_raw_content_fingerprint  text NOT NULL,
    -- O OUTRO LADO DO CONTRATO 1:1. Ele está aqui para que «a normalização não
    -- filtra» seja um CHECK, e não uma disciplina: uma versão com menos linhas
    -- que a crua está afirmando, no próprio corpo, que alguma partida saiu
    -- silenciosamente do conjunto de comparação.
    source_row_count                integer NOT NULL DEFAULT 0,

    -- ================================== a representação, por extenso ==
    --
    -- QUATRO DECISÕES TORNAM DOIS NÚMEROS COMPARÁVEIS: o espaço, o plano, o
    -- conjunto de artefatos e a codificação de saída. Trocar qualquer uma
    -- torna a comparação falsa — e plausível, que é o pior tipo de falsa.
    space_fingerprint               text NOT NULL,
    plan_name                       text NOT NULL,
    plan_version                    text NOT NULL,
    plan_fingerprint                text NOT NULL,
    artifact_set_id                 uuid NOT NULL
                                    REFERENCES normalizer_artifact_sets (id),
    artifact_set_fingerprint        text NOT NULL,
    -- A impressão das quatro juntas. É ELA que responde «estas duas linhas
    -- podem ser comparadas número a número?».
    representation_fingerprint      text NOT NULL,
    representation                  jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- ===================================== as três impressões (§35) ==
    --
    -- A DO MEIO É A QUE SUSTENTA O PR. Acrescentar uma partida à avaliação muda
    -- a global e a de avaliação, e NÃO PODE mudar a de referência. Sem uma
    -- coluna própria para ela, «a base de comparação não mudou» deixaria de ser
    -- uma afirmação verificável e viraria opinião sobre a impressão global.
    normalized_content_fingerprint              text,
    normalized_reference_content_fingerprint    text,
    normalized_evaluation_content_fingerprint   text,

    manifest_id                     uuid,
    match_count                     integer NOT NULL DEFAULT 0,
    row_count                       integer NOT NULL DEFAULT 0,
    reference_matches               integer NOT NULL DEFAULT 0,
    evaluation_matches              integer NOT NULL DEFAULT 0,
    reference_rows                  integer NOT NULL DEFAULT 0,
    evaluation_rows                 integer NOT NULL DEFAULT 0,

    created_at                      timestamptz NOT NULL,
    created_by                      text NOT NULL,
    created_by_kind                 text NOT NULL,
    completed_at                    timestamptz,
    failure_reason                  text,
    superseded_by                   uuid
                                    REFERENCES normalized_feature_dataset_versions (id),

    CONSTRAINT nfdv_versao_unica UNIQUE (dataset_id, version_major, version_minor),
    CONSTRAINT nfdv_status CHECK (
        status IN ('DRAFT', 'BUILDING', 'VALIDATING', 'READY', 'FAILED', 'SUPERSEDED')
    ),
    CONSTRAINT nfdv_impressoes CHECK (
        source_raw_content_fingerprint ~ '^[0-9a-f]{64}$'
        AND space_fingerprint ~ '^[0-9a-f]{64}$'
        AND plan_fingerprint ~ '^[0-9a-f]{64}$'
        AND artifact_set_fingerprint ~ '^[0-9a-f]{64}$'
        AND representation_fingerprint ~ '^[0-9a-f]{64}$'
        AND (normalized_content_fingerprint IS NULL
             OR normalized_content_fingerprint ~ '^[0-9a-f]{64}$')
        AND (normalized_reference_content_fingerprint IS NULL
             OR normalized_reference_content_fingerprint ~ '^[0-9a-f]{64}$')
        AND (normalized_evaluation_content_fingerprint IS NULL
             OR normalized_evaluation_content_fingerprint ~ '^[0-9a-f]{64}$')
    ),
    -- PUBLICAR EXIGE AS DUAS IMPRESSÕES, e não só a global. A de referência é a
    -- única que permite afirmar, entre duas versões publicadas, que a base
    -- estatística é a mesma.
    CONSTRAINT nfdv_publicada_tem_prova CHECK (
        status NOT IN ('READY', 'SUPERSEDED')
        OR (normalized_content_fingerprint IS NOT NULL
            AND normalized_reference_content_fingerprint IS NOT NULL
            AND manifest_id IS NOT NULL
            AND row_count > 0)
    ),
    -- A NORMALIZAÇÃO É 1:1 (§94). Uma linha a menos é uma partida
    -- silenciosamente fora do conjunto de comparação, e não um dataset «mais
    -- limpo».
    CONSTRAINT nfdv_um_para_um CHECK (
        status NOT IN ('READY', 'SUPERSEDED')
        OR source_row_count = 0
        OR row_count = source_row_count
    ),
    CONSTRAINT nfdv_terminal_tem_fim CHECK (
        status IN ('DRAFT', 'BUILDING', 'VALIDATING') OR completed_at IS NOT NULL
    ),
    CONSTRAINT nfdv_falha_tem_motivo CHECK (
        status <> 'FAILED' OR length(btrim(coalesce(failure_reason, ''))) > 0
    ),
    CONSTRAINT nfdv_substituida_diz_por_qual CHECK (
        status <> 'SUPERSEDED' OR superseded_by IS NOT NULL
    ),
    CONSTRAINT nfdv_metades_fecham CHECK (
        reference_rows + evaluation_rows = row_count
        AND reference_matches + evaluation_matches = match_count
    ),
    CONSTRAINT nfdv_contagens_nao_negativas CHECK (
        match_count >= 0 AND row_count >= 0 AND source_row_count >= 0
        AND reference_matches >= 0 AND evaluation_matches >= 0
        AND reference_rows >= 0 AND evaluation_rows >= 0
    )
);

-- «QUE DATASETS SAÍRAM DESTE AJUSTE?» — descobrir que uma competição foi
-- ajustada sobre referência incompleta obriga a achar tudo que foi normalizado
-- com aqueles números.
CREATE INDEX nfdv_ajuste_idx
    ON normalized_feature_dataset_versions (artifact_set_id);

CREATE INDEX nfdv_origem_idx
    ON normalized_feature_dataset_versions (source_version_id);

CREATE INDEX nfdv_publicadas_idx
    ON normalized_feature_dataset_versions (dataset_id, version_major DESC, version_minor DESC)
    WHERE status = 'READY';

-- «ESTAS DUAS VERSÕES SÃO COMPARÁVEIS NÚMERO A NÚMERO?» — uma consulta, e não
-- uma reconstrução de política de seis meses atrás.
CREATE INDEX nfdv_comparabilidade_idx
    ON normalized_feature_dataset_versions (representation_fingerprint);

-- «A BASE DE COMPARAÇÃO MUDOU ENTRE ESTAS DUAS PUBLICAÇÕES?» — a pergunta do
-- PR, respondida por igualdade de coluna.
CREATE INDEX nfdv_referencia_idx
    ON normalized_feature_dataset_versions (normalized_reference_content_fingerprint)
    WHERE normalized_reference_content_fingerprint IS NOT NULL;

-- =========================================== os manifestos ==

CREATE TABLE normalized_feature_dataset_manifests (
    id                              uuid PRIMARY KEY,
    version_id                      uuid NOT NULL
                                    REFERENCES normalized_feature_dataset_versions (id)
                                    ON DELETE CASCADE,
    schema_version                  text NOT NULL,
    document                        jsonb NOT NULL,
    -- AS DUAS IMPRESSÕES, lado a lado e nomeadas: a primeira é o CONTEÚDO do
    -- dataset, a segunda são os BYTES do documento. A primeira não muda entre
    -- duas construções iguais; a segunda muda com o carimbo de tempo.
    normalized_content_fingerprint  text NOT NULL,
    manifest_sha256                 text NOT NULL,
    object_key                      text,
    created_at                      timestamptz NOT NULL,

    CONSTRAINT nfdm_um_por_versao UNIQUE (version_id),
    CONSTRAINT nfdm_impressoes CHECK (
        normalized_content_fingerprint ~ '^[0-9a-f]{64}$'
        AND manifest_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX nfdm_conteudo_idx
    ON normalized_feature_dataset_manifests (normalized_content_fingerprint);

ALTER TABLE normalized_feature_dataset_versions
    ADD CONSTRAINT nfdv_manifest_fk
    FOREIGN KEY (manifest_id) REFERENCES normalized_feature_dataset_manifests (id)
    DEFERRABLE INITIALLY DEFERRED;

-- ================================== as execuções de construção ==

CREATE TABLE normalized_feature_dataset_build_runs (
    id                          uuid PRIMARY KEY,
    version_id                  uuid NOT NULL
                                REFERENCES normalized_feature_dataset_versions (id)
                                ON DELETE CASCADE,
    status                      text NOT NULL,
    started_at                  timestamptz NOT NULL,
    started_by                  text NOT NULL,
    started_by_kind             text NOT NULL,
    finished_at                 timestamptz,
    rows_read                   integer NOT NULL DEFAULT 0,
    rows_written                integer NOT NULL DEFAULT 0,
    objects_written             integer NOT NULL DEFAULT 0,
    bytes_written               bigint NOT NULL DEFAULT 0,
    -- QUANTAS CÉLULAS O AJUSTE PERDEU — e não a origem. É a métrica de saúde
    -- do AJUSTE: um salto aqui entre duas execuções diz que uma competição
    -- perdeu escala, e não que a coleta caiu. Um contador só apagaria a
    -- distinção exatamente onde ela decide o que fazer.
    artifact_unavailable_cells  bigint NOT NULL DEFAULT 0,
    failure_reason              text,

    CONSTRAINT nfdbr_status CHECK (
        status IN ('BUILDING', 'VALIDATING', 'READY', 'FAILED')
    ),
    CONSTRAINT nfdbr_terminal_tem_fim CHECK (
        status IN ('BUILDING', 'VALIDATING') OR finished_at IS NOT NULL
    ),
    CONSTRAINT nfdbr_falha_tem_motivo CHECK (
        status <> 'FAILED' OR length(btrim(coalesce(failure_reason, ''))) > 0
    ),
    CONSTRAINT nfdbr_custos_nao_negativos CHECK (
        rows_read >= 0 AND rows_written >= 0 AND objects_written >= 0
        AND bytes_written >= 0 AND artifact_unavailable_cells >= 0
    )
);

CREATE INDEX nfdbr_versao_idx
    ON normalized_feature_dataset_build_runs (version_id, started_at DESC);

-- ============================================ os objetos escritos ==

CREATE TABLE normalized_feature_objects (
    version_id          uuid NOT NULL
                        REFERENCES normalized_feature_dataset_versions (id)
                        ON DELETE CASCADE,
    object_key          text NOT NULL,
    split               text NOT NULL,
    competition         text NOT NULL,
    season              text NOT NULL,
    sha256              text NOT NULL,
    size_bytes          bigint NOT NULL,
    row_count           integer NOT NULL,
    match_count         integer NOT NULL DEFAULT 0,
    -- DE QUAL OBJETO CRU ESTE SAIU. O contrato 1:1 vale globalmente e vale por
    -- partição, e conferir só o total deixaria passar o caso em que uma
    -- partição perdeu linhas e outra ganhou.
    source_object_key   text NOT NULL DEFAULT '',
    content_type        text NOT NULL DEFAULT 'application/vnd.apache.parquet',

    PRIMARY KEY (version_id, object_key),
    CONSTRAINT nfo_split CHECK (split IN ('REFERENCE', 'EVALUATION')),
    CONSTRAINT nfo_sha CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT nfo_contagens CHECK (
        size_bytes >= 0 AND row_count >= 0 AND match_count >= 0
    )
);

CREATE INDEX nfo_particao_idx
    ON normalized_feature_objects (version_id, split, competition, season);
