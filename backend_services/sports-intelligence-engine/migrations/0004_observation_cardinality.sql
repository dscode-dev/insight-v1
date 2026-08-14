-- 0004 — Cardinalidade de observação, e o índice de candidatos por token
--
-- DUAS MUDANÇAS, as duas exigidas por defeito medido no PR-03.1. Nenhuma
-- delas é «marcar o PR»: sem a primeira, a correção de odds não tem onde
-- gravar; sem a segunda, a correção de determinismo faz sequential scan.

-- ================================ 1. uma linha por fonte deixou de valer ==
--
-- O QUE A CONSTRAINT ANTIGA AFIRMAVA. `UNIQUE (group_id, provider_id)` dizia
-- que uma fonte contribui com no máximo uma linha por grupo. É verdade para
-- FUSÃO ESCALAR — duas linhas da mesma fonte dizendo o placar são duplicata
-- interna — e é FALSO para CONJUNTO DE OBSERVAÇÕES: uma fonte que publica
-- uma linha por casa de apostas manda `Bet365 @ 2.00` e `Pinnacle @ 2.05`
-- como duas linhas, e as duas são verdade ao mesmo tempo.
--
-- O benchmark do PR-03.1 mediu o estrago: a segunda casa era descartada, e a
-- dispersão entre casas — que é o sinal que o Odds Intelligence vai ler —
-- sumia sem erro nenhum.
--
-- A CHAVE PASSA A SER A LINHA. `record_ref` é `dataset:arquivo:linha`: ele
-- identifica exatamente uma linha de exatamente um arquivo, então continua
-- impedindo que a MESMA linha entre duas vezes no mesmo grupo — que é a
-- duplicata que a constraint precisa mesmo barrar.

ALTER TABLE fusion_group_records
    DROP CONSTRAINT IF EXISTS fusion_group_records_group_id_provider_id_key;

-- O nome da constraint gerada pelo `UNIQUE (...)` inline varia com a versão
-- do PostgreSQL. Este bloco cobre o caso de ela ter nascido com outro nome.
DO $$
DECLARE
    nome text;
BEGIN
    SELECT conname INTO nome
    FROM pg_constraint
    WHERE conrelid = 'fusion_group_records'::regclass
      AND contype = 'u'
      AND pg_get_constraintdef(oid) LIKE '%provider_id%'
      AND pg_get_constraintdef(oid) NOT LIKE '%record_ref%';
    IF nome IS NOT NULL THEN
        EXECUTE format('ALTER TABLE fusion_group_records DROP CONSTRAINT %I', nome);
    END IF;
END $$;

ALTER TABLE fusion_group_records
    ADD CONSTRAINT fusion_group_records_linha_unica UNIQUE (group_id, record_ref);

-- A consulta que lista as fontes de um grupo continua existindo, e agora
-- pode devolver mais de uma linha por fonte.
CREATE INDEX IF NOT EXISTS fusion_group_records_provedor_idx
    ON fusion_group_records (group_id, provider_id);

-- ===================== 2. candidatos por token, para o universo estável ===
--
-- O PROBLEMA QUE ISTO RESOLVE. Até o PR-03.1, o universo de candidatos de
-- similaridade era «os times que o LOTE carregou por chave exata» — então um
-- lote de cinco mil linhas enxergava candidatos que um lote de duzentos e
-- cinquenta nem lia. A medição pegou: 2,7% das listas de alternativas
-- mudavam com o tamanho do lote.
--
-- A correção busca candidatos POR NOME, e não por lote: os times que
-- compartilham pelo menos um token com o nome consultado. O resultado passa a
-- ser função só do nome — que é o que torna a decisão independente do lote.
--
-- `gin` SOBRE `string_to_array(normalized_name, ' ')` É O QUE FAZ ISSO
-- CUSTAR BARATO. Sem ele, o operador `&&` cai em sequential scan e a
-- correção de determinismo viraria uma regressão de performance.
--
-- NÃO É `pg_trgm`: a extensão não está instalada e exigi-la mudaria o
-- requisito de infraestrutura do projeto. Token compartilhado é mais grosso
-- que trigrama e basta para o corte de candidato, que é 0,55.

CREATE INDEX IF NOT EXISTS teams_tokens_idx
    ON teams USING gin (string_to_array(normalized_name, ' '));

CREATE INDEX IF NOT EXISTS players_tokens_idx
    ON players USING gin (string_to_array(normalized_name, ' '));
