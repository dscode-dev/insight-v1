"""A fusão em nível de campo — e por que nunca é `dict_a.update(dict_b)`.

O QUE `update` DESTRÓI, e destrói em silêncio:

    quem venceu          a última fonte escrita ganha, por acidente de ordem
    o que foi descartado o valor da outra fonte some
    por que              nenhuma regra foi registrada
    de onde veio         a procedência por campo não existe

Depois disso, `home_score = 2` é um número sem pai. Ninguém consegue dizer se
saiu da fonte A ou da B, se elas concordavam, ou se uma delas dizia 3.

Então cada campo do resultado é um `CanonicalFieldCandidate`: valor escolhido,
fonte escolhida, alternativas preservadas, regra que decidiu, confiança e
procedência. Um campo — não o registro.

DUAS FUSÕES DIFERENTES, E CONFUNDI-LAS APAGA DADO (§52):

    ESCALAR          `home_score`, `formation`, `attendance`
                     há um valor certo; as fontes concordam ou conflitam.

    CONJUNTO DE      odds de várias casas, eventos de várias fontes
    OBSERVAÇÕES      não há valor certo — há observações distintas, e todas
                     são verdade ao mesmo tempo.

Cotações de 2,00 na casa X e 2,05 na casa Y não estão em conflito. Fundi-las
numa cotação única destruiria a informação inteira — e é justamente a
diferença entre elas que o Odds Intelligence vai ler (§54).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import EntityId, MatchId, ProviderId
from sports_intelligence.domain.shared.provenance import LicenseClass, SourceType
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.sources.records import DatasetRecordRef
from sports_intelligence.domain.sources.semantics import SemanticRole

MAX_ALTERNATIVES_PER_FIELD: Final[int] = 8

#: O `kind` do conjunto de observações de odds na saída fundida.
#:
#: MORA NO DOMÍNIO porque ele faz parte do CONTRATO da saída, e não do motor
#: que a produz: quem lê um candidato fundido — a avaliação de qualidade, a
#: construção canônica — precisa reconhecer o conjunto sem importar o motor de
#: fusão para isso. Um literal `"odds"` repetido em cada leitor divergiria no
#: primeiro que alguém escrevesse `"ODDS"`.
ODDS_OBSERVATION_KIND: Final[str] = "odds"


class FusionRule(StrEnum):
    """Como um valor foi escolhido. Catálogo fechado, sem `AUTO`.

    A regra é o que permite responder «por que este número e não o outro» sem
    reexecutar a fusão — e a política que a produziu já pode ter mudado.
    """

    #: Todas as fontes disseram a mesma coisa. NÃO é um caso trivial: a
    #: concordância é evidência, e registrá-la distingue um valor confirmado
    #: por três fontes de um valor que só uma trouxe.
    EXACT_AGREEMENT = "EXACT_AGREEMENT"
    #: Houve divergência e a política nomeia uma fonte preferida para o campo.
    PREFERRED_SOURCE = "PREFERRED_SOURCE"
    #: Divergência resolvida pela qualidade declarada das fontes.
    HIGHEST_QUALITY = "HIGHEST_QUALITY"
    #: Só uma fonte trouxe o campo. Não é conflito; é cobertura.
    MOST_COMPLETE = "MOST_COMPLETE"
    #: Divergência de precisão, não de valor: `59.8` contra `60`. A mais
    #: precisa vence, e a outra fica como alternativa.
    MOST_PRECISE = "MOST_PRECISE"
    MANUAL_SELECTION = "MANUAL_SELECTION"
    #: Houve divergência e a política NÃO diz como resolver. O campo fica sem
    #: valor selecionado, com todas as alternativas preservadas.
    #:
    #: ESTE É O RESULTADO DESEJÁVEL quando não se sabe. Escolher por
    #: desempate arbitrário produziria um número que parece decidido.
    CONFLICT_UNRESOLVED = "CONFLICT_UNRESOLVED"

    @property
    def selected_a_value(self) -> bool:
        return self is not FusionRule.CONFLICT_UNRESOLVED

    @property
    def had_conflict(self) -> bool:
        return self in (
            FusionRule.PREFERRED_SOURCE,
            FusionRule.HIGHEST_QUALITY,
            FusionRule.MOST_PRECISE,
            FusionRule.MANUAL_SELECTION,
            FusionRule.CONFLICT_UNRESOLVED,
        )


@final
@dataclass(frozen=True, slots=True)
class FieldContribution:
    """O que UMA fonte disse sobre UM campo.

    CARREGA A PROCEDÊNCIA COMPLETA porque é ela que responde «de onde veio
    este valor» — dataset, arquivo, linha. Sem isso, a resposta seria «da
    fonte B», que não permite conferir.
    """

    record_ref: DatasetRecordRef
    provider_id: ProviderId
    source_type: SourceType
    license_class: LicenseClass
    #: O valor como texto canônico. Texto e não `Any` porque a comparação
    #: entre fontes é feita sobre a forma normalizada, e `Any` faria
    #: `Decimal("2.0")` e `2.0` parecerem valores diferentes.
    value: str
    #: Precisão declarada, para `MOST_PRECISE`. Casas decimais, quando
    #: numérico; `None` quando não se aplica.
    precision: int | None = None
    quality: float | None = None

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValidationError("contribuição sem valor")
        if self.quality is not None and not 0.0 <= self.quality <= 1.0:
            raise ValidationError(f"qualidade {self.quality!r} fora de [0,1]")

    def __str__(self) -> str:
        return f"{self.provider_id}={self.value!r} @ {self.record_ref}"


@final
@dataclass(frozen=True, slots=True)
class CanonicalFieldCandidate:
    """Um campo fundido: o que foi escolhido, o que sobrou, e por quê."""

    field_name: SemanticRole
    rule: FusionRule
    contributions: tuple[FieldContribution, ...]
    #: `None` em `CONFLICT_UNRESOLVED` — e a ausência é a informação. Um
    #: campo em conflito sem valor é honesto; com um valor escolhido por
    #: desempate arbitrário, pareceria decidido.
    selected_value: str | None = None
    selected_from: ProviderId | None = None
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not self.contributions:
            raise ValidationError("campo fundido sem nenhuma contribuição")
        if self.rule.selected_a_value:
            if self.selected_value is None or self.selected_from is None:
                raise ValidationError(
                    f"regra {self.rule} sem valor selecionado — ela afirma ter "
                    "escolhido e não diz o quê"
                )
            if not any(c.provider_id == self.selected_from for c in self.contributions):
                raise ValidationError(
                    f"valor selecionado atribuído a {self.selected_from}, que não "
                    "contribuiu para este campo"
                )
        elif self.selected_value is not None:
            raise ValidationError(
                "CONFLICT_UNRESOLVED com valor selecionado: o conflito não foi "
                "resolvido, e um valor aqui seria lido como se tivesse sido"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValidationError(f"confiança {self.confidence!r} fora de [0,1]")
        if len(self.contributions) > MAX_ALTERNATIVES_PER_FIELD:
            raise ValidationError(
                f"{len(self.contributions)} contribuições para um campo, acima de "
                f"{MAX_ALTERNATIVES_PER_FIELD}"
            )

    @property
    def is_unresolved_conflict(self) -> bool:
        return self.rule is FusionRule.CONFLICT_UNRESOLVED

    @property
    def agreeing_sources(self) -> tuple[ProviderId, ...]:
        """Quem disse o valor escolhido.

        PLURAL DE PROPÓSITO. Quando três fontes concordam, as três aparecem —
        e a concordância é evidência que um único `selected_from` apagaria.
        """
        if self.selected_value is None:
            return ()
        return tuple(
            sorted(
                {c.provider_id for c in self.contributions if c.value == self.selected_value},
                key=str,
            )
        )

    @property
    def alternatives(self) -> tuple[FieldContribution, ...]:
        """As contribuições que NÃO foram escolhidas. Preservadas sempre."""
        if self.selected_value is None:
            return self.contributions
        return tuple(c for c in self.contributions if c.value != self.selected_value)

    @property
    def licenses(self) -> frozenset[LicenseClass]:
        """As licenças de TODAS as fontes que contribuíram.

        DE TODAS, e não só da escolhida (§76). Um campo cujo valor veio da
        fonte permissiva mas cujo conflito foi resolvido consultando a fonte
        restrita foi produzido usando as duas — e a restrição mais forte do
        conjunto é a que vale.
        """
        return frozenset(c.license_class for c in self.contributions)

    def __str__(self) -> str:
        if self.is_unresolved_conflict:
            valores = " vs ".join(sorted({c.value for c in self.contributions}))
            return f"{self.field_name}: CONFLITO NÃO RESOLVIDO ({valores})"
        fontes = ", ".join(str(p) for p in self.agreeing_sources)
        return f"{self.field_name} = {self.selected_value!r} [{self.rule}] ← {fontes}"


@final
@dataclass(frozen=True, slots=True)
class Observation:
    """Uma observação de um conjunto — uma cotação, um evento.

    NÃO PARTICIPA DE FUSÃO ESCALAR. Duas observações do mesmo conjunto não
    são candidatas ao mesmo valor: elas coexistem. O que existe aqui é
    DEDUPLICAÇÃO — a mesma observação trazida por duas fontes — e nunca
    seleção entre valores.
    """

    #: O que distingue uma observação das outras do mesmo conjunto: a casa de
    #: apostas, o mercado e a linha, para odds. É a chave de deduplicação.
    discriminator: str
    values: dict[str, str]
    record_ref: DatasetRecordRef
    provider_id: ProviderId
    license_class: LicenseClass
    observed_at: Instant | None = None

    def __post_init__(self) -> None:
        if not self.discriminator.strip():
            raise ValidationError(
                "observação sem discriminante: duas cotações de casas diferentes "
                "ficariam indistinguíveis e uma delas seria descartada como duplicata"
            )
        if not self.values:
            raise ValidationError("observação sem valores")

    def __str__(self) -> str:
        return f"{self.discriminator}: {self.values}"


@final
@dataclass(frozen=True, slots=True)
class ObservationSet:
    """Um conjunto de observações do mesmo tipo, deduplicado.

    A DEDUPLICAÇÃO É POR DISCRIMINANTE, e só. Se duas fontes trazem a cotação
    da mesma casa para o mesmo mercado, é a mesma observação e uma basta. Se
    trazem casas diferentes, são duas observações e as duas ficam.

    NUNCA UMA MÉDIA. `(2.00 + 2.05) / 2 = 2.025` é um preço que casa nenhuma
    ofereceu, e ele apagaria justamente a dispersão entre casas — que é o
    sinal (§54, §90).
    """

    kind: str
    observations: tuple[Observation, ...]

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValidationError("conjunto de observações sem tipo")
        chaves = [o.discriminator for o in self.observations]
        if len(set(chaves)) != len(chaves):
            repetidas = sorted({c for c in chaves if chaves.count(c) > 1})
            raise ValidationError(
                f"conjunto com discriminante repetido: {repetidas} — a deduplicação "
                "deveria ter acontecido antes de construir o conjunto"
            )

    @classmethod
    def deduplicated(cls, kind: str, observations: tuple[Observation, ...]) -> Self:
        """Constrói deduplicando por discriminante, de forma determinística.

        QUANDO DUAS FONTES TRAZEM A MESMA OBSERVAÇÃO, fica a da fonte cujo
        identificador vem primeiro em ordem alfabética. É um desempate
        arbitrário e é DECLARADO como tal — o que importa é que seja o mesmo
        em toda execução, para que o reprocessamento reproduza (§33).
        """
        por_chave: dict[str, Observation] = {}
        for observacao in sorted(observations, key=lambda o: (o.discriminator, str(o.provider_id))):
            por_chave.setdefault(observacao.discriminator, observacao)
        return cls(kind=kind, observations=tuple(por_chave.values()))

    @property
    def providers(self) -> frozenset[ProviderId]:
        return frozenset(o.provider_id for o in self.observations)

    @property
    def licenses(self) -> frozenset[LicenseClass]:
        return frozenset(o.license_class for o in self.observations)

    def __len__(self) -> int:
        return len(self.observations)


@final
@dataclass(frozen=True, slots=True)
class ResolvedSourceRecord:
    """Um registro cuja identidade FOI PROVADA. O ingresso da fusão.

    O TIPO É A GUARDA (ADR-0022). A fusão aceita este tipo e não
    `SourceRecord`: um registro cuja identidade não foi resolvida não tem
    como ser construído aqui, então não há caminho de código que o funda.
    A ordem obrigatória — identidade, depois agrupamento, depois fusão —
    deixa de ser convenção e passa a ser assinatura.
    """

    record_ref: DatasetRecordRef
    provider_id: ProviderId
    source_type: SourceType
    license_class: LicenseClass
    #: A entidade canônica que este registro representa, provada por decisão.
    canonical_entity_id: EntityId
    #: A decisão que provou. Fecha a linhagem do valor até o raw.
    resolution_decision_id: str
    values: dict[SemanticRole, str]
    quality: float | None = None

    def __post_init__(self) -> None:
        if not self.resolution_decision_id.strip():
            raise ValidationError(
                "registro resolvido sem decisão: ele afirmaria identidade provada "
                "sem nada que a prove"
            )

    @property
    def observation_identity(self) -> str | None:
        """O que faz DESTA linha uma observação distinta. `None` se não é uma.

        AS DUAS PERGUNTAS QUE ISTO SEPARA (§5):

            esta linha é a MESMA linha de novo?      duplicata — descartar
            é OUTRA observação da mesma fonte?       preservar

        A CASA DE APOSTAS FAZ PARTE DA IDENTIDADE (§7). Sem ela, `Bet365` e
        `Pinnacle` na mesma partida seriam a mesma coisa, e a segunda sumiria
        — que é exatamente o defeito que o PR-03.1 mediu.

        O PAYLOAD TAMBÉM FAZ (§8, §9, §11). A V1 não tem papel semântico para
        instante da cotação nem para id da cotação no provedor, então não há
        como distinguir «tick seguinte» de «linha repetida» por metadado. Na
        dúvida, o §8 manda PRESERVAR: valores diferentes são observações
        diferentes, e só o payload IDÊNTICO da mesma casa é tratado como
        repetição. É a regra segura — ela pode preservar de sobra e nunca
        destrói informação legítima.

        MERCADO É IMPLÍCITO na V1: os três papéis de odds descrevem 1X2 e
        nada mais. Quando houver mais de um mercado, ele entra aqui.
        """
        cotacoes = {
            papel.value: valor
            for papel in _PAPEIS_DE_ODDS
            if (valor := self.values.get(papel)) is not None and valor.strip()
        }
        if not cotacoes:
            return None
        casa = (self.values.get(SemanticRole.BOOKMAKER_NAME) or "").strip()
        partes = [
            str(self.provider_id),
            casa or f"?{self.provider_id}",
            _MERCADO_1X2,
            *(f"{papel}={valor}" for papel, valor in sorted(cotacoes.items())),
        ]
        return "|".join(partes)

    def __str__(self) -> str:
        return f"{self.canonical_entity_id} ← {self.record_ref} ({self.provider_id})"


#: Os papéis que compõem o mercado 1X2. Uma constante porque a lista é
#: comparada em três lugares, e três literais divergem.
_PAPEIS_DE_ODDS: Final[tuple[SemanticRole, ...]] = (
    SemanticRole.ODDS_HOME,
    SemanticRole.ODDS_DRAW,
    SemanticRole.ODDS_AWAY,
)
#: O único mercado da V1. Nomeado para que o dia em que houver um segundo
#: seja uma mudança visível, e não um literal escondido numa f-string.
_MERCADO_1X2: Final[str] = "1X2"


@final
@dataclass(frozen=True, slots=True)
class FusionGroup:
    """Os registros de várias fontes que representam a MESMA partida.

    TODOS APONTAM PARA A MESMA ENTIDADE CANÔNICA, e isso é verificado na
    construção. Um grupo com duas entidades diferentes seria a fusão de duas
    partidas — exatamente o dano que o PR inteiro existe para impedir.
    """

    id: str
    canonical_match_id: MatchId
    records: tuple[ResolvedSourceRecord, ...]
    #: Linhas ADICIONAIS da mesma fonte que carregam observações distintas.
    #:
    #: POR QUE ELAS EXISTEM À PARTE DE `records`. A regra de `records` — uma
    #: linha por fonte — está certa para FUSÃO ESCALAR: duas linhas da mesma
    #: fonte dizendo o placar são duplicata interna, e contá-las como duas
    #: fontes inflaria a concordância.
    #:
    #: Ela está ERRADA para CONJUNTO DE OBSERVAÇÕES, e o PR-03.1 mediu o
    #: estrago: uma fonte que publica uma linha por casa de apostas tinha
    #: todas menos a primeira descartadas. `Bet365 @ 2.00` e `Pinnacle @ 2.05`
    #: não são a mesma fonte falando duas vezes — são duas observações que são
    #: verdade ao mesmo tempo, e a dispersão entre elas é o sinal.
    #:
    #: Então a linha extra entra AQUI: ela contribui para o conjunto de
    #: observações e NÃO para nenhum campo escalar. `mesma fonte` continua
    #: significando `uma contribuição` onde isso importa.
    extra_observations: tuple[ResolvedSourceRecord, ...] = ()

    def __post_init__(self) -> None:
        if not self.records:
            raise ValidationError("grupo de fusão vazio")
        alvos = {str(r.canonical_entity_id) for r in self.records}
        if len(alvos) > 1:
            raise ConflictError(
                f"grupo com {len(alvos)} entidades canônicas distintas: {sorted(alvos)}. "
                "Fundi-las combinaria partidas diferentes num registro só.",
                context={"group_id": self.id},
            )
        if str(self.canonical_match_id) not in alvos:
            raise ConflictError(
                f"grupo declarado para {self.canonical_match_id} mas os registros "
                f"apontam para {sorted(alvos)}"
            )
        for extra in self.extra_observations:
            if str(extra.canonical_entity_id) not in alvos:
                raise ConflictError(
                    f"observação extra aponta para {extra.canonical_entity_id}, fora "
                    f"do grupo {self.canonical_match_id}"
                )
            if extra.observation_identity is None:
                raise ValidationError(
                    f"registro {extra.record_ref} entrou como observação extra sem "
                    "identidade de observação — sem ela ele é duplicata interna da "
                    "fonte, e duplicata não vira contribuição"
                )
        identidades = [e.observation_identity for e in self.extra_observations]
        if len(set(identidades)) != len(identidades):
            raise ValidationError(
                "duas observações extras com a MESMA identidade no grupo — elas são "
                "a mesma cotação contada duas vezes"
            )

        provedores = [str(r.provider_id) for r in self.records]
        if len(set(provedores)) != len(provedores):
            # DUAS LINHAS DA MESMA FONTE PARA A MESMA PARTIDA é duplicata
            # dentro da fonte, não fusão entre fontes. Fundi-las contaria a
            # mesma observação duas vezes como se fossem duas confirmações.
            repetidos = sorted({p for p in provedores if provedores.count(p) > 1})
            raise ConflictError(
                f"o provedor {repetidos} aparece duas vezes no mesmo grupo — duas "
                "linhas da mesma fonte para a mesma partida são duplicata interna, "
                "e contá-las como duas fontes inflaria a concordância",
                context={"group_id": self.id},
            )

    @classmethod
    def of(
        cls,
        match_id: MatchId,
        records: tuple[ResolvedSourceRecord, ...],
        extra_observations: tuple[ResolvedSourceRecord, ...] = (),
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            canonical_match_id=match_id,
            records=records,
            extra_observations=extra_observations,
        )

    @property
    def observation_records(self) -> tuple[ResolvedSourceRecord, ...]:
        """Todas as linhas que podem carregar observação, em ordem estável.

        AS PRINCIPAIS TAMBÉM ENTRAM: a primeira linha de uma fonte carrega
        campos escalares E cotações, e excluí-la aqui perderia a primeira casa
        de apostas de toda fonte.
        """
        return tuple(
            sorted(
                (*self.records, *self.extra_observations),
                key=lambda r: (str(r.provider_id), str(r.record_ref)),
            )
        )

    @property
    def providers(self) -> tuple[ProviderId, ...]:
        return tuple(sorted((r.provider_id for r in self.records), key=str))

    @property
    def is_multi_source(self) -> bool:
        return len(self.records) > 1

    @property
    def licenses(self) -> frozenset[LicenseClass]:
        return frozenset(r.license_class for r in self.records)

    def contributions_for(self, role: SemanticRole) -> tuple[FieldContribution, ...]:
        """As contribuições de todas as fontes para um campo, em ordem estável.

        ORDENADAS PELO PROVEDOR porque a ordem das contribuições afeta o
        desempate na política, e o desempate precisa ser reproduzível.
        """
        return tuple(
            FieldContribution(
                record_ref=registro.record_ref,
                provider_id=registro.provider_id,
                source_type=registro.source_type,
                license_class=registro.license_class,
                value=valor,
                precision=_casas_decimais(valor),
                quality=registro.quality,
            )
            for registro in sorted(self.records, key=lambda r: str(r.provider_id))
            if (valor := registro.values.get(role)) is not None and valor.strip()
        )

    def __str__(self) -> str:
        return (
            f"grupo {self.id[:8]} · {self.canonical_match_id} · "
            f"{len(self.records)} fonte(s): {', '.join(str(p) for p in self.providers)}"
        )


def _casas_decimais(valor: str) -> int | None:
    """Casas decimais de um valor numérico, para `MOST_PRECISE`.

    `None` para o que não é número. Contar casas de um texto produziria uma
    precisão inventada, e a regra escolheria a formação `4-2-3-1` sobre
    `4-3-3` por ter «mais casas decimais».
    """
    try:
        decimal = Decimal(valor)
    except (ArithmeticError, ValueError):
        return None
    expoente = decimal.as_tuple().exponent
    return -int(expoente) if isinstance(expoente, int) and expoente < 0 else 0
