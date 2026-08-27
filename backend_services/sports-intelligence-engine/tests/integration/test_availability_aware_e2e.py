"""O E2E do PR-06.2 — cobertura, penalidade e evidência sobre dados reais.

PostgreSQL 17 e object store de verdade, dataset normalizado `READY`, e um
corpus construído pelo caminho INTEIRO. Nada é montado em memória.

O CENÁRIO CONTÉM AUSÊNCIA DE PROPÓSITO (§139, §140), e a medição está no
cabeçalho de `availability_scenario`:

    perfil     6 eixos — xG em janela de 10 min e o gap até a partida anterior
    piso       `5s >= 18`  ->  `s >= 4`, e o mínimo absoluto também é 4
    universo   candidatos com s = 6, s = 4 e s = 3

    s = 6   caso completo, e o ranking deles bate com o do PR-06.1
    s = 4   EXATAMENTE no piso — um eixo a menos e seriam recusados
    s = 3   ABAIXO do piso, contados e sem distância

UM E2E EM QUE TODO CANDIDATO TIVESSE COBERTURA CHEIA passaria sem tocar nada do
que este PR introduziu. É por isso que a variedade acima é uma PRÉ-CONDIÇÃO
verificada logo no primeiro teste: se ela sumir, os outros deixam de significar
o que dizem significar.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from sports_intelligence.domain.retrieval.availability import (
    availability_mask,
    count,
    shared_mask,
)
from sports_intelligence.domain.retrieval.candidate_policy import IneligibilityReason
from sports_intelligence.domain.retrieval.coverage import (
    DEFAULT_COVERAGE_POLICY,
    AvailabilityCoveragePolicy,
    QueryInsufficientCoverageError,
    RationalFloor,
)
from sports_intelligence.domain.retrieval.profile import (
    AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
    DEFAULT_RETRIEVAL_PROFILE,
)

pytestmark = pytest.mark.integration

K = 5


@pytest.fixture
async def recuperacao(database: Any, object_store: Any) -> dict[str, Any]:
    """Corpus com ausência → dataset normalizado `READY` → contêiner."""
    from tests.support.availability_e2e import dataset_com_ausencia

    return await dataset_com_ausencia(database, object_store)


async def _queries(recuperacao: dict[str, Any], limite: int = 60) -> list[Any]:
    from tests.support.retrieval_e2e import queries_disponiveis

    return await queries_disponiveis(
        recuperacao["conteiner"].source,
        dataset_name="match-state-normalized",
        version=str(recuperacao["versao_n"].version),
        limite=limite,
    )


async def _uma(recuperacao: dict[str, Any]) -> Any:
    """A primeira query disponível, resolvida sob o perfil ciente."""
    queries = await _queries(recuperacao, limite=1)
    assert queries, "o cenário precisa ter queries de avaliação"
    return queries[0][0]


# ================================================= a pré-condição ==


class TestOCenarioTemAusenciaDeVerdade:
    """§139, §140 — sem isto, os outros testes não provam nada."""

    async def test_o_universo_tem_coberturas_diferentes(self, recuperacao: dict[str, Any]) -> None:
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        chave = await _uma(recuperacao)

        contexto = await conteiner.retrieve_aware.resolve(version_id=versao.id, key=chave)
        perfil = contexto.resolution.profile
        candidatos = await conteiner.retrieve.candidates(contexto.resolution)
        mascara_da_query = availability_mask(
            feature_keys=perfil.feature_keys,
            values=contexto.resolution.snapshot.values,
            availabilities=contexto.resolution.snapshot.availabilities,
            owner="query",
        )
        compartilhados = sorted(
            count(
                shared_mask(
                    mascara_da_query,
                    availability_mask(
                        feature_keys=perfil.feature_keys,
                        values=c.values,
                        availabilities=c.availabilities,
                        owner=c.key.text,
                    ),
                )
            )
            for c in candidatos
        )
        piso = DEFAULT_COVERAGE_POLICY
        m = perfil.axis_count

        assert len(set(compartilhados)) > 1, (
            "o universo tem cobertura uniforme: este E2E passaria sem tocar o piso "
            f"— {compartilhados}"
        )
        assert any(s == m for s in compartilhados), "faltam candidatos de caso completo"
        assert any(not piso.admits_pair(shared=s, profile_axes=m) for s in compartilhados), (
            f"nenhum candidato abaixo do piso — {compartilhados}"
        )
        assert any(
            piso.admits_pair(shared=s, profile_axes=m)
            and not piso.admits_pair(shared=s - 1, profile_axes=m)
            for s in compartilhados
        ), f"nenhum candidato EXATAMENTE no piso — {compartilhados}"

    async def test_o_perfil_tem_eixos_de_duas_familias(self, recuperacao: dict[str, Any]) -> None:
        """Uma família sempre disponível e outra parcialmente — é isso que move
        a cobertura de um lado para o outro da fronteira."""
        conteiner = recuperacao["conteiner"]
        contexto = await conteiner.retrieve_aware.resolve(
            version_id=recuperacao["versao_n"].id, key=await _uma(recuperacao)
        )
        chaves = contexto.resolution.profile.feature_keys
        assert any(k.startswith("xg_") for k in chaves)
        assert any(k.startswith("ctx_") for k in chaves)


class TestOMercadoEhEstruturalmenteIndisponivel:
    """A medição que desmentiu a primeira hipótese do cenário.

    ELA VIROU TESTE, e não nota de rodapé. O cenário publica cotações de
    verdade — elas chegam ao banco canônico —, e nenhum eixo de mercado fica
    disponível, porque uma cotação sem `observed_at` é `UNKNOWN` para a guarda
    temporal e o caminho de ingestão não tem papel semântico para esse carimbo.

    ISSO É O FAIL-CLOSED DO PR-05.1 FUNCIONANDO. O teste fixa o comportamento
    para que o dia em que alguém acrescentar o carimbo seja um dia em que este
    teste falha, e não um dia em que ninguém percebe.
    """

    async def test_as_cotacoes_chegam_ao_banco(
        self, database: Any, recuperacao: dict[str, Any]
    ) -> None:
        async with database.acquire() as conexao:
            total = await conexao.fetchval("SELECT count(*) FROM canonical_odds_observations")
            sem_carimbo = await conexao.fetchval(
                "SELECT count(*) FROM canonical_odds_observations WHERE observed_at IS NULL"
            )
        assert total > 0, "o cenário publica cotações: se elas sumirem, o teste seguinte mente"
        assert sem_carimbo == total

    async def test_e_nenhum_eixo_de_mercado_fica_disponivel(
        self, database: Any, recuperacao: dict[str, Any]
    ) -> None:
        async with database.acquire() as conexao:
            linhas = await conexao.fetch(
                """
                SELECT feature_key, status, available_count
                FROM normalizer_fit_artifacts
                WHERE set_id = $1 AND feature_key LIKE 'market_%'
                """,
                uuid.UUID(recuperacao["ajuste"].artifact_set.id),
            )
        assert linhas, "o plano tem eixos de mercado"
        assert all(linha["available_count"] == 0 for linha in linhas)
        assert all(linha["status"] == "INSUFFICIENT_SAMPLE" for linha in linhas)

    async def test_e_por_isso_eles_nao_entram_no_perfil(self, recuperacao: dict[str, Any]) -> None:
        contexto = await recuperacao["conteiner"].retrieve_aware.resolve(
            version_id=recuperacao["versao_n"].id, key=await _uma(recuperacao)
        )
        assert not [k for k in contexto.resolution.profile.feature_keys if k.startswith("market_")]


# ================================================= o universo ==


class TestOUniversoEhOMesmoDoPR061:
    """§5, §6, §43, §101 — a política não mudou, logo o universo não mudou."""

    async def test_a_impressao_do_universo_e_identica(self, recuperacao: dict[str, Any]) -> None:
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        chave = await _uma(recuperacao)

        ciente = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
        exato = await conteiner.retrieve.execute(version_id=versao.id, key=chave, k=K)

        assert ciente.candidate_universe_fingerprint == exato.candidate_universe_fingerprint
        assert ciente.universe_count == exato.universe_count
        assert ciente.candidate_policy_fingerprint == exato.candidate_policy_fingerprint

    async def test_os_dois_perfis_resolvem_os_mesmos_eixos(
        self, recuperacao: dict[str, Any]
    ) -> None:
        """§7, §10 — a diferença entre os dois é SÓ a política de ausência."""
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        chave = await _uma(recuperacao)

        completo = await conteiner.retrieve.resolve(
            version_id=versao.id, key=chave, profile=DEFAULT_RETRIEVAL_PROFILE
        )
        ciente = await conteiner.retrieve_aware.resolve(
            version_id=versao.id, key=chave, profile=AVAILABILITY_AWARE_RETRIEVAL_PROFILE
        )
        assert completo.profile.feature_keys == ciente.resolution.profile.feature_keys
        assert completo.profile.fingerprint != ciente.resolution.profile.fingerprint


# ================================================= a atrição ==


class TestAAtricaoEhContadaESeparada:
    """§63, §65 — cada candidato do universo cai numa das três contagens."""

    async def test_a_soma_fecha_com_o_universo(self, recuperacao: dict[str, Any]) -> None:
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        for chave, _ in await _queries(recuperacao, limite=12):
            resultado = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
            assert (
                resultado.coverage_eligible_count
                + resultado.coverage_ineligible_count
                + resultado.structural_ineligible_count
            ) == resultado.universe_count
            assert resultado.exhaustive

    async def test_o_candidato_abaixo_do_piso_e_contado_e_NAO_entra(
        self, recuperacao: dict[str, Any]
    ) -> None:
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        chave = await _uma(recuperacao)
        resultado = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=50)
        assert resultado.coverage_ineligible_count > 0
        assert (
            resultado.ineligible[IneligibilityReason.INSUFFICIENT_SHARED_COVERAGE.value]
            == resultado.coverage_ineligible_count
        )
        # NENHUM VIZINHO DEVOLVIDO ESTÁ ABAIXO DO PISO — a garantia do §179.
        assert all(v.evidence.coverage.meets_shared_floor for v in resultado.neighbors)
        assert all(v.shared_count >= 4 for v in resultado.neighbors)

    async def test_a_recuperacao_de_candidatos_e_positiva(
        self, recuperacao: dict[str, Any]
    ) -> None:
        """§61, §76 — mais candidatos MEDIDOS, e o nome disso é recuperação."""
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        chave = await _uma(recuperacao)
        comparacao = await conteiner.compare.execute(version_id=versao.id, key=chave, k=K)

        assert comparacao.candidate_recovery > 0
        assert comparacao.availability_aware_eligible > comparacao.complete_case_comparable
        assert comparacao.universe_count > 0


# ================================================= a equivalência ==


class TestEquivalenciaComOCasoCompletoSobreDadosReais:
    """§41, §42, §90, §181 — o ranking dos completos é o do PR-06.1."""

    async def test_a_ordem_dos_completos_e_a_mesma(self, recuperacao: dict[str, Any]) -> None:
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        conferidas = 0
        for chave, _ in await _queries(recuperacao, limite=12):
            ciente = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=50)
            exato = await conteiner.retrieve.execute(version_id=versao.id, key=chave, k=50)
            if not exato.neighbors:
                continue
            conferidas += 1
            assert [v.key.text for v in ciente.complete_case_neighbors] == [
                v.key.text for v in exato.neighbors
            ]
            por_chave = {v.key.text: v.squared_distance for v in exato.neighbors}
            for vizinho in ciente.complete_case_neighbors:
                assert vizinho.dissimilarity == por_chave[vizinho.key.text] / ciente.axis_count
        assert conferidas > 0, "nenhuma query teve vizinho de caso completo"


# ================================================= o determinismo ==


class TestODeterminismoSobreOParquetReal:
    """§135, §137, §183 — o layout físico e o lote não podem decidir nada."""

    async def test_duas_execucoes_dao_a_mesma_impressao(self, recuperacao: dict[str, Any]) -> None:
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        chave = await _uma(recuperacao)
        primeira = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
        segunda = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
        assert primeira.fingerprint == segunda.fingerprint
        assert [v.evidence.fingerprint for v in primeira.neighbors] == [
            v.evidence.fingerprint for v in segunda.neighbors
        ]

    @pytest.mark.parametrize("lote", [1, 3, 4096])
    async def test_o_lote_nao_muda_o_resultado(
        self, recuperacao: dict[str, Any], lote: int
    ) -> None:
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        chave = await _uma(recuperacao)
        esperado = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
        obtido = await conteiner.retrieve_aware.execute(
            version_id=versao.id, key=chave, k=K, batch_rows=lote
        )
        assert obtido.fingerprint == esperado.fingerprint

    async def test_o_prefixo_do_K_vale_sobre_o_dataset_real(
        self, recuperacao: dict[str, Any]
    ) -> None:
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        chave = await _uma(recuperacao)
        grande = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=50)
        for k in (1, 2, 3):
            if k > grande.returned_k:
                break
            pequeno = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=k)
            assert [v.key.text for v in grande.top(k)] == [v.key.text for v in pequeno.neighbors]


# ================================================= o piso ==


class TestOPisoDecideSobreDadosReais:
    """§25, §86, §158 — a fronteira, exercitada nas duas direções."""

    async def test_um_piso_mais_alto_recusa_mais(self, recuperacao: dict[str, Any]) -> None:
        """A sensibilidade, executável: `1/1` só admite o caso completo."""
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        chave = await _uma(recuperacao)

        padrao = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=50)
        estrito = await conteiner.retrieve_aware.execute(
            version_id=versao.id,
            key=chave,
            k=50,
            coverage_policy=AvailabilityCoveragePolicy(
                name="CASO_COMPLETO_COMO_PISO",
                shared_coverage_floor=RationalFloor(1, 1),
            ),
        )
        assert estrito.coverage_eligible_count < padrao.coverage_eligible_count
        assert all(v.is_complete_case for v in estrito.neighbors)

    async def test_um_piso_mais_baixo_admite_mais(self, recuperacao: dict[str, Any]) -> None:
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        chave = await _uma(recuperacao)

        padrao = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=50)
        frouxo = await conteiner.retrieve_aware.execute(
            version_id=versao.id,
            key=chave,
            k=50,
            coverage_policy=AvailabilityCoveragePolicy(
                name="PISO_DE_METADE",
                minimum_shared_axes=1,
                minimum_query_available_axes=1,
                shared_coverage_floor=RationalFloor(1, 2),
                query_coverage_floor=RationalFloor(1, 2),
            ),
        )
        assert frouxo.coverage_eligible_count > padrao.coverage_eligible_count
        # E O PISO ENTRA NA IMPRESSÃO: os dois números não se confundem.
        assert frouxo.coverage_policy_fingerprint != padrao.coverage_policy_fingerprint
        assert frouxo.distance_definition_fingerprint != padrao.distance_definition_fingerprint

    async def test_uma_query_sem_cobertura_e_recusada_com_tipo_proprio(
        self, recuperacao: dict[str, Any]
    ) -> None:
        """§25, §86 — com um piso que a query não alcança, ela para.

        O PISO É FORÇADO PARA O CASO COMPLETO NA QUERY. O cenário produz
        queries com cobertura cheia neste instante, então a recusa é provocada
        pela política — que é o caminho que precisa estar testado.
        """
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        chave = await _uma(recuperacao)
        contexto = await conteiner.retrieve_aware.resolve(version_id=versao.id, key=chave)
        m = contexto.resolution.profile.axis_count

        with pytest.raises(QueryInsufficientCoverageError) as erro:
            await conteiner.retrieve_aware.execute(
                version_id=versao.id,
                key=chave,
                k=K,
                coverage_policy=AvailabilityCoveragePolicy(
                    name="QUERY_IMPOSSIVEL",
                    minimum_profile_axes=1,
                    minimum_query_available_axes=m + 1,
                    minimum_shared_axes=1,
                ),
            )
        assert erro.value.reason == "QUERY_INSUFFICIENT_COVERAGE"


# ================================================= a evidência ==


class TestAEvidenciaSobreDadosReais:
    """§182, §195 — todo vizinho reconstrói o próprio número."""

    async def test_toda_evidencia_fecha_a_conta(self, recuperacao: dict[str, Any]) -> None:
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        vistos = 0
        for chave, _ in await _queries(recuperacao, limite=8):
            resultado = await conteiner.retrieve_aware.execute(version_id=versao.id, key=chave, k=K)
            for vizinho in resultado.neighbors:
                vistos += 1
                prova = vizinho.evidence
                assert prova.is_reconstructible
                assert (
                    prova.observed_squared_sum + prova.missing_penalty_sum
                ) / resultado.axis_count == vizinho.dissimilarity
                assert prova.missing_penalty_sum == float(
                    resultado.axis_count - vizinho.shared_count
                )
        assert vistos > 0

    async def test_o_vizinho_parcial_carrega_incerteza_e_o_completo_nao(
        self, recuperacao: dict[str, Any]
    ) -> None:
        conteiner = recuperacao["conteiner"]
        versao = recuperacao["versao_n"]
        completos = parciais = 0
        for chave, _ in await _queries(recuperacao, limite=8):
            resultado = await conteiner.retrieve_aware.execute(
                version_id=versao.id, key=chave, k=50
            )
            for vizinho in resultado.neighbors:
                if vizinho.is_complete_case:
                    completos += 1
                    assert vizinho.evidence.missing_penalty_sum == 0.0
                else:
                    parciais += 1
                    assert vizinho.evidence.missing_penalty_sum > 0.0
                    assert vizinho.penalty_share is not None
        assert completos > 0
        assert parciais > 0, "nenhum vizinho parcial entrou no top-K"


# ================================================= a causalidade ==


class TestNenhumFatoCanonicoEhLido:
    """§49, §116 — medido por instrumentação, e não por leitura de código."""

    async def test_nenhuma_tabela_de_fato_e_tocada(
        self, database: Any, recuperacao: dict[str, Any]
    ) -> None:
        proibidas = (
            "canonical_match_events",
            "canonical_odds_observations",
            "lineups",
            "lineup_entries",
            "match_results",
            "historical_canonical_members",
            "historical_canonical_event_members",
        )
        consultas: list[str] = []
        original = database.acquire

        class _Espiao:
            def __init__(self, conexao: Any) -> None:
                self._c = conexao

            def __getattr__(self, nome: str) -> Any:
                alvo = getattr(self._c, nome)
                if nome not in {"fetch", "fetchrow", "fetchval", "execute", "executemany"}:
                    return alvo

                async def _registrar(sql: str, *args: Any, **kwargs: Any) -> Any:
                    consultas.append(sql)
                    return await alvo(sql, *args, **kwargs)

                return _registrar

        class _Contexto:
            def __init__(self, interno: Any) -> None:
                self._i = interno

            async def __aenter__(self) -> Any:
                return _Espiao(await self._i.__aenter__())

            async def __aexit__(self, *args: Any) -> Any:
                return await self._i.__aexit__(*args)

        database.acquire = lambda: _Contexto(original())
        try:
            await recuperacao["conteiner"].retrieve_aware.execute(
                version_id=recuperacao["versao_n"].id, key=await _uma(recuperacao), k=K
            )
        finally:
            database.acquire = original

        assert consultas, "a instrumentação não capturou consulta nenhuma"
        for sql in consultas:
            for tabela in proibidas:
                assert tabela not in sql.lower(), f"leu {tabela}: {sql[:120]}"
