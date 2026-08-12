-- LIMPEZA — as seis tabelas que ficaram sem nenhum código.
--
-- O CRITÉRIO, e ele é estreito de propósito: só cai a tabela cujo pacote foi
-- removido e cujo nome não aparece mais em nenhum arquivo `.py` do Atlas.
-- Verificado com grep antes desta migration existir; as seis deram zero.
--
--   explorer_*  (4)  — `atlas.ingestion` carregava `explorer-atlas.ingest.v1`,
--                      o contrato pelo qual o Explorer mandaria observações
--                      de inteligência. Nunca mandou nenhuma. Substituído por
--                      `atlas.intake`, que recebe partidas por contrato
--                      explícito, com relatório por linha.
--
--   dataset_*   (2)  — registro de datasets, com tela no console. As duas
--                      tabelas nunca receberam uma linha, e a tela foi
--                      removida junto.
--
-- O QUE FICA, E POR QUÊ. `atlas.atlas_vector_memory` tem 14.522 linhas e é
-- lida pelo orquestrador de inteligência e pela sonda de similaridade da
-- pipeline de trends — dois subsistemas que rodam a cada 30 segundos. As
-- outras 12 tabelas vazias pertencem a essa mesma máquina (trends, padrões,
-- coerência), ao registro de modelos, e ao Quality Gate.
--
-- Vazia ali significa "esse caminho ainda não recebeu evento", que é
-- diferente de "decorativo" — e a diferença decide se remover quebra algo.
-- `promotion_decisions` é o caso mais claro: ela está vazia porque nenhuma
-- promoção foi aprovada ainda, e é o registro que o ATLAS_V1_FROZEN.md exige
-- que exista. Apagá-la seria destruir a evidência de uma exigência de
-- governança porque ela ainda não foi exercida.
DROP TABLE IF EXISTS atlas.explorer_behavior_observations;
DROP TABLE IF EXISTS atlas.explorer_signal_observations;
DROP TABLE IF EXISTS atlas.explorer_memory_snapshots;
DROP TABLE IF EXISTS atlas.explorer_ingestion_batches;
DROP TABLE IF EXISTS atlas.dataset_records;
DROP TABLE IF EXISTS atlas.dataset_registry;

-- Rollback: recriar exige o DDL das migrations que as criaram (0003, 0009).
-- Nenhuma das seis tinha linha, então não há dado a restaurar — o rollback é
-- reverter o código que as escrevia, e ele está no git.
