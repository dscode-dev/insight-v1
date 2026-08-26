-- 0012 — O dataset histórico de features (PR-05.5.1)
--
-- POR QUE UMA MIGRATION NOVA E NÃO UMA EDIÇÃO. O aplicador guarda o SHA-256 de
-- cada migration aplicada e RECUSA seguir quando o arquivo muda depois. O
-- caminho de volta é sempre uma migration nova.
--
-- O QUE ELA RESOLVE. O PR-05.4 fechou o cálculo: dada uma partida e um corte,
-- o motor produz um `FeatureSnapshot` de 105 dimensões. O que não existe é o
-- CONJUNTO — «as features de dez mil partidas em noventa e um cortes cada, sob
-- estas políticas, congeladas sob este nome». Sem ele não há população para
-- ajustar escala, não há base de vizinhos, e não há como duas execuções
-- provarem que produziram a mesma coisa.
--
-- A DIFERENÇA CENTRAL PARA O CORPUS (ADR-0037). No corpus, o PostgreSQL é a
-- fonte da verdade e o Parquet é uma cópia colunar: apagar o bucket não perde
-- fato nenhum. Aqui é o contrário — as LINHAS de feature moram no Parquet e
-- só nele. Estas tabelas guardam identidade, políticas, contagens, rastro de
-- execução e PONTEIROS.
--
--   por que não guardar as linhas no PostgreSQL. Dez mil partidas × noventa e
--   uma linhas × cento e cinco valores são 95,5 milhões de números. Em linhas
--   largas isso é uma tabela de centenas de colunas que nenhum índice ajuda;
--   em formato estreito (`chave, valor`) são 95 milhões de linhas para
--   responder uma pergunta que é sempre colunar e sempre em massa. Nenhuma das
--   duas formas é o que este dado é.
--
--   e o que se perde com isso é declarado: o dataset depende do object store
--   estar de pé. A troca é aceita porque a reconstrução é determinística — a
--   versão do corpus é imutável, as políticas são impressas, e reconstruir
--   produz o mesmo `raw_content_fingerprint`.
--
-- AS POLÍTICAS ENTRAM PELA IMPRESSÃO, E NÃO PELO OBJETO SERIALIZADO SOZINHO.
-- Uma coluna `jsonb` responderia «quais eram as regras»; a impressão responde
-- «estas duas versões são comparáveis?», que é a pergunta que se faz de fato.
-- As duas estão aqui: o `jsonb` para ler, a impressão para comparar.

-- ============================================ a identidade lógica ==
--
-- ELA NÃO CARREGA ESCOPO NEM CONTAGEM, pela mesma razão do corpus: um dataset
-- que soubesse quantas linhas contém teria de mudar quando a v1.1 acrescentasse
-- partidas, e deixaria de ser identidade estável.

CREATE TABLE historical_feature_datasets (
    id                  uuid PRIMARY KEY,
    name                text NOT NULL,
    description         text,
    created_at          timestamptz NOT NULL,
    created_by          text NOT NULL,
    created_by_kind     text NOT NULL,

    CONSTRAINT hfd_nome_unico UNIQUE (name),
    -- O NOME VIRA CAMINHO NO OBJECT STORE. Barra e espaço produziriam uma
    -- chave que não é a que se pensou ter escrito.
    CONSTRAINT hfd_nome_valido CHECK (
        length(btrim(name)) > 0
        AND position('/' IN name) = 0
        AND position(' ' IN name) = 0
    )
);

-- ================================================= as versões ==

