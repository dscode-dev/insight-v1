-- 0009 — Eventos canônicos históricos (PR-04.4.1)
--
-- A TABELA QUE FALTAVA. `CanonicalMatchEvent` existe no domínio desde o PR-01,
-- com taxonomia, detalhes tipados, coordenadas e semântica de revisão. O que
-- nunca existiu foi onde gravá-lo: nenhuma migration criou tabela de evento, e
-- `CanonicalEventRepositoryPort` era um port sem adapter.
--
-- Por isso a análise do PR-04.3.1 classificou a capacidade como
-- `NOT_IMPLEMENTED` e não como `NOT_DECLARED`: não era o dado que faltava, era
-- o caminho.
--
-- QUATRO DECISÕES DE MODELAGEM, e cada uma tem um custo do outro lado:
--
-- 1. O RELÓGIO É `(period, minute, stoppage)` E NÃO UM INTEIRO. `45+3` achatado
--    para `48` confunde o terceiro minuto de acréscimo do primeiro tempo com o
--    terceiro minuto do segundo — momentos táticos opostos. Uma coluna a mais
--    contra uma ambiguidade que nenhuma consulta desfaz depois.
--
-- 2. OS DETALHES SÃO `jsonb` VALIDADO PELO DOMÍNIO, e não trinta colunas
--    esparsas. A taxonomia tem vinte e sete tipos com detalhes heterogêneos:
--    uma coluna por campo de cada detalhe daria uma tabela em que noventa por
--    cento das colunas é `NULL` em qualquer linha. O que impede o `jsonb` de
--    virar depósito é que NADA o escreve direto — ele é serializado a partir
--    de `ShotDetail`, `CardDetail`, `SubstitutionDetail`, que são contratos
--    tipados, e a constraint abaixo exige que a chave `kind` esteja lá.
--
-- 3. A REVISÃO É UMA LINHA NOVA, e o predecessor permanece. Não há `UPDATE`
--    que mude fato: o único que existe muda `status`, que é metadado sobre a
--    linha e não conteúdo dela.
--
-- 4. A IDENTIDADE É O `uuid5` DERIVADO. Reprocessar a mesma fonte reencontra o
--    mesmo evento em vez de criar outro — e é a chave primária que faz isso
--    valer, não a boa vontade de quem escreve.

-- ====================================== execuções de canonicalização ==
--
-- ELA VEM PRIMEIRO porque `canonical_match_events.created_by_build_run` aponta
-- para cá: uma migration é aplicada de cima para baixo, e uma chave estrangeira
-- para uma tabela que ainda não existe falha na criação.

CREATE TABLE canonical_event_build_runs (
    id                      uuid PRIMARY KEY,
    dataset_id              uuid NOT NULL REFERENCES datasets (id),
    quality_run_id          uuid REFERENCES quality_runs (id),
    provider_id             text NOT NULL,
    scope                   text NOT NULL,
    policy_version          integer NOT NULL,
    type_mapping_version    integer NOT NULL,

    status                  text NOT NULL,
    started_at              timestamptz NOT NULL,
    completed_at            timestamptz,
    failure_reason          text,

    records_read            integer NOT NULL DEFAULT 0,
    events_built            integer NOT NULL DEFAULT 0,
    events_reused           integer NOT NULL DEFAULT 0,
    events_skipped          integer NOT NULL DEFAULT 0,
    events_review_required  integer NOT NULL DEFAULT 0,
    events_failed           integer NOT NULL DEFAULT 0,

    triggered_by            text NOT NULL,
    triggered_by_kind       text NOT NULL,

    CONSTRAINT cebr_escopo CHECK (scope IN ('RESEARCH', 'COMMERCIAL')),
    CONSTRAINT cebr_status CHECK (
        status IN ('PENDING', 'RUNNING', 'COMPLETED', 'COMPLETED_WITH_REVIEW',
                   'FAILED', 'CANCELLED')
    ),
    CONSTRAINT cebr_terminal_tem_fim CHECK (
        status IN ('PENDING', 'RUNNING') OR completed_at IS NOT NULL
    ),
    CONSTRAINT cebr_falha_tem_motivo CHECK (
        status <> 'FAILED' OR length(btrim(coalesce(failure_reason, ''))) > 0
    ),
    -- AS CONTAGENS FECHAM. A diferença silenciosa entre elas é onde um lote
    -- perdido se esconde, e o banco é o último lugar que ainda pode pegar.
    CONSTRAINT cebr_contagens_fecham CHECK (
        events_built + events_reused + events_skipped + events_review_required
        + events_failed = records_read
    ),
    CONSTRAINT cebr_ator CHECK (length(btrim(triggered_by)) > 0)
);

CREATE INDEX cebr_dataset_idx ON canonical_event_build_runs (dataset_id, started_at DESC);

