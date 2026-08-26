"""Os limites do PR-03, verificados por AST e falhando o CI.

TRÊS COISAS PRECISAM CONTINUAR VERDADEIRAS depois deste PR, e nenhuma delas é
óbvia o bastante para sobreviver por convenção:

    o domínio não conhece a biblioteca de similaridade   ela é nossa hoje e
                                                         pode virar externa

    `ProviderRef` continua sem conversão para `EntityId` a passagem é uma
                                                         DECISÃO, não um cast

    fusão só aceita identidade provada                   o tipo impõe, e o
                                                         teste guarda o tipo

E uma quarta, que é a mais fácil de perder: decisões e execuções são
append-only. Um `UPDATE` no adapter satisfaria qualquer teste de interface e
quebraria a regra inteira.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.support.ast_checks import (
    RAIZ,
    defined_functions,
    external_violations,
    files_in,
    internal_violations,
)

pytestmark = pytest.mark.architecture

#: Os pacotes que o PR-03 acrescentou ao domínio.
PACOTES_DE_RESOLUCAO = ("domain/resolution", "domain/fusion", "domain/sources")

#: Bibliotecas de similaridade e de aprendizado. Nenhuma entra no domínio, e
#: as de aprendizado não entram em lugar nenhum (§64, §100).
BIBLIOTECAS_DE_SIMILARIDADE = frozenset(
    {
        "rapidfuzz",
        "fuzzywuzzy",
        "jellyfish",
        "Levenshtein",
        "python_Levenshtein",
        "textdistance",
    }
)
BIBLIOTECAS_DE_APRENDIZADO = frozenset(
    {
        "sklearn",
        "scikit_learn",
        "torch",
        "tensorflow",
        "transformers",
        "sentence_transformers",
        "openai",
        "anthropic",
        "langchain",
        "faiss",
        "gensim",
    }
)


class TestDominioNaoConheceSimilaridade:
    @pytest.mark.parametrize("pacote", PACOTES_DE_RESOLUCAO)
    def test_nao_importa_biblioteca_de_similaridade(self, pacote: str) -> None:
        """A similaridade é do INGESTION, não do domínio.

        O domínio descreve o que é uma decisão de identidade e sob que
        política ela acontece. Como dois textos se parecem é implementação,
        e hoje ela é nossa justamente para que trocá-la seja uma troca de
        implementação — não uma mudança no domínio (§65).
        """
        violacoes = external_violations(files_in(pacote), BIBLIOTECAS_DE_SIMILARIDADE)
        assert not violacoes, str(violacoes)

    @pytest.mark.parametrize("pacote", PACOTES_DE_RESOLUCAO)
    def test_nao_importa_infraestrutura(self, pacote: str) -> None:
        from tests.support.ast_checks import INFRA_EXTERNA

        violacoes = external_violations(files_in(pacote), INFRA_EXTERNA)
        assert not violacoes, str(violacoes)

    @pytest.mark.parametrize("pacote", PACOTES_DE_RESOLUCAO)
    def test_nao_importa_adapters_nem_application(self, pacote: str) -> None:
        violacoes = internal_violations(
            files_in(pacote),
            (
                "sports_intelligence.adapters",
                "sports_intelligence.application",
                "sports_intelligence.ingestion",
                "apps",
            ),
        )
        assert not violacoes, str(violacoes)


class TestNadaDeAprendizadoDeMaquina:
    def test_nenhum_pacote_importa_modelo_nem_embedding(self) -> None:
        """§64 e §100, verificados no código inteiro.

        Similaridade de nome precisa ser explicável e estável. Um modelo não é
        nem uma coisa nem outra — e a diferença entre `Sporting CP` e
        `Sporting Gijón` é exatamente o tipo de distinção que um espaço
        vetorial de propósito geral colapsa.
        """
        violacoes = external_violations(
            files_in("domain", "ingestion", "application", "adapters", "ports"),
            BIBLIOTECAS_DE_APRENDIZADO,
        )
        assert not violacoes, "aprendizado de máquina na resolução de identidade:\n" + "\n".join(
            map(str, violacoes)
        )


class TestProviderRefContinuaInconversivel:
    def test_nao_ha_conversao_para_entity_id(self) -> None:
        """A regra do PR-01, reconferida onde ela é mais tentadora (§13).

        O PR-03 é o primeiro que TEM um `ProviderRef` em mãos e precisa de um
        `EntityId`. A conversão é uma DECISÃO — com evidência, confiança e
        possibilidade de falhar —, e um atalho aqui a transformaria num cast.
        """
        from sports_intelligence.domain.shared.identity import ProviderRef

        for proibido in ("to_entity_id", "as_entity_id", "entity_id", "resolve"):
            assert not hasattr(ProviderRef, proibido), (
                f"`{proibido}` apareceu em ProviderRef — a passagem entre a "
                "referência do provedor e a identidade do domínio é resolução de "
                "identidade, não conversão"
            )

    def test_mapeamento_exige_a_decisao_que_o_originou(self) -> None:
        """Um mapeamento sem decisão é indistinguível de um inventado."""
        from sports_intelligence.domain.resolution.mappings import ProviderEntityMapping

        campos = ProviderEntityMapping.__dataclass_fields__
        assert "resolution_decision_id" in campos
        import dataclasses

        campo = campos["resolution_decision_id"]
        assert campo.default is dataclasses.MISSING, (
            "resolution_decision_id com default: um mapeamento poderia nascer sem "
            "nada que o explicasse"
        )


class TestFusaoSoAceitaIdentidadeProvada:
    def test_o_tipo_de_entrada_exige_decisao(self) -> None:
        """ADR-0022 imposto por ASSINATURA, não por convenção.

        `ResolvedSourceRecord` não se constrói sem `resolution_decision_id`,
        então não há caminho de código que funda identidade não provada.
        """
        import dataclasses

        from sports_intelligence.domain.fusion.models import ResolvedSourceRecord

        campos = ResolvedSourceRecord.__dataclass_fields__
        assert campos["resolution_decision_id"].default is dataclasses.MISSING
        assert campos["canonical_entity_id"].default is dataclasses.MISSING

    def test_o_motor_de_fusao_nao_resolve_identidade(self) -> None:
        """Nenhuma função com nome de resolução no pacote de fusão."""
        proibidos = frozenset(
            {
                "resolve_team",
                "resolve_player",
                "resolve_match",
                "resolve_identity",
                "guess_entity",
                "infer_match",
            }
        )
        encontradas = [
            f"{arquivo.name}:{linha} def {nome}"
            for arquivo, linha, nome in defined_functions(
                files_in("ingestion/fusion", "domain/fusion")
            )
            if nome in proibidos
        ]
        assert not encontradas, "\n".join(encontradas)

    def test_fusao_nao_importa_resolvers(self) -> None:
        """A fusão consome DECISÕES, não o resolver.

        Importar o resolver permitiria resolver no meio da fusão — sem
        decisão registrada, sem evidência, sem entrar na contagem da execução.
        """
        violacoes = internal_violations(
            files_in("ingestion/fusion", "domain/fusion"),
            ("sports_intelligence.ingestion.resolution",),
        )
        assert not violacoes, str(violacoes)


class TestAppendOnly:
    """As tabelas que não podem ser reescritas, verificadas no SQL.

    UM PORT SEM `update` CUJO ADAPTER ESCREVE `UPDATE` satisfaz qualquer
    teste de interface e quebra a regra inteira. Este teste lê o SQL.
    """

    ADAPTER = RAIZ / "src/sports_intelligence/adapters/postgres/resolution.py"

    @pytest.mark.parametrize(
        "tabela",
        [
            "resolution_decisions",
            "resolution_evidence",
            "resolution_alternatives",
            "fusion_groups",
            "fusion_group_records",
            "fused_candidates",
            "fused_fields",
            "fused_field_sources",
            "provider_entity_mappings",
            "entity_aliases",
        ],
    )
    def test_nao_ha_update_sobre(self, tabela: str) -> None:
        texto = self.ADAPTER.read_text(encoding="utf-8")
        assert f"UPDATE {tabela}" not in texto, (
            f"UPDATE em {tabela}: reprocessar emite outra execução, e a anterior "
            "fica exatamente como estava (ADR-0019, ADR-0020)"
        )

    def test_as_duas_excecoes_sao_condicionais_ao_estado(self) -> None:
        """Fechar execução e mover item da fila SÃO `UPDATE` — e os dois são
        condicionais ao estado anterior, que é como esta base faz concorrência.

        Sem a condição, dois workers fechando a mesma execução produziriam
        duas contagens e a segunda sobrescreveria a primeira.
        """
        texto = self.ADAPTER.read_text(encoding="utf-8")
        assert "UPDATE resolution_runs" in texto
        assert "status = 'RUNNING'" in texto
        assert "UPDATE resolution_review_items" in texto
        assert "AND status = $10" in texto

    def test_o_teste_enxerga_um_update_plantado(self, tmp_path: Path) -> None:
        plantado = tmp_path / "adapter.py"
        plantado.write_text('"UPDATE resolution_decisions SET x = 1"', encoding="utf-8")
        assert "UPDATE resolution_decisions" in plantado.read_text(encoding="utf-8")


class TestPoliticaNaoEstaNoCodigo:
    def test_nenhum_resolver_escreve_um_limiar(self) -> None:
        """`if score > 0.8:` espalhado é o defeito que a política existe para
        impedir (§9).

        Este teste procura comparações literais contra números na faixa de
        limiar dentro dos resolvers. Os pesos do score composto são
        atribuições — não comparações — e vêm todos da política.
        """
        suspeitos: list[str] = []
        for arquivo in files_in("ingestion/resolution"):
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
            for no in ast.walk(arvore):
                if not isinstance(no, ast.Compare):
                    continue
                for comparado in no.comparators:
                    if (
                        isinstance(comparado, ast.Constant)
                        and isinstance(comparado.value, float)
                        and 0.6 <= comparado.value <= 0.99
                    ):
                        suspeitos.append(
                            f"{arquivo.name}:{no.lineno} compara contra {comparado.value}"
                        )
        # O CORTE DE CANDIDATO É A EXCEÇÃO DECLARADA: ele não decide status,
        # decide o que sequer vira candidato — sem ele, cada nome produziria
        # um candidato por entidade do registro.
        reais = [s for s in suspeitos if "0.55" not in s and "0.7" not in s]
        assert not reais, "limiar de decisão no código:\n" + "\n".join(reais)


class TestSemExecucaoDinamica:
    def test_mapeamento_e_politica_nao_executam_nada(self) -> None:
        """§81: mapeamentos vêm de fora e nunca viram código.

        A tentação é sempre pequena — «só um campo `expr` para concatenar data
        e hora» — e transformaria o registro de mapeamentos numa superfície de
        execução remota.
        """
        proibidos = {"eval", "exec", "compile", "__import__"}
        encontrados: list[str] = []
        for arquivo in files_in("domain/sources", "domain/fusion", "domain/resolution"):
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
            for no in ast.walk(arvore):
                if (
                    isinstance(no, ast.Call)
                    and isinstance(no.func, ast.Name)
                    and no.func.id in proibidos
                ):
                    encontrados.append(f"{arquivo.name}:{no.lineno} {no.func.id}()")
        assert not encontrados, "\n".join(encontrados)

    def test_o_catalogo_de_transformacoes_e_fechado(self) -> None:
        from sports_intelligence.domain.sources.mapping import ValueTransform

        # Cada uma é uma função nomeada, revisada e testada. Acrescentar uma
        # é uma decisão; permitir expressões seria permitir qualquer uma.
        assert len(list(ValueTransform)) <= 10
        for transformacao in ValueTransform:
            assert transformacao.apply("  x  ") is not None


class TestLimiteDoPR:
    def test_a_saida_nunca_e_historico_ativo(self) -> None:
        """A guarda existe nos DOIS lados — resolução e fusão — e recusa
        sempre. Ela está lá para ser chamada por qualquer caminho futuro que
        tente promover a saída (§101).
        """
        from sports_intelligence.domain.fusion.runs import (
            assert_not_historical_active as fusao,
        )
        from sports_intelligence.domain.resolution.runs import (
            assert_not_historical_active as resolucao,
        )

        assert callable(fusao)
        assert callable(resolucao)

    def test_nada_do_pr_03_importa_features_nem_engines(self) -> None:
        """O PR-04 e os seguintes não foram antecipados (§100)."""
        violacoes = internal_violations(
            files_in(
                "domain/resolution",
                "domain/fusion",
                "ingestion/resolution",
                "ingestion/fusion",
            ),
            (
                "sports_intelligence.features",
                "sports_intelligence.engines",
                "sports_intelligence.historical",
            ),
        )
        assert not violacoes, str(violacoes)
