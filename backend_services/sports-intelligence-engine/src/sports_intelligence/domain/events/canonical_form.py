"""A forma canônica de UM evento — a mesma para o registro e para o corpus.

DUAS PERGUNTAS, UMA SERIALIZAÇÃO (PR-04.4.2 §9, §69):

    o registro   «este evento que chegou é o MESMO que já está gravado sob
                 esta identidade, ou é outro fato com o mesmo id?»
                 → `event_fact_form`, SEM o estado do ciclo de vida
    o corpus     «esta versão publica o mesmo conteúdo de evento que aquela?»
                 → `event_content_form`, COM ele

A diferença entre as duas é uma chave (`status`) e ela vale um parágrafo em
cada função: sem ela, reprocessar um evento já corrigido seria acusado de
conflito; com ela, duas versões que publicam históricos diferentes teriam a
mesma impressão.

As duas se respondem comparando o CONTEÚDO do evento, e responder cada uma com
uma serialização INDEPENDENTE seria o defeito: elas divergiriam no primeiro
campo novo, e a divergência apareceria como um conflito que o corpus vê e o
registro não — ou o contrário, que é pior. Aqui a segunda é a primeira mais uma
chave, e não uma cópia.

O QUE ENTRA: tudo que descreve o FATO — identidade, tipo, relógio, quem, onde,
o detalhe tipado e a revisão.

O QUE NÃO ENTRA: procedência de execução (qual build, qual arquivo, qual
linha) e carimbos de ingestão. Dois processamentos do mesmo evento a partir do
mesmo dado têm procedências diferentes e são o mesmo fato; incluí-la faria a
comparação dizer «conflito» sobre reprocessamento honesto.

A LICENÇA TAMBÉM NÃO ENTRA, e a ausência é deliberada: ela decide se o evento
PODE ser publicado num escopo, não o que ele afirma. Um mesmo gol sob duas
licenças continua sendo um gol — e é a pertinência da versão, não o conteúdo,
que muda entre o corpus de pesquisa e o comercial.
"""

from __future__ import annotations

import hashlib
from typing import Final

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.events.coordinates import PitchCoordinate
from sports_intelligence.domain.events.details import (
    CardDetail,
    DuelDetail,
    EventDetail,
    GoalkeeperDetail,
    PassDetail,
    ShotDetail,
    SubstitutionDetail,
)
from sports_intelligence.domain.shared.canonical import canonical_json, uuid_text
from sports_intelligence.domain.shared.feature_value import FeatureValue

#: A VERSÃO DO CONTRATO do detalhe tipado serializado (§20). Ele viaja como
#: JSON canônico dentro do Parquet e dentro da impressão; sem versão, um campo
#: novo num detalhe faria dois arquivos com formas diferentes parecerem o
#: mesmo schema — e quem lê não teria como saber qual das duas está lendo.
EVENT_DETAIL_SCHEMA_VERSION: Final[str] = "1.0"

#: O nome de cada detalhe tipado na serialização. FECHADO e explícito: derivar
#: de `type(detail).__name__` faria uma renomeação de classe — refatoração
#: interna — mudar o conteúdo publicado de todo corpus já existente.
_NOME_DO_DETALHE: Final[dict[type, str]] = {
    ShotDetail: "SHOT",
    PassDetail: "PASS",
    CardDetail: "CARD",
    SubstitutionDetail: "SUBSTITUTION",
    GoalkeeperDetail: "GOALKEEPER",
    DuelDetail: "DUEL",
}


def detail_kind(detail: EventDetail | None) -> str | None:
    """O discriminador do detalhe, ou `None` quando não há detalhe."""
    if detail is None:
        return None
    nome = _NOME_DO_DETALHE.get(type(detail))
    if nome is None:  # pragma: no cover - o catálogo é fechado
        raise ValueError(f"detalhe tipado sem nome canônico: {type(detail).__name__}")
    return nome


def detail_form(detail: EventDetail | None) -> dict[str, object] | None:
    """O detalhe tipado como dicionário canônico, ou `None`.

    NÃO É `repr()` NEM `asdict()` (§20). O primeiro não é estável entre
    versões de Python; o segundo despeja `FeatureValue` como objeto e arrasta
    campos privados para dentro do que é publicado. Aqui cada detalhe declara
    o que publica, campo a campo.

    `xg` É TRÊS ESTADOS, e os três sobrevivem: número, ausente-com-motivo, e
    detalhe que não tem xG nenhum. `xg=None` com `xg_unavailable_reason`
    preenchido é «a fonte declarou e não veio»; as duas chaves ausentes é «este
    tipo de detalhe não fala de xG». Nenhum dos dois é zero (§23, §24).
    """
    if detail is None:
        return None
    if isinstance(detail, ShotDetail):
        return {
            "body_part": None if detail.body_part is None else detail.body_part.value,
            "kind": "SHOT",
            "outcome": detail.outcome.value,
            **_xg_form(detail.xg),
        }
    if isinstance(detail, PassDetail):
        return {
            "body_part": None if detail.body_part is None else detail.body_part.value,
            "kind": "PASS",
            "outcome": detail.outcome.value,
            "recipient_id": (
                None if detail.recipient_id is None else uuid_text(str(detail.recipient_id))
            ),
        }
    if isinstance(detail, CardDetail):
        return {
            "card_type": detail.card_type.value,
            "kind": "CARD",
            "reason": detail.reason,
        }
    if isinstance(detail, SubstitutionDetail):
        return {
            "kind": "SUBSTITUTION",
            "player_in": uuid_text(str(detail.player_in)),
            "player_out": uuid_text(str(detail.player_out)),
        }
    if isinstance(detail, GoalkeeperDetail):
        return {
            "action_type": detail.action_type.value,
            "kind": "GOALKEEPER",
            "outcome": detail.outcome.value,
        }
    if isinstance(detail, DuelDetail):
        return {
            "kind": "DUEL",
            "opponent_id": (
                None if detail.opponent_id is None else uuid_text(str(detail.opponent_id))
            ),
            "outcome": detail.outcome.value,
        }
    raise ValueError(  # pragma: no cover - o catálogo é fechado
        f"detalhe tipado sem forma canônica: {type(detail).__name__}"
    )