CREATE TABLE historical_feature_dataset_versions (
    id                          uuid PRIMARY KEY,
    dataset_id                  uuid NOT NULL
                                REFERENCES historical_feature_datasets (id),
    version_major               integer NOT NULL,
    version_minor               integer NOT NULL,
    status                      text NOT NULL,

    -- ==================================================== a origem ==
    --
    -- A VERSÃO DO CORPUS, E NÃO O DATASET CANÔNICO. «As features da 1.0» é
    -- verificável; «as features do corpus» mudaria de significado toda vez que
    -- o corpus publicasse. A impressão vem junto porque o id sozinho diz «da
    -- 1.0» e não diz «da 1.0 cujo conteúdo era este».
    source_version_id           uuid NOT NULL
                                REFERENCES historical_canonical_dataset_versions (id),
    source_version_major        integer NOT NULL,
    source_version_minor        integer NOT NULL,
    source_corpus_fingerprint   text NOT NULL,

    -- ================================================ as políticas ==
    --
    -- CADA UMA COM NOME, VERSÃO E IMPRESSÃO. Duas versões construídas sob
    -- grades diferentes NÃO são comparáveis linha a linha, e sem a impressão
    -- essa descoberta exigiria reconstruir a política de seis meses atrás.
    space_name                  text NOT NULL,
    space_version               text NOT NULL,
    space_fingerprint           text NOT NULL,
    grid_name                   text NOT NULL,
    grid_version                integer NOT NULL,
    grid_fingerprint            text NOT NULL,
    split_name                  text NOT NULL,
    split_version               integer NOT NULL,
    split_fingerprint           text NOT NULL,
    -- A FRONTEIRA, EM COLUNA PRÓPRIA e não só dentro do `jsonb`. «Que datasets
    -- têm avaliação começando depois de junho?» é pergunta administrativa
    -- real, e dentro do documento ela vira varredura.
    reference_end_exclusive     timestamptz NOT NULL,
    -- A FORMA CANÔNICA COMPLETA DAS POLÍTICAS, com os PARÂMETROS delas — e é
    -- daqui que a reconstrução sai, não das colunas acima.
    --
    -- POR QUE AS COLUNAS NÃO BASTAM. Elas guardam nome, versão e impressão: o
    -- que se CONSULTA. Reconstruir uma política a partir delas traz os
    -- parâmetros PADRÃO — uma grade de cinco cortes voltaria com noventa e um,
    -- e a impressão acusaria a divergência sem conseguir consertá-la. Uma
    -- política com parâmetros só é reconstrutível a partir dos parâmetros.
    --
    -- OS DOIS SÃO CONFERIDOS UM CONTRA O OUTRO na leitura. Um índice que
    -- apontasse para uma impressão diferente da do documento tornaria a
    -- consulta «quais versões são comparáveis com esta?» silenciosamente
    -- errada — e silenciosamente é a palavra que importa.
    spec                        jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- =================================== o conteúdo, quando existe ==
    --
    -- `NULL` ATÉ A CONSTRUÇÃO TERMINAR. Uma versão em DRAFT não tem conteúdo
    -- para imprimir, e um zero no lugar diria que ela tem conteúdo vazio.
    raw_content_fingerprint     text,
    manifest_id                 uuid,
    match_count                 integer NOT NULL DEFAULT 0,
    row_count                   integer NOT NULL DEFAULT 0,
    -- AS CONTAGENS POR METADE SÃO COLUNAS, e não um `jsonb`: «a referência
    -- ficou vazia?» é a pergunta que se faz depois de errar a fronteira, e ela
    -- precisa ser um predicado.
    reference_matches           integer NOT NULL DEFAULT 0,
    evaluation_matches          integer NOT NULL DEFAULT 0,
    reference_rows              integer NOT NULL DEFAULT 0,
    evaluation_rows             integer NOT NULL DEFAULT 0,

    created_at                  timestamptz NOT NULL,
    created_by                  text NOT NULL,
    created_by_kind             text NOT NULL,
    completed_at                timestamptz,
    failure_reason              text,
    superseded_by               uuid
                                REFERENCES historical_feature_dataset_versions (id),

    -- «1.0» PRECISA SIGNIFICAR UM CONTEÚDO SÓ, PARA SEMPRE.
    CONSTRAINT hfdv_versao_unica UNIQUE (dataset_id, version_major, version_minor),
    CONSTRAINT hfdv_status CHECK (
        status IN ('DRAFT', 'BUILDING', 'VALIDATING', 'READY', 'FAILED', 'SUPERSEDED')
    ),
    CONSTRAINT hfdv_impressoes CHECK (
        source_corpus_fingerprint ~ '^[0-9a-f]{64}$'
        AND space_fingerprint ~ '^[0-9a-f]{64}$'
        AND grid_fingerprint ~ '^[0-9a-f]{64}$'
        AND split_fingerprint ~ '^[0-9a-f]{64}$'
        AND (raw_content_fingerprint IS NULL
             OR raw_content_fingerprint ~ '^[0-9a-f]{64}$')
    ),
    -- READY SEM IMPRESSÃO, SEM MANIFESTO OU SEM LINHA afirmaria estar
    -- publicada sem nada que prove o que publicou. A terceira condição é
    -- própria daqui: um corpus vazio é estranho, um DATASET vazio publicado
    -- devolveria «sem vizinhos» em vez de um erro para quem o consultasse.
    CONSTRAINT hfdv_publicada_tem_prova CHECK (
        status NOT IN ('READY', 'SUPERSEDED')
        OR (raw_content_fingerprint IS NOT NULL
            AND manifest_id IS NOT NULL
            AND row_count > 0)
    ),
    CONSTRAINT hfdv_terminal_tem_fim CHECK (
        status IN ('DRAFT', 'BUILDING', 'VALIDATING') OR completed_at IS NOT NULL
    ),
    CONSTRAINT hfdv_falha_tem_motivo CHECK (
        status <> 'FAILED' OR length(btrim(coalesce(failure_reason, ''))) > 0
    ),
    CONSTRAINT hfdv_substituida_diz_por_qual CHECK (
        status <> 'SUPERSEDED' OR superseded_by IS NOT NULL
    ),
    -- AS DUAS CONTAGENS TÊM DE FECHAR. Um manifesto que se contradiz nunca
    -- chegaria a ser conferido, e o banco é o lugar barato de pegar isso.
    CONSTRAINT hfdv_metades_fecham CHECK (
        reference_rows + evaluation_rows = row_count
        AND reference_matches + evaluation_matches = match_count
    ),
    CONSTRAINT hfdv_contagens_nao_negativas CHECK (
        match_count >= 0 AND row_count >= 0
        AND reference_matches >= 0 AND evaluation_matches >= 0
        AND reference_rows >= 0 AND evaluation_rows >= 0
    )
);