-- ================================================== eventos canônicos ==

CREATE TABLE canonical_match_events (
    -- DERIVADO por uuid5 de (partida, chave da fonte, revisão). Não é
    -- `gen_random_uuid()`: a segunda leitura do mesmo arquivo precisa
    -- reencontrar o evento, e um id aleatório duplicaria o corpus.
    id                      uuid PRIMARY KEY,
    match_id                uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    event_type              text NOT NULL,

    -- ---- o relógio, por extenso.
    period                  text NOT NULL,
    minute                  integer NOT NULL,
    stoppage                integer NOT NULL DEFAULT 0,
    -- A ordem DENTRO do período. Ela existe porque o relógio empata: dois
    -- eventos aos 34 minutos precisam de ordem, e a do arquivo não serve —
    -- um CSV reordenado produziria outra sequência para os mesmos fatos.
    sequence                integer NOT NULL,

    -- ---- quem. NULO É LEGÍTIMO e é o domínio que decide: o apito final não
    -- é de ninguém, e exigir dono obrigaria a inventar um.
    team_id                 uuid REFERENCES teams (id),
    player_id               uuid REFERENCES players (id),

    -- ---- onde. NULO É AUSENTE, e nunca (0,0): a origem do campo é uma
    -- posição real — linha de fundo, na lateral —, e usá-la como «sem
    -- coordenada» juntaria todo evento sem dado espacial no mesmo canto.
    start_x                 double precision,
    start_y                 double precision,
    end_x                   double precision,
    end_y                   double precision,
    coordinate_frame        text,

    -- ---- o detalhe tipado, serializado. `kind` diz qual contrato o produziu.
    detail                  jsonb,

    -- ---- revisão.
    revision                integer NOT NULL DEFAULT 1,
    supersedes_event_id     uuid REFERENCES canonical_match_events (id),
    status                  text NOT NULL DEFAULT 'ACTIVE',

    -- ---- procedência: por onde se volta ao byte bruto.
    provider_id             text NOT NULL,
    source_event_key        text NOT NULL,
    record_ref              text NOT NULL,
    license_class           text NOT NULL,
    raw_event_type          text NOT NULL,

    created_by_build_run    uuid NOT NULL REFERENCES canonical_event_build_runs (id),
    created_at              timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT cme_tipo CHECK (length(btrim(event_type)) > 0),
    CONSTRAINT cme_periodo CHECK (
        period IN ('PRE_MATCH', 'FIRST_HALF', 'HALF_TIME', 'SECOND_HALF',
                   'EXTRA_TIME_FIRST', 'EXTRA_TIME_BREAK', 'EXTRA_TIME_SECOND',
                   'PENALTY_SHOOTOUT', 'FULL_TIME')
    ),
    CONSTRAINT cme_relogio CHECK (minute >= 0 AND stoppage >= 0 AND sequence >= 0),
    CONSTRAINT cme_status CHECK (status IN ('ACTIVE', 'CORRECTED', 'CANCELLED')),
    CONSTRAINT cme_revisao CHECK (revision >= 1),
    -- UM EVENTO NÃO SUCEDE A SI MESMO (§63). Sem isto, uma cadeia de correção
    -- pode virar um laço, e percorrê-la não termina.
    CONSTRAINT cme_nao_sucede_a_si_mesmo CHECK (supersedes_event_id <> id),
    -- REVISÃO MAIOR QUE 1 SEM PREDECESSOR quebra a cadeia: «o que sabíamos
    -- antes» deixa de ter resposta.
    CONSTRAINT cme_revisao_tem_predecessor CHECK (
        revision = 1 OR supersedes_event_id IS NOT NULL
    ),
    -- COORDENADA É PAR OU NADA. Um `x` sem `y` é meio ponto, e meio ponto no
    -- campo não existe.
    CONSTRAINT cme_ponto_inicial CHECK (
        (start_x IS NULL) = (start_y IS NULL)
    ),
    CONSTRAINT cme_ponto_final CHECK ((end_x IS NULL) = (end_y IS NULL)),
    CONSTRAINT cme_coordenada_normalizada CHECK (
        (start_x IS NULL OR (start_x BETWEEN 0 AND 1 AND start_y BETWEEN 0 AND 1))
        AND (end_x IS NULL OR (end_x BETWEEN 0 AND 1 AND end_y BETWEEN 0 AND 1))
    ),
    -- COORDENADA SEM REFERENCIAL É NÚMERO SEM SIGNIFICADO (ADR-0012): uma
    -- fonte normaliza pelo sentido de ataque, outra pelo estádio, e os dois
    -- produzem `0.8` querendo dizer coisas opostas.
    CONSTRAINT cme_referencial_declarado CHECK (
        (start_x IS NULL AND end_x IS NULL) OR coordinate_frame IS NOT NULL
    ),
    CONSTRAINT cme_referencial CHECK (
        coordinate_frame IS NULL OR coordinate_frame IN ('ATTACKING', 'ABSOLUTE')
    ),
    -- O `jsonb` NÃO É DEPÓSITO: quando existe, ele diz qual contrato tipado o
    -- produziu, e é isso que permite desserializá-lo de volta ao tipo certo.
    CONSTRAINT cme_detalhe_tem_tipo CHECK (
        detail IS NULL OR detail ? 'kind'
    ),
    CONSTRAINT cme_licenca CHECK (
        license_class IN ('PUBLIC_DOMAIN', 'ATTRIBUTION_REQUIRED', 'RESEARCH_ONLY',
                          'COMMERCIAL_ALLOWED', 'UNKNOWN')
    ),
    CONSTRAINT cme_procedencia CHECK (
        length(btrim(source_event_key)) > 0 AND length(btrim(record_ref)) > 0
    )
);

