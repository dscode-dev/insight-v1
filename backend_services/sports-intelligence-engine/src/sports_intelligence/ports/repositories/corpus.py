"""Os ports do corpus histórico — dataset, versão, pertinência, manifesto.

TRÊS PORTS E NÃO UM, e a separação é a mesma do domínio (§6, §7, §18):

    HistoricalCanonicalDatasetRepositoryPort   identidade lógica e versões
    CorpusMembershipRepositoryPort             quem pertence a qual versão
    CanonicalManifestRepositoryPort            a descrição publicada

Um repositório único faria «listar datasets» e «paginar dez mil membros»
viverem atrás da mesma fachada, e a segunda operação arrastaria a primeira
para uma assinatura que ela não precisa.

TUDO EM MASSA, OUTRA VEZ (§67, §86). Nenhum método aqui recebe ou devolve uma
partida sozinha num laço: a pertinência é gravada em lote e lida por chave,
porque dez mil partidas é o tamanho que o benchmark do §90 exige.

NÃO EXISTE `update_version_content`. Uma versão `READY` é imutável (§10,
§115): a ausência do método é o que impede o caminho de código que mudaria
uma publicação por dentro. O que existe é `supersede`, que cria a sucessão
sem tocar no que já foi publicado.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.build.decisions import BuildDecision
from sports_intelligence.domain.corpus.facts import MatchCorpusFacts
from sports_intelligence.domain.corpus.manifest import (
    CorpusObjectRef,
    HistoricalCanonicalManifest,
)
from sports_intelligence.domain.corpus.membership import CorpusMember
from sports_intelligence.domain.corpus.versions import (
    DatasetVersionStatus,
    HistoricalCanonicalDataset,
    HistoricalCanonicalDatasetVersion,
)
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.versioning import DatasetVersion


@runtime_checkable
class HistoricalCanonicalDatasetRepositoryPort(Protocol):
    """Datasets e suas versões. O nome é único; a versão, imutável."""

    async def create_dataset(
        self, dataset: HistoricalCanonicalDataset
    ) -> HistoricalCanonicalDataset:
        """Cria o dataset. Recusa nome repetido no BANCO (§80).

        A UNICIDADE É CONSTRAINT E NÃO CONSULTA-ANTES-DE-INSERIR. Duas
        requisições simultâneas com o mesmo nome passariam as duas pela
        consulta e inseririam as duas — a corrida é estreita e existe. Quem
        arbitra é o índice único, e o adapter traduz a violação em
        `ConflictError`.
        """
        ...

    async def dataset_by_name(self, name: str) -> HistoricalCanonicalDataset | None: ...

    async def dataset_by_id(self, dataset_id: str) -> HistoricalCanonicalDataset | None: ...

    async def list_datasets(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[HistoricalCanonicalDataset], int]: ...

    async def create_version(
        self, version: HistoricalCanonicalDatasetVersion
    ) -> HistoricalCanonicalDatasetVersion:
        """Cria a versão em `DRAFT`. `(dataset_id, version)` é único (§64).

        A MESMA VERSÃO DUAS VEZES É UM ERRO E NÃO UM REUSO. «1.0» precisa
        significar um conteúdo só, para sempre; aceitar a segunda faria dois
        corpus diferentes atenderem pelo mesmo nome, e todo resultado citando
        «1.0» ficaria ambíguo retroativamente.
        """
        ...

    async def version_by_id(self, version_id: str) -> HistoricalCanonicalDatasetVersion | None: ...

    async def version_of(
        self, dataset_id: str, version: DatasetVersion
    ) -> HistoricalCanonicalDatasetVersion | None: ...

    async def transition(
        self,
        version: HistoricalCanonicalDatasetVersion,
        *,
        expected: DatasetVersionStatus,
    ) -> bool:
        """Grava a transição SE o estado gravado ainda for `expected`.

        É O `UPDATE ... WHERE status = ?` DO PR-03, e ele é a única escrita
        que uma versão aceita. `False` significa que outra execução chegou
        primeiro — e quem chamou decide, em vez de sobrescrever.

        CONCORRÊNCIA SEM REDIS (§84). A serialização é do banco: duas
        publicações simultâneas da mesma versão disputam a mesma linha, e a
        segunda vê `False`. Um lock distribuído seria uma dependência a mais
        para resolver o que uma cláusula `WHERE` já resolve.
        """
        ...

    async def list_versions(
        self,
        dataset_id: str,
        *,
        status: DatasetVersionStatus | None = None,
        usage: UsageScope | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[HistoricalCanonicalDatasetVersion], int]:
        """As versões de um dataset, da mais nova para a mais velha.

        FILTRA POR ESCOPO DE USO porque pesquisa e comércio produzem versões
        distintas do mesmo dataset (ADR-0025), e listar as duas juntas sem
        distinção faria alguém publicar a de pesquisa achando que é a outra.
        """
        ...

    async def latest_ready(
        self, dataset_id: str, *, usage: UsageScope
    ) -> HistoricalCanonicalDatasetVersion | None:
        """A versão publicada mais recente daquele escopo — a do §72.

        `SUPERSEDED` NÃO CONTA AQUI, e conta em `list_versions`. São duas
        perguntas: «qual é o corpus atual» e «quais corpus existem». A
        primeira tem uma resposta só; a segunda tem histórico.
        """
        ...

    async def register_builds(self, version_id: str, build_run_ids: Sequence[str]) -> int:
        """Liga a versão às execuções que a compõem (§21).

        TABELA PRÓPRIA E NÃO COLUNA `text[]`. Uma versão feita de trinta
        builds cabe num array; o que não cabe é a pergunta inversa — «quais
        versões usaram este build?» — que num array vira varredura e numa
        tabela vira índice.
        """
        ...

    async def build_run_ids_of(self, version_id: str) -> Sequence[str]: ...

    async def versions_using_build(
        self, build_run_id: str, *, limit: int = 20
    ) -> Sequence[HistoricalCanonicalDatasetVersion]:
        """A travessia para a frente: deste build saíram quais corpus (§99)."""
        ...


@runtime_checkable
class CorpusMembershipRepositoryPort(Protocol):
    """Quem pertence a qual versão. Gravado, nunca derivado (§114)."""

    async def append_members(self, version_id: str, members: Sequence[CorpusMember]) -> int:
        """Grava um lote de membros. Devolve quantos entraram.

        IDEMPOTENTE POR `(version_id, match_id)` (§83). Um retry depois de um
        timeout parcial não pode duplicar a partida — a contagem do manifesto
        passaria a discordar do conteúdo, e ela é justamente o que alguém usa
        para conferir o conteúdo.
        """
        ...

    async def page_members(
        self,
        version_id: str,
        *,
        limit: int = 500,
        after_match_id: str | None = None,
    ) -> Sequence[CorpusMember]:
        """O próximo lote, em ordem de `match_id`. Keyset, nunca `OFFSET`.

        É COMO A MATERIALIZAÇÃO E A IMPRESSÃO CONSOMEM A VERSÃO (§86, §87).
        `OFFSET 9500` faz o banco percorrer 9.500 linhas para descartá-las, e
        varrer dez mil membros em lotes vira quadrático sem ninguém perceber.
        """
        ...

    async def members_by_match(
        self, version_id: str, match_ids: Sequence[MatchId]
    ) -> Sequence[CorpusMember]:
        """Os membros de um lote de partidas, numa consulta."""
        ...

    async def count_members(self, version_id: str) -> int:
        """A contagem REAL, do banco. É ela que o §67 compara ao manifesto."""
        ...

    async def versions_containing(self, match_id: MatchId, *, limit: int = 20) -> Sequence[str]:
        """Em quais versões esta partida entrou — a travessia do §99.

        A MESMA PARTIDA EM VÁRIAS VERSÕES É O NORMAL e não uma anomalia: ela
        entra na 1.0, entra na 1.1 e entra no corpus comercial com famílias
        diferentes. O fato canônico continua sendo um só (§116).
        """
        ...


@runtime_checkable
class CanonicalManifestRepositoryPort(Protocol):
    """Manifestos publicados. Um por versão, imutável (§53)."""

    async def save(
        self,
        manifest: HistoricalCanonicalManifest,
        *,
        object_key: str | None = None,
    ) -> HistoricalCanonicalManifest:
        """Grava o manifesto e o liga à versão.

        `object_key` É OPCIONAL porque o manifesto vive nos DOIS lugares: a
        linha no PostgreSQL responde consulta, e o `manifest.json` no object
        store é o artefato que viaja junto do corpus (ADR-0027). Sem a chave,
        só existe o primeiro — que é o caso de uma versão sem Parquet.
        """
        ...

    async def by_version(self, version_id: str) -> HistoricalCanonicalManifest | None: ...

    async def record_objects(self, version_id: str, objects: Sequence[CorpusObjectRef]) -> int:
        """Grava o que a materialização de fato escreveu (§55, §118).

        POR QUE NÃO BASTA O MANIFESTO. O documento descreve os objetos, e
        `historical_canonical_objects` os torna CONSULTÁVEIS: «o corpus 1.0
        escreveu quais arquivos» e «que arquivos ficaram órfãos daquela versão
        que falhou» são consultas com índice aqui, e varredura de bucket lá.

        IDEMPOTENTE POR `(version_id, object_key)`: a chave contém a versão e o
        índice do pedaço, então reexecutar a composição de uma versão que
        falhou reescreve as mesmas linhas em vez de duplicá-las.
        """
        ...

    async def objects_of(self, version_id: str) -> Sequence[CorpusObjectRef]:
        """Os objetos de uma versão, em ordem de chave."""
        ...

    async def by_fingerprint(
        self, corpus_fingerprint: str, *, limit: int = 10
    ) -> Sequence[HistoricalCanonicalManifest]:
        """Quais publicações produziram ESTE mesmo corpus (§89).

        PLURAL DE PROPÓSITO. Duas publicações independentes dos mesmos fatos
        têm a mesma impressão e ids diferentes — encontrá-las é a razão de a
        impressão excluir carimbo de tempo e id de execução (§31).
        """
        ...


@runtime_checkable
class CorpusCompositionReaderPort(Protocol):
    """De onde saem os fatos que uma versão publica.

    POR QUE ELE NÃO É `CanonicalRegistryPort` COM UM FILTRO. O registro
    canônico é GLOBAL: ele contém tudo que qualquer build já escreveu,
    inclusive o que um build de pesquisa produziu e o corpus comercial não
    pode conter. A composição precisa da interseção «fatos canônicos QUE ESTES
    builds autorizaram», e essa pergunta só tem resposta cruzando o registro
    com a linhagem — que é o que este port faz numa consulta em vez de em duas
    por partida.

    UMA PASSAGEM SÓ, E ELA CARREGA TUDO (§32, §43). A impressão do conteúdo e
    as linhas do Parquet saem do MESMO objeto: lê-los em duas passagens abriria
    a porta para a impressão descrever um conteúdo e o arquivo carregar outro.
    """

    async def page_facts(
        self,
        build_run_ids: Sequence[str],
        *,
        limit: int = 500,
        after_match_id: str | None = None,
    ) -> Sequence[MatchCorpusFacts]:
        """O próximo lote, UMA LINHA POR (PARTIDA, BUILD), em ordem de `match_id`.

        KEYSET E NUNCA `OFFSET`, pelo mesmo motivo do resto: varrer dez mil
        partidas com `OFFSET` crescente é quadrático, e o §90 exige dez mil.

        A MESMA PARTIDA EM DOIS BUILDS VOLTA DUAS VEZES, E É DELIBERADO
        (PR-04.3.1 §22). O PR-04.3 deduplicava aqui com
        `DISTINCT ON (match_id) … ORDER BY created_at DESC`, e ao deduplicar
        respondia uma pergunta que ninguém fez: «qual build vence?». Com ele, as
        famílias e a linhagem do build perdedor sumiam em silêncio.

        A DEDUPLICAÇÃO VIROU COMPOSIÇÃO, e ela é decisão de domínio: união de
        famílias quando os fatos concordam, recusa quando divergem, linhagem
        inteira nos dois casos. Nenhuma cláusula SQL sabe tomar essa decisão —
        `domain/corpus/composition.py` sabe.

        AS LINHAS DE UMA MESMA PARTIDA SÃO ADJACENTES, garantido pelo
        `ORDER BY match_id`. É o que permite a quem consome cortar a página no
        fim da última partida completa em vez de compor uma partida pela metade.
        """
        ...

    async def usage_scopes_of(self, build_run_ids: Sequence[str]) -> Mapping[str, UsageScope]:
        """O escopo de uso de cada execução pedida (PR-04.3.1 §27).

        POR QUE ELE É CONFERIDO ANTES DE COMPOR. Um build de pesquisa e um
        comercial sobre a MESMA partida não são contribuições complementares —
        são leituras da mesma partida sob regras de publicação diferentes.
        Compô-los produziria a UNIÃO das famílias, e a união de um corpus
        comercial com um de pesquisa é um corpus de pesquisa com rótulo
        comercial: as odds restritas que a política comercial acabou de excluir
        voltariam pela porta do outro build.

        UMA CONSULTA PARA TODOS OS BUILDS. Ela roda uma vez por publicação, e
        não por lote — o escopo de uma execução não muda no meio da varredura.
        """
        ...

    async def decisions_of(
        self, build_run_ids: Sequence[str], match_ids: Sequence[MatchId]
    ) -> Sequence[BuildDecision]:
        """As decisões por família de um lote — inclusive as EXCLUSÕES.

        UMA DECISÃO POR (BUILD, PARTIDA), e o plural é o ponto: dois builds
        decidem separadamente sobre a mesma partida, e misturá-los numa decisão
        só produziria a mesma família duas vezes (PR-04.3.1 §22).

        ELAS NÃO VÊM EM `page_facts` de propósito: o que ficou de fora não tem
        fato para carregar, e enfiá-lo num objeto chamado «fatos» faria a
        exclusão parecer conteúdo.
        """
        ...