def _xg_form(xg: FeatureValue | None) -> dict[str, object]:
    """As chaves de xG — e a distinção entre os três estados (§23, §24).

    `xg = 0.0` É UM VALOR OBSERVADO: um chute de fora da área com
    probabilidade praticamente nula. `xg` ausente é outra coisa inteiramente —
    a fonte não mediu. Colapsar os dois envenena qualquer média calculada
    depois, e o sintoma aparece longe da causa.
    """
    if xg is None:
        return {}
    if xg.is_available:
        return {"xg": _numero(xg.require("forma canônica de evento"))}
    return {"xg": None, "xg_unavailable_reason": None if xg.reason is None else xg.reason.value}


def _numero(valor: float) -> float | int:
    """Um float que é inteiro sai como inteiro — `1.0` e `1` são o mesmo xG.

    Sem isto, o mesmo valor lido de dois caminhos (`Decimal("0")` e `0.0`)
    produziria formas diferentes, e a comparação de conteúdo apontaria um
    conflito que não existe.
    """
    return int(valor) if float(valor).is_integer() else float(valor)


def _ponto_form(point: PitchCoordinate | None) -> dict[str, object] | None:
    if point is None:
        return None
    return {"frame": point.frame.value, "x": _numero(point.x), "y": _numero(point.y)}


def event_fact_form(event: CanonicalMatchEvent) -> dict[str, object]:
    """O que o evento AFIRMA — sem o estado do ciclo de vida dele.

    A AUSÊNCIA DE `status` É A DECISÃO INTEIRA DESTA FUNÇÃO. `ACTIVE`,
    `CORRECTED` e `CANCELLED` não descrevem o que aconteceu em campo: eles
    dizem o que o motor SOUBE DEPOIS — que veio uma correção, que o VAR anulou.
    O evento não muda quando é corrigido; o que muda é a posição dele na
    cadeia.

    ISSO IMPORTA NUM PONTO CONCRETO (§69). Reprocessar o mesmo arquivo produz
    o evento com `ACTIVE`, e o registro pode tê-lo em `CORRECTED` desde a
    semana passada. Com `status` aqui dentro, esse reprocessamento — o caso
    mais comum que existe — seria acusado de conflito, e o motor recusaria uma
    releitura perfeitamente honesta.

    ELA É ORDENADA EM TUDO, e nenhum valor chega como objeto: os UUID viram
    texto normalizado, os enums viram o valor declarado, e os números passam
    pela normalização acima.
    """
    return {
        "detail": detail_form(event.detail),
        "end_location": _ponto_form(event.end_location),
        "event_id": uuid_text(str(event.id)),
        "match_id": uuid_text(str(event.match_id)),
        "minute": event.clock.minute,
        "period": event.clock.period.value,
        "player_id": None if event.player_id is None else uuid_text(str(event.player_id)),
        "revision": event.revision,
        "sequence": event.sequence,
        "start_location": _ponto_form(event.start_location),
        "stoppage": event.clock.stoppage,
        "supersedes": None if event.supersedes is None else uuid_text(str(event.supersedes)),
        "team_id": None if event.team_id is None else uuid_text(str(event.team_id)),
        "type": event.type.value,
    }


def event_content_form(event: CanonicalMatchEvent) -> dict[str, object]:
    """O que o corpus PUBLICA — o fato, MAIS o estado do ciclo de vida.

    AQUI `status` ENTRA, e pela razão oposta à de cima: uma versão que publica
    o gol como `ACTIVE` e outra que o publica como `CORRECTED` publicam
    HISTÓRIAS diferentes, e a impressão do corpus precisa enxergar a diferença
    (§15). O que para o registro é ruído de ciclo de vida, para o corpus é
    conteúdo.
    """
    return {**event_fact_form(event), "status": event.status.value}


def event_fact_digest(event: CanonicalMatchEvent) -> str:
    """O SHA-256 do FATO — estável enquanto o evento existir.

    É ELE QUE O REGISTRO GRAVA (§69). Dois eventos com a mesma identidade
    derivada e digests diferentes são um CONFLITO: a identidade afirma serem o
    mesmo evento e o conteúdo afirma o contrário, e sobrescrever escolheria
    qual dos dois fatos é verdade — decisão que não é do motor.

    ELE NÃO MUDA QUANDO O STATUS MUDA, e é isso que permite gravá-lo UMA vez,
    na inserção: a transição de revisão toca `status` e nada mais, então o
    digest continua descrevendo a linha corretamente.
    """
    return hashlib.sha256(canonical_json(event_fact_form(event))).hexdigest()


def event_content_digest(event: CanonicalMatchEvent) -> str:
    """O SHA-256 do que o corpus publica — fato mais estado.

    É ele que a pertinência de evento grava: «esta versão publicou ESTE
    conteúdo». Ele muda quando o evento é corrigido, e é exatamente o que se
    quer — a versão anterior publicou outra coisa.
    """
    return hashlib.sha256(canonical_json(event_content_form(event))).hexdigest()