-- A CONSULTA DO PR-05: os eventos de uma partida, em ordem determinística.
-- Ela é a razão de o índice ter esta forma exata — sem ele, cada leitura
-- ordena centenas de milhares de linhas.
CREATE INDEX cme_ordem_idx
    ON canonical_match_events (match_id, period, minute, stoppage, sequence, id);

CREATE INDEX cme_player_idx ON canonical_match_events (player_id)
    WHERE player_id IS NOT NULL;
CREATE INDEX cme_team_idx ON canonical_match_events (team_id)
    WHERE team_id IS NOT NULL;
CREATE INDEX cme_tipo_idx ON canonical_match_events (event_type, match_id);

-- A IDENTIDADE DO PROVEDOR. Ela não é UNIQUE de propósito: um evento corrigido
-- tem a MESMA chave de origem e revisão diferente, e um índice único aqui
-- impediria a correção de existir. O que garante a idempotência é a chave
-- primária derivada, que já inclui a revisão.
CREATE INDEX cme_origem_idx
    ON canonical_match_events (provider_id, source_event_key, revision);

-- A cadeia de correção, percorrida para trás.
CREATE INDEX cme_supersedes_idx ON canonical_match_events (supersedes_event_id)
    WHERE supersedes_event_id IS NOT NULL;

-- ============================================= linhagem por evento ==
--
-- ELA GRAVA O QUE NÃO ENTROU TAMBÉM, e é aí que está o valor: «por que este
-- evento não está no registro» só tem resposta se a recusa deixou linha. Sem
-- ela, «excluído por licença» e «nunca veio no arquivo» ficam idênticos.

CREATE TABLE canonical_event_build_records (
    id                      uuid PRIMARY KEY,
    build_run_id            uuid NOT NULL
                            REFERENCES canonical_event_build_runs (id) ON DELETE CASCADE,
    match_id                uuid NOT NULL,
    source_key              text NOT NULL,
    record_ref              text NOT NULL,
    status                  text NOT NULL,
    event_id                uuid,
    reason                  text,
    raw_event_type          text,
    detail                  text,
    created_at              timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT cebrec_status CHECK (
        status IN ('BUILT', 'REUSED', 'SKIPPED', 'REVIEW_REQUIRED', 'FAILED')
    ),
    -- QUEM AFIRMA TER MATERIALIZADO PRECISA DIZER O QUÊ. Sem isto a travessia
    -- de linhagem termina num beco no primeiro salto.
    CONSTRAINT cebrec_materializado_tem_fato CHECK (
        (status IN ('BUILT', 'REUSED')) = (event_id IS NOT NULL)
    ),
    CONSTRAINT cebrec_motivo CHECK (
        reason IS NULL OR reason IN ('MATCH_NOT_ELIGIBLE', 'IDENTITY_FAILURE',
                                     'UNMAPPED_TYPE', 'QUALITY_BLOCKER',
                                     'LICENSE_POLICY', 'IDENTITY_CONFLICT',
                                     'DANGLING_REVISION', 'INVALID_CLOCK')
    ),
    -- UM EVENTO QUE FICOU DE FORA PRECISA DIZER POR QUÊ.
    CONSTRAINT cebrec_exclusao_tem_motivo CHECK (
        status IN ('BUILT', 'REUSED') OR reason IS NOT NULL
    ),
    CONSTRAINT cebrec_unico UNIQUE (build_run_id, source_key)
);

CREATE INDEX cebrec_partida_idx ON canonical_event_build_records (match_id, created_at);
CREATE INDEX cebrec_execucao_idx ON canonical_event_build_records (build_run_id, status);
CREATE INDEX cebrec_evento_idx ON canonical_event_build_records (event_id)
    WHERE event_id IS NOT NULL;
