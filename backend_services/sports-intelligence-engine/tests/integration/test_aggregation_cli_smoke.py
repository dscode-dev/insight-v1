"""A CLI da agregação — o que ela mostra, o que ela recusa, e como ela fala.

TRÊS PERGUNTAS, E A TERCEIRA É A QUE COSTUMA PASSAR BATIDA:

    §75   os comandos existem e recusam entrada inválida
    §82   o `lambda` resolvido e a impressão da política aparecem
    §73   e NENHUMA coluna chama peso de probabilidade

A TERCEIRA É UM TESTE DE VOCABULÁRIO, e ele existe porque um cabeçalho é mais
lido que uma documentação. Uma coluna chamada «chance» seria entendida como
chance por quem olhasse a saída, e nenhuma nota de rodapé desfaria isso.

AS RECUSAS SÃO TESTADAS SEM INFRAESTRUTURA de propósito: elas acontecem antes
de abrir o pool, e é justamente essa a propriedade que interessa — um `--k 0`
que só falha depois de conectar gastou a conexão para dizer o óbvio.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from typer.testing import CliRunner

pytestmark = pytest.mark.smoke

CLI = Path(__file__).resolve().parents[2] / "apps" / "cli" / "retrieval_aggregation.py"


def _app() -> object:
    from apps.cli.main import app

    return app


class TestOsComandosExistem:
    """§75 — `--help` responde, e diz o que o comando faz."""

    def test_aggregate_state_tem_ajuda(self) -> None:
        resultado = CliRunner().invoke(_app(), ["retrieval", "aggregate-state", "--help"])
        assert resultado.exit_code == 0, resultado.output
        assert "ESTADO" in resultado.output
        assert "--lambda" in resultado.output
        assert "--k" in resultado.output

    def test_aggregate_trajectory_tem_ajuda(self) -> None:
        resultado = CliRunner().invoke(_app(), ["retrieval", "aggregate-trajectory", "--help"])
        assert resultado.exit_code == 0, resultado.output
        assert "TRAJET" in resultado.output.upper()
        assert "--lambda" in resultado.output

    def test_os_dois_aparecem_no_grupo_retrieval(self) -> None:
        resultado = CliRunner().invoke(_app(), ["retrieval", "--help"])
        assert resultado.exit_code == 0
        assert "aggregate-state" in resultado.output
        assert "aggregate-trajectory" in resultado.output


class TestAsRecusas:
    """§75 — entrada inválida falha ALTO, e antes de gastar infraestrutura."""

    @pytest.mark.parametrize("comando", ["aggregate-state", "aggregate-trajectory"])
    def test_chave_sem_o_separador_e_recusada(self, comando: str) -> None:
        resultado = CliRunner().invoke(_app(), ["retrieval", comando, "v1", "sem-separador"])
        assert resultado.exit_code == 1, resultado.output
        assert "<match_id>#<grid_index>" in resultado.output

    @pytest.mark.parametrize("comando", ["aggregate-state", "aggregate-trajectory"])
    def test_indice_nao_numerico_e_recusado(self, comando: str) -> None:
        resultado = CliRunner().invoke(_app(), ["retrieval", comando, "v1", "m1#abc"])
        assert resultado.exit_code == 1, resultado.output

    @pytest.mark.parametrize("comando", ["aggregate-state", "aggregate-trajectory"])
    def test_K_zero_e_recusado_ANTES_de_abrir_o_pool(self, comando: str) -> None:
        resultado = CliRunner().invoke(_app(), ["retrieval", comando, "v1", "m1#3", "--k", "0"])
        assert resultado.exit_code == 1, resultado.output
        assert "K = 0" in resultado.output

    @pytest.mark.parametrize("valor", ["0", "-1"])
    def test_lambda_nao_positivo_e_recusado(self, valor: str) -> None:
        resultado = CliRunner().invoke(
            _app(), ["retrieval", "aggregate-state", "v1", "m1#3", "--lambda", valor]
        )
        assert resultado.exit_code == 1, resultado.output
        assert "lambda" in resultado.output


class TestOVocabularioDaSaida:
    """§73 — a CLI de produção não chama peso de probabilidade."""

    def test_nenhuma_string_da_CLI_chama_peso_de_probabilidade(self) -> None:
        """A varredura é sobre LITERAIS DE TEXTO, e não sobre o arquivo inteiro.

        O ARQUIVO EXPLICA A PROIBIÇÃO nos comentários, e em português e em
        inglês. Uma guarda textual sobre o arquivo cru acusaria exatamente as
        linhas que existem para dizer «não faça isso» — então a varredura olha
        só as strings que podem ir para a tela, e ainda assim precisa deixar
        passar as que NEGAM o termo.
        """
        proibidos = ("probabilidade", "probability", "chance", "confian", "confidence")
        negacoes = ("não é", "nao e", "não são", "nunca", "não")
        arvore = ast.parse(CLI.read_text(encoding="utf-8"))

        # OS DOCSTRINGS SÃO OUTRA COISA, e a primeira versão desta guarda não
        # fazia a distinção — ela acusou o próprio parágrafo que EXPLICA a
        # proibição, que é a armadilha do §77 em miniatura. Um rótulo de coluna
        # vai para a tela como afirmação; um docstring é prosa, e discutir o
        # termo é justamente o que se espera dele.
        docstrings = {
            id(no.body[0].value)
            for no in ast.walk(arvore)
            if isinstance(no, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and no.body
            and isinstance(no.body[0], ast.Expr)
            and isinstance(no.body[0].value, ast.Constant)
            and isinstance(no.body[0].value.value, str)
        }

        rotulos = 0
        prosa = 0
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Constant) or not isinstance(no.value, str):
                continue
            texto = no.value.lower()
            atingidos = [t for t in proibidos if t in texto]
            if not atingidos:
                continue
            if id(no) in docstrings:
                # Prosa: basta que o termo seja NEGADO em algum ponto do texto.
                prosa += 1
                assert any(n in texto for n in negacoes), (
                    f"o docstring cita {atingidos} sem negá-los: {no.value[:120]!r}"
                )
                continue
            # Rótulo: a negação precisa estar COLADA no termo. «não sei, chance
            # de gol» tem um «não» e continua sendo o que o §73 proíbe.
            rotulos += 1
            for termo in atingidos:
                inicio = texto.find(termo)
                while inicio != -1:
                    antes = texto[max(0, inicio - 40) : inicio]
                    assert any(n in antes for n in negacoes), (
                        f"a CLI usa {termo!r} num rótulo sem negá-lo: {no.value!r}"
                    )
                    inicio = texto.find(termo, inicio + 1)

        # E A GUARDA PRECISA ESTAR OLHANDO. Zero ocorrências poderia significar
        # «a CLI está limpa» ou «o `ast` não achou string nenhuma», e as duas
        # leituras produzem o mesmo verde.
        assert prosa + rotulos >= 3, f"a varredura viu {prosa + rotulos} strings — está cega?"

    def test_o_rotulo_de_N_eff_nao_o_chama_de_partidas(self) -> None:
        """§82, §115 — `N_eff = 12,34` não são «12,34 partidas»."""
        corpo = CLI.read_text(encoding="utf-8")
        assert "N_eff (tamanho efetivo)" in corpo
        for proibido in ("N_eff (partidas)", "partidas efetivas", "N_eff em partidas"):
            assert proibido not in corpo


class TestAArquiteturaDaCLI:
    """§70, §84 — a lição do PR-06.4, guardada contra repetição."""

    def test_a_CLI_nao_importa_adapter_nenhum(self) -> None:
        """ELA JÁ FOI QUEBRADA UMA VEZ. No PR-06.4 a CLI da projeção importou
        `PostgresRetrievalProjectionReader` direto, e a guarda do repositório
        pegou. Esta é a mesma guarda, apontada para o módulo novo.
        """
        arvore = ast.parse(CLI.read_text(encoding="utf-8"))
        modulos: set[str] = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos.update(a.name for a in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos.add(no.module)
        for modulo in modulos:
            assert "adapters" not in modulo, f"a CLI importa {modulo!r} — use a composição"
            assert "asyncpg" not in modulo
            assert "psycopg" not in modulo

    def test_a_CLI_passa_pelo_caso_de_uso_da_aplicacao(self) -> None:
        corpo = CLI.read_text(encoding="utf-8")
        assert "application.use_cases.neighbor_aggregation" in corpo
        assert "projecao_da_composicao" in corpo
