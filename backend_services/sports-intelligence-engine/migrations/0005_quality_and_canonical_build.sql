-- 0005 — Execução de qualidade e construção canônica (PR-04.2)
--
-- O QUE ESTA MIGRATION ACRESCENTA, e o que ela deliberadamente NÃO acrescenta.
--
-- Ela acrescenta as tabelas de EXECUÇÃO — avaliações, decisões de build,
-- linhagem por fato — e as três tabelas de FATO canônico que faltavam para as
-- famílias que este PR sabe construir: escalação e odds.
--
-- Ela NÃO recria `competitions`, `seasons`, `teams`, `players`, `matches` nem
-- `match_results`. Eles nasceram na 0003 e continuam sendo o registro canônico
-- (§60): um `canonical_matches_v2` ao lado faria a mesma partida existir em
-- dois lugares, e a segunda cópia divergiria no primeiro build.
--
-- TRÊS DECISÕES DE MODELAGEM QUE VALE EXPLICAR:
--
-- 1. AS DIMENSÕES DE QUALIDADE SÃO COLUNAS, e não um `jsonb` (§57). Elas são
--    seis, são estáveis desde o PR-04.1 e são consultadas — «quantas partidas
--    reprovaram por identidade» é a pergunta do relatório, e ela dentro de um
--    blob exige varredura com extração por linha.
--
-- 2. A COBERTURA É UMA TABELA-FILHA COM `expected_count` NULO (§58). Um
--    `NOT NULL DEFAULT 0` transformaria «não há denominador honesto» em «zero
--    esperados», e as duas afirmações são opostas: a primeira descreve a
--    fonte, a segunda descreve uma falha.
--
-- 3. A LICENÇA É POR FAMÍLIA (§59). Uma coluna `license_class` na avaliação
--    responderia «qual a licença desta partida», que é a pergunta errada — a
--    certa é «e se as odds saírem?», e ela só tem resposta com o mapa.
--
-- NADA AQUI TEM `UPDATE` NO CAMINHO NORMAL. As duas exceções são fechar uma
-- execução em curso, e as duas são condicionais ao estado anterior — como
-- toda transição desta base desde o PR-02.

-- ================================================ execuções de qualidade ==

CREATE TABLE quality_runs (
    id                      uuid PRIMARY KEY,
    policy_major            integer NOT NULL,
    policy_minor            integer NOT NULL,
    -- A IMPRESSÃO DA POLÍTICA INTEIRA, e não só o número da versão. Ela pega
    -- o caso em que alguém edita um limiar sem subir a versão — silencioso, e
    -- faz duas execuções rotuladas `1.0` decidirem diferente.
    policy_fingerprint      text NOT NULL,
    policy_snapshot         jsonb NOT NULL DEFAULT '{}'::jsonb,
    status                  text NOT NULL,
    started_at              timestamptz NOT NULL,
    completed_at            timestamptz,
    failure_reason          text,
    records_examined        integer NOT NULL DEFAULT 0,
    eligible_count          integer NOT NULL DEFAULT 0,
    review_required_count   integer NOT NULL DEFAULT 0,
    ineligible_count        integer NOT NULL DEFAULT 0,
    output_fingerprint      text,
    triggered_by            text NOT NULL,
    triggered_by_kind       text NOT NULL,

    CONSTRAINT quality_runs_status CHECK (
        status IN ('PENDING', 'RUNNING', 'COMPLETED', 'COMPLETED_WITH_REVIEW',
                   'FAILED', 'CANCELLED')
    ),
    -- Uma execução terminada sem instante de conclusão é uma que ninguém sabe
    -- quando acabou — e a duração é a primeira coisa que se olha num incidente.
    CONSTRAINT quality_runs_terminal_tem_fim CHECK (
        status IN ('PENDING', 'RUNNING') OR completed_at IS NOT NULL
    ),
    CONSTRAINT quality_runs_falha_tem_motivo CHECK (
        status <> 'FAILED' OR length(btrim(coalesce(failure_reason, ''))) > 0
    ),
    -- OS TRÊS SOMAM O EXAMINADO. A diferença silenciosa entre eles é onde um
    -- lote perdido se esconde, e o banco é o último lugar que ainda pode pegar.
    CONSTRAINT quality_runs_contagens_fecham CHECK (
        eligible_count + review_required_count + ineligible_count = records_examined
    ),
    CONSTRAINT quality_runs_ator CHECK (length(btrim(triggered_by)) > 0)
);

