"""Similaridade textual — implementada aqui, sem dependência externa.

POR QUE NÃO UMA BIBLIOTECA. `rapidfuzz`, `jellyfish` e `python-Levenshtein`
fazem isto bem e mais rápido. E o que se ganharia com elas é velocidade num
caminho que já roda em lote sobre nomes curtos; o que se pagaria é uma
dependência binária na fronteira mais sensível do motor — a que decide se
dois clubes são o mesmo.

Duas razões concretas pesaram mais:

    DETERMINISMO ENTRE VERSÕES. A implementação de Jaro-Winkler varia entre
    bibliotecas em detalhes que importam: o tamanho do prefixo considerado, o
    fator de escala, o tratamento de transposições. Trocar de versão da
    biblioteca mudaria scores gravados — e decisões de identidade guardam
    score. Aqui a implementação é nossa e muda quando NÓS mudarmos a
    `ResolverVersion`.

    LEITURA. Sessenta linhas de algoritmo publicado, com o comportamento
    escrito e testado contra casos conhecidos, são auditáveis. O resolver é o
    ponto do sistema em que alguém vai querer entender exatamente por que dois
    nomes casaram.

Se o volume justificar velocidade, a troca é substituir esta implementação
atrás do mesmo `StringSimilarityPort` — sem tocar em nenhum resolver.

NADA DE EMBEDDING NEM LLM (§64). Similaridade de nome precisa ser explicável e
estável; um modelo é nem uma coisa nem outra, e a diferença entre `Sporting
CP` e `Sporting Gijón` é justamente o tipo de distinção que um espaço
vetorial de propósito geral colapsa.
"""

from __future__ import annotations

from typing import Final, final

#: Peso do prefixo comum no Jaro-Winkler. 0,1 é o valor do artigo original;
#: fixá-lo aqui — e não deixá-lo configurável — é o que garante que dois
#: scores gravados em datas diferentes signifiquem a mesma coisa.
_ESCALA_DE_PREFIXO: Final[float] = 0.1
#: Quantos caracteres de prefixo contam. Quatro, como no original.
_MAX_PREFIXO: Final[int] = 4
#: Acima disto o Winkler não é aplicado. Sem esta trava, dois nomes longos
#: com o mesmo começo — `atletico mineiro` e `atletico madrid` — ganhariam
#: bônus por dez caracteres iguais.
_LIMIAR_PARA_BONUS: Final[float] = 0.7


def jaro(a: str, b: str) -> float:
    """Similaridade de Jaro, em [0,1].

    Conta caracteres em comum dentro de uma janela proporcional ao tamanho, e
    desconta transposições. É a base do Winkler.
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    janela = max(len(a), len(b)) // 2 - 1
    if janela < 0:
        janela = 0

    marcados_a = [False] * len(a)
    marcados_b = [False] * len(b)
    comuns = 0

    for i, caractere in enumerate(a):
        inicio = max(0, i - janela)
        fim = min(i + janela + 1, len(b))
        for j in range(inicio, fim):
            if marcados_b[j] or b[j] != caractere:
                continue
            marcados_a[i] = True
            marcados_b[j] = True
            comuns += 1
            break

    if comuns == 0:
        return 0.0

    transposicoes = 0
    j = 0
    for i in range(len(a)):
        if not marcados_a[i]:
            continue
        while not marcados_b[j]:
            j += 1
        if a[i] != b[j]:
            transposicoes += 1
        j += 1

    meias = transposicoes / 2
    return (comuns / len(a) + comuns / len(b) + (comuns - meias) / comuns) / 3


def jaro_winkler(a: str, b: str) -> float:
    """Jaro com bônus para prefixo comum, em [0,1].

    O BÔNUS SÓ SE APLICA ACIMA DE 0,7, e a trava importa: sem ela,
    `atletico mineiro` e `atletico madrid` — que compartilham nove caracteres
    de prefixo — ganhariam um empurrão que os aproximaria do limiar de
    resolução. São dois clubes de países diferentes.
    """
    base = jaro(a, b)
    if base < _LIMIAR_PARA_BONUS:
        return base
    prefixo = 0
    for x, y in zip(a[:_MAX_PREFIXO], b[:_MAX_PREFIXO], strict=False):
        if x != y:
            break
        prefixo += 1
    return base + prefixo * _ESCALA_DE_PREFIXO * (1 - base)


def token_set_ratio(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """Similaridade por conjunto de palavras — Jaccard, em [0,1].

    COMPLEMENTAR AO JARO-WINKLER, e não substituta. Ela pega o caso em que a
    ordem muda ou uma palavra falta: `city manchester` contra `manchester
    city`, `real madrid cf` contra `real madrid`. O Jaro-Winkler pega o caso
    em que a grafia varia: `gremio` contra `gremiu`.

    Usar só uma das duas deixa metade dos casos reais de fora.
    """
    if not a or not b:
        return 0.0
    conjunto_a, conjunto_b = set(a), set(b)
    intersecao = conjunto_a & conjunto_b
    uniao = conjunto_a | conjunto_b
    return len(intersecao) / len(uniao) if uniao else 0.0


def token_coverage(shorter: tuple[str, ...], longer: tuple[str, ...]) -> float:
    """Que fração das palavras do menor aparece no maior.

    O CASO `Man City` CONTRA `Manchester City` NÃO CAI AQUI — `man` e
    `manchester` são palavras diferentes. Ele cai no alias explícito, que é o
    caminho certo: abreviações de fonte são registradas, não inferidas.

    Esta função pega o outro caso: `Manchester City` contra `Manchester City
    Football Club`, em que o menor está inteiro dentro do maior.
    """
    if not shorter:
        return 0.0
    presentes = sum(1 for t in shorter if t in set(longer))
    return presentes / len(shorter)


@final
class StringSimilarity:
    """A combinação usada pelos resolvers. Determinística e sem estado.

    A COMBINAÇÃO É FIXA E DECLARADA — 60% Jaro-Winkler, 40% conjunto de
    palavras — e não configurável. Torná-la configurável faria dois scores
    gravados em datas diferentes significarem coisas diferentes sob a mesma
    `ResolverVersion`, que é exatamente o que a versão existe para impedir.
    Mudá-la é mudar a versão.
    """

    PESO_CARACTERE: Final[float] = 0.6
    PESO_PALAVRA: Final[float] = 0.4

    def score(
        self, a: str, b: str, *, tokens_a: tuple[str, ...], tokens_b: tuple[str, ...]
    ) -> float:
        """O score combinado entre dois nomes JÁ NORMALIZADOS.

        RECEBE OS TOKENS PRONTOS de propósito: normalizar aqui dentro faria a
        similaridade recalcular a normalização a cada comparação, e um lote
        compara cada nome de fonte contra dezenas de candidatos. O chamador
        normaliza uma vez.
        """
        if a == b:
            return 1.0
        if not a or not b:
            return 0.0
        caractere = jaro_winkler(a, b)
        palavra = max(
            token_set_ratio(tokens_a, tokens_b),
            token_coverage(
                *((tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a))
            ),
        )
        return self.PESO_CARACTERE * caractere + self.PESO_PALAVRA * palavra
