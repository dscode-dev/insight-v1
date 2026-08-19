-- 0010 — O `RecordKind` do mapeamento de fonte (PR-04.4.1)
--
-- O QUE ESTA COLUNA CONSERTA. `SourceMappingDefinition` ganhou `record_kind`
-- no domínio, e sem coluna a declaração não sobrevivia ao banco: o mapeamento
-- era gravado como `EVENT_RECORD` e relido como `MATCH_RECORD` — o default —,
-- e o `__post_init__` então recusava o próprio mapeamento que acabara de ser
-- aceito. Uma declaração que não persiste é uma declaração que não existe.
--
-- O DEFAULT É `MATCH_RECORD` E É CORRETO PARA O QUE JÁ ESTÁ LÁ: todo
-- mapeamento anterior a este PR descreve uma linha por partida, porque era a
-- única forma que o motor sabia ler. Um default diferente reinterpretaria em
-- silêncio o que alguém declarou.
--
-- MIGRATION NOVA E NÃO EDIÇÃO DA 0009: a 0009 já foi aplicada, e o aplicador
-- guarda o SHA-256 de cada arquivo — mudá-lo depois faz o banco e o
-- repositório discordarem em silêncio.

ALTER TABLE source_mapping_definitions
    ADD COLUMN record_kind text NOT NULL DEFAULT 'MATCH_RECORD';

-- O CATÁLOGO É FECHADO, e a constraint o repete no banco: uma terceira forma
-- inserida por script ganharia leitura sem nunca ter passado por decisão
-- nenhuma — e o leitor não saberia o que fazer com ela.
ALTER TABLE source_mapping_definitions
    ADD CONSTRAINT source_mapping_definitions_record_kind
    CHECK (record_kind IN ('MATCH_RECORD', 'EVENT_RECORD'));

-- «QUAIS DATASETS SÃO DE EVENTO» é a consulta operacional que a coluna
-- habilita. Índice parcial porque os de evento serão a minoria por muito
-- tempo: um índice cheio sobre uma coluna de duas cardinalidades não paga.
CREATE INDEX source_mapping_definitions_evento_idx
    ON source_mapping_definitions (dataset_id)
    WHERE record_kind = 'EVENT_RECORD';
