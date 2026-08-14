"""A normalização de nomes — determinística, versionada e conservadora.

O QUE ELA PRECISA FAZER: `Manchester City FC`, `Man City` e `MANCHESTER
CITY` precisam virar chaves comparáveis.

O QUE ELA NÃO PODE FAZER, E É A METADE DIFÍCIL: `Sporting CP` não pode virar
`sporting`. Existem Sporting CP, Sporting Gijón, Sporting Kansas City e
Sporting Cristal, e apagar o qualificador funde quatro clubes de quatro
continentes — exatamente o defeito que o motor anterior teve, com 591 partidas
atribuídas ao clube errado.

A REGRA GERAL QUE SAI DISSO: remover sufixo é AGRESSIVO por natureza, e cada
remoção precisa de justificativa. `FC` no fim de `Manchester City FC` é
seguro porque o que sobra — `manchester city` — ainda identifica. `CP` no fim
de `Sporting CP` não é, porque o que sobra não identifica.

Então a remoção é:

    apenas de sufixos de um catálogo FECHADO;
    apenas quando sobram pelo menos duas palavras significativas;
    nunca de palavras que compõem identidade (`United`, `City`, `Real`,
    `Sporting`, `Athletic`, `Dynamo`…), mesmo que apareçam soltas.

VERSIONADA porque toda chave normalizada gravada — todo alias, todo índice —
foi produzida por uma versão. Mudar a normalização exige reindexar, e a
versão gravada é o que permite saber o quê. Sem ela, a única saída seria
reindexar tudo, sempre.

DETERMINÍSTICA E SEM ESTADO: a mesma entrada produz a mesma saída em qualquer
execução, sem consultar nada. É o que torna o reprocessamento reproduzível.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.resolution.versions import (
    CURRENT_NORMALIZER_VERSION,
    NormalizerVersion,
)

#: Sufixos societários e de forma jurídica. Removê-los é seguro porque o que
#: sobra continua identificando o clube.
#:
#: O CATÁLOGO É FECHADO. Uma regra genérica — «remova siglas de até três
#: letras no fim» — apagaria `CP`, `CF`, `SC` e `AC` sem distinguir os casos
#: em que eles carregam identidade.
_SUFIXOS_SOCIETARIOS: Final[tuple[str, ...]] = (
    "fc",
    "f c",
    "afc",
    "cfc",
    "football club",
    "futebol clube",
    "clube de futebol",
    "esporte clube",
    "esporte clube de futebol",
    "sad",
    "ltda",
    "s a",
    "sa",
    "plc",
    "gmbh",
    "ev",
    "e v",
)

#: Prefixos que quase sempre são ruído de catálogo, e não identidade.
_PREFIXOS_REMOVIVEIS: Final[tuple[str, ...]] = ("the",)

#: Palavras que NUNCA são removidas, em nenhuma posição.
#:
#: Cada uma tem um caso real por trás. `City` distingue Manchester City de
#: Manchester United. `Real` distingue Real Madrid de Madrid (Atlético).
#: `Sporting` é a identidade inteira de quatro clubes diferentes. `Athletic`
#: separa Athletic Bilbao de Atlético. Removê-las «para normalizar» produz
#: colisões entre continentes.
PALAVRAS_DE_IDENTIDADE: Final[frozenset[str]] = frozenset(
    {
        "united",
        "city",
        "real",
        "sporting",
        "athletic",
        "atletico",
        "atletic",
        "dynamo",
        "dinamo",
        "olympique",
        "olympiacos",
        "internacional",
        "international",
        "nacional",
        "juventude",
        "juventus",
        "america",
        "americano",
        "wanderers",
        "rangers",
        "rovers",
        "albion",
        "county",
        "town",
        "hotspur",
        "forest",
        "villa",
        "palace",
        "orient",
        "argentinos",
        "juniors",
        "plate",
        "boca",
        "river",
        "central",
        "norte",
        "sul",
    }
)

#: Quantas palavras precisam sobrar para uma remoção ser aceita. Duas: com
#: uma, `Sporting CP` viraria `sporting`.
_MINIMO_DE_PALAVRAS_APOS_REMOCAO: Final[int] = 2

_ESPACOS = re.compile(r"\s+")
_PONTUACAO = re.compile(r"[^\w\s]", re.UNICODE)


@final
@dataclass(frozen=True, slots=True)
class NormalizationOptions:
    """As opções de uma normalização. Todas com default conservador.

    `strip_accents` É `True` E VALE A JUSTIFICATIVA. Fontes públicas escrevem
    `Grêmio` e `Gremio`, `Atlético` e `Atletico`, e tratá-los como clubes
    diferentes é o defeito mais comum de ingestão em português e espanhol.
    O risco oposto — dois clubes que só diferem por acento — não existe na
    prática nas cinco competições da V1.
    """

    casefold: bool = True
    strip_accents: bool = True
    strip_punctuation: bool = True
    #: Remoção de sufixo societário. `False` produz uma chave mais estrita,
    #: usada quando se quer casamento exato sem tolerância.
    strip_corporate_suffixes: bool = True
    strip_leading_articles: bool = True


#: A forma padrão. Uma constante nomeada e não `NormalizationOptions()`
#: espalhado: se o default mudar, todo lugar que o repetia muda junto sem
#: ninguém decidir.
DEFAULT_OPTIONS: Final[NormalizationOptions] = NormalizationOptions()

#: A forma estrita, para casamento exato contra chave canônica.
STRICT_OPTIONS: Final[NormalizationOptions] = NormalizationOptions(
    strip_corporate_suffixes=False, strip_leading_articles=False
)


@final
class NameNormalizer:
    """Texto de fonte em chave comparável. Sem estado, sem I/O.

    SEM ESTADO É REQUISITO, não estilo: uma normalização que dependesse de
    configuração carregada em runtime produziria chaves diferentes conforme o
    que estivesse no banco, e o reprocessamento deixaria de reproduzir.
    """

    def __init__(
        self,
        *,
        version: NormalizerVersion = CURRENT_NORMALIZER_VERSION,
        options: NormalizationOptions = DEFAULT_OPTIONS,
    ) -> None:
        self._version = version
        self._options = options

    @property
    def version(self) -> NormalizerVersion:
        return self._version

    def normalize(self, raw: str) -> str:
        """A chave comparável de um nome.

        A ORDEM DAS OPERAÇÕES IMPORTA e está fixada: decomposição Unicode,
        remoção de acento, minúsculas, remoção de pontuação, colapso de
        espaço, remoção de artigo, remoção de sufixo. Trocar a ordem muda o
        resultado — remover pontuação depois de sufixo deixaria `F.C.` sem
        casar com o catálogo, que lista `fc`.
        """
        texto = unicodedata.normalize("NFKD", raw)
        if self._options.strip_accents:
            texto = "".join(c for c in texto if not unicodedata.combining(c))
        texto = unicodedata.normalize("NFKC", texto)
        if self._options.casefold:
            texto = texto.casefold()
        if self._options.strip_punctuation:
            texto = _PONTUACAO.sub(" ", texto)
        texto = _ESPACOS.sub(" ", texto).strip()
        if not texto:
            return ""
        if self._options.strip_leading_articles:
            texto = _remover_prefixo(texto)
        if self._options.strip_corporate_suffixes:
            texto = _remover_sufixo(texto)
        return texto

    def tokens(self, raw: str) -> tuple[str, ...]:
        """As palavras da forma normalizada, para similaridade por conjunto."""
        normalizado = self.normalize(raw)
        return tuple(normalizado.split()) if normalizado else ()

    def initials(self, raw: str) -> str:
        """As iniciais — `manchester city` vira `mc`.

        Serve para reconhecer sigla contra nome (`MCI` contra `Manchester
        City`) como evidência FRACA. Nunca como autoridade: `MC` também é
        Mônaco, Melbourne City e mais uma dúzia.
        """
        return "".join(t[0] for t in self.tokens(raw) if t)


def _remover_prefixo(texto: str) -> str:
    for prefixo in _PREFIXOS_REMOVIVEIS:
        candidato = f"{prefixo} "
        if texto.startswith(candidato):
            restante = texto[len(candidato) :].strip()
            if len(restante.split()) >= 1 and restante:
                return restante
    return texto


def _remover_sufixo(texto: str) -> str:
    """Remove UM sufixo societário, se sobrar identidade suficiente.

    UM SÓ, e não em laço: remover repetidamente transformaria
    `Athletic Club FC SA` num resíduo, e o ganho de tratar o caso triplo não
    compensa o risco de encurtar demais.

    A GUARDA DAS DUAS PALAVRAS É O CORAÇÃO DESTA FUNÇÃO. Ela é o que impede
    `sporting cp` de virar `sporting` — e é a razão de existir o catálogo de
    palavras de identidade logo abaixo dela, como segunda linha.
    """
    palavras = texto.split()
    for sufixo in sorted(_SUFIXOS_SOCIETARIOS, key=len, reverse=True):
        partes = sufixo.split()
        if len(palavras) <= len(partes):
            continue
        if palavras[-len(partes) :] != partes:
            continue
        restante = palavras[: -len(partes)]
        if len(restante) < _MINIMO_DE_PALAVRAS_APOS_REMOCAO:
            # SOBRARIA UMA PALAVRA SÓ. `Sporting CP` cairia aqui se `cp`
            # estivesse no catálogo; `Chelsea FC` também cai, e continua
            # `chelsea fc` — que é conservador e correto: o alias explícito
            # resolve, e a remoção não.
            continue
        if any(p in PALAVRAS_DE_IDENTIDADE for p in partes):
            continue
        return " ".join(restante)
    return texto


def normalized_equals(a: str, b: str, *, normalizer: NameNormalizer | None = None) -> bool:
    """Se dois nomes normalizam para a mesma chave."""
    n = normalizer or NameNormalizer()
    return bool(n.normalize(a)) and n.normalize(a) == n.normalize(b)
