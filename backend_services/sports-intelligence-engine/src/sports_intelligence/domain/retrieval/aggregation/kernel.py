"""O núcleo matemático — pesos normalizados e tamanho efetivo de amostra.

UM LUGAR SÓ, PARA ESTADO E TRAJETÓRIA. A geometria é a mesma nos dois: um vetor
de dissimilaridades vira um vetor de massas relativas. O que difere entre eles é
a POLÍTICA (o `lambda`) e a evidência que os acompanha — não a aritmética.
Duplicar estas funções seria criar duas versões da mesma fórmula para divergirem
na primeira correção que só uma recebesse.

## O que os pesos são, e o que eles NÃO são

    p_i     a massa RELATIVA que o núcleo atribui ao vizinho i
            sob a política ativa

    NÃO é   probabilidade de desfecho
    NÃO é   confiança
    NÃO é   verossimilhança

`sum(p_i) = 1` porque é uma normalização, e não porque descreve um espaço
amostral. Somar a um é o que uma média ponderada exige; não é uma afirmação
sobre o mundo.

## Por que a forma deslocada, e não a ingênua

A forma óbvia é `exp(-lambda * d)` seguida de divisão pela soma. Ela produz
`0/0` quando todas as distâncias são grandes o bastante:

    lambda = 4, d = 200   ->   exp(-800) = 0.0     (underflow)
    todos os pesos zero   ->   divisão por zero

A saída é deslocar pelo mínimo ANTES de exponenciar:

    u_i = exp(-lambda * (d_i - d_min))

O maior `u` vale exatamente `1` por construção, o denominador nunca é zero, e o
resultado normalizado é IDÊNTICO ao da forma ingênua — porque a constante
`exp(-lambda * d_min)` aparece no numerador e no denominador e se cancela.

    p_i = u_i / sum(u_j)
        = [exp(-l·d_i)/exp(-l·d_min)] / sum[exp(-l·d_j)/exp(-l·d_min)]
        = exp(-l·d_i) / sum exp(-l·d_j)

É essa identidade que torna o deslocamento uma escolha de IMPLEMENTAÇÃO e não de
semântica — e é ela que a invariância a deslocamento constante testa.

## A forma congelada

Entre as duas equivalentes do contrato — deslocar pelo máximo de `a_i = -l·d_i`
ou pelo mínimo de `d_i` — a V1 usa a do MÍNIMO DE DISTÂNCIA. Elas são a mesma
conta (`max(-l·d) = -l·min(d)` para `l > 0`), e a segunda é a que se lê na
linguagem do domínio: «quão mais longe este vizinho está do mais próximo».
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final

from sports_intelligence.domain.shared.errors import ValidationError

#: A forma congelada da normalização (§16).
SHIFTED_EXPONENTIAL_MIN_DISTANCE_V1: Final[str] = "SHIFTED_EXPONENTIAL_MIN_DISTANCE_V1"

#: A aritmética. `binary64` e `fsum`, como no resto do motor.
IEEE754_FLOAT64_FSUM_V1: Final[str] = "IEEE754_FLOAT64_FSUM_V1"


def assert_distances(distances: Sequence[float]) -> None:
    """As distâncias precisam ser finitas e não negativas (§39).

    UM `NaN` AQUI ENVENENARIA TUDO EM SILÊNCIO: ele sobrevive à exponenciação,
    contamina a soma e sai do outro lado como um peso que compara falso consigo
    mesmo. Uma distância negativa é pior — ela produz um peso MAIOR que o do
    vizinho mais próximo, e inverte a ordem sem erro nenhum.
    """
    for indice, d in enumerate(distances):
        if not math.isfinite(d):
            raise ValidationError(
                f"dissimilaridade não finita na posição {indice}: {d!r}. Ela viria "
                "de uma distância que o oráculo exato não produz, e sobreviveria à "
                "exponenciação como um peso que compara falso consigo mesmo"
            )
        if d < 0.0:
            raise ValidationError(
                f"dissimilaridade negativa na posição {indice}: {d!r}. O núcleo é "
                "decrescente na distância, e um valor negativo daria a este vizinho "
                "mais massa que a do mais próximo — invertendo a ordem sem falhar"
            )


def assert_lambda(value: float) -> None:
    """`lambda > 0`, finito, e nunca implícito (§20).

    ZERO SERIA UNIFORME, e uniforme é uma decisão — não um efeito colateral de
    um parâmetro esquecido. Quem quer pesos iguais pede a política uniforme pelo
    nome; quem passa `lambda = 0` quase sempre errou.
    """
    if not math.isfinite(value):
        raise ValidationError(f"lambda não finito: {value!r}")
    if value <= 0.0:
        raise ValidationError(
            f"lambda = {value!r}: o núcleo exige `lambda > 0`. Zero produziria pesos "
            "uniformes, e uniforme é uma POLÍTICA com nome próprio — não o efeito "
            "de um parâmetro esquecido"
        )


def normalized_weights(distances: Sequence[float], *, lam: float) -> tuple[float, ...]:
    """As massas relativas `p_i`, pela forma deslocada pelo mínimo.

    A SOMA É `1` POR CONSTRUÇÃO, e não por sorte: o denominador é a soma dos
    mesmos `u_i` do numerador, calculada com `fsum` para que a ordem das
    parcelas não mude o resultado.

    O CASO VAZIO DEVOLVE VAZIO, e não um erro: «nenhum vizinho» é um estado
    legítimo do retrieval — a agregação o reporta como `NO_NEIGHBORS`, e quem
    decide o que fazer com isso é a camada de cima.
    """
    if not distances:
        return ()
    assert_lambda(lam)
    assert_distances(distances)

    minima = min(distances)
    # `d_i - minima >= 0` por construção, logo o expoente é <= 0 e `exp` nunca
    # estoura para cima. O maior `u` vale exatamente 1.0.
    naos_normalizados = [math.exp(-lam * (d - minima)) for d in distances]
    total = math.fsum(naos_normalizados)
    if total <= 0.0 or not math.isfinite(total):
        # INALCANÇÁVEL POR CONSTRUÇÃO — o maior termo é 1.0, logo a soma é >= 1.
        # A guarda existe porque «inalcançável» e «não conferido» são coisas
        # diferentes, e a segunda é a que produz divisão por zero em produção.
        raise ValidationError(
            f"soma de pesos inválida ({total!r}) sobre {len(distances)} vizinhos: "
            "a forma deslocada garante um termo igual a 1, e este resultado "
            "indicaria que o deslocamento não foi aplicado"
        )
    return tuple(u / total for u in naos_normalizados)


def effective_sample_size(weights: Sequence[float]) -> float | None:
    """`N_eff = 1 / sum(p_i^2)` — a CONCENTRAÇÃO dos pesos.

    O QUE ELE MEDE, e o que ele não mede. `N_eff = 4,2` sobre `K = 20` diz que
    a massa está concentrada como se estivesse em aproximadamente quatro
    observações igualmente ponderadas. Não diz que existiram 4,2 partidas, não
    é «42% de confiança», e não são 4,2 ensaios independentes.

    OS LIMITES SÃO `1 <= N_eff <= K`, e os dois extremos têm significado:

        uniforme      todos os `p` iguais      ->  N_eff = K
        dominante     um `p` tende a 1         ->  N_eff -> 1

    `None` PARA CONJUNTO VAZIO, e nunca zero. Zero seria um número numa escala
    cujo mínimo é um — ele diria «concentração abaixo do possível» quando o que
    houve foi ausência de vizinhos.
    """
    if not weights:
        return None
    soma_dos_quadrados = math.fsum(p * p for p in weights)
    if soma_dos_quadrados <= 0.0:
        raise ValidationError(
            "soma dos quadrados nula: pesos normalizados não podem ser todos zero"
        )
    return 1.0 / soma_dos_quadrados


def uniform_weights(count: int) -> tuple[float, ...]:
    """`p_i = 1/k` — a linha de base do §25.

    ELA NÃO É POLÍTICA DE PRODUÇÃO. Existe para os goldens: sob ela `N_eff` tem
    de dar exatamente `k`, e é isso que prova que a implementação de `N_eff` não
    depende do núcleo exponencial.
    """
    if count < 0:
        raise ValidationError(f"contagem negativa: {count}")
    if count == 0:
        return ()
    return tuple(1.0 / count for _ in range(count))


def weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float | None:
    """A média ponderada, com `fsum`. Diagnóstico geométrico, e não confiança."""
    if not values:
        return None
    if len(values) != len(weights):
        raise ValidationError(
            f"{len(values)} valores contra {len(weights)} pesos: a média ponderada "
            "estaria somando posições que não se correspondem"
        )
    return math.fsum(v * p for v, p in zip(values, weights, strict=True))


def top_mass(weights: Sequence[float], *, how_many: int = 3) -> float | None:
    """A massa dos `how_many` maiores pesos (§47).

    ELA DETECTA CONCENTRAÇÃO onde `N_eff` só a resume. Duas consultas com o
    mesmo `N_eff` podem ter formas diferentes — uma com três vizinhos fortes e
    uma cauda, outra com dez médios —, e a massa do topo separa as duas.
    """
    if not weights:
        return None
    if how_many < 1:
        raise ValidationError(f"top_mass com {how_many} posições")
    return math.fsum(sorted(weights, reverse=True)[:how_many])