-- A TRAVESSIA PARA FRENTE: «que datasets saíram desta versão do corpus?».
-- Descobrir um defeito numa versão do corpus obriga a achar tudo que foi
-- construído sobre ela, e sem este índice a resposta é uma varredura.
CREATE INDEX hfdv_origem_idx
    ON historical_feature_dataset_versions (source_version_id);

-- «QUAL É A VERSÃO PUBLICADA MAIS RECENTE» — a pergunta da produção.
CREATE INDEX hfdv_publicadas_idx
    ON historical_feature_dataset_versions (dataset_id, version_major DESC, version_minor DESC)
    WHERE status = 'READY';

-- «QUE VERSÕES SÃO COMPARÁVEIS COM ESTA?» A comparabilidade é a conjunção das
-- três impressões, e este índice é o que a torna uma consulta.
CREATE INDEX hfdv_comparabilidade_idx
    ON historical_feature_dataset_versions (space_fingerprint, grid_fingerprint, split_fingerprint);

-- ================================================== os manifestos ==

CREATE TABLE historical_feature_dataset_manifests (
    id                          uuid PRIMARY KEY,
    version_id                  uuid NOT NULL
                                REFERENCES historical_feature_dataset_versions (id)
                                ON DELETE CASCADE,
    schema_version              text NOT NULL,
    -- O documento inteiro, do jeito que foi serializado. IMUTÁVEL: não há
    -- `UPDATE` no caminho normal.
    document                    jsonb NOT NULL,
    -- AS DUAS IMPRESSÕES, lado a lado e nomeadas, porque confundi-las é caro:
    -- a primeira é o conteúdo do dataset, a segunda são os bytes do documento.
    raw_content_fingerprint     text NOT NULL,
    manifest_sha256             text NOT NULL,
    object_key                  text,
    created_at                  timestamptz NOT NULL,

    CONSTRAINT hfdm_um_por_versao UNIQUE (version_id),
    CONSTRAINT hfdm_impressoes CHECK (
        raw_content_fingerprint ~ '^[0-9a-f]{64}$'
        AND manifest_sha256 ~ '^[0-9a-f]{64}$'
    )
);

-- «QUAIS CONSTRUÇÕES PRODUZIRAM ESTE MESMO CONTEÚDO». Plural de propósito:
-- duas construções independentes sob as mesmas políticas sobre a mesma versão
-- do corpus têm a mesma impressão e ids diferentes — e descobrir isso é o que
-- permite não reconstruir.
CREATE INDEX hfdm_conteudo_idx
    ON historical_feature_dataset_manifests (raw_content_fingerprint);

