-- 0002 — Identity Resolution & Data Fusion (PR-03)
--
-- O QUE ESTE SCHEMA PROTEGE, e é diferente do PR-02. Lá as constraints
-- garantiam que os BYTES não duplicassem. Aqui elas garantem que uma DECISÃO
-- DE IDENTIDADE não nasça duas vezes, não seja reescrita, e não aponte para
-- duas entidades ao mesmo tempo.
--
-- A REGRA CENTRAL: decisões, evidências, execuções e saídas de fusão são
-- APPEND-ONLY. Não há `UPDATE` sobre nenhuma delas em lugar nenhum do código,
-- e um teste de arquitetura verifica isso lendo o SQL do adapter. Reprocessar
-- emite outra execução; a anterior fica exatamente como estava (ADR-0019,
-- ADR-0020).
--
-- A EXCEÇÃO DECLARADA é `resolution_review_items`: um item muda de estado
-- porque um humano o pegou e decidiu. Mesmo ali, a decisão que sai é uma
-- linha nova em `resolution_decisions` — nunca uma edição.

-- ================================================== mapeamentos e aliases ==

CREATE TABLE provider_entity_mappings (
    id                      uuid PRIMARY KEY,
    provider_id             text NOT NULL,
    entity_type             text NOT NULL,
    provider_entity_id      text NOT NULL,
    canonical_entity_id     uuid NOT NULL,
    -- OBRIGATÓRIA. Um mapeamento sem decisão que o explique é
    -- indistinguível de um mapeamento inventado (§13).
    resolution_decision_id  uuid NOT NULL,
    valid_from              timestamptz,
    valid_to                timestamptz,
    created_at              timestamptz NOT NULL,
    created_by              text NOT NULL,

    CONSTRAINT mappings_tipo_conhecido CHECK (
        entity_type IN ('COMPETITION', 'SEASON', 'TEAM', 'PLAYER', 'MATCH')
    ),
    CONSTRAINT mappings_autor CHECK (length(btrim(created_by)) > 0),
    CONSTRAINT mappings_janela CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

-- A CONSTRAINT QUE IMPEDE O MAPEAMENTO DUPLICADO (§34, §93). Dois workers
-- resolvendo o mesmo provedor em paralelo chegam juntos, os dois consultam,
-- os dois não encontram, e os dois inserem. Só o banco impede.
--
-- PARCIAL, sobre os vigentes: um mapeamento expirado e um novo para a mesma
-- referência coexistem legitimamente — é assim que se corrige um id que o
-- provedor reciclou, sem reescrever o histórico lido sob a tradução antiga.
CREATE UNIQUE INDEX mappings_vigente_unico
    ON provider_entity_mappings (provider_id, entity_type, provider_entity_id)
    WHERE valid_to IS NULL;

CREATE INDEX mappings_canonico_idx
    ON provider_entity_mappings (entity_type, canonical_entity_id);
CREATE INDEX mappings_decisao_idx ON provider_entity_mappings (resolution_decision_id);

CREATE TABLE entity_aliases (
    id                      uuid PRIMARY KEY,
    entity_type             text NOT NULL,
    entity_id               uuid NOT NULL,
    alias_original          text NOT NULL,
    alias_normalized        text NOT NULL,
    -- A VERSÃO DO NORMALIZADOR VIAJA JUNTO porque ele muda, e quando mudar
    -- os aliases gravados sob a versão antiga precisam ser reindexados. Sem
    -- ela, a única saída seria reindexar tudo, sempre (§66).
    normalizer_major        integer NOT NULL,
    normalizer_minor        integer NOT NULL,
    provider_id             text,
    valid_from              timestamptz,
    valid_to                timestamptz,
    resolution_decision_id  uuid,
    created_at              timestamptz NOT NULL,
    created_by              text NOT NULL,

    CONSTRAINT aliases_tipo_conhecido CHECK (
        entity_type IN ('COMPETITION', 'SEASON', 'TEAM', 'PLAYER', 'MATCH')
    ),
    CONSTRAINT aliases_nao_vazio CHECK (length(btrim(alias_normalized)) > 0)
);

-- O MESMO ALIAS NÃO APONTA PARA DUAS ENTIDADES sob a mesma versão de
-- normalizador e do mesmo provedor. Sem isto, `sporting` poderia apontar
-- para quatro clubes e a resolução escolheria por ordem de leitura.
CREATE UNIQUE INDEX aliases_unico
    ON entity_aliases (
        entity_type, alias_normalized, normalizer_major, normalizer_minor,
        coalesce(provider_id, '')
    )
    WHERE valid_to IS NULL;

-- A CONSULTA QUENTE DA RESOLUÇÃO: nome normalizado → candidatos.
CREATE INDEX aliases_busca_idx
    ON entity_aliases (entity_type, alias_normalized, normalizer_major, normalizer_minor);
CREATE INDEX aliases_entidade_idx ON entity_aliases (entity_type, entity_id);

-- ============================================== mapeamento de fonte ========

CREATE TABLE source_mapping_definitions (
    id              uuid PRIMARY KEY,
    dataset_id      uuid NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    version_major   integer NOT NULL,
    version_minor   integer NOT NULL,
    provider_id     text NOT NULL,
    version         integer NOT NULL,
    status          text NOT NULL,
    -- INERTE. Um dicionário de coluna para papel semântico, mais
    -- transformações de um catálogo fechado. Nada aqui é executado (§81).
    fields          jsonb NOT NULL,
    conventions     jsonb NOT NULL DEFAULT '{}'::jsonb,
    description     text,
    created_at      timestamptz NOT NULL,
    created_by      text NOT NULL,

    CONSTRAINT source_mapping_status CHECK (status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')),
    CONSTRAINT source_mapping_versao CHECK (version >= 1),
    CONSTRAINT source_mapping_campos CHECK (jsonb_typeof(fields) = 'array')
);

-- UM MAPEAMENTO ATIVO POR DATASET. Dois ativos fariam a execução escolher
-- por ordem de leitura qual interpretação do arquivo usar.
CREATE UNIQUE INDEX source_mapping_ativo_unico
    ON source_mapping_definitions (dataset_id)
    WHERE status = 'ACTIVE';
CREATE UNIQUE INDEX source_mapping_versao_unica
    ON source_mapping_definitions (dataset_id, version);

-- ================================================ execuções de resolução ==

CREATE TABLE resolution_runs (
    id                      uuid PRIMARY KEY,
    dataset_id              uuid NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
    version_major           integer NOT NULL,
    version_minor           integer NOT NULL,
    -- FECHA A LINHAGEM: sem ela, «esta execução rodou sobre o dataset X» é
    -- uma afirmação sobre um dataset que pode ter mudado desde então (§78).
    manifest_fingerprint    text NOT NULL,
    resolver_major          integer NOT NULL,
    resolver_minor          integer NOT NULL,
    normalizer_major        integer NOT NULL,
    normalizer_minor        integer NOT NULL,
    policy_major            integer NOT NULL,
    policy_minor            integer NOT NULL,
    status                  text NOT NULL,
    total_records           integer NOT NULL DEFAULT 0,
    resolved                integer NOT NULL DEFAULT 0,
    unresolved              integer NOT NULL DEFAULT 0,
    ambiguous               integer NOT NULL DEFAULT 0,
    review_required         integer NOT NULL DEFAULT 0,
    rejected                integer NOT NULL DEFAULT 0,
    started_at              timestamptz NOT NULL,
    completed_at            timestamptz,
    triggered_by            text NOT NULL,
    triggered_by_kind       text NOT NULL,
    failure_reason          text,

    CONSTRAINT resolution_runs_status CHECK (
        status IN ('PENDING', 'RUNNING', 'COMPLETED', 'COMPLETED_WITH_REVIEW', 'FAILED', 'CANCELLED')
    ),
    CONSTRAINT resolution_runs_fingerprint CHECK (manifest_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT resolution_runs_ordem CHECK (completed_at IS NULL OR completed_at >= started_at),
    -- AS CONTAGENS PRECISAM FECHAR. Uma execução cuja soma por status não
    -- bate com o total está mentindo sobre o que processou.
    CONSTRAINT resolution_runs_contagens CHECK (
        status IN ('PENDING', 'RUNNING', 'FAILED', 'CANCELLED')
        OR resolved + unresolved + ambiguous + review_required + rejected = total_records
    )
);

CREATE INDEX resolution_runs_dataset_idx ON resolution_runs (dataset_id, started_at DESC);
CREATE INDEX resolution_runs_status_idx ON resolution_runs (status, started_at DESC);

-- ==================================================== decisões (append) ===

CREATE TABLE resolution_decisions (
    id                      uuid PRIMARY KEY,
    run_id                  uuid NOT NULL REFERENCES resolution_runs (id) ON DELETE CASCADE,
    subject_type            text NOT NULL,
    provider_id             text NOT NULL,
    provider_entity_id      text,
    source_raw              text NOT NULL,
    source_normalized       text NOT NULL,
    normalizer_major        integer NOT NULL,
    normalizer_minor        integer NOT NULL,
    status                  text NOT NULL,
    method                  text NOT NULL,
    confidence              double precision NOT NULL,
    canonical_entity_id     uuid,
    resolver_major          integer NOT NULL,
    resolver_minor          integer NOT NULL,
    policy_major            integer NOT NULL,
    policy_minor            integer NOT NULL,
    dataset_id              uuid NOT NULL,
    dataset_version_major   integer NOT NULL,
    dataset_version_minor   integer NOT NULL,
    manifest_fingerprint    text NOT NULL,
    record_ref              text,
    decided_at              timestamptz NOT NULL,
    decided_by              text NOT NULL,
    decided_by_kind         text NOT NULL,
    reason                  text,

    CONSTRAINT decisions_subject CHECK (
        subject_type IN ('COMPETITION', 'SEASON', 'TEAM', 'PLAYER', 'MATCH')
    ),
    CONSTRAINT decisions_status CHECK (
        status IN ('RESOLVED', 'UNRESOLVED', 'AMBIGUOUS', 'REVIEW_REQUIRED', 'REJECTED')
    ),
    CONSTRAINT decisions_method CHECK (
        method IN ('EXACT_PROVIDER_MAPPING', 'EXACT_CANONICAL_KEY', 'EXACT_ALIAS',
                   'COMPOSITE_RULE', 'CONFIDENCE_MATCH', 'MANUAL_REVIEW')
    ),
    CONSTRAINT decisions_confianca CHECK (confidence >= 0 AND confidence <= 1),
    -- A REGRA CENTRAL, COBRADA TAMBÉM NO BANCO: só `RESOLVED` produz
    -- referência canônica. `RESOLVED` sem entidade afirmaria ter resolvido
    -- sem dizer para quê; qualquer outro estado COM entidade produziria uma
    -- referência que alguém usaria por engano.
    CONSTRAINT decisions_referencia_so_em_resolved CHECK (
        (status = 'RESOLVED') = (canonical_entity_id IS NOT NULL)
    ),
    -- Decisão humana sem motivo é o registro que não explica nada depois.
    CONSTRAINT decisions_manual_tem_motivo CHECK (
        method <> 'MANUAL_REVIEW' OR length(btrim(coalesce(reason, ''))) > 0
    ),
    CONSTRAINT decisions_ator_coerente CHECK (
        (method = 'MANUAL_REVIEW') = (decided_by_kind IN ('HUMAN_OPERATOR', 'CLI'))
    )
);

CREATE INDEX decisions_run_idx ON resolution_decisions (run_id, subject_type);
CREATE INDEX decisions_status_idx ON resolution_decisions (run_id, status);
-- A CONSULTA QUE A FUSÃO FAZ: as resolvidas de uma execução, por sujeito.
-- Índice PARCIAL porque ela só olha `RESOLVED`, e um índice sobre a tabela
-- toda pagaria por linhas que essa consulta nunca lê.
CREATE INDEX decisions_resolvidas_idx
    ON resolution_decisions (run_id, subject_type, record_ref)
    WHERE status = 'RESOLVED';
CREATE INDEX decisions_entidade_idx
    ON resolution_decisions (subject_type, canonical_entity_id)
    WHERE canonical_entity_id IS NOT NULL;

CREATE TABLE resolution_evidence (
    id              bigserial PRIMARY KEY,
    decision_id     uuid NOT NULL REFERENCES resolution_decisions (id) ON DELETE CASCADE,
    ordinal         integer NOT NULL,
    kind            text NOT NULL,
    outcome         text NOT NULL,
    explanation     text NOT NULL,
    -- O PESO É GRAVADO COM A EVIDÊNCIA porque a política muda: sem ele,
    -- reler uma decisão antiga aplicaria os pesos de hoje ao raciocínio de
    -- ontem.
    weight          double precision NOT NULL,
    source_value    text,
    canonical_value text,

    CONSTRAINT evidence_outcome CHECK (outcome IN ('MATCHED', 'MISMATCHED', 'UNAVAILABLE')),
    CONSTRAINT evidence_peso CHECK (weight >= 0 AND weight <= 1),
    CONSTRAINT evidence_ordem_unica UNIQUE (decision_id, ordinal)
);

CREATE INDEX evidence_decisao_idx ON resolution_evidence (decision_id, ordinal);
-- «Quantas resoluções de jogador dependeram de data de nascimento?» — a
-- pergunta que um campo de texto livre não responderia.
CREATE INDEX evidence_kind_idx ON resolution_evidence (kind, outcome);

CREATE TABLE resolution_alternatives (
    id                  bigserial PRIMARY KEY,
    decision_id         uuid NOT NULL REFERENCES resolution_decisions (id) ON DELETE CASCADE,
    ordinal             integer NOT NULL,
    canonical_entity_id uuid NOT NULL,
    score               double precision NOT NULL,
    evidence_summary    text NOT NULL,
    label               text,

    CONSTRAINT alternatives_score CHECK (score >= 0 AND score <= 1),
    CONSTRAINT alternatives_ordem_unica UNIQUE (decision_id, ordinal)
);

CREATE INDEX alternatives_decisao_idx ON resolution_alternatives (decision_id, ordinal);

-- ================================================== fila de revisão =======

CREATE TABLE resolution_review_items (
    id                      uuid PRIMARY KEY,
    run_id                  uuid NOT NULL REFERENCES resolution_runs (id) ON DELETE CASCADE,
    subject_type            text NOT NULL,
    provider_id             text NOT NULL,
    source_raw              text NOT NULL,
    source_normalized       text NOT NULL,
    normalizer_major        integer NOT NULL,
    normalizer_minor        integer NOT NULL,
    record_ref              text NOT NULL,
    context                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    reason_status           text NOT NULL,
    candidates              jsonb NOT NULL DEFAULT '[]'::jsonb,
    status                  text NOT NULL,
    assigned_to             text,
    assigned_to_kind        text,
    resolved_at             timestamptz,
    resolved_by             text,
    resolved_by_kind        text,
    resolution_decision_id  uuid,
    decision_reason         text,
    created_at              timestamptz NOT NULL,

    CONSTRAINT review_status CHECK (status IN ('OPEN', 'IN_REVIEW', 'RESOLVED', 'REJECTED')),
    CONSTRAINT review_motivo_do_status CHECK (
        reason_status IN ('AMBIGUOUS', 'REVIEW_REQUIRED')
    ),
    -- Um item fechado sem quem decidiu e por quê é o registro que responde
    -- «quando» e não responde «quem» nem «por quê».
    CONSTRAINT review_fechado_tem_autor CHECK (
        status IN ('OPEN', 'IN_REVIEW')
        OR (resolved_at IS NOT NULL AND resolved_by IS NOT NULL
            AND length(btrim(coalesce(decision_reason, ''))) > 0)
    ),
    -- A fila é HUMANA. Um ator de serviço fechando item é o automático
    -- fingindo ter resolvido o que ele próprio não conseguiu.
    CONSTRAINT review_fechado_por_humano CHECK (
        resolved_by_kind IS NULL OR resolved_by_kind IN ('HUMAN_OPERATOR', 'CLI')
    ),
    CONSTRAINT review_resolvido_tem_decisao CHECK (
        status <> 'RESOLVED' OR resolution_decision_id IS NOT NULL
    )
);

-- IDEMPOTÊNCIA DA FILA (§93). Reexecutar uma resolução que falhou no meio
-- duplicaria itens, e um operador decidiria duas vezes a mesma coisa.
CREATE UNIQUE INDEX review_item_unico
    ON resolution_review_items (run_id, record_ref, subject_type);

-- A consulta do operador: o que está aberto, mais antigo primeiro. PARCIAL,
-- porque a fila fechada não é lida no dia a dia e cresce indefinidamente.
CREATE INDEX review_abertos_idx
    ON resolution_review_items (subject_type, created_at)
    WHERE status IN ('OPEN', 'IN_REVIEW');
CREATE INDEX review_run_idx ON resolution_review_items (run_id, status);

-- =================================================== execuções de fusão ===

CREATE TABLE fusion_runs (
    id                      uuid PRIMARY KEY,
    policy_major            integer NOT NULL,
    policy_minor            integer NOT NULL,
    status                  text NOT NULL,
    groups                  integer NOT NULL DEFAULT 0,
    multi_source_groups     integer NOT NULL DEFAULT 0,
    fields_selected         integer NOT NULL DEFAULT 0,
    conflicts               integer NOT NULL DEFAULT 0,
    unresolved_conflicts    integer NOT NULL DEFAULT 0,
    observation_sets        integer NOT NULL DEFAULT 0,
    output_fingerprint      text,
    started_at              timestamptz NOT NULL,
    completed_at            timestamptz,
    triggered_by            text NOT NULL,
    triggered_by_kind       text NOT NULL,
    failure_reason          text,

    CONSTRAINT fusion_runs_status CHECK (
        status IN ('PENDING', 'RUNNING', 'COMPLETED', 'COMPLETED_WITH_REVIEW', 'FAILED', 'CANCELLED')
    ),
    CONSTRAINT fusion_runs_conflitos CHECK (unresolved_conflicts <= conflicts),
    CONSTRAINT fusion_runs_grupos CHECK (multi_source_groups <= groups),
    CONSTRAINT fusion_runs_ordem CHECK (completed_at IS NULL OR completed_at >= started_at),
    CONSTRAINT fusion_runs_fingerprint CHECK (
        output_fingerprint IS NULL OR output_fingerprint ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX fusion_runs_status_idx ON fusion_runs (status, started_at DESC);

-- A LIGAÇÃO ENTRE AS DUAS EXECUÇÕES, e é ela que fecha a linhagem em ambas
-- as direções (§77): do candidato fundido até o raw, e do raw até tudo que
-- foi produzido a partir dele.
CREATE TABLE fusion_run_inputs (
    fusion_run_id       uuid NOT NULL REFERENCES fusion_runs (id) ON DELETE CASCADE,
    resolution_run_id   uuid NOT NULL REFERENCES resolution_runs (id) ON DELETE CASCADE,
    PRIMARY KEY (fusion_run_id, resolution_run_id)
);

CREATE INDEX fusion_inputs_resolucao_idx ON fusion_run_inputs (resolution_run_id);

CREATE TABLE fusion_groups (
    id                  uuid PRIMARY KEY,
    fusion_run_id       uuid NOT NULL REFERENCES fusion_runs (id) ON DELETE CASCADE,
    canonical_match_id  uuid NOT NULL,
    record_count        integer NOT NULL,
    providers           text[] NOT NULL,

    CONSTRAINT fusion_groups_registros CHECK (record_count >= 1)
);

-- UM GRUPO POR PARTIDA POR EXECUÇÃO. Dois grupos para a mesma partida na
-- mesma execução produziriam dois candidatos concorrentes, e ninguém saberia
-- qual é o certo.
CREATE UNIQUE INDEX fusion_groups_unico
    ON fusion_groups (fusion_run_id, canonical_match_id);

CREATE TABLE fusion_group_records (
    id                      bigserial PRIMARY KEY,
    group_id                uuid NOT NULL REFERENCES fusion_groups (id) ON DELETE CASCADE,
    record_ref              text NOT NULL,
    provider_id             text NOT NULL,
    source_type             text NOT NULL,
    license_class           text NOT NULL,
    -- A DECISÃO QUE PROVOU A IDENTIDADE. Obrigatória: a fusão só aceita
    -- identidade provada, e sem esta coluna a garantia viveria só no tipo
    -- Python (ADR-0022).
    resolution_decision_id  uuid NOT NULL,

    CONSTRAINT fusion_records_provedor_unico UNIQUE (group_id, provider_id)
);

CREATE INDEX fusion_records_grupo_idx ON fusion_group_records (group_id);
CREATE INDEX fusion_records_decisao_idx ON fusion_group_records (resolution_decision_id);

CREATE TABLE fused_candidates (
    id                  uuid PRIMARY KEY,
    fusion_run_id       uuid NOT NULL REFERENCES fusion_runs (id) ON DELETE CASCADE,
    group_id            uuid NOT NULL REFERENCES fusion_groups (id) ON DELETE CASCADE,
    canonical_match_id  uuid NOT NULL,
    schema_version      text NOT NULL,
    fingerprint         text NOT NULL,
    -- A saída inteira, na forma canônica. `jsonb` porque ela é lida por
    -- completo ou não é lida; consultar campo a campo é o que as tabelas
    -- abaixo servem.
    body                jsonb NOT NULL,
    most_restrictive_license text NOT NULL,

    CONSTRAINT fused_fingerprint CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT fused_unico UNIQUE (fusion_run_id, canonical_match_id)
);

CREATE INDEX fused_run_idx ON fused_candidates (fusion_run_id);
CREATE INDEX fused_match_idx ON fused_candidates (canonical_match_id);

CREATE TABLE fused_fields (
    id                  bigserial PRIMARY KEY,
    candidate_id        uuid NOT NULL REFERENCES fused_candidates (id) ON DELETE CASCADE,
    field_name          text NOT NULL,
    rule                text NOT NULL,
    selected_value      text,
    selected_from       text,
    confidence          double precision NOT NULL DEFAULT 0,
    contribution_count  integer NOT NULL,

    CONSTRAINT fused_fields_rule CHECK (
        rule IN ('EXACT_AGREEMENT', 'PREFERRED_SOURCE', 'HIGHEST_QUALITY',
                 'MOST_COMPLETE', 'MOST_PRECISE', 'MANUAL_SELECTION', 'CONFLICT_UNRESOLVED')
    ),
    -- CONFLITO NÃO RESOLVIDO NÃO TEM VALOR ESCOLHIDO, e a ausência é a
    -- informação: um valor aqui seria lido como se tivesse sido decidido.
    CONSTRAINT fused_fields_conflito_sem_valor CHECK (
        (rule = 'CONFLICT_UNRESOLVED') = (selected_value IS NULL)
    ),
    CONSTRAINT fused_fields_unico UNIQUE (candidate_id, field_name)
);

CREATE INDEX fused_fields_candidato_idx ON fused_fields (candidate_id);
-- A consulta do operador de conflitos. PARCIAL pelo mesmo motivo de sempre.
CREATE INDEX fused_fields_conflitos_idx
    ON fused_fields (candidate_id, field_name)
    WHERE rule = 'CONFLICT_UNRESOLVED';

-- A PROCEDÊNCIA POR CAMPO (§55). É esta tabela que responde «de onde veio
-- este valor» com dataset, arquivo e linha — e que preserva o que a outra
-- fonte disse.
CREATE TABLE fused_field_sources (
    id              bigserial PRIMARY KEY,
    field_id        bigint NOT NULL REFERENCES fused_fields (id) ON DELETE CASCADE,
    provider_id     text NOT NULL,
    record_ref      text NOT NULL,
    value           text NOT NULL,
    license_class   text NOT NULL,
    was_selected    boolean NOT NULL DEFAULT false,

    CONSTRAINT fused_sources_unico UNIQUE (field_id, provider_id)
);

CREATE INDEX fused_sources_campo_idx ON fused_field_sources (field_id);
CREATE INDEX fused_sources_registro_idx ON fused_field_sources (record_ref);

-- ===================================== seed: aliases do catálogo fechado ==
--
-- O CATÁLOGO DE COMPETIÇÕES É FECHADO E CONHECIDO (PR-01), então os nomes
-- pelos quais as cinco são chamadas também são. Semeá-los é a diferença entre
-- `EPL` resolver na primeira execução e `EPL` cair na fila de revisão para
-- alguém decidir o óbvio.
--
-- O SEED NÃO ESTÁ AQUI, e o motivo é honesto: os `CompetitionId` são
-- derivados por `uuid5` sobre um namespace que vive no Python. Escrevê-los
-- como literais em SQL criaria duas fontes de verdade que divergem no dia em
-- que o namespace mudar — e a divergência seria silenciosa, com o alias
-- apontando para um id que não é de competição nenhuma.
--
-- `seed_competition_aliases()` (adapters/postgres/resolution.py) roda depois
-- das migrations, deriva os ids da MESMA função que o resto do motor usa, e é
-- idempotente. Um teste de integração confere que o que ela grava bate com o
-- que `entry_for(code).id` produz.
