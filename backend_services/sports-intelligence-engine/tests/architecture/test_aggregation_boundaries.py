"""As fronteiras do PR-06.5 — o que a agregação nunca pode saber ou tocar.

TRÊS PROIBIÇÕES, E CADA UMA TEM UM MOTIVO DIFERENTE:

    §6    NENHUM DESFECHO.       Peso é influência relativa, e não predição.
                                 Se a agregação puder ler o placar final, ela
                                 deixa de ser uma transformação e vira um
                                 modelo — não declarado, e não avaliado.

    §71   NENHUMA LEITURA.       Ela recebe o resultado do retrieval pronto.
                                 Um `SELECT` aqui significaria que o agregado
                                 depende de algo que o retrieval não viu.

    §74   NENHUMA INFRAESTRUTURA. O domínio da agregação é aritmética pura, e
                                 importar um adapter o prenderia a um
                                 armazenamento.

A GUARDA MIRA IMPORTS E SÍMBOLOS, e não texto solto (§77). Este próprio arquivo
menciona «desfecho» e «probabilidade» em português e em inglês; uma guarda
textual acusaria os comentários que EXPLICAM a proibição.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.support.ast_checks import FONTE

pytestmark = pytest.mark.architecture

AGREGACAO = FONTE / "domain" / "retrieval" / "aggregation"


def _arquivos() -> list[Path]:
    return sorted(AGREGACAO.rglob("*.py"))


def _modulos_importados(caminho: Path) -> set[str]:
    """Os módulos que o arquivo importa — pelo AST, e não por texto."""
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    modulos: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            modulos.update(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            modulos.add(no.module)
            modulos.update(f"{no.module}.{a.name}" for a in no.names)
    return modulos


def _nomes_definidos_ou_usados(caminho: Path) -> set[str]:
    """Os identificadores que o CÓDIGO usa. Docstrings e comentários fora."""
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Name):
            nomes.add(no.id)
        elif isinstance(no, ast.Attribute):
            nomes.add(no.attr)
        elif isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            nomes.add(no.name)
    return nomes


class TestOHarnesEncontraOPacote:
    """Uma guarda contra a guarda que passa porque não achou nada."""

    def test_o_pacote_existe_e_tem_modulos(self) -> None:
        arquivos = _arquivos()
        assert len(arquivos) >= 4, [p.name for p in arquivos]
        assert {p.name for p in arquivos} >= {
            "kernel.py",
            "policy.py",
            "aggregate.py",
            "summaries.py",
        }


class TestNaoOlhaODesfecho:
    """§6, §77 — a agregação é cega ao que aconteceu depois."""

    def test_nao_importa_nada_de_desfecho(self) -> None:
        proibidos = (
            "matches.result",
            "match_result",
            "MatchResult",
            "QualificationOutcome",
            "outcome",
            "outcomes",
        )
        for arquivo in _arquivos():
            modulos = _modulos_importados(arquivo)
            for modulo in modulos:
                for proibido in proibidos:
                    assert proibido.lower() not in modulo.lower(), (
                        f"{arquivo.name} importa {modulo!r}: a agregação atribui "
                        "influência relativa, e ler o desfecho a transformaria num "
                        "modelo não declarado"
                    )

    def test_nao_usa_simbolos_de_desfecho_nem_de_predicao(self) -> None:
        """§77 — símbolos do CÓDIGO, e não palavras nos comentários."""
        proibidos = {
            "MatchResult",
            "QualificationOutcome",
            "winner",
            "goals_after",
            "future_goal",
            "final_score",
            "predict",
            "prediction",
            "probability_of",
            "win_probability",
        }
        for arquivo in _arquivos():
            usados = _nomes_definidos_ou_usados(arquivo)
            intersecao = usados & proibidos
            assert not intersecao, f"{arquivo.name} usa {sorted(intersecao)}"


class TestNaoChamaPesoDeProbabilidade:
    """§13, §14 — o vocabulário do contrato importa.

    UM CAMPO CHAMADO `probability` SERIA LIDO COMO PROBABILIDADE por quem
    consumir o contrato, e nenhuma quantidade de documentação desfaz um nome.
    """

    def test_nenhum_simbolo_publico_chama_peso_de_probabilidade(self) -> None:
        proibidos = {
            "probability",
            "probabilities",
            "confidence",
            "likelihood",
            "certainty",
        }
        for arquivo in _arquivos():
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
            for no in ast.walk(arvore):
                nome = None
                if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    nome = no.name
                elif isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name):
                    nome = no.target.id
                if nome and nome.lower() in proibidos:
                    pytest.fail(f"{arquivo.name} define {nome!r} — peso não é probabilidade")


class TestNaoLeNada:
    """§71 — a agregação recebe tudo do retrieval, e não busca nada."""

    def test_nao_importa_infraestrutura(self) -> None:
        proibidos = (
            "asyncpg",
            "psycopg",
            "sqlalchemy",
            "pyarrow",
            "boto3",
            "minio",
            "redis",
            "clickhouse",
            "fastapi",
            "adapters",
            "apps.",
        )
        for arquivo in _arquivos():
            for modulo in _modulos_importados(arquivo):
                for proibido in proibidos:
                    assert proibido not in modulo.lower(), (
                        f"{arquivo.name} importa {modulo!r}: o domínio da agregação "
                        "é aritmética pura sobre um resultado já produzido"
                    )

    def test_nao_ha_SQL_no_pacote(self) -> None:
        for arquivo in _arquivos():
            corpo = arquivo.read_text(encoding="utf-8").lower()
            for termo in ("select ", "insert into", "update ", "delete from"):
                assert termo not in corpo, f"{arquivo.name} contém {termo!r}"


class TestNaoFundeEstadoComTrajetoria:
    """§11, §56 — os dois sinais continuam separados."""

    def test_nao_ha_score_composto(self) -> None:
        proibidos = {
            "composite_score",
            "combined_score",
            "fused_score",
            "state_trajectory_score",
            "blend",
        }
        for arquivo in _arquivos():
            usados = {n.lower() for n in _nomes_definidos_ou_usados(arquivo)}
            intersecao = usados & proibidos
            assert not intersecao, f"{arquivo.name} usa {sorted(intersecao)}"

    def test_o_catalogo_de_tipos_e_fechado_e_tem_DOIS_membros(self) -> None:
        from sports_intelligence.domain.retrieval.aggregation.policy import RetrievalKind

        assert {k.value for k in RetrievalKind} == {"STATE", "TRAJECTORY"}


class TestNaoRecalculaDistancia:
    """§9, §10 — a dissimilaridade exata é a única entrada permitida."""

    def test_o_pacote_nao_importa_definicoes_de_distancia(self) -> None:
        """ELE NÃO PRECISA DELAS. Recebe números, e não réguas.

        Importar uma `DistanceDefinition` aqui abriria a porta para recalcular —
        e o §9 proíbe justamente isso, porque uma segunda distância com o mesmo
        nome é como as duas divergem.
        """
        proibidos = (
            "availability_distance",
            "trajectory_distance",
            "retrieval.distance",
        )
        for arquivo in _arquivos():
            for modulo in _modulos_importados(arquivo):
                for proibido in proibidos:
                    assert proibido not in modulo, f"{arquivo.name} importa {modulo!r}"


class TestSemMigracaoNova:
    """§70, §129 — a agregação não persiste nada."""

    def test_a_ultima_migracao_continua_sendo_a_0014(self) -> None:
        from tests.support.ast_checks import RAIZ

        migracoes = sorted(p.name for p in (RAIZ / "migrations").glob("*.sql"))
        assert migracoes[-1] == "0014_historical_retrieval_projection.sql", (
            f"o PR-06.5 opera em memória sobre o resultado do retrieval — {migracoes[-3:]}"
        )
        assert len(migracoes) == 15 - 1


class TestOCaminhoDeAplicacaoEDaCLI:
    """§70, §84, §96 — a lição do PR-06.4, guardada onde ela foi quebrada.

    NO PR-06.4 A CLI DA PROJEÇÃO IMPORTOU O ADAPTER DIRETO, e a guarda do
    repositório pegou. O módulo de agregação é novo e reproduziria o mesmo erro
    com a mesma facilidade — então a guarda vem junto com ele, e não depois.
    """

    def test_o_caso_de_uso_da_agregacao_nao_importa_adapter(self) -> None:
        caminho = FONTE / "application" / "use_cases" / "neighbor_aggregation.py"
        assert caminho.exists(), caminho
        for modulo in _modulos_importados(caminho):
            for proibido in ("adapters", "asyncpg", "psycopg", "pyarrow", "boto3", "minio"):
                assert proibido not in modulo.lower(), (
                    f"o caso de uso importa {modulo!r}: ele orquestra o caminho "
                    "projetado, e a infraestrutura chega pela composição"
                )

    def test_a_CLI_da_agregacao_nao_importa_adapter(self) -> None:
        from tests.support.ast_checks import RAIZ

        caminho = RAIZ / "apps" / "cli" / "retrieval_aggregation.py"
        assert caminho.exists(), caminho
        for modulo in _modulos_importados(caminho):
            for proibido in ("adapters", "asyncpg", "psycopg", "pyarrow", "boto3", "minio"):
                assert proibido not in modulo.lower(), f"a CLI importa {modulo!r}"

    def test_o_caso_de_uso_nao_le_desfecho(self) -> None:
        caminho = FONTE / "application" / "use_cases" / "neighbor_aggregation.py"
        usados = _nomes_definidos_ou_usados(caminho)
        proibidos = {"MatchResult", "QualificationOutcome", "winner", "final_score", "prediction"}
        assert not (usados & proibidos), sorted(usados & proibidos)


class TestAAgregacaoNaoPonderaEIXO:
    """A cobertura que o estreitamento em `test_retrieval_boundaries` cedeu.

    AS DUAS PONDERAÇÕES NÃO SÃO A MESMA COISA, e é por isso que uma é permitida
    aqui e a outra não:

        PONDERAR VIZINHO   exp(-lambda*d) sobre um top-K já calculado.
                           É o PR-06.5.

        PONDERAR EIXO      alpha*x1 + beta*x2 DENTRO da distância.
                           Continua proibido — inclusive aqui.

    A SEGUNDA CONTINUARIA SENDO UM DEFEITO se aparecesse neste pacote, e com
    agravante: a agregação recebe distâncias prontas, então um coeficiente por
    eixo aqui significaria que alguém recalculou a distância às escondidas.
    """

    def test_nao_ha_coeficiente_por_eixo(self) -> None:
        proibidos = {"alpha", "beta", "gamma", "axis_weight", "axis_weights", "per_axis_weight"}
        for arquivo in _arquivos():
            usados = {n.lower() for n in _nomes_definidos_ou_usados(arquivo)}
            intersecao = usados & proibidos
            assert not intersecao, (
                f"{arquivo.name} usa {sorted(intersecao)}: a agregação recebe a "
                "distância pronta, e um coeficiente por eixo aqui significaria "
                "que ela foi recalculada"
            )

    def test_o_unico_lambda_e_o_da_POLITICA(self) -> None:
        """§20 — nenhum `lambda` literal escondido num corpo de função.

        O VALOR VEM SEMPRE DA POLÍTICA. As constantes selecionadas são nomeadas
        e entram na impressão; o que esta guarda impede é o `lam=1.0` solto no
        meio de uma função, que seria um parâmetro que ninguém declarou.
        """
        import ast as _ast

        from sports_intelligence.domain.retrieval.aggregation.policy import (
            SELECTED_STATE_LAMBDA,
            SELECTED_TRAJECTORY_LAMBDA,
        )

        assert SELECTED_STATE_LAMBDA == 8.0
        assert SELECTED_TRAJECTORY_LAMBDA == 16.0

        permitidos = {"kernel.py", "policy.py"}
        for arquivo in _arquivos():
            if arquivo.name in permitidos:
                continue
            arvore = _ast.parse(arquivo.read_text(encoding="utf-8"))
            for no in _ast.walk(arvore):
                if not isinstance(no, _ast.keyword) or no.arg != "lam":
                    continue
                assert not isinstance(no.value, _ast.Constant), (
                    f"{arquivo.name} passa lam={no.value.value!r} literal — o valor "
                    "precisa vir da política, senão a execução esconde qual foi"
                )
