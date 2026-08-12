"""A ponte entre a partida ao vivo e a memória histórica.

    tick ao vivo  →  identidade da partida  →  atlas.match_vector

O QUE ESTAVA ERRADO, E NÃO ERA O ALVO. A versão anterior montava um vetor de
32 dimensões a partir do estado EM JOGO do tick — pressão, momento, densidade
de sinal — e buscava com ele em `atlas.atlas_vector_memory`. O próprio
docstring dela admitia uma "lacuna semântica conhecida": a dimensão 10 é
pressão do mercado no corpus e recebia pressão em campo aqui; a 28 é
tendência de gols lá e recebia densidade de sinal aqui.

Aquilo não era um bug de mapeamento. Era um contorno. O corpus histórico
descreve a partida ANTES do apito; o tick descreve o que está acontecendo
DURANTE. São espaços diferentes, e nenhuma correspondência entre eles seria
correta — nem no espaço antigo, nem no de 25 dimensões que o substituiu.

A CAUSA REAL: os dois lados não têm chave em comum. O caminho ao vivo fala
`canonical_match_id`, um UUID cunhado por `atlas.identity` — cuja tabela tem
zero linhas. O corpus fala `match_uid`, derivado de (competição, temporada,
mandante, visitante, dia). Nada liga um ao outro. Foi por não ter como ligar
que a sonda passou a casar por estado em jogo.

O QUE ESTA VERSÃO FAZ. Pede a identidade da partida — competição, temporada e
os dois clubes — pelo nome. Tendo-a, consulta `atlas.vector.service` com a
lente `resultado`, a MESMA que a tela do console e o fluxo de produção usam,
medida em +9,8 pontos sobre a taxa base. Não tendo, devolve None e registra
qual campo faltou, em vez de fabricar um vetor com o que sobrou.

O tick ainda contribui com o que sabe e é comparável: as cotações. Mercado
existe nos dois lados — as que acompanham a partida em andamento são da mesma
natureza das que precederam as partidas do corpus. Estado em campo (pressão,
posse, momento) NÃO entra, porque não tem equivalente num espaço de pré-jogo,
e foi exatamente forçar essa correspondência que produziu a lacuna anterior.

DEPENDE DO CAMINHO CANÔNICO CARREGAR A IDENTIDADE NO CONTEXTO. Enquanto não
carregar, a sonda fica inerte e diz por quê — uma vez por processo, porque o
motivo é estrutural e repeti-lo por tick afogaria o log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from atlas.trends.models import TrendInputs

if TYPE_CHECKING:  # pragma: no cover
    from atlas.similarity.contracts import SimilarityContext

logger = logging.getLogger(__name__)

#: Onde a identidade PODE estar no contexto recomputado, para os produtores
#: que ainda não preenchem `TrendInputs.identity`.
#:
#: MANTIDO COMO COMPATIBILIDADE, NÃO COMO CAMINHO. Procurar por quatro
#: grafias é o mesmo que não ter contrato: quando um produtor escolher uma
#: quinta, nada quebra e a sonda fica inerte em silêncio. O caminho é
#: `inputs.identity`, e este dicionário some quando o último produtor migrar.
_CHAVES = {
    "competition": ("competition", "competition_key", "competicao"),
    "season": ("season", "temporada"),
    "home_club_id": ("home_club_id", "home_team", "home", "mandante"),
    "away_club_id": ("away_club_id", "away_team", "away", "visitante"),
}


def identidade_de(inputs: TrendInputs) -> dict[str, str] | None:
    """A identidade da partida, se o tick a carregar.

    O CAMPO PRIMEIRO. `TrendInputs.identity` é o contrato; o dicionário de
    grafias abaixo é a rampa para os produtores que ainda não migraram, e
    deixa de existir quando o último migrar.

    Devolve None nomeando o que faltou — nunca preenche com o que sobrou. Um
    vizinho encontrado a partir de identidade parcial descreve outra partida.
    """
    contexto = inputs.context or {}
    encontrado: dict[str, str] = {}
    faltando: list[str] = []
    identidade = getattr(inputs, "identity", None)
    if identidade is not None:
        campos = {
            "competition": getattr(identidade, "competition", None),
            "season": getattr(identidade, "season", None),
            "home_club_id": getattr(identidade, "home_club_id", None),
            "away_club_id": getattr(identidade, "away_club_id", None),
        }
        if all(campos.values()):
            return {k: str(v) for k, v in campos.items()}

    for campo, grafias in _CHAVES.items():
        valor = next(
            (
                str(contexto[g]).strip()
                for g in grafias
                if isinstance(contexto.get(g), str) and str(contexto[g]).strip()
            ),
            None,
        )
        if valor is None:
            faltando.append(campo)
        else:
            encontrado[campo] = valor

    if faltando:
        logger.debug(
            "atlas_similarity_probe_sem_identidade",
            extra={
                "canonical_match_id": str(inputs.canonical_match_id),
                "faltando": faltando,
            },
        )
        return None
    return encontrado


class OnlineSimilarityProbe:
    """Anexa vizinhos históricos ao tick, quando dá para saber qual partida é.

    Consome `atlas.vector.service.QueryService` — o mesmo caminho da consulta
    de produção e da tela do console. Não há segundo backend de busca, e é
    isso que garante que o que o detector vê ao vivo é o que a tela mostra.
    """

    def __init__(self, consulta=None) -> None:
        # `None` é aceito para que o serviço suba sem memória vetorial
        # construída — a sonda fica inerte em vez de derrubar o boot.
        self._consulta = consulta
        self._avisou = False

    async def probe(self, inputs: TrendInputs) -> SimilarityContext | None:
        identidade = identidade_de(inputs)
        if identidade is None:
            if not self._avisou:
                # Uma vez por processo: o motivo é estrutural e não muda a
                # cada tick, e repeti-lo por evento afogaria o log com a
                # mesma frase.
                logger.info(
                    "atlas_similarity_probe_inerte",
                    extra={
                        "motivo": (
                            "o contexto do tick não carrega competição, temporada "
                            "e clubes; sem isso não há como ligar a partida ao vivo "
                            "ao corpus histórico"
                        )
                    },
                )
                self._avisou = True
            return None

        if self._consulta is None:
            return None

        from datetime import datetime, timezone

        from atlas.vector.bridge import para_contexto
        from atlas.vector.query import Consulta

        consulta = Consulta(
            categoria="resultado",
            competition=identidade["competition"],
            season=identidade["season"],
            home_club_id=identidade["home_club_id"],
            away_club_id=identidade["away_club_id"],
            # O corte é AGORA: a partida está em andamento, e só o que já
            # aconteceu pode descrevê-la.
            as_of=datetime.now(timezone.utc),
            features=_features_conhecidas(inputs),
        )
        vizinhos, espaco, _ = await self._consulta.vizinhos(consulta)
        if espaco is None:
            return None

        # A TAXA BASE DESTA COMPETIÇÃO, da mesma tabela com que a lente foi
        # validada. O detector precisa dela para julgar concordância — 50% de
        # vitórias do mandante entre os vizinhos é notável na Premier League
        # (base 43,3%) e é exatamente o normal no Brasileirão (48,4%).
        #
        # `None` quando a competição nunca foi medida, e o detector cai no
        # padrão declarado dele em vez de supor zero.
        medida = await self._consulta.validacoes.para(
            consulta.categoria, consulta.competition
        )
        return para_contexto(
            consulta,
            vizinhos,
            taxa_base=medida.taxa_base if medida is not None else None,
        )


def _features_conhecidas(inputs: TrendInputs) -> dict[str, float]:
    """O que o tick sabe que também existe no espaço histórico.

    Curto de propósito. O tick carrega estado em jogo — pressão, momento,
    posse — e o espaço histórico descreve o pré-jogo. A interseção real é o
    mercado, que existe nos dois: as cotações que acompanham a partida são
    comparáveis com as que precederam as partidas do corpus.

    Tudo que não estiver aqui entra como a média do corpus, que padroniza
    para zero — "não informa nada" — e aparece nomeado na incerteza da
    resposta.
    """
    conhecidas: dict[str, float] = {}
    if inputs.odds_history:
        ultimo = inputs.odds_history[-1]
        precos = [
            getattr(ultimo, campo, None) for campo in ("home", "draw", "away")
        ]
        if all(isinstance(p, (int, float)) and p and p > 1.0 for p in precos):
            inversos = [1.0 / float(p) for p in precos]
            total = sum(inversos)
            conhecidas["implied_home"] = inversos[0] / total
            conhecidas["implied_draw"] = inversos[1] / total
            conhecidas["implied_away"] = inversos[2] / total
            conhecidas["overround"] = total - 1.0
            ordenadas = sorted(
                (i / total for i in inversos), reverse=True
            )
            conhecidas["favourite_margin"] = ordenadas[0] - ordenadas[1]
    return conhecidas