CREATE INDEX quality_runs_status_idx ON quality_runs (status, started_at DESC);

-- AS FUSÕES CONSUMIDAS, com a impressão da saída de cada uma (§8). Sem ela,
-- «esta avaliação rodou sobre a fusão X» é uma afirmação sobre uma fusão que
-- pode ter sido reexecutada desde então.
CREATE TABLE quality_run_inputs (
    quality_run_id              uuid NOT NULL REFERENCES quality_runs (id) ON DELETE CASCADE,
    fusion_run_id               uuid NOT NULL REFERENCES fusion_runs (id),
    fusion_output_fingerprint   text,

    PRIMARY KEY (quality_run_id, fusion_run_id)
);

CREATE INDEX quality_run_inputs_fusao_idx ON quality_run_inputs (fusion_run_id);

-- =========================================== avaliações por partida ==

CREATE TABLE match_quality_assessments (
    id                      uuid PRIMARY KEY,
    quality_run_id          uuid NOT NULL REFERENCES quality_runs (id) ON DELETE CASCADE,
    match_id                uuid NOT NULL,
    fusion_group_id         uuid NOT NULL,

    -- OS SEIS EIXOS, EM COLUNAS TIPADAS (§57). `double precision` e não
    -- `numeric`: são frações calculadas, comparadas contra pisos, e a precisão
    -- decimal exata não compra nada aqui — ao contrário das odds, onde compra.
    integrity               double precision NOT NULL,
    consistency             double precision NOT NULL,
    completeness            double precision NOT NULL,
    identity_confidence     double precision NOT NULL,
    temporal_integrity      double precision NOT NULL,
    provenance_quality      double precision NOT NULL,

    eligibility             text NOT NULL,
    reason                  text,

    -- A ELEGIBILIDADE DE USO FICA AO LADO DA TÉCNICA, em colunas próprias
    -- (§16, §30). Um registro pode ser tecnicamente elegível e comercialmente
    -- inelegível, e as duas afirmações são verdadeiras ao mesmo tempo.
    usage_research          text NOT NULL,
    usage_commercial        text NOT NULL,
    requires_attribution    boolean NOT NULL DEFAULT false,

    -- As famílias que a construção precisa saber e a qualidade não julga.
    families_in_conflict            text[] NOT NULL DEFAULT '{}',
    families_unresolved_identity    text[] NOT NULL DEFAULT '{}',

    created_at              timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT assessments_eixos_em_faixa CHECK (
        integrity BETWEEN 0 AND 1 AND consistency BETWEEN 0 AND 1
        AND completeness BETWEEN 0 AND 1 AND identity_confidence BETWEEN 0 AND 1
        AND temporal_integrity BETWEEN 0 AND 1 AND provenance_quality BETWEEN 0 AND 1
    ),
    CONSTRAINT assessments_elegibilidade CHECK (
        eligibility IN ('ELIGIBLE', 'REVIEW_REQUIRED', 'INELIGIBLE')
    ),
    CONSTRAINT assessments_uso CHECK (
        usage_research IN ('ELIGIBLE', 'REVIEW_REQUIRED', 'INELIGIBLE')
        AND usage_commercial IN ('ELIGIBLE', 'REVIEW_REQUIRED', 'INELIGIBLE')
    ),
    -- UMA AVALIAÇÃO POR PARTIDA POR EXECUÇÃO. Duas seriam dois vereditos sob
    -- a mesma política, e a construção escolheria por ordem de leitura.
    CONSTRAINT assessments_unica_por_execucao UNIQUE (quality_run_id, match_id)
);

