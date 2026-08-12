-- O vetor passa de 28 para 32 dimensões: a tabela e a geografia.
--
-- O QUE MOTIVA, MEDIDO. O mercado separa as partidas de cada campeonato em
-- graus muito diferentes, e a ordem é exatamente a do desempenho das lentes:
--
--     competição        desvio de implied_home    lente `resultado`
--     premier_league          0,196                    +13,0%
--     la_liga                 0,173                     +9,5%
--     brasileirao             0,138                     +1,0%
--     argentina_liga          0,122                     +0,5%
--
-- Não falta dado de mercado — o passo 3 leu tudo o que havia no arquivo e não
-- moveu nada de forma conclusiva. O que falta é um sinal que NÃO venha do
-- mercado, porque num campeonato equilibrado o que distingue duas partidas
-- não é qualidade, e qualidade é o que o mercado precifica.
--
--   table_position_home  posição na tabela ANTES da partida, normalizada
--   table_position_away
--   stakes               quão perto o clube está de uma fronteira que muda o
--                        destino da temporada, pesado por quanto já passou.
--                        Declarada só onde o formato é estável — o futebol
--                        argentino mudou quase todo ano no período que temos,
--                        de 190 a 510 partidas por temporada.
--   travel_distance      km entre as cidades. Grêmio-Fortaleza são 3.500;
--                        Arsenal-Chelsea são 8. Não tem análogo europeu, que
--                        é exatamente por que vale medir.
--
-- JUNTO VAI UM CONSERTO: `season_progress` dividia por 380 fixo. A Premier
-- League tem 380 e não se notava; as temporadas argentinas vão de 190 a 510,
-- então a dimensão de MAIOR PESO de `contexto` estava comprimida a um terço
-- da escala lá, ou saturada em 1,0 nas mais longas.
BEGIN;

DROP INDEX IF EXISTS atlas.ix_match_vector_hnsw;
TRUNCATE TABLE atlas.match_vector;

ALTER TABLE atlas.match_vector
    ALTER COLUMN embedding TYPE vector(32);

CREATE INDEX ix_match_vector_hnsw
    ON atlas.match_vector USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

DELETE FROM atlas.vector_space WHERE version = 'atlas.vector.v1';
-- As medidas foram apuradas no espaço de 28 dimensões e descrevem uma
-- vizinhança que deixou de existir.
DELETE FROM atlas.lens_validation WHERE space_version = 'atlas.vector.v1';

COMMIT;
