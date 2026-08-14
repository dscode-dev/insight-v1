"""O mapeamento declarativo de uma fonte — validado, versionado, inerte.

INERTE É A PALAVRA IMPORTANTE. Um mapeamento chega de fora: JSON enviado pela
API, arquivo passado à CLI. É entrada não confiável, e entrada não confiável
nunca vira código. Aqui não há expressão, não há `eval`, não há lambda em
texto, não há regex fornecida pelo usuário. Há um dicionário de coluna para
papel semântico, mais transformações de um catálogo FECHADO (§81).

A tentação contrária é forte e sempre parece pequena: «só um campo `expr` para
concatenar data e hora». Ela transforma o registro de mapeamentos numa
superfície de execução remota, e a primeira fonte que precisar de algo fora do
catálogo vai empurrar nessa direção. A resposta certa é acrescentar uma
transformação nomeada ao catálogo — que é revisável — em vez de uma linguagem.

VERSIONADO porque a interpretação de um arquivo muda. Corrigir um mapeamento
não reescreve o antigo: publica outro, e as execuções que rodaram sob o
anterior continuam explicáveis.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import DatasetId, ProviderId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.domain.sources.semantics import SemanticRole, ValueKind

MAX_COLUMNS_MAPPED: Final[int] = 128
MAX_COLUMN_NAME_LENGTH: Final[int] = 128
MAX_RAW_VALUE_LENGTH: Final[int] = 512


class ValueTransform(StrEnum):
    """As transformações permitidas. Catálogo FECHADO.

    Cada uma é uma função nomeada, revisada e testada. Acrescentar uma é uma
    decisão; permitir expressões seria permitir qualquer uma, para sempre.
    """

    NONE = "NONE"
    TRIM = "TRIM"
    UPPER = "UPPER"
    LOWER = "LOWER"
    #: Percentual escrito como `59.8%` vira `59.8`. Sem isto, toda fonte que
    #: escreve o símbolo precisaria de um papel semântico próprio.
    STRIP_PERCENT = "STRIP_PERCENT"
    #: `1.234,5` (pt-BR) vira `1234.5`. Declarado pela fonte, nunca
    #: adivinhado: `1.234` é mil e duzentos e trinta e quatro numa convenção
    #: e um vírgula duzentos e trinta e quatro na outra, e adivinhar erra por
    #: um fator de mil sem nenhum aviso.
    DECIMAL_COMMA = "DECIMAL_COMMA"

    def apply(self, raw: str) -> str:
        if self is ValueTransform.NONE:
            return raw
        if self is ValueTransform.TRIM:
            return raw.strip()
        if self is ValueTransform.UPPER:
            return raw.strip().upper()
        if self is ValueTransform.LOWER:
            return raw.strip().lower()
        if self is ValueTransform.STRIP_PERCENT:
            return raw.strip().rstrip("%").strip()
        return raw.strip().replace(".", "").replace(",", ".")


#: Formatos de data e hora aceitos. FECHADO, e é aqui que a decisão do PR-00
#: sobre fuso é respeitada: nenhum formato sem fuso é convertido para UTC por
#: conta própria. A fonte declara o fuso no mapeamento, ou o valor vira
#: evidência fraca e não correção silenciosa (§25).
_FORMATOS_DE_DATA: Final[tuple[str, ...]] = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y%m%d",
)
_FORMATOS_DE_HORA: Final[tuple[str, ...]] = ("%H:%M", "%H:%M:%S", "%H%M")

_NOME_DE_COLUNA = re.compile(r"^[^\x00-\x1f]{1,128}$")


@final
@dataclass(frozen=True, slots=True)
class SourceFieldMapping:
    """Uma coluna do arquivo, e o papel que ela carrega."""

    column: str
    role: SemanticRole
    transform: ValueTransform = ValueTransform.TRIM
    #: O formato de data/hora desta coluna, quando a fonte o declara. `None`
    #: faz a leitura tentar os formatos do catálogo, em ordem — e recusar se
    #: nenhum servir, em vez de adivinhar.
    date_format: str | None = None
    #: O fuso da fonte, declarado. `None` NÃO vira UTC: vira uma observação
    #: sem fuso, que a resolução trata como evidência fraca.
    timezone: str | None = None

    def __post_init__(self) -> None:
        nome = self.column.strip()
        if not _NOME_DE_COLUNA.match(nome):
            raise ValidationError(
                f"nome de coluna inválido: {self.column!r} — 1 a "
                f"{MAX_COLUMN_NAME_LENGTH} caracteres, sem caracteres de controle"
            )
        object.__setattr__(self, "column", nome)
        if self.date_format is not None and self.date_format not in (
            *_FORMATOS_DE_DATA,
            *_FORMATOS_DE_HORA,
        ):
            aceitos = ", ".join((*_FORMATOS_DE_DATA, *_FORMATOS_DE_HORA))
            raise ValidationError(
                f"formato {self.date_format!r} fora do catálogo. Aceitos: {aceitos}. "
                "O catálogo é fechado de propósito: um formato livre é uma string "
                "vinda de fora entrando num parser."
            )

    def extract(self, raw: str | None) -> ParsedValue:
        """Converte o valor cru no tipo do papel, ou diz por que não deu.

        NUNCA LEVANTA. Um arquivo de cem mil linhas tem células ruins, e uma
        exceção por célula pararia a leitura na primeira. O resultado carrega
        a falha, e a falha vira evidência ausente — que é diferente de
        evidência divergente.
        """
        if raw is None:
            return ParsedValue.absent(self.role)
        if len(raw) > MAX_RAW_VALUE_LENGTH:
            return ParsedValue.invalid(
                self.role, raw[:80], f"valor com {len(raw)} caracteres"
            )
        texto = self.transform.apply(raw)
        if not texto:
            return ParsedValue.absent(self.role)
        return _converter(self.role, texto, self.date_format)

    def __str__(self) -> str:
        return f"{self.column!r} → {self.role}"


@final
@dataclass(frozen=True, slots=True)
class ParsedValue:
    """O valor lido de uma célula — presente, ausente ou inválido.

    TRÊS ESTADOS E NÃO DOIS. `None` sozinho confunde «a fonte não trouxe» com
    «a fonte trouxe lixo», e as duas pedem coisas diferentes: a primeira é
    normal e vira evidência ausente; a segunda é defeito do arquivo e precisa
    aparecer no relatório.
    """

    role: SemanticRole
    text: str | None = None
    number: Decimal | None = None
    integer: int | None = None
    day: date | None = None
    clock: time | None = None
    moment: datetime | None = None
    #: Preenchido quando a conversão falhou. A presença dele É o erro.
    error: str | None = None

    @property
    def is_present(self) -> bool:
        return self.error is None and any(
            v is not None
            for v in (self.text, self.number, self.integer, self.day, self.clock, self.moment)
        )

    @property
    def is_invalid(self) -> bool:
        return self.error is not None

    @classmethod
    def absent(cls, role: SemanticRole) -> Self:
        return cls(role=role)

    @classmethod
    def invalid(cls, role: SemanticRole, raw: str, motivo: str) -> Self:
        return cls(role=role, text=raw, error=motivo)

    def as_text(self) -> str | None:
        """A forma textual, qualquer que tenha sido o tipo lido.

        Existe porque a resolução compara texto normalizado, e o resolver não
        deveria precisar saber se a coluna foi lida como inteiro ou como
        string para poder normalizá-la.
        """
        if self.error is not None:
            return None
        for valor in (self.text, self.integer, self.number, self.day, self.moment, self.clock):
            if valor is not None:
                return str(valor)
        return None


def _converter(role: SemanticRole, texto: str, formato: str | None) -> ParsedValue:
    tipo = role.value_kind
    if tipo is ValueKind.TEXT:
        return ParsedValue(role=role, text=texto)
    if tipo is ValueKind.INTEGER:
        try:
            return ParsedValue(role=role, integer=int(texto))
        except ValueError:
            return ParsedValue.invalid(role, texto, "não é inteiro")
    if tipo is ValueKind.DECIMAL:
        try:
            return ParsedValue(role=role, number=Decimal(texto))
        except (InvalidOperation, ValueError):
            return ParsedValue.invalid(role, texto, "não é decimal")
    if tipo is ValueKind.DATE:
        dia = _parse_data(texto, formato)
        return (
            ParsedValue(role=role, day=dia)
            if dia
            else ParsedValue.invalid(role, texto, "não é data em formato conhecido")
        )
    if tipo is ValueKind.TIME:
        hora = _parse_hora(texto, formato)
        return (
            ParsedValue(role=role, clock=hora)
            if hora
            else ParsedValue.invalid(role, texto, "não é hora em formato conhecido")
        )
    momento = _parse_timestamp(texto, formato)
    return (
        ParsedValue(role=role, moment=momento)
        if momento
        else ParsedValue.invalid(role, texto, "não é instante em formato conhecido")
    )


def _candidatos_de_formato(
    declarado: str | None, catalogo: tuple[str, ...]
) -> tuple[str, ...]:
    """O formato declarado pela fonte, ou o catálogo inteiro.

    O DECLARADO GANHA E É O ÚNICO TENTADO. Cair para o catálogo quando o
    formato declarado falha adivinharia — e `03/04/2019` é 3 de abril numa
    convenção e 4 de março na outra. Uma célula que não bate com o formato
    declarado é célula inválida, não célula em outro formato.
    """
    return (declarado,) if declarado else catalogo


def _parse_data(texto: str, formato: str | None) -> date | None:
    for candidato in _candidatos_de_formato(formato, _FORMATOS_DE_DATA):
        try:
            return datetime.strptime(texto, candidato).date()  # noqa: DTZ007
        except ValueError:
            continue
    return None


def _parse_hora(texto: str, formato: str | None) -> time | None:
    for candidato in _candidatos_de_formato(formato, _FORMATOS_DE_HORA):
        try:
            return datetime.strptime(texto, candidato).time()  # noqa: DTZ007
        except ValueError:
            continue
    return None


def _parse_timestamp(texto: str, formato: str | None) -> datetime | None:
    """ISO-8601 primeiro; depois os formatos do catálogo.

    O RESULTADO PODE SER INGÊNUO, e é deliberado. Um instante sem fuso
    continua sem fuso até que o mapeamento declare qual é — supor UTC aqui é
    o defeito clássico de ingestão de fonte pública, e ele move a partida
    para o dia errado quando o jogo é à noite (PR-00, `instant`).
    """
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        pass
    dia = _parse_data(texto, formato)
    return datetime.combine(dia, time.min) if dia else None


class MappingStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    #: Substituído por uma versão nova. Fica, porque execuções antigas
    #: rodaram sob ele e precisam continuar explicáveis.
    SUPERSEDED = "SUPERSEDED"


@final
@dataclass(frozen=True, slots=True)
class SourceMappingDefinition:
    """Como ler UM dataset. Versionado e imutável.

    O `provider_id` MORA AQUI e não no dataset porque é o mapeamento que
    afirma de qual provedor as referências de id daquele arquivo são. Um
    dataset pode ter arquivos de origens distintas; o mapeamento é por
    interpretação, não por bytes.
    """

    id: str
    dataset_id: DatasetId
    dataset_version: DatasetVersion
    provider_id: ProviderId
    version: int
    fields: tuple[SourceFieldMapping, ...]
    status: MappingStatus
    created_at: Instant
    created_by: str
    #: O que a fonte diz sobre si mesma e que nenhuma coluna carrega: a
    #: convenção de temporada, o fuso padrão. Chaves fechadas.
    conventions: dict[str, str] = field(default_factory=dict)
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.fields:
            raise ValidationError("mapeamento sem nenhuma coluna: não haveria o que ler")
        if len(self.fields) > MAX_COLUMNS_MAPPED:
            raise ValidationError(
                f"{len(self.fields)} colunas mapeadas, acima de {MAX_COLUMNS_MAPPED}"
            )
        if self.version < 1:
            raise ValidationError(f"versão de mapeamento {self.version} inválida")
        if not self.created_by.strip():
            raise ValidationError("mapeamento sem autor")

        colunas = [f.column.lower() for f in self.fields]
        if len(set(colunas)) != len(colunas):
            repetidas = sorted({c for c in colunas if colunas.count(c) > 1})
            raise ValidationError(
                f"coluna mapeada duas vezes: {repetidas} — duas leituras da mesma "
                "coluna produziriam dois valores para o mesmo registro"
            )
        papeis = [f.role for f in self.fields]
        repetidos = sorted({p.value for p in papeis if papeis.count(p) > 1})
        if repetidos:
            raise ValidationError(
                f"papel semântico atribuído a duas colunas: {repetidos} — qual das "
                "duas o resolver deveria usar não estaria definido"
            )
        desconhecidas = set(self.conventions) - _CONVENCOES_CONHECIDAS
        if desconhecidas:
            raise ValidationError(
                f"convenção desconhecida: {sorted(desconhecidas)}. Aceitas: "
                f"{sorted(_CONVENCOES_CONHECIDAS)}"
            )

    @classmethod
    def draft(
        cls,
        *,
        dataset_id: DatasetId,
        dataset_version: DatasetVersion,
        provider_id: ProviderId,
        version: int,
        fields: tuple[SourceFieldMapping, ...],
        at: Instant,
        created_by: str,
        conventions: dict[str, str] | None = None,
        description: str | None = None,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            provider_id=provider_id,
            version=version,
            fields=fields,
            status=MappingStatus.ACTIVE,
            created_at=at,
            created_by=created_by,
            conventions=conventions or {},
            description=description,
        )

    def by_role(self, role: SemanticRole) -> SourceFieldMapping | None:
        return next((f for f in self.fields if f.role is role), None)

    def column_for(self, role: SemanticRole) -> str | None:
        campo = self.by_role(role)
        return campo.column if campo else None

    @property
    def roles(self) -> frozenset[SemanticRole]:
        return frozenset(f.role for f in self.fields)

    @property
    def identity_roles(self) -> frozenset[SemanticRole]:
        return frozenset(r for r in self.roles if r.is_identity)

    @property
    def observation_roles(self) -> frozenset[SemanticRole]:
        return frozenset(r for r in self.roles if r.is_observation)

    def assert_resolvable_as_matches(self) -> None:
        """Recusa um mapeamento que não permite sequer procurar uma partida.

        FALHA NO REGISTRO, e não na execução. Descobrir que falta o nome do
        visitante depois de processar cem mil linhas custa a execução inteira;
        descobrir no `POST` custa uma mensagem.
        """
        from sports_intelligence.domain.sources.semantics import MATCH_REQUIRED_ROLES

        faltando = MATCH_REQUIRED_ROLES - self.roles
        tem_kickoff = bool(
            self.roles & {SemanticRole.KICKOFF, SemanticRole.KICKOFF_DATE}
        )
        if faltando or not tem_kickoff:
            problemas = sorted(r.value for r in faltando)
            if not tem_kickoff:
                problemas.append("KICKOFF ou KICKOFF_DATE")
            raise ValidationError(
                f"mapeamento não permite resolver partidas: faltam {problemas}",
                context={"mapping_id": self.id},
            )

    def superseded(self) -> Self:
        from dataclasses import replace

        return replace(self, status=MappingStatus.SUPERSEDED)

    def __str__(self) -> str:
        return (
            f"mapeamento v{self.version} [{self.status}] {self.provider_id} · "
            f"{len(self.fields)} coluna(s)"
        )


#: As convenções que a fonte pode declarar. FECHADO — uma chave livre aqui
#: seria configuração não validada chegando ao resolver.
_CONVENCOES_CONHECIDAS: Final[frozenset[str]] = frozenset(
    {
        # `CALENDAR_YEAR` (Brasileirão) ou `SPLIT_YEAR` (Premier League).
        # Sem isso, `2024` é ambíguo e a temporada não resolve (§15).
        "season_convention",
        # Fuso padrão do arquivo, quando nenhuma coluna o traz.
        "default_timezone",
        # Nome da casa de apostas, quando o arquivo é de uma só.
        "bookmaker",
    }
)


class SeasonConvention(StrEnum):
    """Como a fonte escreve temporada. Declarado, nunca adivinhado.

    `2024` NO BRASILEIRÃO é a temporada de 2024. `2024` NUMA FONTE DE PREMIER
    LEAGUE costuma ser 2023/24 — ou 2024/25, conforme o publicador. Resolver
    universalmente para um dos dois erra metade das vezes, em silêncio (§15).
    """

    CALENDAR_YEAR = "CALENDAR_YEAR"
    SPLIT_YEAR = "SPLIT_YEAR"
    #: A fonte não declarou. A resolução de temporada exige outra evidência —
    #: a data da partida — e sem ela vai para revisão.
    UNDECLARED = "UNDECLARED"
