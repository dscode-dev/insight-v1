-- O vetor passa de 25 para 28 dimensões.
--
-- AS TRÊS QUE ENTRAM ESTAVAM NO ARQUIVO O TEMPO TODO. O CSV do football-data
-- tem 106 colunas e o conversor lia 29. Destas 77 ignoradas saem:
--
--   market_disagreement  melhor preço contra a média do mercado. Quanto as
--                        casas DISCORDAM — nenhuma cotação de uma casa só
--                        carrega isso, e era tudo o que o Atlas lia. Presente
--                        em 100% de TODAS as competições, inclusive as
--                        sul-americanas, onde é o único sinal novo possível.
--
--   implied_over_2_5     o mercado de total de gols. É literalmente a
--                        pergunta da lente `gols`, respondida por quem tem
--                        dinheiro em jogo. Europa apenas.
--
--   handicap_line        a diferença de gols que o mercado espera, numa
--                        escala contínua. O 1x2 arredonda para o mesmo lugar
--                        partidas que -0,25 e -0,75 separam. Europa apenas.
--
-- POR QUE `vector` PRECISA DE MIGRAÇÃO E `features` NÃO. `features` é JSONB e
-- aceita chave nova sozinho; `embedding` é `vector(25)`, com o tamanho no
-- tipo. Inserir 28 números ali falha na hora — o que é bom: um espaço que
-- silenciosamente truncasse as três últimas dimensões produziria vizinhos
-- plausíveis calculados sobre menos do que a régua diz.
--
-- O ÍNDICE É RECONSTRUÍDO, não convertido. Um HNSW é construído sobre as
-- distâncias entre os vetores que existiam; com dimensões novas as distâncias
-- mudam, e um grafo antigo devolveria vizinhos do espaço velho com a
-- confiança do novo.
--
-- OS VETORES SÃO APAGADOS, e isto é seguro: `atlas.match_vector` é DERIVADA
-- de `atlas.match_record`, e `scripts/atlas_vector_build.py` a reconstrói
-- inteira em 11 segundos para 15.628 partidas. Nenhum dado de origem é
-- tocado.
BEGIN;

DROP INDEX IF EXISTS atlas.ix_match_vector_hnsw;

-- Vazia antes de trocar o tipo: converter 15.628 vetores de 25 para 28
-- exigiria inventar os três números que faltam, e inventá-los é exatamente
-- o que o `features` omitido evita.
TRUNCATE TABLE atlas.match_vector;

ALTER TABLE atlas.match_vector
    ALTER COLUMN embedding TYPE vector(28);

CREATE INDEX ix_match_vector_hnsw
    ON atlas.match_vector USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- O espaço gravado descreve 25 dimensões e não descreve mais nada real.
-- Apagá-lo força a reconstrução: sem ele, a consulta responde "memória
-- vetorial não construída" em vez de padronizar com constantes de um espaço
-- que não existe.
DELETE FROM atlas.vector_space WHERE version = 'atlas.vector.v1';

-- As medidas de validação foram apuradas no espaço de 25 dimensões. Mantê-las
-- faria toda resposta carregar um ganho medido sobre uma vizinhança que mudou
-- — que é o defeito que a coluna `space_version` existe para denunciar, aqui
-- desfeito na origem.
DELETE FROM atlas.lens_validation WHERE space_version = 'atlas.vector.v1';

COMMIT;

-- Rollback:
--
-- BEGIN;
-- DROP INDEX IF EXISTS atlas.ix_match_vector_hnsw;
-- TRUNCATE TABLE atlas.match_vector;
-- ALTER TABLE atlas.match_vector ALTER COLUMN embedding TYPE vector(25);
-- CREATE INDEX ix_match_vector_hnsw
--     ON atlas.match_vector USING hnsw (embedding vector_cosine_ops)
--     WITH (m = 16, ef_construction = 64);
-- DELETE FROM atlas.vector_space WHERE version = 'atlas.vector.v1';
-- COMMIT;
-- (e depois: python scripts/atlas_vector_build.py + atlas_lens_measure --gravar)