-- A CONSULTA DA CONSTRUÇÃO: os elegíveis de uma execução, em ordem de partida.
-- A ordem entra na chave porque a varredura em lotes pagina por ela (§67) — um
-- índice sem `match_id` faria cada página ordenar de novo.
CREATE INDEX assessments_elegiveis_idx
    ON match_quality_assessments (quality_run_id, eligibility, match_id);
-- A CONSULTA DA LINHAGEM: todas as avaliações de uma partida, de todas as
-- execuções. É o §99 — reprocessar preserva as antigas, e elas se leem juntas.
CREATE INDEX assessments_partida_idx ON match_quality_assessments (match_id);
CREATE INDEX assessments_grupo_idx ON match_quality_assessments (fusion_group_id);

-- ------------------------------------------------------------- cobertura --
--
-- `expected_count` É NULO QUANDO NÃO HÁ DENOMINADOR HONESTO (§13, §58, §83).
-- A constraint abaixo é a que faz o `NOT_DECLARED` sobreviver ao banco como
-- distinto de `0%`: só `MEASURED` pode ter denominador, e só ela precisa dele.

CREATE TABLE quality_assessment_coverage (
    assessment_id       uuid NOT NULL REFERENCES match_quality_assessments (id) ON DELETE CASCADE,
    family              text NOT NULL,
    state               text NOT NULL,
    available_count     integer NOT NULL DEFAULT 0,
    expected_count      integer,

    PRIMARY KEY (assessment_id, family),
    CONSTRAINT coverage_familia CHECK (
        family IN ('MATCH', 'LINEUP', 'EVENT', 'PLAYER', 'ODDS', 'SPATIAL', 'TRACKING')
    ),
    CONSTRAINT coverage_estado CHECK (
        state IN ('MEASURED', 'AVAILABILITY_ONLY', 'NOT_DECLARED')
    ),
    CONSTRAINT coverage_nao_negativa CHECK (
        available_count >= 0 AND (expected_count IS NULL OR expected_count >= 0)
    ),
    -- «MEDIDO» SEM ESPERADO É DISPONIBILIDADE COM OUTRO NOME, e o nome errado
    -- faz o relatório afirmar mais do que sabe.
    CONSTRAINT coverage_medido_tem_denominador CHECK (
        state <> 'MEASURED' OR expected_count IS NOT NULL
    ),
    -- E o inverso: um denominador em `NOT_DECLARED` seria um zero disfarçado.
    CONSTRAINT coverage_nao_declarado_sem_denominador CHECK (
        state <> 'NOT_DECLARED' OR (expected_count IS NULL AND available_count = 0)
    ),
    CONSTRAINT coverage_nao_passa_de_cem CHECK (
        expected_count IS NULL OR available_count <= expected_count
    )
);

-- ---------------------------------------------------- licença por família --
--
-- POR FAMÍLIA E NÃO GLOBAL (§59). Com uma licença só por partida,
-- `RESEARCH_ONLY` em qualquer campo condenaria o registro inteiro; com o mapa,
-- a política de build consegue perguntar «e se as odds saírem?».

CREATE TABLE quality_assessment_licenses (
    assessment_id   uuid NOT NULL REFERENCES match_quality_assessments (id) ON DELETE CASCADE,
    family          text NOT NULL,
    license_class   text NOT NULL,

    PRIMARY KEY (assessment_id, family, license_class),
    CONSTRAINT licenses_familia CHECK (
        family IN ('MATCH', 'LINEUP', 'EVENT', 'PLAYER', 'ODDS', 'SPATIAL', 'TRACKING')
    ),
    CONSTRAINT licenses_classe CHECK (
        license_class IN ('PUBLIC_DOMAIN', 'ATTRIBUTION_REQUIRED', 'RESEARCH_ONLY',
                          'COMMERCIAL_ALLOWED', 'UNKNOWN')
    )
);

