"""O caso de uso: reprocessamento, lotes, N+1 e o desfecho real.

O QUE SÓ ESTE ARQUIVO PROVA. Os testes de canonicalização exercitam o
pipeline puro, sobre registros em memória. Aqui entram os repositórios — ainda
duplos, mas com as MESMAS restrições dos reais — e com eles três propriedades
que o pipeline sozinho não tem:

    idempotência         reler a mesma fonte não duplica (§24, §99)
    desfecho real        `REUSED` vem de quem escreveu, não de quem construiu
    lote                 as consultas crescem com os LOTES, não com as linhas
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import pytest

from sports_intelligence.application.use_cases.events import (
    LINEAGE_SAMPLE_LIMIT,
    RunHistoricalEventCanonicalization,
)
from sports_intelligence.domain.events.build import EventBuildRecordStatus
from sports_intelligence.domain.events.canonical import EventStatus
from sports_intelligence.domain.events.records import (
    EventRevisionKind,
    HistoricalEventRecord,
)
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.historical.events.eligibility import EventEligibilityPolicy
from sports_intelligence.ports.clock import FrozenClock
from tests.support.build_fixtures import AGORA
from tests.support.event_doubles import (
    FakeCanonicalEventBuildRunRepository,
    FakeCanonicalEventWriter,
    FakeEventBuildRecordRepository,
    FakeProviderMappingRepository,
    mapeamento,
)
from tests.support.event_fixtures import (
    ARTILHEIRO,
    DATASET,
    PARTIDA,
    PROVEDOR,
    REF_DA_PARTIDA,
    REF_DO_ARTILHEIRO,
    REF_DO_RESERVA,
    REF_DO_TIME,
    RESERVA,
    TIME,
    cartao,
    evento,
    gol,
    substituicao,
    tabela_de_tipos,
    tipo_desconhecido,
)

CANONICALIZADOR = Actor(id="historical-event-canonicalizer", kind=ActorKind.SERVICE)


def _traducoes() -> FakeProviderMappingRepository:
    """As traduções que a resolução JÁ provou — e só elas."""
    return FakeProviderMappingRepository(
        [
            mapeamento(
                provider=PROVEDOR,
                subject=SubjectType.MATCH,
                externo=REF_DA_PARTIDA,
                canonico=str(PARTIDA),
                at=AGORA,
            ),
            mapeamento(
                provider=PROVEDOR,
                subject=SubjectType.TEAM,
                externo=REF_DO_TIME,
                canonico=str(TIME),
                at=AGORA,
            ),
            mapeamento(
                provider=PROVEDOR,
                subject=SubjectType.PLAYER,
                externo=REF_DO_ARTILHEIRO,
                canonico=str(ARTILHEIRO),
                at=AGORA,
            ),
            mapeamento(
                provider=PROVEDOR,
                subject=SubjectType.PLAYER,
                externo=REF_DO_RESERVA,
                canonico=str(RESERVA),
                at=AGORA,
            ),
        ]
    )


class Ambiente:
    """O grafo com duplos, montado uma vez por teste."""

    def __init__(self, *, policy: EventEligibilityPolicy | None = None) -> None:
        self.mappings = _traducoes()
        self.events = FakeCanonicalEventWriter()
        self.lineage = FakeEventBuildRecordRepository()
        self.runs = FakeCanonicalEventBuildRunRepository()
        self.caso = RunHistoricalEventCanonicalization(
            mappings=self.mappings,
            events=self.events,
            lineage=self.lineage,
            runs=self.runs,
            clock=FrozenClock(AGORA),
            types=tabela_de_tipos(),
            policy=policy or EventEligibilityPolicy.research(),
        )

    async def rodar(
        self,
        registros: Sequence[HistoricalEventRecord],
        *,
        lote: int = 1_000,
        license_class: LicenseClass = LicenseClass.PUBLIC_DOMAIN,
    ) -> object:
        async def lotes() -> AsyncIterator[Sequence[HistoricalEventRecord]]:
            for inicio in range(0, len(registros), lote):
                yield registros[inicio : inicio + lote]

        return await self.caso.execute(
            actor=CANONICALIZADOR,
            dataset_id=DATASET,
            provider_id=PROVEDOR,
            batches=lotes(),
            eligible_matches=frozenset({PARTIDA}),
            license_class=license_class,
        )


UM_JOGO = (gol(1), cartao(4), substituicao(5))


class TestAExecucao:
    async def test_conclui_com_as_contagens_fechadas(self) -> None:
        ambiente = Ambiente()
        saida = await ambiente.rodar(UM_JOGO)
        execucao = saida.run  # type: ignore[attr-defined]
        assert execucao.status is RunStatus.COMPLETED
        assert execucao.counts.records_read == 3
        assert execucao.counts.events_built == 3
        execucao.counts.assert_consistent()

    async def test_revisao_pendente_muda_o_estado_da_execucao(self) -> None:
        """`COMPLETED_WITH_REVIEW` diz que há trabalho humano esperando —
        `COMPLETED` faria alguém achar que acabou."""
        ambiente = Ambiente()
        saida = await ambiente.rodar((gol(1), tipo_desconhecido(7)))
        assert saida.run.status is RunStatus.COMPLETED_WITH_REVIEW  # type: ignore[attr-defined]
        assert saida.run.counts.events_review_required == 1  # type: ignore[attr-defined]

    async def test_a_execucao_guarda_a_versao_da_tabela_de_tipos(self) -> None:
        """Um evento que ontem foi `UNMAPPED_TYPE` e hoje entra mudou por
        causa da TABELA, e sem o número não há como dizer isso."""
        ambiente = Ambiente()
        saida = await ambiente.rodar(UM_JOGO)
        assert saida.run.type_mapping_version == tabela_de_tipos().version  # type: ignore[attr-defined]

    async def test_a_execucao_e_persistida_e_fechada(self) -> None:
        """Ela é aberta ANTES do primeiro evento e fechada depois do último —
        um fato gravado sem quem o produziu não teria explicação."""
        ambiente = Ambiente()
        saida = await ambiente.rodar(UM_JOGO)
        gravada = await ambiente.runs.by_id(saida.run.id)  # type: ignore[attr-defined]
        assert gravada is not None
        assert gravada.status is RunStatus.COMPLETED
        assert gravada.counts.events_built == 3

    async def test_uma_execucao_concluida_e_imutavel(self) -> None:
        from sports_intelligence.domain.shared.errors import ConflictError

        ambiente = Ambiente()
        saida = await ambiente.rodar(UM_JOGO)
        with pytest.raises(ConflictError, match="imutável"):
            saida.run.complete(counts=saida.run.counts, at=AGORA)  # type: ignore[attr-defined]


class TestOReprocessamento:
    """§24, §99. A mesma fonte duas vezes."""

    async def test_reler_a_mesma_fonte_nao_duplica(self) -> None:
        ambiente = Ambiente()
        await ambiente.rodar(UM_JOGO)
        assert len(ambiente.events.events) == 3

        await ambiente.rodar(UM_JOGO)
        assert len(ambiente.events.events) == 3, (
            "a segunda leitura criou eventos novos — a identidade derivada "
            "deixou de ser determinística"
        )
        assert ambiente.events.reaproveitados == 3

    async def test_a_segunda_execucao_reporta_REUSED(self) -> None:
        """O desfecho REAL vem de quem escreveu. Afirmar `BUILT` sobre um
        reprocessamento seria a declaração falsa do §66 do PR-04.2."""
        ambiente = Ambiente()
        await ambiente.rodar(UM_JOGO)
        segunda = await ambiente.rodar(UM_JOGO)
        assert segunda.run.counts.events_reused == 3  # type: ignore[attr-defined]
        assert segunda.run.counts.events_built == 0  # type: ignore[attr-defined]

    async def test_a_linhagem_da_segunda_execucao_e_nova(self) -> None:
        """O fato é o mesmo; a EXECUÇÃO é outra, e a linhagem de cada uma
        sobrevive — «quantas vezes este evento foi processado» tem resposta."""
        ambiente = Ambiente()
        primeira = await ambiente.rodar(UM_JOGO)
        segunda = await ambiente.rodar(UM_JOGO)
        assert primeira.run.id != segunda.run.id  # type: ignore[attr-defined]
        assert len(ambiente.lineage.records) == 6

    async def test_os_ids_canonicos_sao_os_mesmos_nas_duas(self) -> None:
        ambiente = Ambiente()
        primeira = await ambiente.rodar(UM_JOGO)
        de_antes = {r.event_id for r in primeira.records if r.event_id}  # type: ignore[attr-defined]
        segunda = await ambiente.rodar(UM_JOGO)
        de_agora = {r.event_id for r in segunda.records if r.event_id}  # type: ignore[attr-defined]
        assert de_antes == de_agora


class TestOLote:
    """§67, §68, §104. As consultas crescem com os LOTES."""

    async def test_as_consultas_crescem_por_lote_e_nao_por_linha(self) -> None:
        muitos = tuple(gol(n, minuto=n % 90, id_do_evento=f"ev-{n}") for n in range(1, 61))
        de_um_lote = Ambiente()
        await de_um_lote.rodar(muitos, lote=1_000)
        de_seis_lotes = Ambiente()
        await de_seis_lotes.rodar(muitos, lote=10)

        # TRÊS CONSULTAS POR LOTE — partidas, times, jogadores. Com N+1 seriam
        # três por LINHA, e sessenta linhas dariam cento e oitenta.
        assert de_um_lote.mappings.consultas == 3
        assert de_seis_lotes.mappings.consultas == 18

    async def test_o_tamanho_do_lote_nao_muda_o_resultado(self) -> None:
        """§104. Mesmos eventos canônicos, qualquer que seja o lote."""
        muitos = tuple(gol(n, minuto=n % 90, id_do_evento=f"ev-{n}") for n in range(1, 41))
        resultados = []
        for tamanho in (250, 1_000, 5_000):
            ambiente = Ambiente()
            await ambiente.rodar(muitos, lote=tamanho)
            resultados.append(
                sorted(
                    (str(e.id), e.sequence, e.clock.minute) for e in ambiente.events.events.values()
                )
            )
        assert resultados[0] == resultados[1] == resultados[2]

    async def test_lotes_pequenos_nao_reiniciam_a_sequencia(self) -> None:
        """A sequência é por `(partida, período)` e SOBREVIVE entre lotes: se
        reiniciasse, dois eventos do mesmo tempo teriam a mesma posição."""
        muitos = tuple(gol(n, minuto=n, id_do_evento=f"ev-{n}") for n in range(1, 7))
        ambiente = Ambiente()
        await ambiente.rodar(muitos, lote=2)
        sequencias = sorted(e.sequence for e in ambiente.events.events.values())
        assert sequencias == [0, 1, 2, 3, 4, 5]


class TestAAmostraDeLinhagem:
    """PR-04.4.2 §84, §85, §86. A saída devolve AMOSTRA, e diz que é amostra.

    POR QUE ELA É LIMITADA. A linhagem completa de uma execução de cem mil
    eventos são cem mil objetos; acumulá-los para devolvê-los a um chamador que
    quase sempre só quer as contagens faria o pico de memória seguir o VOLUME
    DO ARQUIVO. A linhagem completa mora no repositório — que é onde ela é
    completa.
    """

    async def test_a_amostra_respeita_o_teto(self) -> None:
        muitos = tuple(gol(n, minuto=n % 90, id_do_evento=f"ev-{n}") for n in range(1, 41))
        ambiente = Ambiente()
        saida = await ambiente.rodar(muitos, lote=10)
        assert len(saida.records) <= LINEAGE_SAMPLE_LIMIT  # type: ignore[attr-defined]

    async def test_sem_truncamento_a_amostra_e_a_linhagem_inteira(self) -> None:
        """Quarenta linhas cabem folgadamente no teto — e aí `records_truncated`
        precisa dizer `False`, senão quem lê descarta uma resposta completa."""
        muitos = tuple(gol(n, minuto=n % 90, id_do_evento=f"ev-{n}") for n in range(1, 41))
        ambiente = Ambiente()
        saida = await ambiente.rodar(muitos, lote=10)
        assert saida.records_truncated is False  # type: ignore[attr-defined]
        assert len(saida.records) == len(ambiente.lineage.records)  # type: ignore[attr-defined]

    async def test_a_amostra_e_deterministica_e_nao_a_ordem_do_banco(self) -> None:
        """§85. Duas execuções do mesmo conjunto devolvem a MESMA amostra, na
        mesma ordem: ela vem da ordem canônica de leitura, e não da ordem
        natural em que o banco devolveria as linhas."""
        muitos = tuple(gol(n, minuto=n % 90, id_do_evento=f"ev-{n}") for n in range(1, 21))
        primeira = await Ambiente().rodar(muitos, lote=5)
        segunda = await Ambiente().rodar(muitos, lote=5)
        assert [r.source_key for r in primeira.records] == [  # type: ignore[attr-defined]
            r.source_key for r in segunda.records  # type: ignore[attr-defined]
        ]

    async def test_o_repositorio_continua_sendo_a_autoridade(self) -> None:
        """§86. A amostra não substitui a linhagem: ela é atalho de
        diagnóstico, e o que responde «o que aconteceu com cada linha» é o
        repositório."""
        muitos = tuple(gol(n, minuto=n % 90, id_do_evento=f"ev-{n}") for n in range(1, 41))
        ambiente = Ambiente()
        await ambiente.rodar(muitos, lote=10)
        assert len(ambiente.lineage.records) == 40


class TestARevisaoNoRegistro:
    """§22, §23, §100. O anterior sobrevive no registro."""

    async def test_a_correcao_marca_o_anterior_como_corrigido(self) -> None:
        original = gol(1, id_do_evento="ev-1")
        correcao = evento(
            2,
            tipo="goal",
            minuto=24,
            id_do_evento="ev-1c",
            jogador=REF_DO_ARTILHEIRO,
            revisao=EventRevisionKind.CORRECTION,
            substitui="ev-1",
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        ambiente = Ambiente()
        await ambiente.rodar((original, correcao))

        assert len(ambiente.events.events) == 2
        estados = {e.status for e in ambiente.events.events.values()}
        assert estados == {EventStatus.CORRECTED, EventStatus.ACTIVE}

    async def test_a_leitura_normal_esconde_o_corrigido_e_nao_o_apaga(self) -> None:
        original = gol(1, id_do_evento="ev-1")
        correcao = evento(
            2,
            tipo="goal",
            minuto=24,
            id_do_evento="ev-1c",
            jogador=REF_DO_ARTILHEIRO,
            revisao=EventRevisionKind.CORRECTION,
            substitui="ev-1",
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        ambiente = Ambiente()
        await ambiente.rodar((original, correcao))

        atuais = await ambiente.events.events_of_match(PARTIDA)
        todos = await ambiente.events.events_of_match(PARTIDA, include_superseded=True)
        assert len(atuais) == 1
        assert len(todos) == 2

    async def test_o_cancelamento_preserva_o_evento_anulado(self) -> None:
        original = gol(1, id_do_evento="ev-1")
        cancelamento = evento(
            2,
            tipo="goal",
            minuto=23,
            id_do_evento="ev-1x",
            jogador=REF_DO_ARTILHEIRO,
            revisao=EventRevisionKind.CANCELLATION,
            substitui="ev-1",
            detalhes={"EVENT_OUTCOME": "GOAL"},
        )
        ambiente = Ambiente()
        await ambiente.rodar((original, cancelamento))

        assert len(ambiente.events.events) == 1
        unico = next(iter(ambiente.events.events.values()))
        assert unico.status is EventStatus.CANCELLED

    async def test_a_leitura_e_deterministicamente_ordenada(self) -> None:
        """§65, §66. Ela vai alimentar janelas móveis no PR-05."""
        ambiente = Ambiente()
        await ambiente.rodar(UM_JOGO)
        lidos = await ambiente.events.events_of_match(PARTIDA)
        minutos = [e.clock.minute for e in lidos]
        assert minutos == sorted(minutos)


class TestALinhagemPersistida:
    async def test_o_que_nao_entrou_tambem_deixa_linha(self) -> None:
        ambiente = Ambiente()
        await ambiente.rodar((gol(1), tipo_desconhecido(7)))
        recusados = ambiente.lineage.by_status(EventBuildRecordStatus.REVIEW_REQUIRED)
        assert len(recusados) == 1
        assert recusados[0].raw_type == "corner_won"

    async def test_a_linhagem_e_idempotente_por_execucao_e_chave(self) -> None:
        ambiente = Ambiente()
        await ambiente.rodar(UM_JOGO)
        gravadas = len(ambiente.lineage.records)
        await ambiente.lineage.append_many(list(ambiente.lineage.records.values()))
        assert len(ambiente.lineage.records) == gravadas
        assert ambiente.lineage.ignorados == gravadas
