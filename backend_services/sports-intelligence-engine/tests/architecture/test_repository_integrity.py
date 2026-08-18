"""O artefato validado é o REPOSITÓRIO, não o filesystem do agente.

O DEFEITO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR JÁ ACONTECEU. Uma regra ampla
no `.gitignore` do monorepo — `build/`, sem barra inicial — casava qualquer
diretório com esse nome em qualquer profundidade. Os pacotes
`domain/build/` e `historical/build/` sumiram do commit, e `data/` fez o mesmo
com `docs/data/` inteiro.

Nada falhou. A suíte ficava verde, o `mypy` ficava verde, os testes de
integração passavam contra PostgreSQL de verdade — porque tudo isso lê o
WORKING TREE, e o working tree estava completo. O que estava quebrado era o
artefato: um `clone` do repositório não conseguia nem importar o motor, porque
o adapter commitado importava um pacote que não foi.

    o working tree passar  ≠  o repositório ser válido

E o Ruff piorava a situação em silêncio: ele respeita `.gitignore` por padrão,
então os dois pacotes ignorados também eram invisíveis para o lint. «All
checks passed» significava «tudo que o Git deixou eu ver passou».

TRÊS CAMADAS DE PROTEÇÃO, e as três são baratas:

    check-ignore     nenhum caminho essencial pode estar ignorado
    ls-files         «não ignorado» não implica «versionado»
    árvore limpa     só o conteúdo versionado, importado do zero
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.support.ast_checks import FONTE, RAIZ

pytestmark = pytest.mark.architecture

#: As raízes sem as quais o artefato não é o motor. NÃO é uma lista de
#: arquivos: proteger centenas de caminhos individualmente envelheceria a cada
#: PR e daria a impressão de cobertura sem dar cobertura. O que se protege são
#: os DIRETÓRIOS cuja ausência quebra o import ou apaga contrato.
RAIZES_OBRIGATORIAS: tuple[str, ...] = (
    "src/sports_intelligence",
    "src/sports_intelligence/domain/quality",
    "src/sports_intelligence/domain/build",
    "src/sports_intelligence/historical/quality",
    "src/sports_intelligence/historical/build",
    "src/sports_intelligence/adapters/postgres",
    "src/sports_intelligence/ports/repositories",
    "apps",
    "migrations",
    "docs/data",
    "docs/architecture/adr",
)

#: O módulo que precisa importar numa árvore limpa. Importar o pacote raiz não
#: bastaria — ele é quase vazio; este puxa domínio, ports e adapters juntos.
MODULO_DE_FUMACA: str = "sports_intelligence.adapters.postgres.canonical"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def _sem_git() -> bool:
    return _git("rev-parse", "--is-inside-work-tree").returncode != 0


def _regra_que_ignora(caminho: str) -> str | None:
    """A regra de ignore que de fato exclui este caminho, ou `None`.

    `git check-ignore` SOZINHO NÃO RESPONDE A PERGUNTA. Ele sai com zero
    sempre que o caminho CASA alguma regra — inclusive uma NEGAÇÃO, que
    significa o contrário de ignorar. Um teste que olhasse só o código de
    saída acusaria como ignorado exatamente o caminho que acabou de ser
    reincluído, e a proteção viraria ruído até alguém desligá-la.

    Então a resposta vem do PADRÃO: `-v` imprime `arquivo:linha:padrão`, e um
    padrão iniciado por `!` é reinclusão.
    """
    saida = _git("check-ignore", "-v", "--no-index", caminho).stdout.strip()
    if not saida:
        return None
    primeira = saida.splitlines()[0]
    padrao = primeira.split("\t", 1)[0].rsplit(":", 1)[-1]
    return None if padrao.startswith("!") else padrao


pulo_sem_git = pytest.mark.skipif(
    _sem_git(), reason="fora de um repositório Git: não há artefato a validar"
)


@pulo_sem_git
class TestNadaEssencialEstaIgnorado:
    """`git check-ignore` — a primeira camada, e a que pegou o bug real."""

    @pytest.mark.parametrize("raiz", list(RAIZES_OBRIGATORIAS))
    def test_a_raiz_nao_e_ignorada(self, raiz: str) -> None:
        regra = _regra_que_ignora(raiz)
        assert regra is None, (
            f"`{raiz}` está IGNORADO pela regra `{regra}`.\n\n"
            "O working tree continuaria passando e um clone limpo viria sem este "
            "diretório. Se a regra é legítima, reinclua o caminho explicitamente "
            "no `.gitignore` deste serviço."
        )

    def test_o_teste_enxerga_uma_regra_plantada(self) -> None:
        """A proteção precisa saber ACUSAR, senão ela é decorativa. `/build/`
        continua ignorando o artefato de distribuição na raiz do serviço — e é
        exatamente ele que a regra existe para pegar."""
        assert _regra_que_ignora("build/artefato.whl") is not None
        assert _regra_que_ignora(".venv/qualquer.py") is not None

    def test_nenhum_package_python_do_motor_esta_ignorado(self) -> None:
        """A proteção GENÉRICA (§24): vale para `build/`, e para a próxima
        colisão de nome que ninguém previu.

        Todo diretório com `__init__.py` sob `src/sports_intelligence` é um
        pacote que o import precisa encontrar. Um deles ignorado é um
        `ModuleNotFoundError` no clone de outra pessoa.
        """
        pacotes = sorted(
            p.parent.relative_to(RAIZ).as_posix()
            for p in FONTE.rglob("__init__.py")
        )
        assert pacotes, "nenhum pacote encontrado: o teste está olhando o lugar errado"

        ignorados = [p for p in pacotes if _regra_que_ignora(p) is not None]
        assert not ignorados, (
            "pacotes Python do motor ignorados pelo Git:\n  "
            + "\n  ".join(ignorados)
            + "\n\nEles existem no disco e não existiriam num clone."
        )


@pulo_sem_git
class TestTudoEssencialEstaVersionado:
    """`git ls-files` — porque «não ignorado» não implica «versionado».

    Um arquivo novo que ninguém adicionou não é ignorado e também não está no
    artefato. A primeira camada não pega esse caso; esta pega.
    """

    @pytest.mark.parametrize("raiz", list(RAIZES_OBRIGATORIAS))
    def test_a_raiz_tem_conteudo_versionado(self, raiz: str) -> None:
        resultado = _git("ls-files", "--", raiz)
        arquivos = [linha for linha in resultado.stdout.splitlines() if linha.strip()]
        assert arquivos, (
            f"`{raiz}` não tem NENHUM arquivo versionado. Ele existe no disco e "
            "não faz parte do repositório — um clone viria sem ele."
        )

    def test_todo_package_do_motor_tem_o_proprio_init_versionado(self) -> None:
        """O `__init__.py` é o que faz o diretório ser um pacote. Um pacote
        cujos módulos foram versionados e cujo `__init__.py` não seria um
        import quebrado de um jeito especialmente confuso."""
        no_disco = {
            p.relative_to(RAIZ).as_posix() for p in FONTE.rglob("__init__.py")
        }
        versionados = set(
            _git("ls-files", "--", "src/sports_intelligence").stdout.splitlines()
        )
        faltando = sorted(no_disco - versionados)
        assert not faltando, (
            "`__init__.py` presente no disco e ausente do repositório:\n  "
            + "\n  ".join(faltando)
        )

    def test_as_migrations_estao_todas_versionadas(self) -> None:
        """Uma migration não versionada é um schema que só existe na máquina
        de quem a escreveu — e o `checksum` do aplicador não a pega, porque
        ela simplesmente não chega ao outro lado."""
        no_disco = {
            p.relative_to(RAIZ).as_posix() for p in (RAIZ / "migrations").glob("*.sql")
        }
        versionadas = set(_git("ls-files", "--", "migrations").stdout.splitlines())
        assert no_disco <= versionadas, sorted(no_disco - versionadas)


@pulo_sem_git
class TestArvoreVersionadaImporta:
    """A prova final: só o conteúdo versionado, importado do zero (§19, §54).

    NÃO COPIA O WORKING TREE, e é o ponto inteiro. Copiar o diretório
    reproduziria exatamente o erro que este arquivo existe para pegar: os
    arquivos não versionados viriam junto e o import passaria.

    A LISTA VEM DE `git ls-files`, que é a definição operacional de «o que o
    repositório contém». Nada de rede, nada de clone remoto.
    """

    def _exportar(self, destino: Path) -> int:
        rastreados = [
            linha
            for linha in _git(
                "ls-files", "--", "src", "apps", "pyproject.toml"
            ).stdout.splitlines()
            if linha.strip()
        ]
        for caminho in rastreados:
            origem = RAIZ / caminho
            if not origem.is_file():
                continue
            alvo = destino / caminho
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, alvo)
        return len(rastreados)

    def _rodar_na_arvore(self, exportada: Path, corpo: str) -> subprocess.CompletedProcess[str]:
        """Executa `corpo` com a árvore EXPORTADA na frente do `sys.path`.

        DUAS ARMADILHAS AQUI, e as duas fariam o teste passar sem provar nada.

        A PRIMEIRA É `-I`. Ele isola o interpretador e, de quebra, ignora
        `PYTHONPATH` — então o subprocesso importaria pelo `.pth` do install
        editável, que aponta para o WORKING TREE. O teste provaria exatamente
        o contrário do que afirma. Por isso o caminho entra por `sys.path` no
        prólogo, e não por variável de ambiente.

        A SEGUNDA É O `site-packages`. Ele precisa continuar disponível — o
        motor importa `pydantic` na configuração —, e é ele que traz o `.pth`
        do install editável junto. `insert(0, ...)` põe a árvore exportada na
        frente; quem confere que ela de fato venceu é o chamador, olhando de
        onde o módulo foi carregado.
        """
        prologo = f"import sys; sys.path.insert(0, {str(exportada / 'src')!r})\n"
        ambiente = dict(os.environ)
        ambiente.pop("PYTHONHOME", None)
        ambiente.pop("PYTHONPATH", None)
        return subprocess.run(
            [sys.executable, "-c", prologo + corpo],
            cwd=exportada,
            env=ambiente,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )

    def test_a_arvore_versionada_importa_sem_os_arquivos_locais(
        self, tmp_path: Path
    ) -> None:
        quantos = self._exportar(tmp_path)
        assert quantos > 0, "nada versionado em `src`/`apps`: não há artefato"

        resultado = self._rodar_na_arvore(
            tmp_path,
            f"import {MODULO_DE_FUMACA} as m\nprint(m.__file__)\n",
        )
        assert resultado.returncode == 0, (
            "a árvore VERSIONADA não importa — o repositório está quebrado mesmo "
            f"com o working tree verde:\n{resultado.stderr}"
        )

        # O TESTE CONFERE DE ONDE O MÓDULO VEIO, e é o que o torna
        # inescapável: se o import tivesse resolvido pelo install editável,
        # ele estaria lendo o working tree — com os arquivos não versionados
        # dentro — e a prova seria vazia.
        origem = Path(resultado.stdout.strip())
        assert tmp_path in origem.parents, (
            f"o import resolveu para `{origem}`, fora da árvore exportada "
            f"(`{tmp_path}`): o teste estaria provando o working tree, não o "
            "repositório"
        )

    def test_o_dominio_inteiro_importa_da_arvore_versionada(
        self, tmp_path: Path
    ) -> None:
        """Um import só poderia passar por acaso. Este percorre TODOS os
        módulos do pacote — domínio, ports, adapters, ingestão e execução
        histórica —, que é onde os pacotes ignorados moravam."""
        self._exportar(tmp_path)
        corpo = (
            "import importlib, pkgutil\n"
            "import sports_intelligence\n"
            "raiz = sports_intelligence.__file__\n"
            "falhas = []\n"
            "for info in pkgutil.walk_packages(\n"
            "    sports_intelligence.__path__, 'sports_intelligence.'\n"
            "):\n"
            "    try:\n"
            "        importlib.import_module(info.name)\n"
            "    except Exception as erro:\n"
            "        falhas.append(f'{info.name}: {type(erro).__name__}: {erro}')\n"
            "print(raiz)\n"
            "print('\\n'.join(falhas))\n"
            "sys.exit(1 if falhas else 0)\n"
        )
        resultado = self._rodar_na_arvore(tmp_path, corpo)
        linhas = resultado.stdout.splitlines()
        assert linhas, resultado.stderr
        assert tmp_path in Path(linhas[0].strip()).parents, (
            f"o pacote foi carregado de `{linhas[0]}`, fora da árvore exportada"
        )
        assert resultado.returncode == 0, (
            "módulos que não importam a partir da árvore versionada:\n"
            + "\n".join(linhas[1:])
            + resultado.stderr
        )


class TestOLinterEnxergaTudo:
    """§23. O Ruff não pode herdar os pontos cegos do Git."""

    def test_o_ruff_nao_respeita_o_gitignore(self) -> None:
        """A configuração é a proteção: com ela ligada, um pacote ignorado
        continuaria invisível para o lint — e foi assim que sete achados
        ficaram escondidos em `domain/build` e `historical/build`."""
        import tomllib

        configuracao = tomllib.loads(
            (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
        )
        assert configuracao["tool"]["ruff"]["respect-gitignore"] is False, (
            "`respect-gitignore` voltou a ser verdadeiro: um diretório ignorado "
            "pelo Git deixaria de ser lintado sem que nada avisasse"
        )

    def test_o_lint_de_fato_le_os_pacotes_que_ja_estiveram_invisiveis(self) -> None:
        """Não basta a flag: este teste pede ao Ruff a lista de arquivos que
        ele processaria e confere que os dois pacotes estão nela."""
        resultado = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--show-files", "src"],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        if resultado.returncode != 0 and not resultado.stdout.strip():
            pytest.skip(f"ruff indisponível neste ambiente: {resultado.stderr[:200]}")
        vistos = resultado.stdout.replace("\\", "/")
        for pacote in ("domain/build/policy.py", "historical/build/builders.py"):
            assert pacote in vistos, (
                f"o Ruff não enxerga `{pacote}` — o lint está cego para um pacote "
                "do motor, como esteve até o PR-04.2.1"
            )


@pulo_sem_git
class TestDocumentacaoObrigatoria:
    """§25. `docs/data/` guarda os contratos de dado, e sumiu de verdade."""

    def test_os_contratos_de_dado_estao_versionados(self) -> None:
        versionados = {
            Path(linha).name
            for linha in _git("ls-files", "--", "docs/data").stdout.splitlines()
            if linha.strip()
        }
        obrigatorios: Sequence[str] = (
            "HISTORICAL_QUALITY_EXECUTION.md",
            "CANONICAL_BUILD_CORE.md",
            "DATA_FUSION.md",
            "IDENTITY_RESOLUTION.md",
        )
        faltando = [nome for nome in obrigatorios if nome not in versionados]
        assert not faltando, (
            f"documentos de contrato ausentes do repositório: {faltando}. "
            "Eles existem no disco e um clone viria sem eles."
        )

    def test_os_adrs_do_pr_04_estao_versionados(self) -> None:
        versionados = {
            Path(linha).name
            for linha in _git(
                "ls-files", "--", "docs/architecture/adr"
            ).stdout.splitlines()
            if linha.strip()
        }
        do_pr = [nome for nome in versionados if nome.startswith(("0023", "0024", "0025"))]
        assert len(do_pr) == 3, (
            f"ADRs do PR-04.2 versionados: {sorted(do_pr)} — esperados 0023, 0024 e 0025"
        )
