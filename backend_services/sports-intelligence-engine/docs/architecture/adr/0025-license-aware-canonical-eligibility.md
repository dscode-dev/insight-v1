# ADR-0025 — Elegibilidade canônica ciente de licença

**Status:** aceito · **Data:** 2026-08-17

## Contexto

O motor consome fontes com licenças diferentes e produz um corpus só. A
pergunta «temos direito de publicar isto?» costuma ser lembrada tarde — depois
de o dado estar dentro do índice histórico —, e a resposta tardia significa
reconstruir o índice.

Três desenhos ingênuos, e o que cada um custa:

**Uma licença por candidato, a mais permissiva.** Um candidato montado com uma
fonte de domínio público e uma `RESEARCH_ONLY` seria «domínio público» porque
a permissiva contribuiu mais. É contornar a restrição pelo caminho de trás.

**Uma licença por candidato, a mais restritiva.** Corretíssimo e inútil: uma
fonte restrita que só trouxe odds condenaria o núcleo da partida, e o corpus
comercial perderia todas as partidas que alguém quis enriquecer com cotações.

**Licença como dimensão de qualidade.** Uma fonte tecnicamente impecável vira
«ruim», e alguém vai «corrigir» isso.

## Decisão

**A licença é registrada POR FAMÍLIA DE DADO, e o veredito de uso é um par.**

```
LicenseFootprint   família → {licenças que a alimentaram}
UsageVerdict       research: …   commercial: …   (decididos separadamente)
```

**O veredito de uso NÃO é um eixo de qualidade.** `LICENSE_RESTRICTED` e
`LICENSE_UNKNOWN` existem no catálogo de problemas para aparecerem no mesmo
relatório do operador, e a dimensão de qualidade afetada por eles é `None` —
é assim que o tipo diz que eles não pesam num eixo.

**Descartar uma família para contornar licença é uma PERMISSÃO DECLARADA.**
`HistoricalQualityPolicy.commercially_droppable` lista quais famílias podem
sair; a política de build comercial usa exatamente essa lista, e não uma cópia
— duas listas divergiriam no primeiro ajuste, e a divergência significaria
publicar comercialmente uma família que a política de qualidade considerava
restrita.

Uma família restrita que **não** está na lista não é descartada por conta
própria: a partida inteira fica de fora, com motivo. Usar o dado seria
publicar sem direito; descartá-lo sem autorização seria o motor decidindo
sozinho o que pode ser sacrificado.

**A mesma avaliação produz corpus diferentes por escopo, e os dois coexistem:**

```
avaliação
  ├─ build RESEARCH    MATCH incluída · ODDS incluída
  └─ build COMMERCIAL  MATCH incluída · ODDS EXCLUDED_BY_LICENSE (RESEARCH_ONLY)
```

**A identidade da partida é a MESMA nos dois.** O que muda é o conjunto de
famílias materializadas — nunca o `MatchId`, nunca a existência da partida.

**A exclusão deixa rastro com o motivo E a licença.** «ODDS excluída» não
responde nada; «ODDS excluída por `LICENSE_POLICY`, `RESEARCH_ONLY`, num build
`COMMERCIAL`» responde tudo, e é a pergunta que uma auditoria jurídica de fato
faz. Uma constraint exige a licença sempre que o motivo for licença.

**`UNKNOWN` vai para revisão, e não para bloqueio nem para permissão.**
Bloquear faria toda fonte sem licença declarada sumir do corpus sem ninguém
olhar; permitir seria supor permissividade. Revisão custa uma decisão humana,
que é o preço certo.

## Consequências

**Ganhamos:** «este build comercial descartou o quê, e sob qual licença» é uma
consulta com índice parcial. E uma fonte restrita deixa de ser um problema
binário — ela enriquece o corpus de pesquisa sem contaminar o comercial.

**Pagamos:** o mapa por família só é honesto se o avaliador souber atribuir
cada contribuição à família certa. A tabela `role → family` é o ponto onde
isso pode errar, e ela é código revisável em vez de heurística.

**Aceitamos:** os RÓTULOS de identidade não entram no mapa. Toda fonte precisa
trazer competição, temporada e times para resolver, e contá-los faria qualquer
fonte de odds restringir o núcleo por ter dito de que jogo se trata. O `Match`
canônico não é construído a partir desses textos — ele vem do registro, com
identidade provada no PR-03.

---

## Emenda — PR-04.2.1: a fronteira tem dois lados

A decisão acima, aplicada a TODO papel de identidade, abriria a porta oposta.
Uma fonte `RESEARCH_ONLY` que fosse a **única** a afirmar que a partida
existe — home, away, horário — veria o núcleo tratado como comercialmente
livre só porque os times já tinham `TeamId` canônico. Isso é lavagem de
licença pelo caminho da identidade.

**A classificação passa a ser por papel, e não pela categoria:**

```
RÓTULO   HOME_TEAM_NAME, SEASON_LABEL, *_PROVIDER_ID
         evidência para RECONHECER. Não vira conflito, não entra na pegada.

FATO     KICKOFF, ROUND_NUMBER, VENUE_NAME, e todas as observações
         a fonte AFIRMA algo. Vira conflito quando diverge, e é procedência
         factual do núcleo — com as consequências de licença que isso implica.
```

`SemanticRole.is_identity_label` é o catálogo fechado. `KICKOFF` entrou em
`CORE_ROLES`: duas fontes com 20:00 e 23:00 discordam de verdade.

**E confirmação não é derivação.** `LicenseFootprint.independent_support`
guarda as licenças das fontes que sustentam a família **sozinhas**, derivadas
da `FusionRule` que a fusão já gravava: `EXACT_AGREEMENT` e `MOST_COMPLETE`
sustentam; desempate não. `family_verdict` pergunta primeiro «há fonte
elegível que sustenta isto sozinha?», e só cai na regra do conjunto — a mais
restritiva, do §35 do PR-04.1 — quando não há.

Sem isso, uma fonte restrita que apenas CONFIRMA um placar de domínio público
condenaria o placar, e o corpus comercial perderia exatamente as partidas mais
bem confirmadas.

**Os três invariantes, agora provados nos dois sentidos:**

```
RestrictedIdentityEvidence     ⇏  RestrictedCanonicalFact
RestrictedOnlyFactualEvidence  ⇏  CommercialSafeFact
ResolvedIdentity               ⇏  IgnoreFactualProvenance
```

A coluna `quality_assessment_licenses.independent` (migration 0006) faz a
distinção sobreviver ao banco — sem ela, a política de build decidiria
diferente depois de reler.
