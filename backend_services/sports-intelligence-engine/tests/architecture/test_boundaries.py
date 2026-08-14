"""Os limites arquiteturais, verificados por AST — e falhando o CI.

POR QUE UM TESTE E NÃO UMA CONVENÇÃO. Convenção de import sobrevive até a
primeira sexta-feira apertada. O `import` que quebra a direção da dependência
não dá erro, não dá warning, e resolve o problema imediato de quem escreveu.
Só aparece meses depois, quando trocar de banco significa tocar o domínio.

POR QUE AST E NÃO GREP. `grep -r "import fastapi"` não distingue um import
real de uma menção em docstring — e esta base tem docstrings longas que citam
FastAPI, Redis e Postgres por nome, justamente para explicar por que o domínio
não os conhece. Um grep marcaria cada explicação como violação.

A DIREÇÃO PERMITIDA:

    apps → application → domain / features / engines
                              ↑
                            ports
                              ↑
                          adapters

Adapters implementam ports. Nunca o inverso.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.ast_checks import (
    APPS,
    FONTE,
    INFRA_EXTERNA,
)
from tests.support.ast_checks import external_violations as _violacoes
from tests.support.ast_checks import files_in as _arquivos
from tests.support.ast_checks import internal_violations as _violacoes_internas

# O VERIFICADOR MORA EM `tests/support/ast_checks.py` desde o PR-02, que
# acrescentou um segundo arquivo de testes de arquitetura. Duas cópias
# divergiriam na primeira vez que alguém ajustasse uma — e o pior resultado
# disso não é falha, é uma das duas deixar de enxergar em silêncio.

pytestmark = pytest.mark.architecture


class TestDominioNaoConheceInfraestrutura:
    def test_dominio_nao_importa_framework_nem_driver(self) -> None:
        """A regra mais importante da base.

        Um `from fastapi import HTTPException` no domínio funciona, e mata a
        possibilidade de a mesma regra rodar num worker — onde não há
        requisição para responder.
        """
        violacoes = _violacoes(_arquivos("domain"), INFRA_EXTERNA)
        assert not violacoes, "domínio importando infraestrutura:\n" + "\n".join(
            map(str, violacoes)
        )

    def test_features_nao_importam_infraestrutura(self) -> None:
        assert not _violacoes(_arquivos("features"), INFRA_EXTERNA)

    def test_engines_nao_importam_infraestrutura(self) -> None:
        """Um engine que fala com o banco não pode ser testado com uma
        entrada fixa, e sem isso nenhuma medida dele é reproduzível."""
        assert not _violacoes(_arquivos("engines"), INFRA_EXTERNA)

    def test_ports_nao_importam_infraestrutura(self) -> None:
        """O port descreve a necessidade; o adapter escolhe a tecnologia.
        Um port que importa `redis` já escolheu."""
        assert not _violacoes(_arquivos("ports"), INFRA_EXTERNA)


class TestDirecaoDaDependencia:
    def test_dominio_nao_importa_adapters(self) -> None:
        violacoes = _violacoes_internas(
            _arquivos("domain"), ("sports_intelligence.adapters",)
        )
        assert not violacoes, "domínio importando adapter:\n" + "\n".join(
            map(str, violacoes)
        )

    def test_dominio_nao_importa_application_nem_apps(self) -> None:
        """O domínio é a base. Importar a camada acima é ciclo, e ciclo é o
        que torna impossível extrair um serviço depois."""
        violacoes = _violacoes_internas(
            _arquivos("domain"), ("sports_intelligence.application", "apps")
        )
        assert not violacoes

    def test_features_e_engines_nao_importam_adapters(self) -> None:
        violacoes = _violacoes_internas(
            _arquivos("features", "engines"), ("sports_intelligence.adapters",)
        )
        assert not violacoes

    def test_ports_nao_importam_adapters(self) -> None:
        """A inversão que dá nome ao padrão: adapter conhece port, nunca o
        contrário. Se o port importa o adapter, não há inversão nenhuma."""
        violacoes = _violacoes_internas(
            _arquivos("ports"), ("sports_intelligence.adapters",)
        )
        assert not violacoes


class TestFormatoDeProvedorNaoVaza:
    def test_dominio_nao_importa_pacote_de_provider(self) -> None:
        """O tipo de um provedor no domínio significa que trocar de provedor
        muda o domínio — que é exatamente o acoplamento que a camada de
        normalização existe para absorver."""
        violacoes = _violacoes_internas(
            _arquivos("domain", "features", "engines"),
            ("sports_intelligence.adapters.providers",),
        )
        assert not violacoes


class TestAppsNaoContornamAsCamadas:
    def test_apps_nao_importam_adapters_diretamente(self) -> None:
        """A aplicação pede pelo port e recebe o adapter montado na borda.
        Importar o adapter direto amarra o processo à tecnologia.

        DUAS EXCEÇÕES DECLARADAS, e ambas SÃO a borda:

            `apps/_shared.py`                a tradução de erro para HTTP
            `apps/composition.py`            a raiz de composição
            `apps/resolution_composition.py` a do PR-03, mais a leitura de
                                             arquivo que é trabalho de borda

        Todo o resto pede pelo port e recebe o objeto já montado. Um nome novo
        nesta lista é sinal de que a composição vazou, e o sintoma prático de
        vazamento é um processo instanciando o próprio pool — uma conexão por
        requisição.
        """
        excecoes = {"_shared.py", "composition.py", "resolution_composition.py"}
        arquivos = [p for p in sorted(APPS.rglob("*.py")) if p.name not in excecoes]
        violacoes = _violacoes_internas(arquivos, ("sports_intelligence.adapters",))
        assert not violacoes


class TestPacotesDoDominioFutebolistico:
    """Os pacotes que o PR-01 acrescentou, sob as mesmas regras.

    Listados por NOME e não cobertos por `_arquivos("domain")` genérico:
    quando o PR-02 acrescentar `ingestion/normalization`, o teste genérico o
    cobriria em silêncio e ninguém saberia se ele foi de fato verificado.
    """

    @pytest.mark.parametrize(
        "pacote",
        [
            "domain/competitions",
            "domain/teams",
            "domain/players",
            "domain/matches",
            "domain/events",
            "domain/odds",
        ],
    )
    def test_nao_importa_infraestrutura(self, pacote: str) -> None:
        arquivos = _arquivos(pacote)
        assert arquivos, f"{pacote} não tem arquivo para verificar"
        violacoes = _violacoes(arquivos, INFRA_EXTERNA)
        assert not violacoes, f"{pacote} importa infraestrutura: {violacoes}"

    @pytest.mark.parametrize(
        "pacote",
        [
            "domain/competitions",
            "domain/teams",
            "domain/players",
            "domain/matches",
            "domain/events",
            "domain/odds",
        ],
    )
    def test_nao_importa_adapters_nem_camadas_acima(self, pacote: str) -> None:
        violacoes = _violacoes_internas(
            _arquivos(pacote),
            (
                "sports_intelligence.adapters",
                "sports_intelligence.application",
                "sports_intelligence.ports",
                "apps",
            ),
        )
        assert not violacoes, str(violacoes)


class TestApplicationNaoConheceInfraestrutura:
    def test_use_cases_falam_por_ports(self) -> None:
        """A camada de aplicação coordena; ela não escolhe tecnologia. Um
        `import redis` aqui amarraria o caso de uso ao transporte."""
        assert not _violacoes(_arquivos("application"), INFRA_EXTERNA)

    def test_use_cases_nao_importam_adapters(self) -> None:
        violacoes = _violacoes_internas(
            _arquivos("application"), ("sports_intelligence.adapters",)
        )
        assert not violacoes


class TestOTesteVeDeVerdade:
    """O verificador precisa provar que enxerga — senão um teste de
    arquitetura que não lê nada passa sempre, e é pior que não existir."""

    def test_encontra_arquivos_para_analisar(self) -> None:
        assert len(_arquivos("domain")) >= 5
        assert len(_arquivos("ports")) >= 5

    def test_detecta_um_import_proibido_plantado(self, tmp_path: Path) -> None:
        plantado = tmp_path / "violacao.py"
        plantado.write_text("import fastapi\n", encoding="utf-8")
        assert _violacoes([plantado], INFRA_EXTERNA)

    def test_ignora_mencao_em_docstring(self) -> None:
        """A prova de que AST era necessário: esta base cita fastapi, redis e
        boto3 em docstrings explicando por que o domínio não os importa."""
        arquivo = FONTE / "domain" / "shared" / "errors.py"
        texto = arquivo.read_text(encoding="utf-8")
        assert "FastAPI" in texto, "o teste depende desta menção existir"
        assert not _violacoes([arquivo], INFRA_EXTERNA)
