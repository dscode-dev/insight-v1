# Quality Assessment — schema V1

O veredito de qualidade de UMA partida candidata: se dá para confiar, o que
está lá, e se há direito de usar. Três perguntas, três objetos, e nenhum
substitui o outro.

> **Isto NÃO constrói nada.** Avaliar e construir são etapas separadas, e a
> separação é o que permite reavaliar sob política nova sem reconstruir, e
> reconstruir sob política de build nova sem reavaliar (ADR-0024).

---

## Os três eixos

```
QualityVector    posso confiar no que está aqui?      seis eixos, elo mais fraco
CoverageReport   o que está aqui?                     NÃO reprova
UsageVerdict     tenho direito de usar, e para quê?   veredito PRÓPRIO por escopo
```

Um número só erraria de três maneiras ao mesmo tempo: confundiria confiança com
riqueza, qualidade técnica com direito de uso, e esconderia o elo fraco na
média (ADR-0023).

---

## Schema

```jsonc
{
  "id":              "b41c…",
  "quality_run_id":  "9a2f…",
  "match_id":        "4f8a…",
  "fusion_group_id": "7c3d…",           // o elo para trás, até o raw

  "eligibility": "ELIGIBLE",            // ELIGIBLE | REVIEW_REQUIRED | INELIGIBLE
  "reason":      null,                  // o que decidiu, em texto legível

  "quality": {                          // os seis eixos, em [0, 1]
    "integrity":           1.0,
    "consistency":         1.0,
    "completeness":        0.83,
    "identity_confidence": 0.98,
    "temporal_integrity":  1.0,
    "provenance_quality":  0.9
  },

  "coverage": [                         // por FAMÍLIA, e sempre as sete
    { "family": "MATCH",  "state": "MEASURED",
      "available_count": 1, "expected_count": 1 },
    { "family": "ODDS",   "state": "AVAILABILITY_ONLY",
      "available_count": 6, "expected_count": null },   // sem denominador honesto
    { "family": "EVENT",  "state": "NOT_DECLARED",
      "available_count": 0, "expected_count": null }    // a fonte não trabalha com isso
  ],

  "identity": {                         // a confiança POR SUJEITO resolvido
    "COMPETITION": 1.0,
    "SEASON":      1.0,
    "TEAM":        0.99,
    "MATCH":       0.98
  },

  "usage": {
    "research":   "ELIGIBLE",           // ELIGIBLE | REVIEW_REQUIRED | INELIGIBLE
    "commercial": "REVIEW_REQUIRED",
    "footprint": {
      "by_family": {                    // quem ALIMENTOU cada família
        "MATCH": ["PUBLIC_DOMAIN", "RESEARCH_ONLY"],
        "ODDS":  ["RESEARCH_ONLY"]
      },
      "independent_support": {          // quem a sustenta SOZINHO
        "MATCH": ["PUBLIC_DOMAIN"]
      }
    }
  },

  "issues": [                           // ordenados por gravidade
    { "code": "LICENSE_RESTRICTED", "subject": "odds:bet365",
      "severity": "WARNING",            // vem da POLÍTICA, não do validador
      "context": { "provider": "fonte_restrita" } }
  ]
}
```

---

## O que a leitura precisa saber

**A cobertura tem três estados e não um número.** `MEASURED` só existe quando
há denominador honesto; `AVAILABILITY_ONLY` quando há contagem e não há
denominador; `NOT_DECLARED` quando a fonte não trabalha com aquela família. Uma
constraint impede `MEASURED` sem denominador — porque «0%» confunde «a fonte
prometeu e não veio nada» com «a fonte não promete isso», e as duas exigem
ações opostas.

**A cobertura NÃO reprova.** Uma fonte pública de futebol costuma ter placar
impecável e nenhuma escalação; tratá-la como «média» faria o motor rejeitar
exatamente as fontes que mais deveria querer.

**A licença é POR FAMÍLIA.** Com uma licença por registro, `RESEARCH_ONLY` em
qualquer campo condenaria o núcleo da partida. Com o mapa por família dá para
perguntar «e se as odds saírem?» — que é a pergunta do build comercial
(ADR-0025).

**`independent_support` não é redundante com `by_family`.** Confirmação não é
derivação: uma fonte restrita que apenas CONFIRMA um placar de domínio público
aparece em `by_family` e não contamina o fato, porque a fonte pública o
sustenta sozinha. Sem a distinção, o corpus comercial perderia exatamente as
partidas mais bem confirmadas (PR-04.2.1 §42).

**Os RÓTULOS de identidade não entram na pegada; os FATOS entram.**
`HOME_TEAM_NAME` é evidência para RECONHECER — o `Match` canônico não é
construído a partir desse texto. `KICKOFF` é FATO: duas fontes com 20:00 e
23:00 discordam de verdade, e quem o afirma é procedência factual do núcleo. A
fronteira tem dois lados, e os dois são provados (ADR-0025, emenda).

**A severidade vem da POLÍTICA e é gravada junto do problema.** O
`QualityIssue` deliberadamente não a carrega — um validador que carimbasse
severidade estaria tomando decisão de política dentro de um laço de
verificação. E sem a coluna gravada, «quantos bloqueantes esta execução
encontrou» exigiria reaplicar sobre cada linha uma política que pode ter mudado
desde então.

**A avaliação é por PARTIDA e não por dataset.** Um corpus 99% bom e 1%
corrompido avaliado no agregado promove o 1% junto — e o 1% é exatamente o que
vira fato histórico errado que ninguém detecta, porque tudo continua somando.

---

## A execução

Um veredito nunca viaja sozinho. Ele pertence a um `QualityRun`, que grava as
fusões consumidas com a impressão da saída de cada uma, a versão da política, a
IMPRESSÃO da política inteira, o instante, o ator de serviço e as contagens por
desfecho.

**A impressão da política acompanha a versão** porque a versão pega a mudança
declarada e a impressão pega a que ninguém declarou — alguém edita um piso e
esquece de subir o número, e as duas execuções ficam rotuladas `v1.0` decidindo
diferente.

**Uma execução concluída é imutável.** Política nova produz execução nova, e a
anterior fica exatamente como estava. As duas coexistem, e a diferença entre
elas é o que mostra o que a política nova passou a enxergar.

---

## Documentos relacionados

- ADR-0023 — qualidade, cobertura e licença são três eixos
- ADR-0024 — a qualidade decide, a construção consome
- ADR-0025 — elegibilidade canônica ciente de licença (com a emenda do PR-04.2.1)
- `docs/data/HISTORICAL_QUALITY_EXECUTION.md`
- `docs/contracts/HISTORICAL_CANONICAL_MANIFEST_V1.md` — como estes vereditos
  são agregados no manifesto do corpus
