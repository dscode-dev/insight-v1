"""Os casos de uso da reconstrução de estado — onde o I/O vive.

DOIS CASOS DE USO E UM NÚCLEO (§161, §162). O individual reconstrói um estado;
o em lote reconstrói muitos. Eles COMPARTILHAM o mesmo caminho — ler, projetar,
reduzir, imprimir —, porque duas orquestrações divergiriam, e a divergência
apareceria como «pelo lote dá outro resultado».

A CAMADA DE APLICAÇÃO É A ÚNICA COM I/O (§73, §74, §76). Ela lê o corpus pelo
port, entrega contratos tipados ao domínio e devolve o que ele produziu. O
builder não recebe conexão, repositório nem linha de banco.

A SAÍDA EM LOTE É LIMITADA (§159, §160). Reconstruir dez mil estados e
devolvê-los todos numa lista faria o pico de memória seguir o corpus; o que
volta é contagem, problemas agregados e uma AMOSTRA — com o aviso de que ela é
amostra. Quem precisa de todos consome por partida.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol, final, runtime_checkable

from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.state.builder import (
    HistoricalMatchStateBuilder,
    MatchStateBuildResult,
)
from sports_intelligence.domain.features.state.issues import StateIssue
from sports_intelligence.domain.features.state.match_state import HistoricalMatchState
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.shared.errors import NotFoundError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.ports.repositories.feature_state import (
    HistoricalMatchStateSourcePort,
)


@runtime_checkable
class AsOfFactory(Protocol):
    """Quais cortes reconstruir para cada partida.

    ELA É UM PROTOCOLO EM FORMA DE CHAMÁVEL. Um `Callable` cru serviria; o
    nome existe para que a assinatura do caso de uso diga o que ela significa —
    «de onde vêm os cortes» é decisão de quem chama, e não detalhe: uma partida
    pode precisar de cinco cortes e outra de um.
    """

    def __call__(self, match_id: MatchId) -> Sequence[FeatureAsOf]: ...


#: Quantas partidas por leitura. Ele é o eixo do §158: as consultas crescem com
#: o número de LOTES, e não com o de partidas.
DEFAULT_STATE_BATCH: Final[int] = 500

#: Quantos estados a saída em lote carrega de volta (§160). O mesmo padrão da
#: amostra de linhagem do PR-04.4.1: o total é exato, a amostra é limitada, e
#: `sample_truncated` diz quando ela não é o conjunto.
STATE_SAMPLE_LIMIT: Final[int] = 100


@final
@dataclass(frozen=True, slots=True)
class BuildHistoricalMatchState:
    """Reconstrói o estado de UMA partida num corte (§161)."""

    source: HistoricalMatchStateSourcePort
    policy: TemporalAvailabilityPolicy

    async def execute(
        self, *, source_corpus: CorpusSource, as_of: FeatureAsOf
    ) -> MatchStateBuildResult:
        insumos = await self.source.load(source_corpus.version_id, [as_of.match_id])
        entrada = insumos.get(as_of.match_id)
        if entrada is None:
            # A PARTIDA NÃO ESTÁ NA VERSÃO. Isso não é «partida sem eventos»:
            # é «esta partida não pertence a este corpus», e devolver um estado
            # vazio faria as duas situações parecerem a mesma.
            raise NotFoundError(
                f"a partida {as_of.match_id} não pertence à versão publicada "
                f"{source_corpus.version}",
                context={
                    "match_id": str(as_of.match_id),
                    "version_id": source_corpus.version_id,
                },
            )
        return HistoricalMatchStateBuilder(policy=self.policy).build(
            entrada, as_of=as_of, source=source_corpus
        )


@final
@dataclass(frozen=True, slots=True)
class BatchStateOutcome:
    """O resultado de reconstruir muitos estados (§160, §166).

    `states` É AMOSTRA. `built` é o número exato; `sample_truncated` diz quando
    a amostra não é o conjunto. Apresentá-la como o todo seria a mentira mais
    fácil de cometer aqui — e a mais cara, porque quem contasse a amostra
    concluiria que o lote é pequeno.
    """

    built: int = 0
    partial: int = 0
    states: tuple[HistoricalMatchState, ...] = ()
    sample_truncated: bool = False
    issues_by_code: dict[str, int] = field(default_factory=dict)

    @property
    def complete(self) -> int:
        return self.built - self.partial


@final
@dataclass(frozen=True, slots=True)
class BuildHistoricalMatchStates:
    """Reconstrói estados de MUITAS partidas, em lotes (§162, §80).

    ELE NÃO DISTRIBUI TRABALHO e não guarda cache (§92, §93). O que ele faz é
    ler em lote e reduzir por partida — e é o suficiente para o benchmark do
    §155 e para o uso do PR-05.3.
    """

    source: HistoricalMatchStateSourcePort
    policy: TemporalAvailabilityPolicy
    batch_size: int = DEFAULT_STATE_BATCH
    sample_limit: int = STATE_SAMPLE_LIMIT

    async def execute(
        self,
        *,
        source_corpus: CorpusSource,
        match_ids: Sequence[MatchId],
        as_of_of: AsOfFactory,
    ) -> BatchStateOutcome:
        """Reconstrói um estado por partida, com o corte que a fábrica der.

        O CORTE VEM DE FORA (§156). Uma partida pode precisar de vários cortes
        e outra de um só; embutir a escolha aqui obrigaria o caso de uso a ter
        opinião sobre o que se quer medir.
        """
        construtor = HistoricalMatchStateBuilder(policy=self.policy)
        construidos = parciais = 0
        amostra: list[HistoricalMatchState] = []
        problemas: dict[str, int] = {}

        for inicio in range(0, len(match_ids), self.batch_size):
            lote = list(match_ids[inicio : inicio + self.batch_size])
            insumos = await self.source.load(source_corpus.version_id, lote)
            for partida in lote:
                entrada = insumos.get(partida)
                if entrada is None:
                    continue
                for corte in as_of_of(partida):
                    resultado = construtor.build(
                        entrada, as_of=corte, source=source_corpus
                    )
                    construidos += 1
                    if resultado.is_partial:
                        parciais += 1
                    _contar(problemas, resultado.issues)
                    if len(amostra) < self.sample_limit:
                        amostra.append(resultado.state)

        return BatchStateOutcome(
            built=construidos,
            partial=parciais,
            states=tuple(amostra),
            sample_truncated=construidos > len(amostra),
            issues_by_code=dict(sorted(problemas.items())),
        )


def _contar(destino: dict[str, int], issues: Sequence[StateIssue]) -> None:
    for problema in issues:
        destino[problema.code.value] = destino.get(problema.code.value, 0) + 1