-- --------------------------------------------------- identidade por tipo --
--
-- POR TIPO E NUNCA UMA MÉDIA (§13). Uma competição em 1,0 e um jogador em 0,4
-- dão média 0,7, que passa em quase qualquer piso — e o jogador errado é o que
-- contamina o futuro.

CREATE TABLE quality_assessment_identity (
    assessment_id   uuid NOT NULL REFERENCES match_quality_assessments (id) ON DELETE CASCADE,
    subject_type    text NOT NULL,
    confidence      double precision NOT NULL,

    PRIMARY KEY (assessment_id, subject_type),
    CONSTRAINT identity_sujeito CHECK (
        subject_type IN ('COMPETITION', 'SEASON', 'TEAM', 'PLAYER', 'MATCH')
    ),
    CONSTRAINT identity_confianca CHECK (confidence BETWEEN 0 AND 1)
);

-- ------------------------------------------------------------- problemas --
--
-- O CÓDIGO É DO CATÁLOGO FECHADO DO PR-04.1, e a constraint o repete aqui: um
-- código novo inserido por um script ganharia severidade sem nunca ter passado
-- por decisão nenhuma (§12).
--
-- A SEVERIDADE É GRAVADA JUNTO e vem da POLÍTICA, não do código. Ela é
-- redundante com `policy_snapshot` de propósito: sem ela, ler «quantos
-- bloqueantes esta execução encontrou» exigiria reaplicar a política de seis
-- meses atrás sobre cada linha.

CREATE TABLE quality_assessment_issues (
    id              bigserial PRIMARY KEY,
    assessment_id   uuid NOT NULL REFERENCES match_quality_assessments (id) ON DELETE CASCADE,
    issue_code      text NOT NULL,
    severity        text NOT NULL,
    dimension       text,
    family          text,
    subject         text NOT NULL,
    context         jsonb NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT issues_codigo CHECK (
        issue_code IN (
            'MISSING_REQUIRED_IDENTITY', 'DANGLING_CANONICAL_REFERENCE',
            'BROKEN_LINEAGE', 'MANIFEST_FINGERPRINT_MISMATCH',
            'SAME_TEAM_BOTH_SIDES', 'INVALID_SEASON_REFERENCE',
            'COMPETITION_SEASON_MISMATCH', 'NEGATIVE_OBSERVED_VALUE',
            'LINEUP_TEAM_MISMATCH', 'INCOMPLETE_CORE_MATCH', 'MISSING_RESULT',
            'LOW_IDENTITY_CONFIDENCE', 'UNRESOLVED_IDENTITY',
            'TEMPORAL_INCONSISTENCY', 'KICKOFF_OUTSIDE_SEASON_WINDOW',
            'EVENT_OUT_OF_ORDER', 'TENURE_NOT_VALID_AT_DATE',
            'UNRESOLVED_FUSION_CONFLICT', 'LICENSE_RESTRICTED', 'LICENSE_UNKNOWN'
        )
    ),
    CONSTRAINT issues_severidade CHECK (
        severity IN ('INFO', 'WARNING', 'ERROR', 'BLOCKING')
    ),
    CONSTRAINT issues_dimensao CHECK (
        dimension IS NULL OR dimension IN (
            'INTEGRITY', 'CONSISTENCY', 'COMPLETENESS', 'IDENTITY_CONFIDENCE',
            'TEMPORAL_INTEGRITY', 'PROVENANCE_QUALITY'
        )
    ),
    CONSTRAINT issues_sujeito CHECK (length(btrim(subject)) > 0),
    -- O MESMO CÓDIGO SOBRE O MESMO SUJEITO É O MESMO PROBLEMA. A chave existe
    -- para que reexecutar um lote que falhou no meio não duplique a lista —
    -- e uma contagem de problemas duplicada é um relatório que exagera o
    -- estrago, que custa a mesma confiança que um que o esconde.
    CONSTRAINT issues_unico UNIQUE (assessment_id, issue_code, subject)
);

