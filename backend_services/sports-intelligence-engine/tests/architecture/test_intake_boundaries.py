"""O limite que o PR-02 acrescenta: intake NÃO resolve futebol.

O RISCO CONCRETO. A camada de ingestão histórica lê arquivos que contêm
`Manchester City` na coluna `HomeTeam`. A distância entre ter esse texto em
mãos e escrever `resolve_team("Manchester City")` é de uma linha, e a linha
parece útil — ela resolve o problema imediato de quem a escreve.

O custo dela é que resolução de identidade passa a acontecer sem confiança,
sem registro de conflito, sem procedência de decisão e sem fila de revisão —
tudo que o PR-03 existe para trazer. E a falha é silenciosa: três grafias
viram três clubes, cada um com um terço do histórico, e a tabela continua
somando.

ENTÃO: estes testes falham o CI quando `ingestion/historical`,
`ingestion/validation` ou `domain/datasets` importam o domínio futebolístico
ou ganham qualquer função com cara de resolução.

VERIFICADO POR AST, e não por grep, pelo mesmo motivo do PR-00: os módulos
citam `TeamId` e `resolve` em docstrings — de propósito, para explicar por que
não os usam. Um grep marcaria cada explicação como violação.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.ast_checks import (
    INFRA_EXTERNA,
    defined_functions,
    external_violations,
    files_in,
    internal_violations,
)

pytestmark = pytest.mark.architecture

#: Os pacotes do PR-02 que descrevem EVIDÊNCIA, não conhecimento.
PACOTES_DE_INTAKE = (
    "domain/datasets",
    "ingestion/historical",
    "ingestion/validation",
)

#: O domínio futebolístico do PR-01. Nada de intake pode conhecê-lo.
DOMINIO_FUTEBOLISTICO = (
    "sports_intelligence.domain.teams",
    "sports_intelligence.domain.players",
    "sports_intelligence.domain.matches",
    "sports_intelligence.domain.events",
    "sports_intelligence.domain.odds",
)

#: Módulos de resolução e fusão que AINDA NÃO EXISTEM. Listados aqui para que
#: o dia em que alguém os criar e importar do intake seja o dia em que este
#: teste falha — e não seis meses depois, quando o histórico já estiver
#: contaminado.
RESOLUCAO_E_FUSAO = (
    "sports_intelligence.ingestion.resolution",
    "sports_intelligence.ingestion.fusion",
    "sports_intelligence.ingestion.normalization",
    "sports_intelligence.historical.indexing",
)

#: Nomes de função que denunciam resolução acontecendo na camada errada.
#: Casados contra DEFINIÇÕES na árvore sintática — não contra texto.
NOMES_DE_RESOLUCAO = frozenset(
    {
        "resolve_team",
        "resolve_player",
        "resolve_match",
        "resolve_competition",
        "to_team_id",
        "to_player_id",
        "to_match_id",
        "merge_rows",
        "fuse_sources",
        "canonicalize_row",
    }
)


class TestIntakeNaoResolveFutebol:
    """O hard boundary do PR-02, em três formas de verificação."""

    @pytest.mark.parametrize("pacote", PACOTES_DE_INTAKE)
    def test_nao_importa_o_dominio_futebolistico(self, pacote: str) -> None:
        """A verificação principal.

        `domain/competitions` é a ÚNICA exceção e ela é permitida de
        propósito: `CompetitionCode` é um catálogo fechado de cinco códigos
        estáveis, e declarar a que competição um arquivo se refere não resolve
        identidade nenhuma — o operador digitou o código, ninguém leu o
        arquivo. Time, jogador, partida, evento e odds ficam de fora.
        """
        arquivos = files_in(pacote)
        assert arquivos, f"{pacote} não tem arquivo para verificar"
        violacoes = internal_violations(arquivos, DOMINIO_FUTEBOLISTICO)
        assert not violacoes, (
            f"{pacote} importa o domínio futebolístico — o intake trata de EVIDÊNCIA, "
            f"e traduzir evidência em conhecimento é o PR-03:\n"
            + "\n".join(map(str, violacoes))
        )

    @pytest.mark.parametrize("pacote", PACOTES_DE_INTAKE)
    def test_nao_importa_resolucao_nem_fusao(self, pacote: str) -> None:
        """Contra os módulos que ainda não existem.

        O teste passa hoje por vacuidade e é justamente por isso que ele vale:
        ele é a armadilha armada para o dia em que o PR-03 criar esses
        pacotes. Sem ele, o primeiro import viria sem nenhum sinal.
        """
        violacoes = internal_violations(files_in(pacote), RESOLUCAO_E_FUSAO)
        assert not violacoes, (
            "o intake importou resolução/fusão: a evidência estaria virando "
            "conhecimento na camada errada:\n" + "\n".join(map(str, violacoes))
        )

    @pytest.mark.parametrize("pacote", PACOTES_DE_INTAKE)
    def test_nao_define_funcao_de_resolucao(self, pacote: str) -> None:
        """Contra a resolução escrita AQUI, sem import nenhum.

        A proibição por import não cobre o caso mais provável: alguém escreve
        `def resolve_team(nome: str) -> TeamId` dentro do próprio validador,
        sem importar nada de fora. Este teste lê as definições da árvore
        sintática e recusa os nomes.
        """
        encontradas = [
            f"{arquivo.name}:{linha} def {nome}"
            for arquivo, linha, nome in defined_functions(files_in(pacote))
            if nome in NOMES_DE_RESOLUCAO
        ]
        assert not encontradas, (
            "resolução de identidade definida na camada de intake:\n"
            + "\n".join(encontradas)
        )

    def test_o_verificador_enxerga_de_verdade(self, tmp_path: Path) -> None:
        """Um teste de arquitetura que não detecta nada passa sempre.

        As duas metades da verificação são exercitadas contra violações
        plantadas: a função com nome de resolução e o import do domínio
        futebolístico.
        """
        com_funcao = tmp_path / "funcao.py"
        com_funcao.write_text("def resolve_team(nome):\n    return nome\n", encoding="utf-8")
        assert {nome for _, _, nome in defined_functions([com_funcao])} & NOMES_DE_RESOLUCAO

        com_import = tmp_path / "importa.py"
        com_import.write_text(
            "from sports_intelligence.domain.teams.models import Team\n", encoding="utf-8"
        )
        assert internal_violations([com_import], DOMINIO_FUTEBOLISTICO)

    def test_mencao_em_docstring_nao_conta(self) -> None:
        """A prova de que AST era necessário.

        `domain/datasets/models.py` cita `TeamId` e `Manchester City` no
        próprio cabeçalho, para explicar por que um dataset NÃO os conhece. Um
        grep marcaria a explicação como violação — e apagar a explicação para
        satisfazer o verificador é o pior desfecho possível.
        """
        alvo = files_in("domain/datasets")
        modelo = next(p for p in alvo if p.name == "models.py")
        texto = modelo.read_text(encoding="utf-8")
        assert "TeamId" in texto, "o teste depende desta menção existir"
        assert not internal_violations([modelo], DOMINIO_FUTEBOLISTICO)


class TestIntakeRespeitaAsCamadas:
    @pytest.mark.parametrize("pacote", PACOTES_DE_INTAKE)
    def test_nao_importa_infraestrutura_externa(self, pacote: str) -> None:
        """`ingestion/validation` USA pyarrow e polars, e é legítimo: ele é
        quem lê arquivo. O que ele não pode conhecer é banco, HTTP e cliente
        de object store — a leitura vem por `RawDatasetArchivePort`.
        """
        proibidos = INFRA_EXTERNA
        if pacote.startswith(("ingestion/validation", "ingestion/historical")):
            # As duas bibliotecas de leitura são a razão de estes pacotes
            # existirem — `validation` inspeciona, `historical` extrai — e o
            # resto da infraestrutura continua proibido. A leitura do arquivo
            # bruto chega por `RawDatasetArchivePort`, não por cliente de
            # object store.
            proibidos = INFRA_EXTERNA - {"polars", "pyarrow"}
        violacoes = external_violations(files_in(pacote), proibidos)
        assert not violacoes, f"{pacote}: " + "\n".join(map(str, violacoes))

    def test_dominio_de_dataset_nao_conhece_biblioteca_de_leitura(self) -> None:
        """`domain/datasets` NÃO pode importar polars nem pyarrow.

        Um domínio que importa uma biblioteca de dataframe tem um dataframe no
        modelo — e o modelo passa a ser desenhado pelo que é fácil de ler, não
        pelo que é verdade sobre o dado.
        """
        violacoes = external_violations(
            files_in("domain/datasets"), frozenset({"polars", "pyarrow", "pandas", "numpy"})
        )
        assert not violacoes, str(violacoes)

    def test_ingestion_nao_importa_adapters(self) -> None:
        """A ingestão fala por ports. Ela não escolhe S3 nem PostgreSQL."""
        violacoes = internal_violations(
            files_in("ingestion"), ("sports_intelligence.adapters",)
        )
        assert not violacoes, str(violacoes)

    def test_ingestion_nao_importa_application_nem_apps(self) -> None:
        violacoes = internal_violations(
            files_in("ingestion"),
            ("sports_intelligence.application", "apps"),
        )
        assert not violacoes, str(violacoes)


class TestArquivoBrutoNaoTemPortaDeSaida:
    """A imutabilidade verificada pela AUSÊNCIA de método.

    Meia dúzia de invariantes deste PR são protegidos por não existir um
    método. Ausência não falha sozinha: ela some no dia em que alguém escreve
    o que faltava por conveniência. Estes testes são o que dá voz a ela.
    """

    def test_object_store_port_nao_declara_delete_nem_update(self) -> None:
        from sports_intelligence.ports.object_store import ObjectStorePort

        for proibido in ("delete", "remove", "update", "copy", "move", "put"):
            assert not hasattr(ObjectStorePort, proibido), (
                f"`{proibido}` apareceu no ObjectStorePort — o arquivo bruto é a única "
                "camada que não se reconstrói (ADR-0004, ADR-0014)"
            )

    def test_archive_port_nao_declara_delete(self) -> None:
        from sports_intelligence.ports.raw_dataset_archive import RawDatasetArchivePort

        for proibido in ("delete", "remove", "overwrite", "update"):
            assert not hasattr(RawDatasetArchivePort, proibido)

    def test_repositorio_de_validacao_e_append_only(self) -> None:
        """Revalidar emite outro relatório; não corrige o anterior.

        Um `update` destruiria a diferença entre duas execuções — que é
        exatamente o que mostra o que o validador novo passou a enxergar.
        """
        from sports_intelligence.ports.repositories.dataset_registry import (
            DatasetValidationRepositoryPort,
        )

        for proibido in ("update", "update_report", "delete", "amend"):
            assert not hasattr(DatasetValidationRepositoryPort, proibido)

    def test_adapter_postgres_de_validacao_nao_tem_update_no_sql(self) -> None:
        """Verifica o SQL, não só a interface.

        Um port sem `update` cujo adapter escreve `UPDATE dataset_validation_runs`
        satisfaz o teste anterior e quebra a regra. A única exceção legítima é
        o `UPDATE datasets SET latest_validation_id`, que toca outra tabela.
        """
        caminho = (
            Path(__file__).resolve().parents[2]
            / "src/sports_intelligence/adapters/postgres/dataset_registry.py"
        )
        texto = caminho.read_text(encoding="utf-8")
        for tabela in ("dataset_validation_runs", "dataset_validation_issues", "dataset_manifests"):
            assert f"UPDATE {tabela}" not in texto, f"UPDATE em {tabela}: é append-only"

    def test_candidato_de_identidade_nao_ganhou_metodo_de_merge(self) -> None:
        """Herdado do PR-01 e reconferido aqui, porque o PR-02 é o primeiro
        que tem dados reais em mãos — que é quando a tentação aparece."""
        from sports_intelligence.domain.matches.models import MatchIdentityCandidate

        for proibido in ("matches", "merge_with", "similarity_to", "resolve"):
            assert not hasattr(MatchIdentityCandidate, proibido)


class TestSegredoNaoVazaParaOManifesto:
    def test_manifesto_nao_serializa_credencial_nem_caminho_de_bucket(self) -> None:
        """O manifesto é publicado pela API e citado em log.

        `object_key` fica de fora de propósito: publicá-la convida alguém a
        construir uma URL a partir dela, e o arquivo bruto não tem caminho de
        leitura pela API.
        """
        from sports_intelligence.domain.datasets.manifest import DatasetManifest

        campos = set(DatasetManifest.__dataclass_fields__)
        for proibido in ("object_key", "access_key", "secret", "endpoint", "bucket"):
            assert not any(proibido in c for c in campos), f"{proibido} no manifesto"
