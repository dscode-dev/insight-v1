-- A MEDIDA DE CADA LENTE, POR COMPETIÇÃO.
--
-- POR QUE POR COMPETIÇÃO. Até aqui `Validacao` era um número por lente,
-- escrito à mão em `lenses.py`, e ele viajava em TODA resposta do Atlas:
-- "esta lente concorda com o desfecho 9,7 pontos acima da taxa base". Medido
-- sobre o corpus de 15.628 partidas, o mesmo número por lente passou a ser
-- impossível de escrever com honestidade:
--
--     lente             Europa    Brasileirão   Argentina
--     resultado         +10,9%       -4,8%        +0,9%
--     desempenho_time    +7,2%       -0,8%        -0,8%
--     gols               +5,6%       -4,1%        -4,5%
--     contexto           +0,6%       -3,4%        -5,1%
--     confronto          -4,6%       -4,5%        -6,4%
--
-- "+10,9%" é falso para o Brasileirão. "-1,2%" (a média do corpus inteiro) é
-- falso para a Premier League. Não existe um número certo — existe um número
-- por competição, e a resposta sabe qual competição foi consultada.
--
-- A AUSÊNCIA DE MEDIDA É UM ESTADO, NÃO UM ZERO. Competição sem linha aqui
-- faz a resposta dizer que a lente não foi demonstrada ali. Cair para um
-- número global seria exatamente o defeito que esta tabela existe para
-- fechar, com um passo a mais.
CREATE TABLE IF NOT EXISTS atlas.lens_validation (
    lens             VARCHAR(32)      NOT NULL,
    competition      VARCHAR(64)      NOT NULL,

    -- Quantas vezes a maioria dos vizinhos terminou como a partida-alvo.
    agreement        DOUBLE PRECISION NOT NULL,
    -- E quantas vezes o desfecho mais comum da competição teria acertado.
    -- Sem isto, 45% parece bom até se descobrir que chutar dava 45%.
    base_rate        DOUBLE PRECISION NOT NULL,
    lift             DOUBLE PRECISION NOT NULL,
    -- Margem de 95%. `|lift| > margin` é o que separa medida de ruído.
    margin           DOUBLE PRECISION NOT NULL,

    -- Quantas consultas sustentam o número, e sobre que corpus. Uma medida
    -- de 30 consultas e uma de 900 não valem o mesmo, e a resposta que as
    -- carrega precisa poder dizer qual é qual.
    evaluated        INTEGER          NOT NULL,
    corpus           INTEGER          NOT NULL,

    measured_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),
    -- A versão do espaço em que foi medida. Reconstruir o vetor invalida
    -- estes números, e sem esta coluna eles sobreviveriam à mudança que os
    -- torna falsos.
    space_version    VARCHAR(32)      NOT NULL,

    PRIMARY KEY (lens, competition)
);

CREATE INDEX IF NOT EXISTS ix_lens_validation_competition
    ON atlas.lens_validation (competition);

-- Rollback:
--
-- DROP TABLE IF EXISTS atlas.lens_validation;
