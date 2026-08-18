"""A superfície do corpus: as MESMAS operações pela API e pela CLI (§71, §75).

O QUE ESTE ARQUIVO PROTEGE, e nenhum teste funcional protege:

    as duas portas existem          uma operação que só a CLI alcança é uma
                                    operação que o console nunca terá
    as duas entram pelos MESMOS
    casos de uso                    uma orquestração própria por porta faria
                                    uma delas ganhar uma verificação que a
                                    outra não tem, e a diferença apareceria em
                                    produção como «pela CLI funciona»
    a resposta DIZ que não é vetor  deixar o consumidor inferir isso é como a
                                    próxima fase começa a ser usada antes de
                                    existir (§4, §72)

Ele NÃO sobe a aplicação: inspeciona o router e o Typer, que é o que permite
rodá-lo sem PostgreSQL, sem object store e sem token.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.support.ast_checks import RAIZ

pytestmark = pytest.mark.architecture

ROTAS = RAIZ / "apps" / "control_api" / "routes" / "corpus.py"
CLI = RAIZ / "apps" / "cli" / "corpus.py"

#: Os casos de uso de ESCRITA, que o §71 e o §75 exigem nas duas portas.
#:
#: SÓ AS ESCRITAS ESTÃO AQUI, e a distinção é deliberada: as leituras («liste
#: as versões», «me dê o manifesto») passam pelos repositórios diretamente,
#: porque não há decisão a tomar nelas. Exigir um caso de uso por leitura
#: produziria uma classe que só encaminha — e um teste que a exigisse
#: precisaria de uma exceção para cada rota de consulta, o que é o mesmo que
#: não exigir nada.
CASOS_DE_USO: tuple[str, ...] = (
    "create_dataset",
    "build_version",
    "publish_version",
)

#: Os repositórios que as LEITURAS podem alcançar. A lista é fechada: um nome
#: novo aqui é sinal de que uma rota passou a falar com algo que não é o
#: corpus.
LEITURAS: frozenset[str] = frozenset({"datasets", "membership", "manifests"})


def _chamadas(caminho: Path) -> set[str]:
    """Os atributos alcançados a partir de `contêiner.corpus`.

    POR AST E NÃO POR TEXTO: uma busca por substring encontraria a menção num
    comentário, e o que importa aqui é a CHAMADA.
    """
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    encontrados: set[str] = set()
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Attribute):
            continue
        dono = no.value
        if (
            isinstance(dono, ast.Attribute)
            and dono.attr == "corpus"
            and isinstance(dono.value, ast.Name)
        ):
            encontrados.add(no.attr)
    return encontrados


class TestAsDuasPortasExistem:
    def test_a_api_expoe_as_operacoes_do_corpus(self) -> None:
        from apps.control_api.routes import corpus as rotas

        caminhos = {
            f"{sorted(r.methods)[0]} {r.path}"  # type: ignore[attr-defined]
            for r in rotas.router.routes
        }
        assert "POST /v1/historical-corpus/datasets" in caminhos
        assert "POST /v1/historical-corpus/datasets/{dataset_id}/versions" in caminhos
        assert "POST /v1/historical-corpus/versions/{version_id}/publish" in caminhos
        assert "GET /v1/historical-corpus/versions/{version_id}/manifest" in caminhos
        assert "GET /v1/historical-corpus/datasets/{dataset_id}/latest" in caminhos

    def test_a_cli_expoe_os_mesmos_comandos(self) -> None:
        from apps.cli import corpus as comandos

        nomes = {c.name for c in comandos.app.registered_commands}
        assert {"create-dataset", "build", "publish", "versions", "manifest"} <= nomes

    def test_a_cli_esta_registrada_na_aplicacao(self) -> None:
        """Um comando que existe e não é montado é um comando que ninguém
        alcança — e o `--help` não o mostraria."""
        from apps.cli import corpus as comandos
        from apps.cli.main import app

        montados = {grupo.typer_instance for grupo in app.registered_groups}
        assert comandos.app in montados

    def test_a_rota_esta_registrada_na_control_api(self) -> None:
        texto = (RAIZ / "apps" / "control_api" / "main.py").read_text(encoding="utf-8")
        assert "rotas_de_corpus.router" in texto


class TestAsDuasEntramPelosMesmosCasosDeUso:
    @pytest.mark.parametrize("caso", list(CASOS_DE_USO))
    def test_a_api_chama_o_caso_de_uso(self, caso: str) -> None:
        assert caso in _chamadas(ROTAS), f"a rota não alcança `corpus.{caso}`"

    @pytest.mark.parametrize("caso", list(CASOS_DE_USO))
    def test_a_cli_chama_o_caso_de_uso(self, caso: str) -> None:
        assert caso in _chamadas(CLI), f"a CLI não alcança `corpus.{caso}`"

    def test_as_leituras_so_alcancam_repositorio_do_corpus(self) -> None:
        """Uma rota de consulta que falasse com outra coisa estaria montando
        composição na borda — e o pool acabaria criado por requisição."""
        permitido = set(CASOS_DE_USO) | LEITURAS
        for caminho in (ROTAS, CLI):
            estranhos = _chamadas(caminho) - permitido
            assert not estranhos, f"{caminho.name} alcança {sorted(estranhos)}"

    def test_a_cli_chama_os_mesmos_objetos_da_api(self) -> None:
        """A interseção é o ponto: se a CLI usasse objetos próprios, ela e a
        API poderiam divergir no que verificam antes de gravar."""
        comuns = _chamadas(ROTAS) & _chamadas(CLI)
        assert {"create_dataset", "build_version", "publish_version"} <= comuns

    def test_nenhuma_das_duas_grava_direto_no_repositorio(self) -> None:
        """Escrever pelo repositório pularia o gate: a conferência do §67 mora
        no caso de uso, e uma porta que a contorna publica sem conferir."""
        proibidos = {"append_members", "transition", "create_version", "save"}
        for caminho in (ROTAS, CLI):
            alcancados = _chamadas(caminho)
            vazamentos = proibidos & alcancados
            assert not vazamentos, f"{caminho.name} alcança {sorted(vazamentos)}"


class TestARespostaDizQueNaoEVetor:
    def test_toda_saida_de_versao_declara_vector_active(self) -> None:
        """§4, §72. Um corpus pronto pode ser LIDO; ele não é espaço vetorial
        ativo, e a resposta afirma isso em vez de deixar inferir."""
        from apps.control_api.routes.corpus import ManifestOut, VersionOut

        assert VersionOut.model_fields["vector_active"].default is False
        assert ManifestOut.model_fields["vector_active"].default is False

    def test_o_motivo_e_obrigatorio_para_publicar(self) -> None:
        """Publicar é decisão administrativa, e uma decisão sem motivo é a
        linha de trilha que ninguém entende seis meses depois."""
        from apps.control_api.routes.corpus import PublishVersionIn

        campo = PublishVersionIn.model_fields["reason"]
        assert campo.is_required()