-- A CONSULTA DO RELATÓRIO: quantos de cada código nesta execução.
CREATE INDEX issues_avaliacao_idx ON quality_assessment_issues (assessment_id);
CREATE INDEX issues_codigo_idx ON quality_assessment_issues (issue_code, severity);

-- ============================================== execuções de construção ==

CREATE TABLE canonical_build_runs (
    id                      uuid PRIMARY KEY,
    quality_run_id          uuid NOT NULL REFERENCES quality_runs (id),
    build_policy_major      integer NOT NULL,
    build_policy_minor      integer NOT NULL,
    -- A MESMA AVALIAÇÃO SOB DUAS POLÍTICAS PRODUZ CORPUS DIFERENTES (§18).
    -- O escopo em coluna própria é o que torna «me dê o build comercial desta
    -- avaliação» uma consulta em vez de uma leitura de `jsonb`.
    scope                   text NOT NULL,
    build_policy_snapshot   jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- A versão da política de QUALIDADE sob a qual a avaliação rodou (§21).
    -- Um build é explicável por DUAS políticas, e buscar a segunda em outra
    -- tabela faz alguém não buscar.
    quality_policy_major    integer NOT NULL,
    quality_policy_minor    integer NOT NULL,

    status                  text NOT NULL,
    started_at              timestamptz NOT NULL,
    completed_at            timestamptz,
    failure_reason          text,

    records_attempted       integer NOT NULL DEFAULT 0,
    records_built           integer NOT NULL DEFAULT 0,
    records_reused          integer NOT NULL DEFAULT 0,
    records_skipped         integer NOT NULL DEFAULT 0,
    records_review_required integer NOT NULL DEFAULT 0,
    records_failed          integer NOT NULL DEFAULT 0,
    families_excluded       integer NOT NULL DEFAULT 0,

    output_fingerprint      text,
    triggered_by            text NOT NULL,
    triggered_by_kind       text NOT NULL,

    CONSTRAINT build_runs_escopo CHECK (scope IN ('RESEARCH', 'COMMERCIAL')),
    CONSTRAINT build_runs_status CHECK (
        status IN ('PENDING', 'RUNNING', 'COMPLETED', 'COMPLETED_WITH_REVIEW',
                   'FAILED', 'CANCELLED')
    ),
    CONSTRAINT build_runs_terminal_tem_fim CHECK (
        status IN ('PENDING', 'RUNNING') OR completed_at IS NOT NULL
    ),
    CONSTRAINT build_runs_falha_tem_motivo CHECK (
        status <> 'FAILED' OR length(btrim(coalesce(failure_reason, ''))) > 0
    ),
    CONSTRAINT build_runs_contagens_fecham CHECK (
        records_built + records_reused + records_skipped + records_review_required
        + records_failed = records_attempted
    ),
    -- UMA EXECUÇÃO COM FATOS FALHADOS NÃO PODE SE DECLARAR CONCLUÍDA (§66).
    -- É a constraint que impede a mentira mais cara deste PR: um corpus que
    -- perdeu partidas e informa sucesso para quem decide publicar.
    CONSTRAINT build_runs_falha_nao_conclui CHECK (
        records_failed = 0 OR status NOT IN ('COMPLETED', 'COMPLETED_WITH_REVIEW')
    ),
    CONSTRAINT build_runs_ator CHECK (length(btrim(triggered_by)) > 0)
);

CREATE INDEX build_runs_qualidade_idx
    ON canonical_build_runs (quality_run_id, started_at DESC);
CREATE INDEX build_runs_status_idx ON canonical_build_runs (status, started_at DESC);

CREATE TABLE canonical_build_run_inputs (
    build_run_id    uuid NOT NULL REFERENCES canonical_build_runs (id) ON DELETE CASCADE,
    fusion_run_id   uuid NOT NULL REFERENCES fusion_runs (id),

    PRIMARY KEY (build_run_id, fusion_run_id)
);