ALTER TABLE historical_feature_dataset_versions
    ADD CONSTRAINT hfdv_manifest_fk
    FOREIGN KEY (manifest_id) REFERENCES historical_feature_dataset_manifests (id)
    DEFERRABLE INITIALLY DEFERRED;

-- ============================================ as execuções de construção ==
--
-- O RASTRO NÃO É O CONTEÚDO. Duas execuções sobre a mesma versão — a segunda
-- depois de uma falha — são dois rastros e um conteúdo. Guardar o custo aqui é
-- o que permite responder «por que a 1.1 demorou o triplo da 1.0» sem ter de
-- ter estado olhando na hora.

CREATE TABLE historical_feature_dataset_build_runs (
    id                  uuid PRIMARY KEY,
    version_id          uuid NOT NULL
                        REFERENCES historical_feature_dataset_versions (id)
                        ON DELETE CASCADE,
    status              text NOT NULL,
    started_at          timestamptz NOT NULL,
    started_by          text NOT NULL,
    started_by_kind     text NOT NULL,
    finished_at         timestamptz,
    matches_processed   integer NOT NULL DEFAULT 0,
    rows_written        integer NOT NULL DEFAULT 0,
    objects_written     integer NOT NULL DEFAULT 0,
    bytes_written       bigint NOT NULL DEFAULT 0,
    failure_reason      text,

    CONSTRAINT hfdbr_status CHECK (
        status IN ('BUILDING', 'VALIDATING', 'READY', 'FAILED')
    ),
    CONSTRAINT hfdbr_terminal_tem_fim CHECK (
        status IN ('BUILDING', 'VALIDATING') OR finished_at IS NOT NULL
    ),
    CONSTRAINT hfdbr_falha_tem_motivo CHECK (
        status <> 'FAILED' OR length(btrim(coalesce(failure_reason, ''))) > 0
    ),
    CONSTRAINT hfdbr_custos_nao_negativos CHECK (
        matches_processed >= 0 AND rows_written >= 0
        AND objects_written >= 0 AND bytes_written >= 0
    )
);

CREATE INDEX hfdbr_versao_idx
    ON historical_feature_dataset_build_runs (version_id, started_at DESC);

-- ================================================= os objetos escritos ==
--
-- AQUI ELES NÃO SÃO CONFERÊNCIA — SÃO O ÍNDICE DO CONTEÚDO. No corpus estas
-- linhas existem para achar e conferir uma cópia; aqui elas são o único
-- caminho do banco para os dados. Uma versão sem objetos registrados é uma
-- versão sem conteúdo alcançável.

CREATE TABLE historical_feature_objects (
    version_id      uuid NOT NULL
                    REFERENCES historical_feature_dataset_versions (id)
                    ON DELETE CASCADE,
    object_key      text NOT NULL,
    -- A PARTIÇÃO EM COLUNAS, e não extraída da chave. Reconciliar manifesto
    -- com registro não pode depender de fazer análise sintática de caminho.
    split           text NOT NULL,
    competition     text NOT NULL,
    season          text NOT NULL,
    sha256          text NOT NULL,
    size_bytes      bigint NOT NULL,
    row_count       integer NOT NULL,
    match_count     integer NOT NULL DEFAULT 0,
    content_type    text NOT NULL DEFAULT 'application/vnd.apache.parquet',

    -- UM OBJETO POR CHAVE POR VERSÃO. Reescrever o mesmo `part-00003.parquet`
    -- é o caminho normal do retry depois de uma falha parcial; sem esta chave
    -- ele duplicaria a contagem do manifesto.
    PRIMARY KEY (version_id, object_key),
    CONSTRAINT hfo_split CHECK (split IN ('REFERENCE', 'EVALUATION')),
    CONSTRAINT hfo_sha CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT hfo_contagens CHECK (
        size_bytes >= 0 AND row_count >= 0 AND match_count >= 0
    )
);

-- «AS PARTIÇÕES DA METADE DE REFERÊNCIA» — o predicado que o ajuste de escala
-- e a busca de vizinhos vão usar em todo caminho de leitura.
CREATE INDEX hfo_particao_idx
    ON historical_feature_objects (version_id, split, competition, season);
