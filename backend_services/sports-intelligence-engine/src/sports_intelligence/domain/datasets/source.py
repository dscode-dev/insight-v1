"""De onde o dataset veio — a fonte, que não é o arquivo.

A CONFUSÃO QUE ESTE MÓDULO EXISTE PARA EVITAR. "Fonte" e "arquivo" viram
sinônimos com facilidade, e o custo aparece na primeira operação real: o
football-data.co.uk publica um CSV por competição por temporada. São vinte
arquivos e UMA fonte — um publicador, uma licença, uma URL base, uma data de
coleta. Modelar fonte por arquivo faria a licença ser declarada vinte vezes, e
bastaria uma divergir para a pergunta "posso publicar isto?" ficar sem
resposta única.

Então: uma fonte por dataset, muitos arquivos por fonte.

`retrieved_at` NÃO É `published_at`. É quando NÓS baixamos. A distinção
importa porque fonte pública corrige o passado em silêncio: o mesmo endereço
devolve conteúdo diferente em março e em agosto, sem aviso e sem changelog. O
carimbo de coleta é o que explica por que dois datasets do mesmo endereço têm
hashes diferentes — sem ele, a divergência parece defeito nosso.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, final
from urllib.parse import urlparse

from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import ProviderId
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    LicenseClass,
    SourceType,
)
from sports_intelligence.domain.shared.temporal import Instant, ObservationTimes

#: As origens que fazem sentido para intake histórico manual.
#:
#: `INSIGHT_NATIVE` está fora, e a exclusão é estrutural: dado nativo nasce do
#: próprio motor processando uma partida ao vivo (ADR-0006). Ele nunca chega
#: por upload — se chegasse, seria dado nosso voltando pela porta da frente
#: como se fosse externo, e a precedência do ADR-0009 passaria a favorecê-lo
#: sobre a fonte que de fato o originou.
ORIGENS_DE_INTAKE: Final[frozenset[SourceType]] = frozenset(
    {
        SourceType.OPEN_DATA,
        SourceType.COMMERCIAL_PROVIDER,
        SourceType.MANUAL,
    }
)

#: Esquemas aceitos em `source_url`. `file://` fica de fora de propósito: um
#: caminho local numa ficha de origem é irreproduzível para qualquer outra
#: pessoa, e a ficha existe justamente para que outra pessoa reencontre o
#: dado.
_ESQUEMAS_ACEITOS: Final[frozenset[str]] = frozenset({"http", "https", "ftp"})

_NOME_DE_FONTE = re.compile(r"^[\w][\w .,'&()/+-]{1,119}$", re.UNICODE)

MAX_NOTES_LENGTH: Final[int] = 2000


def assert_intake_origin(source_type: SourceType) -> None:
    """Recusa origem que não pode chegar por upload manual."""
    if source_type not in ORIGENS_DE_INTAKE:
        aceitos = ", ".join(sorted(o.value for o in ORIGENS_DE_INTAKE))
        raise ValidationError(
            f"{source_type} não é uma origem de intake histórico. Aceitas: {aceitos}. "
            "INSIGHT_NATIVE é produzido pelo próprio motor e entra pelo caminho "
            "live→historical (ADR-0006), nunca por upload.",
            context={"source_type": source_type.value},
        )


@final
@dataclass(frozen=True, slots=True)
class DatasetSource:
    """A ficha de origem de um dataset. Uma por dataset, muitos arquivos.

    ELA EXISTE PARA RESPONDER TRÊS PERGUNTAS SEM ARQUEOLOGIA: de onde isto
    veio, quando pegamos, e o que temos direito de fazer com isso. As três
    são fáceis de responder na semana do upload e impossíveis dois anos
    depois, que é exatamente quando alguém pergunta.
    """

    source_name: str
    source_type: SourceType
    license_class: LicenseClass
    retrieved_at: Instant
    source_url: str | None = None
    publisher: str | None = None
    provider_id: ProviderId | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        assert_intake_origin(self.source_type)

        nome = self.source_name.strip()
        if not _NOME_DE_FONTE.match(nome):
            raise ValidationError(
                f"nome de fonte {self.source_name!r} inválido: 2 a 120 caracteres, "
                "letras, dígitos e pontuação simples"
            )
        object.__setattr__(self, "source_name", nome)

        if self.source_url is not None:
            object.__setattr__(self, "source_url", _url_valida(self.source_url))

        # A mesma exigência do `DataProvenance`, cobrada aqui em vez de lá:
        # um dado de provedor sem provedor não tem como perder um desempate
        # (ADR-0009), e descobrir isso na hora do desempate é tarde.
        externa = (SourceType.OPEN_DATA, SourceType.COMMERCIAL_PROVIDER)
        if self.source_type in externa and self.provider_id is None:
            raise ValidationError(
                f"origem {self.source_type} exige provider_id — "
                "sem ele não há precedência possível quando duas fontes discordarem",
                context={"source_type": self.source_type.value},
            )
        if self.source_type is SourceType.MANUAL and self.provider_id is not None:
            raise ValidationError(
                "origem MANUAL não tem provedor: o dado foi digitado ou montado "
                "por uma pessoa, e atribuí-lo a um provedor falsifica a procedência"
            )

        if self.publisher is not None:
            publicador = self.publisher.strip()
            if not publicador:
                raise ValidationError("publisher vazio: omita o campo em vez de mandar vazio")
            object.__setattr__(self, "publisher", publicador)

        if self.notes is not None and len(self.notes) > MAX_NOTES_LENGTH:
            raise ValidationError(
                f"notes com {len(self.notes)} caracteres excede o limite de {MAX_NOTES_LENGTH}"
            )

    @property
    def requires_attribution(self) -> bool:
        return self.license_class.requires_attribution

    @property
    def allows_commercial_use(self) -> bool:
        """Se a licença permite uso comercial HOJE, pelo que foi declarado.

        `UNKNOWN` responde `False`, e é a resposta certa: uma licença não
        declarada é a mais restritiva possível, nunca a mais permissiva. O
        default de uma pergunta sem resposta não pode ser "pode tudo".
        """
        return self.license_class.allows_commercial_use

    @property
    def needs_license_review(self) -> bool:
        """Se promover este dado para uso comercial exige decisão humana.

        NESTE PR ISTO É SINALIZAÇÃO, NÃO BLOQUEIO. Armazenar e validar um
        dataset `UNKNOWN` ou `RESEARCH_ONLY` é legítimo — a evidência precisa
        ser guardada antes de qualquer decisão sobre ela. O que a marca
        garante é que a promoção futura para uso ativo não possa acontecer
        por omissão: quem promover terá de responder à pergunta.
        """
        return self.license_class in (LicenseClass.UNKNOWN, LicenseClass.RESEARCH_ONLY)

    def to_provenance(self, *, ingested_at: Instant) -> DataProvenance:
        """A procedência do ARQUIVO, herdada da fonte.

        GRANULARIDADE DE ARQUIVO, E NÃO DE LINHA, DE PROPÓSITO. Dar
        procedência a cada linha agora seria inventar precisão: neste estágio
        todas as linhas de um arquivo têm exatamente a mesma origem, e a
        diferenciação só passa a existir quando fusão combinar fontes — que é
        o PR-03. Uma granularidade falsa custa espaço e mente sobre o que se
        sabe.

        Os quatro carimbos: a coleta é o que a fonte observou, e a ingestão é
        agora. `occurred_at` recebe a coleta porque, para um arquivo, o fato
        observável é o próprio ato de tê-lo obtido — não há instante mais
        preciso disponível, e inventar um seria pior.
        """
        if self.retrieved_at > ingested_at:
            # A assinatura de um fuso lido errado, e a única chance de pegá-lo
            # é aqui: mais adiante ele vira só um dataset com data estranha.
            raise ValidationError(
                f"retrieved_at ({self.retrieved_at.isoformat()}) está no futuro em relação "
                f"à ingestão ({ingested_at.isoformat()}) — quase sempre fuso declarado errado",
                context={"retrieved_at": self.retrieved_at.isoformat()},
            )
        return DataProvenance(
            source_type=self.source_type,
            provider_id=self.provider_id,
            source_record_id=self.source_url,
            times=ObservationTimes(
                occurred_at=self.retrieved_at,
                observed_at=self.retrieved_at,
                received_at=ingested_at,
                ingested_at=ingested_at,
            ),
            license_class=self.license_class,
        )


def _url_valida(raw: str) -> str:
    texto = raw.strip()
    if not texto:
        raise ValidationError("source_url vazia: omita o campo em vez de mandar vazio")
    partes = urlparse(texto)
    if partes.scheme.lower() not in _ESQUEMAS_ACEITOS:
        aceitos = ", ".join(sorted(_ESQUEMAS_ACEITOS))
        raise ValidationError(
            f"source_url {raw!r} usa esquema {partes.scheme!r}; aceitos: {aceitos}. "
            "Caminho local não serve como ficha de origem — ninguém mais o alcança."
        )
    if not partes.netloc:
        raise ValidationError(f"source_url {raw!r} não tem host")
    return texto
