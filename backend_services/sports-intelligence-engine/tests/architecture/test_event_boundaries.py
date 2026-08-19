"""Os limites da canonicalização de eventos (PR-04.4.1 §118, §119, §120).

O QUE ELES GUARDAM, e por que cada um importa aqui MAIS que nos anteriores:

    nada do PR-05        eventos são a matéria-prima de xG por ação, Player
                         Influence e Tactical Graph. É deste pacote que a
                         tentação de «já calcular enquanto lê» vem — e um
                         cálculo aqui viraria feature derivada disfarçada de
                         fato observado

    nada de corpus       o PR-04.4.1 termina no registro canônico (§80). Um
                         import de `domain/corpus` daqui significaria eventos
                         entrando numa versão publicada sem passar pelo gate

    xG é OBSERVADO       o motor não calcula xG neste PR (§119). O que a fonte
                         deu viaja; o que ela não deu fica ausente
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.support.ast_checks import (
    INFRA_EXTERNA,
    RAIZ,
    external_violations,
    files_in,
    internal_violations,
)

pytestmark = pytest.mark.architecture

#: Os pacotes de evento entregues neste PR.
PACOTES_DE_EVENTO = ("domain/events", "historical/events")

#: O que NENHUM deles pode conhecer.
PACOTES_FUTUROS = (
    "sports_intelligence.features",
    "sports_intelligence.engines",
    "sports_intelligence.ingestion.live",
    "sports_intelligence.adapters.pgvector",
    "sports_intelligence.adapters.clickhouse",
    "sports_intelligence.adapters.redis",
    "sports_intelligence.ports.vector_store",
    "sports_intelligence.ports.analytics_store",
    "sports_intelligence.ports.cache",
)


class TestOsLimitesDoPacoteDeEventos:
    @pytest.mark.parametrize("pacote", list(PACOTES_DE_EVENTO))
    def test_nao_importa_o_futuro(self, pacote: str) -> None:
        violacoes = internal_violations(files_in(pacote), PACOTES_FUTUROS)
        assert not violacoes, str(violacoes)

    def test_o_dominio_de_eventos_nao_importa_infraestrutura(self) -> None:
        violacoes = external_violations(files_in("domain/events"), INFRA_EXTERNA)
        assert not violacoes, str(violacoes)

    def test_o_dominio_de_eventos_nao_importa_adapters_nem_apps(self) -> None:
        violacoes = internal_violations(
            files_in("domain/events"),
            (
                "sports_intelligence.adapters",
                "sports_intelligence.application",
                "apps.",
            ),
        )
        assert not violacoes, str(violacoes)

    def test_a_canonicalizacao_nao_conhece_o_corpus(self) -> None:
        """§80. Este PR termina no registro canônico.

        Um import de `domain/corpus` aqui seria o primeiro passo para eventos
        entrarem numa versão publicada sem passar pelo gate — e o gate é o que
        separa «gravado» de «publicado».
        """
        violacoes = internal_violations(
            files_in("historical/events", "domain/events"),
            ("sports_intelligence.domain.corpus", "sports_intelligence.historical.corpus"),
        )
        assert not violacoes, str(violacoes)


class TestObservadoNaoEDerivado:
    """§119. Nenhum xG é calculado aqui."""

    def test_nada_calcula_xg(self) -> None:
        """A busca é por CÁLCULO, e não pela palavra: `xg` aparece o tempo
        todo — em campo, em papel semântico, em detalhe. O que não pode
        aparecer é aritmética produzindo um."""
        proibidos = {"expected_goals", "compute_xg", "calculate_xg", "estimate_xg"}
        encontrados: list[str] = []
        for arquivo in files_in(*PACOTES_DE_EVENTO):
            texto = arquivo.read_text(encoding="utf-8")
            encontrados.extend(f"{arquivo.name}: {n}" for n in proibidos if n in texto)
        assert not encontrados, "\n".join(encontrados)

    def test_o_xg_do_dominio_e_um_feature_value(self) -> None:
        """`FeatureValue` é o tipo que distingue «não medido» de «zero». Um
        `float` aqui teria feito xG ausente virar `0.0` no primeiro default."""
        from sports_intelligence.domain.events.details import ShotDetail

        anotacao = ShotDetail.__dataclass_fields__["xg"].type
        assert "FeatureValue" in str(anotacao)


class TestSemExecucaoDinamica:
    def test_a_canonicalizacao_nao_executa_nada(self) -> None:
        """A tabela de tipos vem de configuração e nunca vira código."""
        proibidos = {"eval", "exec", "compile", "__import__"}
        encontrados: list[str] = []
        for arquivo in files_in(*PACOTES_DE_EVENTO):
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
            for no in ast.walk(arvore):
                if not isinstance(no, ast.Call):
                    continue
                alvo = no.func
                if isinstance(alvo, ast.Name) and alvo.id in proibidos:
                    encontrados.append(f"{arquivo.name}:{no.lineno} {alvo.id}")
        assert not encontrados, "\n".join(encontrados)


class TestAEscritaDeEventoNaoEDestrutiva:
    """§22, §100. O único `UPDATE` muda estado, nunca conteúdo."""

    ADAPTER: Path = RAIZ / "src/sports_intelligence/adapters/postgres/events.py"

    def test_todo_update_muda_apenas_status(self) -> None:
        texto = self.ADAPTER.read_text(encoding="utf-8")
        assert "UPDATE canonical_match_events" in texto
        for bloco in texto.split("UPDATE canonical_match_events")[1:]:
            trecho = bloco.split('"""')[0]
            assert "SET status" in trecho, (
                "há um UPDATE em `canonical_match_events` que não muda apenas o "
                "estado — um evento gravado é fato, e reescrevê-lo apagaria «o "
                "que sabíamos antes»"
            )

    def test_o_teste_enxerga_um_update_plantado(self, tmp_path: Path) -> None:
        plantado = tmp_path / "adapter.py"
        plantado.write_text('"UPDATE canonical_match_events SET minute = 1"', encoding="utf-8")
        texto = plantado.read_text(encoding="utf-8")
        trecho = texto.split("UPDATE canonical_match_events")[1]
        assert "SET status" not in trecho


class TestOLimiteDaFase:
    def test_o_registro_canonico_nao_e_corpus_publicado(self) -> None:
        """§80, §128. Uma versão `READY` existente NÃO ganha eventos por eles
        passarem a existir: `PublishedVersion + NewCapability ⇏ Mutation`.

        A prova é estrutural: a pertinência do corpus é escrita pelo caso de
        uso de corpus, e o de eventos não o alcança.
        """
        from sports_intelligence.application.use_cases import events

        fonte = Path(events.__file__).read_text(encoding="utf-8")
        assert "historical_canonical_members" not in fonte
        assert "CorpusMember" not in fonte
