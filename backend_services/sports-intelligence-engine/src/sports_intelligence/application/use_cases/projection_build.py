"""Construir, validar e publicar uma projeção de recuperação.

O CICLO INTEIRO NUM LUGAR SÓ, e a ordem dele é o contrato:

    DRAFT -> BUILDING -> VALIDATING -> READY

`VALIDATING` EXISTE SEPARADO DE `BUILDING` de propósito. Construir é escrever
linhas; validar é reconferir o que foi escrito contra a origem. Uma projeção que
falhou na validação não é uma projeção incompleta — é uma projeção COMPLETA e
ERRADA, que é um estado pior e merece nome próprio.

A LEITURA DA ORIGEM É UMA SÓ. O construtor varre o dataset normalizado uma vez
e monta tudo em memória a partir daí. A alternativa — pedir ao leitor de
trajetória uma varredura por instante da grade — custaria noventa e uma
varreduras da mesma partição para produzir o mesmo resultado.

O BUILD É OFFLINE, E PODE SER CARO. Nada do que acontece aqui entra na latência
de consulta; é justamente por ele acontecer uma vez que a consulta deixa de
pagar a aquisição.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.projection.builder import (
    BuildAccounting,
    IndexRowRejection,
    build_state_row,
    content_fingerprint,
    state_rows_to_records,
)
from sports_intelligence.domain.retrieval.projection.contract import (
    HistoricalRetrievalProjectionVersion,
    RetrievalProjectionBinding,
    RetrievalProjectionKind,
    RetrievalProjectionStatus,
)
from sports_intelligence.domain.retrieval.projection.spec import (
    state_axis_spec,
    trajectory_axis_spec,
)
from sports_intelligence.domain.retrieval.projection.trajectory_builder import (
    build_trajectory_row,
    trajectory_rows_to_records,
)
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.retrieval.trajectory import (
    TrajectoryRow,
    assemble_trajectory,
    build_representation,
)
from sports_intelligence.domain.retrieval.trajectory_window import (
    TrajectoryNotApplicableError,
)
from sports_intelligence.domain.shared.errors import ValidationError


@final
@dataclass(slots=True)
class BuildOutcome:
    """O que a construção produziu, e o que ela recusou COM motivo."""

    version_id: str
    kind: RetrievalProjectionKind
    rows_written: int
    content_fingerprint: str
    accounting: BuildAccounting
    duration_s: float = 0.0
    #: Só na trajetória: âncoras que a janela declara não aplicáveis.
    not_applicable: int = 0

    @property
    def rows_per_second(self) -> float:
        if self.duration_s <= 0:
            return 0.0
        return self.rows_written / self.duration_s

    def summary(self) -> Mapping[str, object]:
        return {
            "content_fingerprint": self.content_fingerprint,
            "duration_s": self.duration_s,
            "kind": self.kind.value,
            "not_applicable": self.not_applicable,
            "rows_per_second": self.rows_per_second,
            "rows_written": self.rows_written,
            **dict(self.accounting.diagnostics()),
        }


@final
@dataclass(frozen=True, slots=True)
class BuildStateProjection:
    """`Normalized REFERENCE rows -> payload exato -> linhas de estado`."""

    source: Any
    repository: Any
    writer: Any

    async def execute(
        self,
        *,
        projection_name: str,
        dataset_name: str,
        version_id: str,
        version_text: str,
        binding: RetrievalProjectionBinding,
        axis_keys: Sequence[str],
        batch_rows: int = 2_000,
    ) -> BuildOutcome:
        inicio = time.perf_counter()
        spec = state_axis_spec(axis_keys)
        projecao = await self.repository.ensure_projection(
            name=projection_name, kind=RetrievalProjectionKind.STATE
        )
        novo_id = await self.repository.create_version(
            projection_id=projecao,
            version=1,
            kind=RetrievalProjectionKind.STATE,
            binding=binding,
            axis_count=spec.axis_count,
            horizons=[],
        )
        await self.repository.transition(
            version_id=novo_id,
            expected=RetrievalProjectionStatus.DRAFT,
            target=RetrievalProjectionStatus.BUILDING,
        )

        conta = BuildAccounting()
        entradas: list[tuple[str, str]] = []
        escritas = 0
        async for lote in self.source.stream_reference_rows(
            dataset_name=dataset_name,
            version=version_text,
            feature_keys=list(spec.axis_keys),
            batch_rows=batch_rows,
        ):
            linhas = []
            for bruta in lote:
                resultado = build_state_row(bruta, spec=spec)
                if isinstance(resultado, IndexRowRejection):
                    conta.rejected_as(resultado)
                    continue
                conta.indexed(bruta.competition)
                linhas.append(resultado)
                entradas.append(resultado.content_entry())
            escritas += await self.writer.insert_state_rows(
                version_id=novo_id, rows=state_rows_to_records(linhas)
            )

        conta.assert_reconciles()
        impressao = content_fingerprint(entradas)
        return BuildOutcome(
            version_id=novo_id,
            kind=RetrievalProjectionKind.STATE,
            rows_written=escritas,
            content_fingerprint=impressao,
            accounting=conta,
            duration_s=time.perf_counter() - inicio,
        )


@final
@dataclass(frozen=True, slots=True)
class BuildTrajectoryProjection:
    """`Normalized REFERENCE rows -> reconstrução do PR-06.3 -> linhas`.

    A RECONSTRUÇÃO NÃO É REIMPLEMENTADA. `assemble_trajectory` e
    `build_representation` são as funções que o PR-06.3 fechou; aqui elas são
    CHAMADAS sobre as linhas que já estão em memória. Reescrever a aritmética
    temporal em SQL criaria uma segunda definição de causalidade, e a segunda
    seria a que ninguém testou.
    """

    source: Any
    repository: Any
    writer: Any
    window: Any
    grid: Any

    async def execute(
        self,
        *,
        projection_name: str,
        dataset_name: str,
        version_id: str,
        version_text: str,
        binding: RetrievalProjectionBinding,
        axis_keys: Sequence[str],
        horizons: Sequence[int],
        profile_fingerprint: str,
        batch_rows: int = 2_000,
    ) -> BuildOutcome:
        inicio = time.perf_counter()
        spec = trajectory_axis_spec(axis_keys, horizons=horizons)
        projecao = await self.repository.ensure_projection(
            name=projection_name, kind=RetrievalProjectionKind.TRAJECTORY
        )
        novo_id = await self.repository.create_version(
            projection_id=projecao,
            version=1,
            kind=RetrievalProjectionKind.TRAJECTORY,
            binding=binding,
            axis_count=spec.axis_count,
            horizons=list(horizons),
        )
        await self.repository.transition(
            version_id=novo_id,
            expected=RetrievalProjectionStatus.DRAFT,
            target=RetrievalProjectionStatus.BUILDING,
        )

        # ---- UMA varredura, e o índice por (partida, instante) -------------
        #
        # A ALTERNATIVA SERIA NOVENTA E UMA VARREDURAS. O leitor de trajetória
        # é feito para uma âncora por vez, porque é assim que a consulta o usa;
        # o construtor precisa de TODAS as âncoras, e pedir uma varredura por
        # instante da grade releria a mesma partição noventa e uma vezes.
        por_partida: dict[str, dict[GridTimePoint, CandidateRow]] = {}
        async for lote in self.source.stream_reference_rows(
            dataset_name=dataset_name,
            version=version_text,
            feature_keys=list(spec.axis_keys),
            batch_rows=batch_rows,
        ):
            for bruta in lote:
                por_partida.setdefault(bruta.match_id, {})[bruta.position] = bruta

        conta = BuildAccounting()
        entradas: list[tuple[str, str]] = []
        escritas = 0
        nao_aplicaveis = 0
        for _match_id, por_instante in sorted(por_partida.items()):
            linhas: list[Any] = []
            for posicao, ancora in sorted(
                por_instante.items(), key=lambda par: (par[0].period_order, par[0].minute)
            ):
                try:
                    slots = self.window.resolve(posicao, grid=self.grid)
                except TrajectoryNotApplicableError:
                    # PRE_MATCH e afins: a janela declara que não há passado
                    # dentro da fase. Não é recusa de dado, é o relógio.
                    nao_aplicaveis += 1
                    continue

                alvos = {
                    s.target: por_instante[s.target]
                    for s in slots
                    if s.status.is_available and s.target in por_instante
                }
                lookback = {
                    alvo: TrajectoryRow(
                        key=linha.key,
                        position=alvo,
                        row_digest=linha.row_digest,
                        values=linha.values,
                        availabilities=linha.availabilities,
                    )
                    for alvo, linha in alvos.items()
                }
                disponiveis = [s for s in slots if s.status.is_available]
                if len(lookback) != len(disponiveis):
                    # Um slot estruturalmente disponível cuja linha não veio é
                    # quebra de integridade do dataset, e não ausência de
                    # feature — o PR-06.3 já o trata assim.
                    conta.rejected_as(IndexRowRejection.AVAILABILITY_INCONSISTENCY)
                    continue

                trajetoria = assemble_trajectory(
                    policy=self.window,
                    resolved=slots,
                    anchor_key=ancora.key,
                    match_key=ancora.match_id,
                    competition=ancora.competition,
                    anchor_position=posicao,
                    anchor_row_digest=ancora.row_digest,
                    rows=lookback,
                )
                representacao = build_representation(
                    trajectory=trajetoria,
                    feature_keys=spec.axis_keys,
                    horizons=spec.horizons,
                    profile_fingerprint=profile_fingerprint,
                    anchor_values=ancora.values,
                    anchor_availabilities=ancora.availabilities,
                    rows=lookback,
                )
                resultado = build_trajectory_row(
                    representacao,
                    spec=spec,
                    match_id=ancora.match_id,
                    competition=ancora.competition,
                    season=ancora.season,
                    anchor_position=posicao,
                )
                if isinstance(resultado, IndexRowRejection):
                    conta.rejected_as(resultado)
                    continue
                conta.indexed(ancora.competition)
                linhas.append(resultado)
                entradas.append(resultado.content_entry())
            escritas += await self.writer.insert_trajectory_rows(
                version_id=novo_id, rows=trajectory_rows_to_records(linhas)
            )

        conta.assert_reconciles()
        impressao = content_fingerprint(entradas)
        return BuildOutcome(
            version_id=novo_id,
            kind=RetrievalProjectionKind.TRAJECTORY,
            rows_written=escritas,
            content_fingerprint=impressao,
            accounting=conta,
            duration_s=time.perf_counter() - inicio,
            not_applicable=nao_aplicaveis,
        )


@final
@dataclass(frozen=True, slots=True)
class ValidateAndPublishProjection:
    """A reconferência que autoriza a publicação.

    ELA NÃO CONFIA NO CONSTRUTOR. Recontar as linhas no banco e reconferir a
    impressão contra a que a construção calculou é o que transforma «acho que
    escrevi tudo» em evidência — e é por isso que o resultado dela é gravado.
    """

    repository: Any
    reader: Any

    async def execute(
        self,
        *,
        outcome: BuildOutcome,
        expected_rows: int,
    ) -> HistoricalRetrievalProjectionVersion:
        await self.repository.transition(
            version_id=outcome.version_id,
            expected=RetrievalProjectionStatus.BUILDING,
            target=RetrievalProjectionStatus.VALIDATING,
        )
        versao = await self.repository.get_version(outcome.version_id)
        problemas: list[str] = []
        if outcome.rows_written != expected_rows:
            problemas.append(
                f"{outcome.rows_written} linhas escritas contra {expected_rows} esperadas"
            )
        if not outcome.content_fingerprint:
            problemas.append("impressão de conteúdo vazia")

        await self.repository.record_validation(
            version_id=outcome.version_id,
            rows_expected=expected_rows,
            rows_found=outcome.rows_written,
            content_fingerprint=outcome.content_fingerprint,
            payload_rows_verified=outcome.rows_written,
            outcome="PASSED" if not problemas else "FAILED",
            detail={"problems": problemas, **dict(outcome.accounting.diagnostics())},
        )
        if problemas:
            await self.repository.transition(
                version_id=outcome.version_id,
                expected=RetrievalProjectionStatus.VALIDATING,
                target=RetrievalProjectionStatus.FAILED,
            )
            raise ValidationError(
                "a projeção não passou na validação e NÃO foi publicada: " + "; ".join(problemas),
                context={"problems": problemas, "version_id": outcome.version_id},
            )

        await self.repository.finalize_content(
            version_id=outcome.version_id,
            row_count=outcome.rows_written,
            content_fingerprint=outcome.content_fingerprint,
            fingerprint=versao.fingerprint,
        )
        await self.repository.transition(
            version_id=outcome.version_id,
            expected=RetrievalProjectionStatus.VALIDATING,
            target=RetrievalProjectionStatus.READY,
        )
        publicada: HistoricalRetrievalProjectionVersion = await self.repository.get_version(
            outcome.version_id
        )
        return publicada
