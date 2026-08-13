"""Os tipos de evento de domínio que o PR-01 publica.

TRÊS, E SÓ TRÊS. A tentação é declarar vinte de uma vez — `TeamRegistered`,
`PlayerRegistered`, `SeasonCreated` — e o custo aparece depois: cada tipo
declarado é um contrato que alguém pode assinar, e um contrato sem consumidor
é peso que nunca some porque ninguém sabe se pode remover.

Estes três têm consumidor previsto:

  `match.registered`         o worker histórico precisa saber que há partida nova
  `match.lineup.confirmed`   a janela pré-jogo fecha quando as duas saem
  `match.lifecycle.changed`  a promoção histórica reage a HISTORICAL_ACTIVE

Constantes e não enum: o tipo é uma string por contrato do `EventEnvelope`, e
um enum aqui daria a impressão de que a lista é fechada — ela cresce a cada PR.
"""

from __future__ import annotations

from typing import Final

from sports_intelligence.domain.events.envelope import SchemaVersion

#: A versão do formato dos payloads abaixo. Sobe quando um campo muda de
#: significado — nunca quando um campo novo é acrescentado no fim.
DOMAIN_SCHEMA: Final = SchemaVersion(1, 0)

MATCH_REGISTERED: Final = "match.registered"
LINEUP_CONFIRMED: Final = "match.lineup.confirmed"
MATCH_LIFECYCLE_CHANGED: Final = "match.lifecycle.changed"

#: Os quatro do PR-02, sob o mesmo critério: cada um tem consumidor previsto.
#:
#:   `dataset.registered`             a trilha administrativa e o inventário
#:   `dataset.file.stored`            a reconciliação e a métrica de tráfego
#:   `dataset.validation.completed`   quem espera o veredito sem ficar sondando
#:   `dataset.staged`                 o PR-03 acorda por aqui
#:
#: `dataset.staged` NÃO SIGNIFICA "pronto para inteligência", e o payload diz
#: isso com um campo próprio em vez de deixar cada consumidor supor.
DATASET_REGISTERED: Final = "dataset.registered"
DATASET_FILE_STORED: Final = "dataset.file.stored"
DATASET_VALIDATION_COMPLETED: Final = "dataset.validation.completed"
DATASET_STAGED: Final = "dataset.staged"
