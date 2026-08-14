-- 0001 — Dataset Registry & Historical Manual Intake (PR-02)
--
-- O QUE ESTE SCHEMA PROTEGE, E O QUE ELE DELIBERADAMENTE NÃO PROTEGE.
--
-- PROTEGE: unicidade e idempotência. Elas precisam do banco porque dois
-- processos concorrentes leem o mesmo estado, os dois concluem que podem, e
-- os dois seguem — lógica Python não tem como impedir isso. Toda constraint
-- aqui existe para transformar uma corrida perdida num erro de constraint em
-- vez de num registro duplicado.
--
-- NÃO PROTEGE: as regras de domínio. Não há trigger validando transição de
-- lifecycle, não há função conferindo severidade de issue. O domínio é a
-- autoridade dos invariantes (ADR-0003); espalhá-los em PL/pgSQL cria uma
-- segunda implementação que diverge da primeira e que nenhum teste de unidade
-- alcança.
--
-- A EXCEÇÃO SÃO OS CHECKs SIMPLES — tamanho não negativo, hash com 64
-- caracteres. Eles não duplicam regra de negócio: são a última linha contra
-- uma escrita que não passou pelo domínio, e custam nada.
--
-- TODO TIMESTAMP É `timestamptz`. `timestamp` sem fuso guarda um horário sem
-- dizer de onde, e a leitura o interpreta no fuso do servidor — que muda
-- quando o servidor muda.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    checksum    text NOT NULL
);

-- ---------------------------------------------------------------- datasets --

CREATE TABLE datasets (
    id                      uuid PRIMARY KEY,
    name                    text NOT NULL,
    version_major           integer NOT NULL,
    version_minor           integer NOT NULL,
    description             text,
    lifecycle               text NOT NULL,
    declared_competitions   text[] NOT NULL,
    declared_seasons        text[] NOT NULL DEFAULT '{}',
    latest_validation_id    uuid,
    created_at              timestamptz NOT NULL,
    created_by              text NOT NULL,
    updated_at              timestamptz NOT NULL DEFAULT now(),

    -- A IDENTIDADE É DERIVADA DE (nome, versão), e esta constraint é o que
    -- torna a derivação confiável: sem ela, dois processos poderiam inserir
    -- o mesmo par com ids diferentes se a derivação mudasse.
    CONSTRAINT datasets_nome_versao_unico UNIQUE (name, version_major, version_minor),
    CONSTRAINT datasets_versao_nao_negativa CHECK (version_major >= 0 AND version_minor >= 0),
    CONSTRAINT datasets_competicao_declarada CHECK (cardinality(declared_competitions) > 0),
    CONSTRAINT datasets_autor_nao_vazio CHECK (length(btrim(created_by)) > 0),
    CONSTRAINT datasets_lifecycle_conhecido CHECK (
        lifecycle IN (
            'REGISTERED', 'UPLOADING', 'UPLOADED', 'VALIDATING',
            'VALIDATED', 'STAGED', 'INVALID', 'REJECTED', 'FAILED'
        )
    )
);

-- As consultas administrativas reais: "o que está esperando validação",
-- "o que entrou esta semana", "o que é da Premier League".
CREATE INDEX datasets_lifecycle_idx ON datasets (lifecycle, created_at DESC);
CREATE INDEX datasets_created_at_idx ON datasets (created_at DESC);
CREATE INDEX datasets_competicoes_idx ON datasets USING gin (declared_competitions);

-- ---------------------------------------------------------- dataset_sources --
--
-- UMA FONTE POR DATASET, e por isso `dataset_id` é a própria chave primária.
-- Uma tabela separada e não colunas em `datasets` porque a ficha de origem é
-- uma unidade com sentido próprio — ela é copiada para o manifesto inteira, e
-- tê-la junta evita montar o objeto a partir de sete colunas espalhadas.

CREATE TABLE dataset_sources (
    dataset_id      uuid PRIMARY KEY REFERENCES datasets (id) ON DELETE CASCADE,
    source_name     text NOT NULL,
    source_type     text NOT NULL,
    license_class   text NOT NULL,
    retrieved_at    timestamptz NOT NULL,
    source_url      text,
    publisher       text,
    provider_id     text,
    notes           text,

    CONSTRAINT dataset_sources_tipo_de_intake CHECK (
        source_type IN ('OPEN_DATA', 'COMMERCIAL_PROVIDER', 'MANUAL')
    ),
    CONSTRAINT dataset_sources_licenca_conhecida CHECK (
        license_class IN (
            'PUBLIC_DOMAIN', 'ATTRIBUTION_REQUIRED', 'RESEARCH_ONLY',
            'COMMERCIAL_ALLOWED', 'UNKNOWN'
        )
    ),
    -- A mesma exigência que `DataProvenance` faz: dado de provedor sem
    -- provedor não tem como perder um desempate (ADR-0009).
    CONSTRAINT dataset_sources_provedor_quando_externa CHECK (
        source_type = 'MANUAL' OR provider_id IS NOT NULL
    )
);

