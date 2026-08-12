"""Busca vetorial sobre o histórico aprovado.

A ASSINATURA CARREGA A VERSÃO DO ESPAÇO, e isso não é opcional: buscar um
vetor de um espaço dentro de um índice de outro devolve vizinhos plausíveis
calculados sobre eixos diferentes. O adapter deve RECUSAR quando as versões
divergirem — nunca converter.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.versioning import FeatureSpaceVersion


@runtime_checkable
class VectorStorePort(Protocol):
    async def search(
        self,
        *,
        embedding: Sequence[float],
        feature_space_version: FeatureSpaceVersion,
        limit: int,
    ) -> Sequence[tuple[MatchId, float]]:
        """Os vizinhos mais próximos, com a similaridade de cada um.

        Só partidas em `HISTORICAL_ACTIVE` podem estar no índice (ADR-0007), e
        garantir isso é responsabilidade de quem INDEXA — filtrar na leitura
        seria tarde: o vizinho errado já estaria no índice para todo mundo.
        """
        ...
