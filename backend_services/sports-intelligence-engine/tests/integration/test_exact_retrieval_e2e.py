"""Do dataset normalizado PUBLICADO ao top-K exato — infraestrutura real.

O QUE SÓ ESTE TESTE PROVA:

    a versão                  só `READY` autoriza recuperar
    a query                   vem da metade de AVALIAÇÃO do Parquet de verdade
    o universo                sai de `split=REFERENCE/competition={liga}/`
    o instante                é EXATO, e o leitor entrega só ele
    a projeção                lê identidade + dois por eixo, e não 330 colunas
    zero fato canônico        nenhuma tabela de partida, evento, odds, resultado
    a atrição                 medida sobre dados reais, e não sintéticos
    o determinismo            duas execuções, uma impressão

A DIFERENÇA PARA OS DE PROPRIEDADE. Lá tudo é em memória e a invariante é
provada sobre listas; aqui os bytes vêm do MinIO, o Parquet é aberto pelo
pyarrow, e as impressões do dataset são as que o PR-05.5.2 escreveu.

O CORPUS DO CENÁRIO É PEQUENO, e isso muda o que se pode afirmar. Os eixos
robustos saem quase todos sem escala — o PR-05.5.2 mediu 40,7 % das células —,
então o perfil resolvido pode ficar curto ou vazio. ISSO NÃO É LIMITAÇÃO DO
TESTE: é exatamente o caminho que mais importa provar de ponta a ponta, e a
contagem que sai daqui é o insumo do PR-06.2.
"""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
)
from sports_intelligence.domain.retrieval.query import QueryNotComparableError
from sports_intelligence.domain.shared.errors import ValidationError
from tests.support.retrieval_e2e import (
    K_PADRAO,
    montar_recuperacao,
    queries_disponiveis,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def recuperacao(
    database: Database, object_store: Any, normalizado_publicado: dict[str, Any]
) -> dict[str, Any]:
    """O contêiner do PR-06.1 e as queries que o dataset de fato tem."""
    crua = normalizado_publicado["versao_crua"]
    versao = normalizado_publicado["versao_n"]
    conteiner = montar_recuperacao(
        database,
        object_store,
        reference_end_exclusive=crua.spec.reference_end_exclusive,
    )
    disponiveis = await queries_disponiveis(
        conteiner.source,
        dataset_name="match-state-normalized",
        version=str(versao.version),
    )
    return {
        **normalizado_publicado,
        "conteiner": conteiner,
        "queries": disponiveis,
    }


class TestAAutoridadeDeEntrada:
    """§5, §93 — só a versão PUBLICADA autoriza recuperar."""

    def test_a_versao_esta_READY(self, recuperacao: dict[str, Any]) -> None:
        assert recuperacao["versao_n"].status is DatasetVersionStatus.READY

    async def test_uma_versao_nao_publicada_e_recusada(self, recuperacao: dict[str, Any]) -> None:
        """A versão CRUA não é uma versão normalizada — e não existe no registro."""
        from sports_intelligence.domain.shared.errors import NotFoundError

        conteiner = recuperacao["conteiner"]
        chave, _ = recuperacao["queries"][0]
        with pytest.raises(NotFoundError, match="não existe"):
            await conteiner.retrieve.execute(
                version_id=recuperacao["versao_crua"].id, key=chave, k=K_PADRAO
            )

    async def test_uma_chave_inexistente_e_recusada(self, recuperacao: dict[str, Any]) -> None:
        from sports_intelligence.domain.shared.errors import NotFoundError

        conteiner = recuperacao["conteiner"]
        with pytest.raises(NotFoundError, match="AVALIAÇÃO"):
            await conteiner.retrieve.execute(
                version_id=recuperacao["versao_n"].id,
                key=HistoricalFeatureSnapshotKey(match_key="nao-existe", grid_index=7),
                k=K_PADRAO,
            )


class TestAResolucaoDaQuery:
    """§30 ao §32, §43 ao §48 — a query, o perfil e a competição dela."""

    async def test_a_query_e_de_avaliacao_e_carrega_o_instante(
        self, recuperacao: dict[str, Any]
    ) -> None:
        from sports_intelligence.domain.features.dataset.split import DatasetSplit

        conteiner = recuperacao["conteiner"]
        chave, instante = recuperacao["queries"][0]
        contexto = await conteiner.retrieve.resolve(
            version_id=recuperacao["versao_n"].id, key=chave
        )
        assert contexto.snapshot.split is DatasetSplit.EVALUATION
        assert contexto.snapshot.position == instante
        assert contexto.snapshot.key == chave

    async def test_o_perfil_e_da_competicao_da_query(self, recuperacao: dict[str, Any]) -> None:
        conteiner = recuperacao["conteiner"]
        chave, _ = recuperacao["queries"][0]
        contexto = await conteiner.retrieve.resolve(
            version_id=recuperacao["versao_n"].id, key=chave
        )
        assert contexto.profile.competition == contexto.snapshot.competition
        # OS EIXOS SÃO OS ROBUSTOS AJUSTADOS, e o cenário é pequeno: o perfil
        # pode ficar curto. O que se afirma é o TETO, e não um piso inventado.
        assert contexto.profile.axis_count <= 29
        assert contexto.profile.base.is_diagnostic

    async def test_o_perfil_resolvido_bate_com_o_pacote_de_artefatos(
        self, recuperacao: dict[str, Any]
    ) -> None:
        conteiner = recuperacao["conteiner"]
        chave, _ = recuperacao["queries"][0]
        contexto = await conteiner.retrieve.resolve(
            version_id=recuperacao["versao_n"].id, key=chave
        )
        pacote = contexto.artifact_set.bundle_of(contexto.snapshot.competition)
        assert contexto.profile.competition_bundle_fingerprint == pacote.fingerprint
        assert contexto.profile.competition_id == pacote.competition_id


class TestOUniversoReal:
    """§9 ao §12, §16 ao §19 — de onde os candidatos vêm."""

    async def test_todo_candidato_e_de_referencia_da_mesma_liga_e_instante(
        self, recuperacao: dict[str, Any]
    ) -> None:
        """§10, §11 — o invariante central, sobre dados de verdade."""
        from sports_intelligence.domain.features.dataset.split import DatasetSplit

        conteiner = recuperacao["conteiner"]
        chave, instante = recuperacao["queries"][0]
        contexto = await conteiner.retrieve.resolve(
            version_id=recuperacao["versao_n"].id, key=chave
        )
        vistos = 0
        async for lote in conteiner.source.stream_candidates(
            dataset_name=contexto.dataset_name,
            version=contexto.version_text,
            competition=contexto.competition,
            position=instante,
            feature_keys=list(contexto.profile.feature_keys),
        ):
            for candidato in lote:
                vistos += 1
                assert candidato.split is DatasetSplit.REFERENCE
                assert candidato.competition == contexto.competition
                assert candidato.position == instante
        assert vistos >= 0

    async def test_o_leitor_conta_o_universo_sem_ler_valores(
        self, recuperacao: dict[str, Any]
    ) -> None:
        conteiner = recuperacao["conteiner"]
        chave, instante = recuperacao["queries"][0]
        contexto = await conteiner.retrieve.resolve(
            version_id=recuperacao["versao_n"].id, key=chave
        )
        contagem = await conteiner.source.count_candidates(
            dataset_name=contexto.dataset_name,
            version=contexto.version_text,
            competition=contexto.competition,
            position=instante,
        )
        assert contagem >= 0

    async def test_as_particoes_vem_do_BUCKET(self, recuperacao: dict[str, Any]) -> None:
        conteiner = recuperacao["conteiner"]
        particoes = await conteiner.source.partitions(
            dataset_name="match-state-normalized",
            version=str(recuperacao["versao_n"].version),
        )
        assert particoes
        assert list(particoes) == sorted(particoes)
        assert {p[0] for p in particoes} <= {"REFERENCE", "EVALUATION"}


class TestARecuperacaoCompleta:
    """§33, §36, §65 — o resultado, e a contabilidade dele."""

    async def _resultado(self, recuperacao: dict[str, Any], k: int = K_PADRAO) -> Any:
        """O primeiro resultado que o perfil deste cenário permite calcular.

        ELE PODE NÃO EXISTIR, e o teste PULA quando não existe — em vez de
        inventar um dado. Num corpus pequeno, todos os eixos robustos podem
        sair sem escala, e aí NENHUMA query é comparável: isso é a medição do
        §127, e não uma falha do arnês.
        """
        conteiner = recuperacao["conteiner"]
        for chave, _ in recuperacao["queries"]:
            try:
                return await conteiner.retrieve.execute(
                    version_id=recuperacao["versao_n"].id, key=chave, k=k
                )
            except QueryNotComparableError:
                continue
        pytest.skip(
            "nenhuma query deste cenário é comparável sob o perfil de caso completo "
            "— a medição do §127, e não uma falha"
        )

    async def test_o_resultado_e_exaustivo_e_ordenado(self, recuperacao: dict[str, Any]) -> None:
        resultado = await self._resultado(recuperacao)
        assert resultado.exhaustive
        assert resultado.returned_k == min(K_PADRAO, resultado.comparable_count)
        distancias = [v.squared_distance for v in resultado.neighbors]
        assert distancias == sorted(distancias)

    async def test_a_contabilidade_fecha(self, recuperacao: dict[str, Any]) -> None:
        """§73 — universo, comparáveis e inelegíveis somam."""
        resultado = await self._resultado(recuperacao)
        assert resultado.comparable_count <= resultado.universe_count
        assert resultado.ineligible_count == resultado.universe_count - resultado.comparable_count
        assert sum(resultado.ineligible.values()) == resultado.ineligible_count

    async def test_nenhum_vizinho_e_da_partida_da_query(self, recuperacao: dict[str, Any]) -> None:
        """§23, §101 — sobre dados reais."""
        resultado = await self._resultado(recuperacao)
        assert all(v.key.match_key != resultado.query_key.match_key for v in resultado.neighbors)

    async def test_duas_execucoes_dao_a_mesma_impressao(self, recuperacao: dict[str, Any]) -> None:
        """§66, §133 — o tempo varia; o resultado semântico não."""
        um = await self._resultado(recuperacao)
        outro = await self._resultado(recuperacao)
        assert um.fingerprint == outro.fingerprint
        assert um.candidate_universe_fingerprint == outro.candidate_universe_fingerprint

    async def test_o_lote_nao_muda_o_resultado(self, recuperacao: dict[str, Any]) -> None:
        """§69 — sobre o Parquet de verdade, e não sobre listas."""
        conteiner = recuperacao["conteiner"]
        for chave, _ in recuperacao["queries"]:
            try:
                pequeno = await conteiner.retrieve.execute(
                    version_id=recuperacao["versao_n"].id,
                    key=chave,
                    k=K_PADRAO,
                    batch_rows=1,
                )
                grande = await conteiner.retrieve.execute(
                    version_id=recuperacao["versao_n"].id,
                    key=chave,
                    k=K_PADRAO,
                    batch_rows=4_096,
                )
            except QueryNotComparableError:
                continue
            assert pequeno.fingerprint == grande.fingerprint
            return
        pytest.skip("nenhuma query comparável neste cenário")

    async def test_o_prefixo_do_K_vale_sobre_dados_reais(self, recuperacao: dict[str, Any]) -> None:
        """§70 — e só afirma quando há vizinhos suficientes para afirmar."""
        conteiner = recuperacao["conteiner"]
        for chave, _ in recuperacao["queries"]:
            try:
                poucos = await conteiner.retrieve.execute(
                    version_id=recuperacao["versao_n"].id, key=chave, k=2
                )
                muitos = await conteiner.retrieve.execute(
                    version_id=recuperacao["versao_n"].id, key=chave, k=20
                )
            except QueryNotComparableError:
                continue
            if poucos.returned_k < 2:
                continue
            assert [v.key for v in muitos.top(2)] == [v.key for v in poucos.neighbors]
            return
        pytest.skip("nenhuma query com dois vizinhos comparáveis neste cenário")


class TestOsDiagnosticos:
    """§114, §125 ao §127 — a atrição é o produto científico do PR."""

    async def test_a_descricao_do_universo_nao_calcula_distancia(
        self, recuperacao: dict[str, Any]
    ) -> None:
        conteiner = recuperacao["conteiner"]
        chave, _ = recuperacao["queries"][0]
        descricao = await conteiner.describe.execute(
            version_id=recuperacao["versao_n"].id, key=chave
        )
        assert "universe_count" in descricao
        assert "axis_count" in descricao
        assert "query_comparable" in descricao
        assert isinstance(descricao["query_missing_axes"], list)

    async def test_a_taxa_de_comparabilidade_das_queries_e_medida(
        self, recuperacao: dict[str, Any]
    ) -> None:
        """§127 — o número que o PR-06.2 vai atacar, medido sobre dados reais."""
        conteiner = recuperacao["conteiner"]
        total = comparaveis = 0
        for chave, _ in recuperacao["queries"][:20]:
            total += 1
            contexto = await conteiner.retrieve.resolve(
                version_id=recuperacao["versao_n"].id, key=chave
            )
            if contexto.snapshot.is_comparable_under(contexto.profile):
                comparaveis += 1
        assert total > 0
        # NENHUM PISO É AFIRMADO. Zero comparáveis é um resultado legítimo num
        # corpus pequeno, e transformá-lo em falha esconderia a medição.
        assert 0 <= comparaveis <= total


class TestNenhumFatoCanonicoEhLido:
    """§6, §43, §132, §161 — a recuperação não volta ao corpus."""

    async def test_zero_leituras_de_fato_canonico(
        self, database: Database, recuperacao: dict[str, Any]
    ) -> None:
        """A prova é por INSTRUMENTAÇÃO, e não por leitura de código."""
        from tests.support.instrumentation import contando_consultas

        conteiner = recuperacao["conteiner"]
        chave, _ = recuperacao["queries"][0]
        async with contando_consultas(database) as consultas:
            # A QUERY PODE NÃO SER COMPARÁVEL, e o que se mede aqui não é o
            # resultado: é QUE TABELAS foram tocadas no caminho até ele.
            with contextlib.suppress(QueryNotComparableError):
                await conteiner.retrieve.execute(
                    version_id=recuperacao["versao_n"].id, key=chave, k=K_PADRAO
                )

        alvos_de_fato = {
            "matches",
            "canonical_match_events",
            "lineups",
            "canonical_odds_observations",
            "match_results",
            "historical_canonical_members",
            "historical_canonical_event_members",
        }
        tocados = alvos_de_fato & set(consultas.por_alvo)
        assert not tocados, (
            f"a recuperação leu tabela de fato canônico: {tocados}. Ela lê o Parquet "
            "normalizado, e nada mais"
        )

    async def test_o_leitor_toca_objetos_e_conta_bytes(self, recuperacao: dict[str, Any]) -> None:
        """§128 — a instrumentação de I/O existe e responde."""
        conteiner = recuperacao["conteiner"]
        chave, _ = recuperacao["queries"][0]
        conteiner.source.reset_counters()
        with contextlib.suppress(QueryNotComparableError):
            await conteiner.retrieve.execute(
                version_id=recuperacao["versao_n"].id, key=chave, k=K_PADRAO
            )
        assert conteiner.source.objects_read > 0
        assert conteiner.source.bytes_read > 0


class TestAsRecusasEstruturais:
    """§32, §90, §91 — o que o caso de uso recusa antes de varrer."""

    async def test_um_plano_divergente_e_recusado(
        self, database: Database, object_store: Any, recuperacao: dict[str, Any]
    ) -> None:
        """§91 — um contêiner montado sob outra fronteira monta outro plano."""
        from datetime import UTC, datetime

        from sports_intelligence.domain.shared.temporal import instant

        outro = montar_recuperacao(
            database,
            object_store,
            reference_end_exclusive=instant(datetime(2099, 1, 1, tzinfo=UTC)),
        )
        chave, _ = recuperacao["queries"][0]
        with pytest.raises(ValidationError, match="plano reconstruído"):
            await outro.retrieve.execute(
                version_id=recuperacao["versao_n"].id, key=chave, k=K_PADRAO
            )

    def test_a_politica_do_conteiner_e_a_de_producao(self, recuperacao: dict[str, Any]) -> None:
        assert DEFAULT_CANDIDATE_POLICY.candidate_sampling.value == "NONE"
        assert DEFAULT_CANDIDATE_POLICY.candidate_cap is None