-- ------------------------------------------------------ linhagem por fato --
--
-- ESTA TABELA É A RESPOSTA DO §50. «Por que este Match entrou no corpus?» sai
-- de uma junção: registro → avaliação → grupo de fusão → `record_ref` → arquivo
-- → SHA-256 do objeto bruto.
--
-- A CHAVE INCLUI `fact_type` (§61). O mesmo build produz `Match` e
-- `MatchResult` da mesma partida, e eles são fatos DIFERENTES — uma chave só
-- por partida faria o segundo sobrescrever o primeiro.

CREATE TABLE canonical_build_records (
    id                      uuid PRIMARY KEY,
    build_run_id            uuid NOT NULL REFERENCES canonical_build_runs (id) ON DELETE CASCADE,
    match_id                uuid NOT NULL,
    fact_type               text NOT NULL,
    fact_id                 text,
    source_fusion_group_id  uuid NOT NULL,
    quality_assessment_id   uuid NOT NULL REFERENCES match_quality_assessments (id),
    status                  text NOT NULL,
    included_families       text[] NOT NULL DEFAULT '{}',
    excluded_families       text[] NOT NULL DEFAULT '{}',
    reason                  text,
    created_at              timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT build_records_tipo CHECK (
        fact_type IN ('MATCH', 'MATCH_RESULT', 'LINEUP', 'MATCH_EVENT',
                      'ODDS_OBSERVATION')
    ),
    CONSTRAINT build_records_status CHECK (
        status IN ('BUILT', 'REUSED', 'SKIPPED', 'REVIEW_REQUIRED', 'FAILED')
    ),
    -- UM REGISTRO QUE AFIRMA TER MATERIALIZADO PRECISA DIZER O QUÊ. Sem isto,
    -- a travessia de linhagem termina num beco no primeiro salto.
    CONSTRAINT build_records_materializado_tem_fato CHECK (
        (status IN ('BUILT', 'REUSED')) = (fact_id IS NOT NULL)
    ),
    CONSTRAINT build_records_falha_tem_motivo CHECK (
        status <> 'FAILED' OR length(btrim(coalesce(reason, ''))) > 0
    ),
    CONSTRAINT build_records_unico UNIQUE (build_run_id, match_id, fact_type)
);

-- A CONSULTA DO §97: toda a linhagem de uma partida, de TODAS as execuções.
-- Um `Match` canônico com dois builds tem duas linhas aqui, e é assim que
-- «uma partida, duas linhagens» se lê.
CREATE INDEX build_records_partida_idx ON canonical_build_records (match_id, created_at);
CREATE INDEX build_records_execucao_idx
    ON canonical_build_records (build_run_id, status);
CREATE INDEX build_records_avaliacao_idx
    ON canonical_build_records (quality_assessment_id);

-- ------------------------------------------------- exclusão por família ---
--
-- EXCLUSÃO NÃO É DESAPARECIMENTO (§20). Uma família descartada por licença
-- precisa deixar rastro com o motivo E a licença — sem isso, «a fonte não
-- trouxe odds» e «tínhamos odds e não podíamos publicá-las» ficam iguais, e as
-- duas exigem ações opostas.