CREATE INDEX dataset_sources_nome_idx ON dataset_sources (source_name);

-- ------------------------------------------------------------ dataset_files --

CREATE TABLE dataset_files (
    id                  uuid PRIMARY KEY,
    dataset_id          uuid NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    version_major       integer NOT NULL,
    version_minor       integer NOT NULL,
    original_filename   text NOT NULL,
    safe_filename       text NOT NULL,
    media_type          text NOT NULL,
    format              text NOT NULL,
    sha256              text NOT NULL,
    size_bytes          bigint NOT NULL,
    object_key          text NOT NULL,
    staging_state       text NOT NULL,
    uploaded_at         timestamptz NOT NULL,
    uploaded_by         text NOT NULL,
    -- A procedência do arquivo, herdada da fonte. `jsonb` porque ela é um
    -- objeto do domínio que viaja inteiro e nunca é consultado por campo.
    provenance          jsonb NOT NULL,
    row_count           bigint,
    column_count        integer,
    failure_reason      text,
    confirmed_at        timestamptz,

    -- A IDEMPOTÊNCIA FÍSICA DO UPLOAD, e ela precisa estar aqui. Dois
    -- uploads simultâneos dos mesmos bytes chegam juntos, os dois consultam,
    -- os dois não encontram nada, e os dois inserem. Só o banco impede.
    CONSTRAINT dataset_files_conteudo_unico UNIQUE (dataset_id, sha256),
    CONSTRAINT dataset_files_sha256_valido CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT dataset_files_tamanho_positivo CHECK (size_bytes > 0),
    CONSTRAINT dataset_files_formato_suportado CHECK (format IN ('PARQUET', 'CSV', 'JSONL')),
    CONSTRAINT dataset_files_estado_conhecido CHECK (
        staging_state IN ('PENDING', 'STORED', 'FAILED')
    ),
    -- O ARQUIVO BRUTO NÃO NEGOCIA SEU PREFIXO. Uma chave fora dele seria um
    -- objeto que a reconciliação não encontra ao listar.
    CONSTRAINT dataset_files_chave_no_prefixo CHECK (object_key LIKE 'datasets/raw/%'),
    -- Um arquivo confirmado tem instante de confirmação. É o que permite
    -- medir a janela do ADR-0017 sem cruzar com a trilha de auditoria.
    CONSTRAINT dataset_files_confirmacao_coerente CHECK (
        (staging_state = 'STORED') = (confirmed_at IS NOT NULL)
    ),
    CONSTRAINT dataset_files_contagens_nao_negativas CHECK (
        (row_count IS NULL OR row_count >= 0)
        AND (column_count IS NULL OR column_count >= 0)
    )
);

CREATE INDEX dataset_files_dataset_idx ON dataset_files (dataset_id, uploaded_at);
-- A consulta da reconciliação: intenções penduradas. Índice PARCIAL porque
-- ela só olha `PENDING`, e um índice sobre a tabela toda pagaria por linhas
-- que essa consulta nunca lê.
CREATE INDEX dataset_files_pendentes_idx
    ON dataset_files (uploaded_at)
    WHERE staging_state = 'PENDING';
-- O mesmo conteúdo em outro dataset: a duplicata que atravessa versões.
CREATE INDEX dataset_files_sha256_idx ON dataset_files (sha256);

-- ------------------------------------------------- dataset_validation_runs --
--
-- APPEND-ONLY. Revalidar não corrige um relatório: emite outro. Não há
-- `UPDATE` sobre esta tabela em lugar nenhum do código, e a diferença entre
-- duas execuções é o que mostra o que o validador novo passou a enxergar.

CREATE TABLE dataset_validation_runs (
    id                  uuid PRIMARY KEY,
    dataset_id          uuid NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    version_major       integer NOT NULL,
    version_minor       integer NOT NULL,
    status              text NOT NULL,
    validator_major     integer NOT NULL,
    validator_minor     integer NOT NULL,
    files_checked       integer NOT NULL,
    rows_observed       bigint NOT NULL,
    issue_count         integer NOT NULL,
    truncated           boolean NOT NULL DEFAULT false,
    schema_observations jsonb NOT NULL DEFAULT '[]'::jsonb,
    execution_error     text,
    started_at          timestamptz NOT NULL,
    generated_at        timestamptz NOT NULL,

    CONSTRAINT validation_runs_status_conhecido CHECK (
        status IN ('PASSED', 'PASSED_WITH_WARNINGS', 'PASSED_WITH_ERRORS', 'BLOCKED')
    ),
    CONSTRAINT validation_runs_contagens CHECK (
        files_checked >= 0 AND rows_observed >= 0 AND issue_count >= 0
    ),
    CONSTRAINT validation_runs_ordem_temporal CHECK (generated_at >= started_at)
);

