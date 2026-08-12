"""A ponte: vizinhos de `atlas.match_vector` no contrato que o detector lê.

    QueryService.vizinhos()  →  SimilarityContext  →  OracleSimilarityDetector

POR QUE UMA PONTE E NÃO UM CONTRATO SÓ. O detector foi escrito contra
`SimilarityContext`, que carrega mais do que uma lista de vizinhos: as versões
com que a busca foi filtrada, a distribuição da vizinhança, o acordo entre os
vizinhos. Reescrever o detector para o contrato novo seria mexer no que
decide o que vira tendência publicada; adaptar a entrada dele não é.

DUAS ARMADILHAS QUE ESTA CONVERSÃO PODIA CAIR, E COMO ESCAPA:

  A SIMILARIDADE AQUI É COSSENO SOBRE VETORES CENTRADOS, então ela vai de -1
  a 1 — e `UnitScore` do contrato antigo exige [0, 1], porque lá os vetores
  viviam todos no octante positivo e o cosseno nunca era negativo. Mapear com
  `max(0, x)` empilharia todo vizinho ruim em zero e faria a distância deles
  parecer idêntica. A conversão usa (1 + cos) / 2, que preserva a ordem e a
  distância relativa em toda a faixa.

  A DISTÂNCIA TEM DE SER COERENTE COM A SIMILARIDADE, porque
  `distance_uniformity` é calculada sobre ela. Se a distância não for
  exatamente o complemento da similaridade convertida, a uniformidade
  descreve outra coisa que não a vizinhança.

O QUE ESTA PONTE PASSOU A CARREGAR. Ela tinha `Vizinho.label` em mãos — como
cada partida vizinha terminou — e o descartava ao montar `SimilarityMatch`.
Com o desfecho ausente, `confidence_for_matches` só podia medir dispersão de
distância, e o detector usava aquilo como portão sob o nome de "acordo entre
vizinhos". Agora o desfecho atravessa, e junto com ele a taxa base da
competição: 50% de vitórias do mandante numa vizinhança é notável na Premier
League (base 43,3%) e é o normal no Brasileirão (48,4%).
"""

from __future__ import annotations

import statistics
import uuid
from typing import Sequence

from atlas.similarity.contracts import (
    SimilarityConfidence,
    SimilarityContext,
    SimilarityDistribution,
    SimilarityFilters,
    SimilarityMatch,
)
from atlas.similarity.scoring import confidence_for_matches
from atlas.vector.features import NOMES
from atlas.vector.query import Consulta, Vizinho
from atlas.vector.space import VERSAO

#: Quantos vizinhos o detector precisa ver para chamar a vizinhança de
#: coerente. O mesmo mínimo que a resposta em JSON usa — abaixo disso a
#: descrição é sobre poucos jogos demais para significar algo.
MINIMO_VIZINHOS = 5


def _unidade(similaridade: float) -> float:
    """Cosseno em [-1, 1] para o [0, 1] que `UnitScore` exige.

    (1 + cos) / 2, e não `max(0, cos)`: o corte empilharia todo vizinho
    dissimilar em zero, e a amplitude das distâncias — que é o que mede o
    acordo entre vizinhos — passaria a descrever um empate que não existe.
    """
    return max(0.0, min(1.0, (1.0 + similaridade) / 2.0))


def para_contexto(
    consulta: Consulta,
    vizinhos: Sequence[Vizinho],
    *,
    limite: int = 25,
    similaridade_minima: float = 0.60,
    taxa_base: float | None = None,
) -> SimilarityContext | None:
    """Constrói o contexto que o detector consome, ou None se não houver base.

    None e não um contexto vazio: o detector já trata `matches` vazio como
    "não emite nada", mas devolver um objeto bem formado sobre 3 vizinhos
    convidaria qualquer consumidor futuro a lê-lo como resposta.
    """
    escolhidos = list(vizinhos[:limite])
    if len(escolhidos) < MINIMO_VIZINHOS:
        return None

    filtros = SimilarityFilters(
        embedding_version=VERSAO,
        feature_schema_version=None,
        competition=consulta.competition,
        season=consulta.season,
    )

    partidas = [
        SimilarityMatch(
            # O uid do corpus é um UUID5 — determinístico e estável — então
            # ele serve como vector_id sem inventar um identificador novo.
            vector_id=uuid.UUID(vizinho.uid),
            match_id=vizinho.uid,
            similarity=_unidade(vizinho.similaridade),
            distance=1.0 - _unidade(vizinho.similaridade),
            embedding_version=VERSAO,
            competition=vizinho.competition,
            season=vizinho.season,
            # O DESFECHO ATRAVESSA A PONTE. Sem ele o detector media
            # concordância sobre as distâncias e chamava aquilo de acordo
            # entre vizinhos — e a ponte tinha o rótulo em mãos, jogando fora.
            outcome=vizinho.label,
        )
        for vizinho in escolhidos
    ]

    confianca: SimilarityConfidence = confidence_for_matches(
        partidas, minimum_neighbors=MINIMO_VIZINHOS
    )
    similaridades = [p.similarity for p in partidas]
    distancias = [p.distance for p in partidas]

    return SimilarityContext(
        matches=partidas,
        confidence=confianca,
        filters=filtros,
        top_k=limite,
        minimum_similarity=similaridade_minima,
        agreement=(
            confianca.outcome_agreement
            if confianca.outcome_agreement is not None
            else confianca.distance_uniformity
        ),
        coverage=min(1.0, len(partidas) / limite),
        distribution=SimilarityDistribution(
            count=len(partidas),
            best_similarity=max(similaridades),
            worst_similarity=min(similaridades),
            mean_similarity=statistics.fmean(similaridades),
            min_distance=min(distancias),
            max_distance=max(distancias),
            mean_distance=statistics.fmean(distancias),
            distance_spread=max(distancias) - min(distancias),
        ),
        reasoning=[
            f"lente '{consulta.categoria}' sobre {len(partidas)} partidas "
            f"anteriores a {consulta.as_of.date().isoformat()}",
            f"espaço {VERSAO}: {len(NOMES)} dimensões padronizadas, "
            "nenhuma constante",
        ],
        metadata={
            # A TAXA BASE VIAJA COM A VIZINHANÇA. O detector é uma função
            # pura de portões e não abre conexão; sem isto ele julgaria
            # concordância contra um número fixo, e 50% de vitórias do
            # mandante quer dizer coisas opostas na Premier League (43,3%) e
            # no Brasileirão (48,4%).
            "taxa_base": taxa_base,
            "categoria": consulta.categoria,
            "home_club_id": consulta.home_club_id,
            "away_club_id": consulta.away_club_id,
            # Quantas dimensões da lente a consulta conseguiu preencher. É o
            # que separa "a vizinhança é fraca" de "a pergunta chegou pela
            # metade", e sem isso as duas viram o mesmo número baixo.
            "dimensoes_informadas": len(consulta.features),
        },
        embedding_version=VERSAO,
    )
