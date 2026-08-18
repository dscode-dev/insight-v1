"""A composição de VÁRIOS builds sobre a mesma partida.

O QUE ESTE MÓDULO EXISTE PARA IMPEDIR (PR-04.3.1, §22 ao §29). O PR-04.3 evitava a
partida em dobro com `DISTINCT ON (match_id) … ORDER BY created_at DESC`. Isso
DEDUPLICA, e ao deduplicar responde uma pergunta que ninguém fez: «qual build
vence?». Um build vencia por ser mais recente, e com ele venciam as famílias
que ele incluiu e a linhagem que ele registrou. As famílias do outro sumiam, e
a linhagem do outro sumia com elas — em silêncio.

QUATRO SITUAÇÕES QUE `DISTINCT ON` NÃO DISTINGUE, e que são o assunto daqui:

    identidade repetida     dois builds falam da MESMA partida. Isso não é
                            defeito — é o normal quando duas temporadas são
                            construídas em execuções diferentes.

    fato EQUIVALENTE        os dois afirmam o mesmo. Um membro, DUAS linhagens.
                            Nenhum vence porque não há disputa.

    famílias COMPLEMENTARES A trouxe ODDS, B trouxe LINEUP. O corpus recebe as
                            duas — a UNIÃO, e não a escolha.

    fato CONFLITANTE        os dois afirmam coisas diferentes sobre o mesmo
                            fato. Aqui NADA é publicado: alguém decide.

A REGRA GERAL: nenhuma linha deveria vencer arbitrariamente. Quando há acordo,
compõe-se; quando não há, recusa-se. `DISTINCT ON` não sabia fazer nem uma
coisa nem outra — ele escolhia.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final, Self, final

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.corpus.facts import MatchCorpusFacts
from sports_intelligence.domain.corpus.fingerprint import canonical_json
from sports_intelligence.domain.corpus.membership import BuildContribution, CorpusMember
from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.matches.result import MatchResult
from sports_intelligence.domain.quality.coverage import FAMILY_ORDER, CoverageFamily
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import MatchId

#: Os campos que definem se dois builds afirmam o MESMO fato. Nomeados porque
#: a lista é a definição de conflito — acrescentar um aqui é decidir que mais
#: uma divergência bloqueia publicação, e isso é uma decisão, não um detalhe.
FACTUAL_KEYS: Final[tuple[str, ...]] = ("match", "lineups", "odds")


@final
@dataclass(frozen=True, slots=True)
class FactualDivergence:
    """UM ponto em que dois builds discordam sobre a mesma partida.

    ELA CARREGA OS DOIS LADOS e não só «divergiu». «kickoff conflitante» manda
    alguém abrir dois bancos; «A diz 20:00, B diz 23:00» já é a investigação.
    """

    match_id: MatchId
    aspect: str
    left_build_run_id: str
    right_build_run_id: str
    left_digest: str
    right_digest: str

    def __str__(self) -> str:
        return (
            f"{self.match_id} · {self.aspect}: build {self.left_build_run_id[:8]} "
            f"({self.left_digest[:12]}) contra {self.right_build_run_id[:8]} "
            f"({self.right_digest[:12]})"
        )


@final
@dataclass(frozen=True, slots=True)
class ComposedMatchCorpusFacts:
    """Uma partida do corpus, composta de um ou mais builds.

    A IDENTIDADE É ÚNICA E OS FATOS SÃO OS MESMOS — é isso que a composição
    verificou antes de existir. O que ela acumula é a UNIÃO das famílias e a
    lista de builds que contribuíram.

    ELA NÃO É UMA MÉDIA NEM UMA ESCOLHA. Se os fatos divergissem, este objeto
    não teria sido construído: `compose` levanta antes.
    """

    match_id: MatchId
    competition: CompetitionCode
    season_label: str
    #: A UNIÃO das famílias incluídas, em ordem canônica.
    included_families: tuple[CoverageFamily, ...]
    contributions: tuple[BuildContribution, ...]
    #: Os fatos, tomados de qualquer contribuinte — todos afirmam o mesmo.
    facts: MatchCorpusFacts

    def __post_init__(self) -> None:
        if not self.contributions:
            raise ValidationError(
                f"{self.match_id} composta sem nenhum build contribuinte — «por que "
                "esta partida está no corpus» ficaria sem resposta"
            )
        if self.facts.included_families != self.included_families:
            raise ValidationError(
                f"{self.match_id}: a união declara "
                f"{[f.value for f in self.included_families]} e os fatos carregam "
                f"{[f.value for f in self.facts.included_families]}. As duas precisam "
                "coincidir, senão o Parquet escreve uma coisa e o manifesto promete "
                "outra"
            )

    @property
    def partition_key(self) -> tuple[str, str]:
        return (self.competition.value, self.season_label)

    def includes(self, family: CoverageFamily) -> bool:
        return family in self.included_families

    def rows_for(self, family: CoverageFamily) -> list[dict[str, object]]:
        """As linhas do Parquet — a MESMA fonte semântica da impressão (§60).

        DELEGA AOS FATOS MESCLADOS, e é por isso que `compose` mescla em vez de
        eleger um portador: se `facts` fosse a contribuição de um build só, uma
        família complementar trazida pelo outro entraria na união declarada e
        sairia vazia no arquivo — o manifesto prometeria conteúdo inexistente.
        """
        return self.facts.rows_for(family)

    def content_fingerprint(self) -> ContentHash:
        """O digest do conteúdo publicado, sobre a UNIÃO das famílias."""
        return self.facts.content_fingerprint()

    def as_member(self) -> CorpusMember:
        return CorpusMember.of(
            match_id=self.match_id,
            competition=self.competition,
            competition_id=self.facts.match.competition_id,
            season_label=self.season_label,
            season_id=self.facts.match.season_id,
            included_families=self.included_families,
            contributions=self.contributions,
            content_fingerprint=self.content_fingerprint(),
        )

    @classmethod
    def of(cls, facts: MatchCorpusFacts) -> Self:
        """A composição trivial: um build só."""
        return cls(
            match_id=facts.match.id,
            competition=facts.competition,
            season_label=facts.season_label,
            included_families=facts.included_families,
            contributions=(
                BuildContribution(
                    build_run_id=facts.build_run_id,
                    quality_assessment_id=facts.quality_assessment_id,
                    included_families=facts.included_families,
                ),
            ),
            facts=facts,
        )


def factual_digests(facts: MatchCorpusFacts) -> dict[str, str]:
    """O digest de cada ASPECTO factual, para comparar dois builds.

    POR ASPECTO E NÃO POR OBJETO INTEIRO. Um digest só diria «divergiu» e
    mandaria alguém procurar onde; por aspecto, a mensagem já diz que foi o
    horário, ou a escalação, ou a cotação.

    ELE COMPARA FATOS, NUNCA `repr()`. A forma vem de `content_form_of`, que é
    a mesma serialização canônica da impressão — comparar `repr()` faria dois
    objetos iguais divergirem por ordem de campo, e comparar JSON não canônico
    faria o mesmo por ordem de chave.
    """
    import hashlib

    forma = facts.factual_form()
    return {
        aspecto: hashlib.sha256(canonical_json(forma.get(aspecto))).hexdigest()
        for aspecto in FACTUAL_KEYS
    }


def divergences(left: MatchCorpusFacts, right: MatchCorpusFacts) -> tuple[FactualDivergence, ...]:
    """Onde dois builds discordam sobre a mesma partida.

    SÓ ASPECTOS QUE OS DOIS AFIRMAM (§32). Se A incluiu `ODDS` e B não, isso é
    complementaridade e não conflito: B não disse nada sobre odds, e silêncio
    não discorda de afirmação. Comparar o silêncio como se fosse um valor
    transformaria toda composição complementar em conflito.

    RÓTULO NÃO É FATO, e a fronteira do PR-04.2.1 continua valendo aqui: a
    grafia do nome do time não entra em `factual_form` porque o `Match`
    canônico não é construído a partir dela — `Man City` e `Manchester City`
    já terminaram no mesmo `TeamId`.
    """
    if left.match.id != right.match.id:
        raise ValidationError(
            f"comparação entre partidas diferentes: {left.match.id} e {right.match.id}"
        )
    da_esquerda, da_direita = factual_digests(left), factual_digests(right)
    familias_de_ambos = set(left.included_families) & set(right.included_families)
    encontradas: list[FactualDivergence] = []
    for aspecto in FACTUAL_KEYS:
        if _FAMILIA_DO_ASPECTO[aspecto] not in familias_de_ambos:
            continue
        if da_esquerda[aspecto] == da_direita[aspecto]:
            continue
        encontradas.append(
            FactualDivergence(
                match_id=left.match.id,
                aspect=aspecto,
                left_build_run_id=left.build_run_id,
                right_build_run_id=right.build_run_id,
                left_digest=da_esquerda[aspecto],
                right_digest=da_direita[aspecto],
            )
        )
    return tuple(encontradas)


#: Qual família cobre cada aspecto factual. `match` cobre identidade e placar
#: porque os dois vêm da família `MATCH` — o resultado não existe sem a partida.
_FAMILIA_DO_ASPECTO: Final[dict[str, CoverageFamily]] = {
    "match": CoverageFamily.MATCH,
    "lineups": CoverageFamily.LINEUP,
    "odds": CoverageFamily.ODDS,
}


def compose(facts: tuple[MatchCorpusFacts, ...]) -> ComposedMatchCorpusFacts:
    """Compõe as contribuições de uma MESMA partida. Recusa divergência.

    A ORDEM DA ENTRADA NÃO IMPORTA (§37): a união de famílias é comutativa, as
    contribuições saem ordenadas por `build_run_id`, e os fatos são os mesmos
    por definição — se não fossem, a função teria levantado.

    QUANDO ELA LEVANTA, NADA É PUBLICADO. Não há «vence o mais recente» nem
    «vence o de maior confiança»: os dois builds afirmam coisas diferentes
    sobre o mesmo fato canônico, e escolher um seria o motor decidindo no lugar
    de quem responde pelo dado (§26).
    """
    if not facts:
        raise ValidationError("composição sem contribuição nenhuma")
    ids = {f.match.id for f in facts}
    if len(ids) != 1:
        raise ValidationError(
            f"composição sobre {len(ids)} partidas diferentes — ela é por partida"
        )

    ordenados = sorted(facts, key=lambda f: f.build_run_id)
    primeiro = ordenados[0]
    todas_as_divergencias: list[FactualDivergence] = []
    for outro in ordenados[1:]:
        todas_as_divergencias.extend(divergences(primeiro, outro))
    if todas_as_divergencias:
        raise ConflictError(
            f"{len(todas_as_divergencias)} divergência(s) factual(is) entre builds "
            f"sobre a mesma partida: {todas_as_divergencias[0]}. Nenhum build vence "
            "por ser mais recente — os dois afirmam coisas diferentes sobre o mesmo "
            "fato canônico, e escolher um seria o motor decidindo no lugar de quem "
            "responde pelo dado (PR-04.3.1 §26)",
            context={
                "match_id": str(primeiro.match.id),
                "divergences": str(len(todas_as_divergencias)),
                "first": str(todas_as_divergencias[0]),
            },
        )

    presentes: set[CoverageFamily] = set()
    for contribuicao in ordenados:
        presentes.update(contribuicao.included_families)
    uniao = tuple(f for f in FAMILY_ORDER if f in presentes)

    # OS FATOS SÃO MESCLADOS, e NÃO eleitos. Eleger um portador quebraria
    # exatamente o caso complementar: com A={MATCH,ODDS} e B={MATCH,LINEUP},
    # nenhum dos dois carrega a união, e o portador escolhido escreveria uma
    # família vazia enquanto o manifesto prometeria as duas (§25, §35).
    #
    # Mesclar é seguro porque as divergências já foram recusadas acima: para
    # toda família que dois builds compartilham, os fatos são idênticos.
    mesclados = replace(
        primeiro,
        included_families=uniao,
        lineups=_primeiro_com(ordenados, CoverageFamily.LINEUP, lambda f: f.lineups),
        odds=_primeiro_com(ordenados, CoverageFamily.ODDS, lambda f: f.odds),
        result=_resultado_de(ordenados),
    )
    return ComposedMatchCorpusFacts(
        match_id=primeiro.match.id,
        competition=primeiro.competition,
        season_label=primeiro.season_label,
        included_families=uniao,
        contributions=tuple(
            BuildContribution(
                build_run_id=f.build_run_id,
                quality_assessment_id=f.quality_assessment_id,
                included_families=f.included_families,
            )
            for f in ordenados
        ),
        facts=mesclados,
    )


def _primeiro_com(
    contribuicoes: Sequence[MatchCorpusFacts],
    family: CoverageFamily,
    extrair: Callable[[MatchCorpusFacts], tuple[Any, ...]],
) -> tuple[Any, ...]:
    """O conteúdo daquela família, de quem a incluiu.

    O PRIMEIRO EM ORDEM DE `build_run_id` — e a escolha é irrelevante porque
    `divergences` já garantiu que todos os que incluem a família afirmam a
    mesma coisa. O que a ordem dá é determinismo, não preferência.
    """
    for contribuicao in contribuicoes:
        if family in contribuicao.included_families:
            return extrair(contribuicao)
    return ()


def _resultado_de(contribuicoes: Sequence[MatchCorpusFacts]) -> MatchResult | None:
    """O resultado, de quem incluiu `MATCH`.

    ELE ACOMPANHA A FAMÍLIA `MATCH` porque um placar não existe sem a partida
    — e por isso ele já foi comparado no aspecto `match` de `divergences`.
    """
    for contribuicao in contribuicoes:
        if CoverageFamily.MATCH in contribuicao.included_families:
            return contribuicao.result
    return None