CREATE INDEX validation_runs_dataset_idx
    ON dataset_validation_runs (dataset_id, generated_at DESC);

-- ---------------------------------------------- dataset_validation_issues --

CREATE TABLE dataset_validation_issues (
    id              bigserial PRIMARY KEY,
    run_id          uuid NOT NULL REFERENCES dataset_validation_runs (id) ON DELETE CASCADE,
    ordinal         integer NOT NULL,
    code            text NOT NULL,
    severity        smallint NOT NULL,
    message         text NOT NULL,
    file_id         uuid,
    location        text,
    occurrences     integer NOT NULL DEFAULT 1,

    CONSTRAINT validation_issues_severidade CHECK (severity IN (10, 20, 30, 40)),
    CONSTRAINT validation_issues_ocorrencias CHECK (occurrences >= 1),
    CONSTRAINT validation_issues_ordem_unica UNIQUE (run_id, ordinal)
);

-- `severity DESC` na chave do índice: quem lê um relatório quer o impeditivo
-- primeiro, e a ordenação vem do índice em vez de um sort a cada leitura.
CREATE INDEX validation_issues_run_idx
    ON dataset_validation_issues (run_id, severity DESC, ordinal);

-- ------------------------------------------------------- dataset_manifests --

CREATE TABLE dataset_manifests (
    fingerprint     text PRIMARY KEY,
    dataset_id      uuid NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    version_major   integer NOT NULL,
    version_minor   integer NOT NULL,
    validation_id   uuid NOT NULL REFERENCES dataset_validation_runs (id) ON DELETE CASCADE,
    body            jsonb NOT NULL,
    created_at      timestamptz NOT NULL,

    CONSTRAINT dataset_manifests_fingerprint_valido CHECK (fingerprint ~ '^[0-9a-f]{64}$')
);

-- A IMPRESSÃO É A CHAVE PRIMÁRIA, e é o que responde "este resultado saiu de
-- quais bytes" com uma consulta em vez de uma reconstrução.
CREATE INDEX dataset_manifests_dataset_idx
    ON dataset_manifests (dataset_id, created_at DESC);

-- ----------------------------------------------------- dataset_transitions --

CREATE TABLE dataset_transitions (
    id              bigserial PRIMARY KEY,
    dataset_id      uuid NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    from_state      text NOT NULL,
    to_state        text NOT NULL,
    reason          text NOT NULL,
    actor_id        text NOT NULL,
    at              timestamptz NOT NULL,

    -- O MOTIVO É OBRIGATÓRIO NO BANCO TAMBÉM. Um histórico de transições sem
    -- motivo responde "quando mudou" e não responde "por que mudou", que é a
    -- única pergunta que alguém faz seis meses depois.
    CONSTRAINT dataset_transitions_motivo CHECK (length(btrim(reason)) > 0),
    CONSTRAINT dataset_transitions_autor CHECK (length(btrim(actor_id)) > 0)
);

CREATE INDEX dataset_transitions_dataset_idx ON dataset_transitions (dataset_id, at);

-- ------------------------------------------------------------- audit_log --
--
-- A trilha administrativa. Só MUTAÇÃO — leitura não entra, senão o volume
-- passa a ser governado pelo tráfego em vez de pelas decisões, e ninguém
-- consegue achar as decisões no meio.

CREATE TABLE dataset_audit_log (
    id              uuid PRIMARY KEY,
    actor_id        text NOT NULL,
    actor_kind      text NOT NULL,
    action          text NOT NULL,
    dataset_id      uuid,
    file_id         uuid,
    correlation_id  text,
    reason          text,
    detail          jsonb NOT NULL DEFAULT '{}'::jsonb,
    at              timestamptz NOT NULL,

    CONSTRAINT audit_log_ator CHECK (length(btrim(actor_id)) > 0),
    -- Decisão humana sem motivo é o registro que não explica nada depois.
    CONSTRAINT audit_log_decisao_tem_motivo CHECK (
        action NOT IN ('DATASET_STAGED', 'DATASET_REJECTED')
        OR length(btrim(coalesce(reason, ''))) > 0
    )
);

-- SEM FOREIGN KEY para `datasets`, e é deliberado: a trilha precisa
-- sobreviver ao que ela descreve. Um `ON DELETE CASCADE` apagaria justamente
-- o registro de quem apagou.
CREATE INDEX audit_log_dataset_idx ON dataset_audit_log (dataset_id, at DESC);
CREATE INDEX audit_log_at_idx ON dataset_audit_log (at DESC);
CREATE INDEX audit_log_actor_idx ON dataset_audit_log (actor_id, at DESC);