CREATE TABLE canonical_build_family_decisions (
    build_run_id    uuid NOT NULL REFERENCES canonical_build_runs (id) ON DELETE CASCADE,
    match_id        uuid NOT NULL,
    family          text NOT NULL,
    outcome         text NOT NULL,
    reason          text,
    license_class   text,

    PRIMARY KEY (build_run_id, match_id, family),
    CONSTRAINT family_decisions_familia CHECK (
        family IN ('MATCH', 'LINEUP', 'EVENT', 'PLAYER', 'ODDS', 'SPATIAL', 'TRACKING')
    ),
    CONSTRAINT family_decisions_desfecho CHECK (
        outcome IN ('INCLUDED', 'EXCLUDED', 'REVIEW_REQUIRED')
    ),
    CONSTRAINT family_decisions_motivo CHECK (
        reason IS NULL OR reason IN (
            'LICENSE_POLICY', 'NOT_AVAILABLE', 'OUT_OF_BUILD_SCOPE',
            'UNRESOLVED_IDENTITY', 'UNRESOLVED_CONFLICT', 'ASSESSMENT_REVIEW',
            'ASSESSMENT_INELIGIBLE', 'MATCH_NOT_BUILT'
        )
    ),
    -- INCLUÍDA NÃO TEM MOTIVO; EXCLUÍDA TEM. Um motivo numa família incluída
    -- seria lido como se ela tivesse ficado de fora.
    CONSTRAINT family_decisions_motivo_coerente CHECK (
        (outcome = 'INCLUDED') = (reason IS NULL)
    ),
    -- E a exclusão por licença sempre diz QUAL licença: é a pergunta que uma
    -- auditoria jurídica de fato faz.
    CONSTRAINT family_decisions_licenca_coerente CHECK (
        (reason = 'LICENSE_POLICY') = (license_class IS NOT NULL)
    )
);

-- A CONSULTA DO §103: «o que este build comercial descartou por licença».
CREATE INDEX family_decisions_licenca_idx
    ON canonical_build_family_decisions (build_run_id, reason)
    WHERE reason = 'LICENSE_POLICY';

-- ======================================= fatos canônicos que faltavam ==
--
-- `matches` E `match_results` JÁ EXISTEM na 0003 e não são recriados (§60).
-- O que falta são as duas famílias que este PR sabe construir e que nunca
-- tiveram tabela: escalação e odds.
--
-- `MATCH_EVENT` CONTINUA SEM TABELA, e é declarado: nenhum papel semântico
-- carrega evento, então não há construtor — e uma tabela vazia esperando um
-- construtor que não existe seria dívida com aparência de cobertura (§92).

CREATE TABLE lineups (
    match_id        uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    team_id         uuid NOT NULL REFERENCES teams (id),
    formation       text,
    recorded_at     timestamptz NOT NULL DEFAULT now(),

    -- UMA ESCALAÇÃO POR TIME POR PARTIDA. Duas seriam duas configurações
    -- iniciais do mesmo time no mesmo jogo, o que não existe.
    PRIMARY KEY (match_id, team_id),
    CONSTRAINT lineups_formacao CHECK (
        formation IS NULL OR formation ~ '^[0-9](-[0-9]){1,4}$'
    )
);

CREATE TABLE lineup_entries (
    match_id        uuid NOT NULL,
    team_id         uuid NOT NULL,
    -- `PlayerId` CANÔNICO, com chave estrangeira. É a constraint que torna o
    -- §36 impossível de violar pelo banco: um id inventado não tem para onde
    -- apontar, e o `INSERT` falha em vez de contaminar o histórico.
    player_id       uuid NOT NULL REFERENCES players (id),
    status          text NOT NULL,
    shirt_number    integer,
    position        text,
    captain         boolean NOT NULL DEFAULT false,

    PRIMARY KEY (match_id, team_id, player_id),
    FOREIGN KEY (match_id, team_id) REFERENCES lineups (match_id, team_id) ON DELETE CASCADE,
    CONSTRAINT lineup_entries_status CHECK (status IN ('STARTER', 'BENCH')),
    CONSTRAINT lineup_entries_camisa CHECK (
        shirt_number IS NULL OR shirt_number BETWEEN 1 AND 99
    ),
    -- Capitão no banco existe no papel e não em campo (PR-01).
    CONSTRAINT lineup_entries_capitao_titular CHECK (NOT captain OR status = 'STARTER')
);

