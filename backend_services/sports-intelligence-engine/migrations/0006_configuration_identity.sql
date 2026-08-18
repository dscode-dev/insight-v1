-- 0006 — Identidade de configuração e procedência independente (PR-04.2.1)
--
-- DUAS COLUNAS, e as duas fecham invariantes que o PR-04.2 deixou implícitos.
-- Nenhuma delas é «marcar o PR»: sem a primeira, dois builds sob políticas
-- editadas sem troca de versão ficam indistinguíveis; sem a segunda, a
-- distinção entre «esta fonte DERIVOU o fato» e «esta fonte CONFIRMOU o fato»
-- não sobrevive ao banco — e é justamente ela que separa uma exclusão por
-- licença legítima de uma lavagem de licença.

-- ================================ 1. impressão da política de build ==
--
-- `QualityRun` já guardava versão E impressão desde a 0005, pelo motivo
-- escrito lá: a versão pega a mudança declarada, a impressão pega a que
-- ninguém declarou. `CanonicalBuildRun` guardava só a versão, e a assimetria
-- era um descuido: os corpus de pesquisa e comercial precisam ser
-- reproduzíveis exatamente como a avaliação precisa.
--
-- A COLUNA É NULA PARA AS EXECUÇÕES ANTERIORES, e é a resposta honesta: elas
-- rodaram antes de a impressão existir. Preenchê-las com o valor de hoje as
-- faria parecer reproduzíveis sob uma política que ninguém gravou — que é
-- exatamente o tipo de mentira que a coluna existe para impedir.

ALTER TABLE canonical_build_runs
    ADD COLUMN build_policy_fingerprint text;

COMMENT ON COLUMN canonical_build_runs.build_policy_fingerprint IS
    'SHA-256 da forma canônica da CanonicalBuildPolicy. NULO só em execuções '
    'anteriores à migration 0006.';

-- ===================== 2. suporte independente por família e licença ==
--
-- O QUE ESTA COLUNA DISTINGUE (PR-04.2.1 §42, §43). Duas situações que a
-- 0005 registrava igual:
--
--     A e B disseram O MESMO       o valor seria idêntico só com A. B
--                                  confirma; não deriva. Se A é elegível, a
--                                  família é utilizável.
--
--     o valor saiu de um DESEMPATE o valor foi produzido comparando A e B;
--     entre A e B                  sem B a comparação teria sido outra, e a
--                                  restrição da mais restritiva vale.
--
-- Sem a distinção, uma fonte `RESEARCH_ONLY` que apenas CONFIRMA um placar de
-- domínio público condenaria o placar — e o corpus comercial perderia
-- exatamente as partidas mais bem confirmadas. Com ela, e só com ela, o
-- inverso continua barrado: quando a restrita é a ÚNICA que sustenta o fato,
-- não há suporte independente elegível e o comercial não pode usá-lo.
--
-- `false` É O DEFAULT E É O CONSERVADOR: uma linha sem suporte independente
-- declarado cai na regra antiga, que é a restritiva.

ALTER TABLE quality_assessment_licenses
    ADD COLUMN independent boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN quality_assessment_licenses.independent IS
    'true quando esta licença pertence a uma fonte que sustenta a família '
    'SOZINHA (EXACT_AGREEMENT ou única contribuinte).';

-- A CONSULTA DA POLÍTICA DE BUILD: «esta família tem suporte independente
-- elegível?». Índice parcial porque só as linhas independentes respondem.
CREATE INDEX licenses_independentes_idx
    ON quality_assessment_licenses (assessment_id, family)
    WHERE independent;