-- O MESMO JOGADOR NOS DOIS TIMES DA MESMA PARTIDA é o sintoma clássico de
-- resolução que fundiu dois homônimos adversários — e toda estatística por
-- jogador daquela partida passa a contar duas vezes. O índice único por
-- (partida, jogador) o torna impossível.
CREATE UNIQUE INDEX lineup_entries_jogador_unico_na_partida
    ON lineup_entries (match_id, player_id);
CREATE INDEX lineup_entries_jogador_idx ON lineup_entries (player_id);

-- ------------------------------------------------------------------ odds --
--
-- OBSERVAÇÕES, E NUNCA UMA COTAÇÃO CONSOLIDADA (§42). `Bet365 @ 2.00` e
-- `Pinnacle @ 2.05` são duas linhas. `2.025` é um preço que casa nenhuma
-- ofereceu, e ele apagaria a dispersão entre casas — que é o sinal.
--
-- `observed_at` É NULO QUANDO A FONTE NÃO DECLARA (§44). Preenchê-lo com o
-- kickoff ou com o instante da leitura inventaria um fato plausível, que é o
-- pior tipo. A identidade da V1 NÃO o inclui (§43): ela continua sendo
-- (partida, casa, mercado, seleção, linha), exatamente como o PR-03.2 deixou.

CREATE TABLE canonical_odds_observations (
    id              bigserial PRIMARY KEY,
    match_id        uuid NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    bookmaker       text NOT NULL,
    market          text NOT NULL,
    selection       text NOT NULL,
    -- `numeric` E NÃO `double precision`, ao contrário dos eixos de qualidade:
    -- cotações vêm como texto decimal e serão comparadas e agrupadas, e o
    -- ruído de representação do binário aparece quando duas casas cotam o
    -- mesmo preço e a comparação diz que não (PR-01).
    decimal_odds    numeric(10, 4) NOT NULL,
    line            numeric(10, 4),
    observed_at     timestamptz,
    -- Procedência: por onde se volta ao byte bruto.
    provider_id     text NOT NULL,
    record_ref      text NOT NULL,
    license_class   text NOT NULL,
    recorded_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT odds_mercado CHECK (
        market IN ('MATCH_RESULT_1X2', 'TOTAL_GOALS', 'ASIAN_HANDICAP',
                   'BOTH_TEAMS_TO_SCORE')
    ),
    CONSTRAINT odds_selecao CHECK (
        selection IN ('HOME', 'DRAW', 'AWAY', 'OVER', 'UNDER', 'YES', 'NO')
    ),
    CONSTRAINT odds_maior_que_um CHECK (decimal_odds > 1 AND decimal_odds <= 1000),
    CONSTRAINT odds_licenca CHECK (
        license_class IN ('PUBLIC_DOMAIN', 'ATTRIBUTION_REQUIRED', 'RESEARCH_ONLY',
                          'COMMERCIAL_ALLOWED', 'UNKNOWN')
    ),
    CONSTRAINT odds_procedencia CHECK (length(btrim(record_ref)) > 0)
);

-- A IDENTIDADE DA V1, COMO ÍNDICE ÚNICO (§43). `coalesce` na linha porque
-- `NULL` não é igual a `NULL` num UNIQUE, e sem ele o mesmo 1X2 entraria
-- quantas vezes o build rodasse — que é o §96 falhando em silêncio.
CREATE UNIQUE INDEX odds_identidade_v1
    ON canonical_odds_observations (
        match_id, bookmaker, market, selection, coalesce(line, -1)
    );
CREATE INDEX odds_partida_idx ON canonical_odds_observations (match_id, bookmaker);

-- ============================================ linhagem do fato canônico ==
--
-- `match_results` NASCEU NA 0003 SEM `recorded_at` ÚTIL para linhagem, e não
-- precisa de mais: quem liga o resultado ao build é `canonical_build_records`,
-- pela chave (build_run_id, match_id, 'MATCH_RESULT'). Duplicar a linhagem
-- dentro de cada tabela de fato seria a cópia que diverge (§47).
