# ADR-0032 — Janelas móveis usam tempo EFETIVO local ao período

**Status:** aceito · **Data:** 2026-08-19

## Contexto

O motor precisa responder «quantas finalizações houve nos últimos cinco
minutos». A pergunta parece trivial e esconde três decisões, cada uma com uma
resposta errada que é mais fácil de escrever que a certa.

**A primeira: qual régua mede a distância.** Um evento tem duas marcas
temporais — quando aconteceu (`EffectiveTime`, o minuto do jogo) e quando pôde
ser conhecido (`KnowledgeTime`, o relógio de parede). Um chute dos 58 cuja
correção só ficou conhecida aos 64 continua sendo um fato dos 58. Usar a
segunda régua para decidir a janela faria a correção «trazer» o chute para
dentro dos últimos cinco minutos — e a feature registraria um pico de pressão
que aconteceu no processamento, não no campo.

**A segunda: o corpus não tem relógio contínuo.** As posições que ele publica
são `(fase, minuto, acréscimo)`. Não há duração de intervalo, não há
`kickoff + delta`. Achatar tudo numa linha contínua exige inventar essa
duração, e a invenção quebra monotonicidade:

```
FIRST_HALF  45+3   →  «minuto global 48»
SECOND_HALF 46     →  «minuto global 46»
```

O primeiro aconteceu ANTES do segundo no relógio da TV e ficaria DEPOIS na
linha inventada. Toda janela construída sobre ela erraria perto do intervalo —
que é exatamente onde o futebol é mais interessante.

**A terceira: qual convenção de intervalo.** `[t-w, t]`, `(t-w, t]`,
`[t-w, t)`. As três são defensáveis; o que não é defensável é ter duas no mesmo
motor. Duas contagens que diferem por um, e nenhuma forma de saber qual está
certa.

## Decisão

**Janelas móveis V1 são `(t - w, t]` sobre tempo EFETIVO, e são LOCAIS AO
PERÍODO.**

```
e ∈ Window_w(t)  ⟺  period(e) = period(t)  ∧  t - w < Effective(e) ≤ t
```

Quatro consequências, e cada uma é uma regra executável:

**1. A membresia é do tempo efetivo; a visibilidade é do tempo de
conhecimento.** As duas perguntas são resolvidas em lugares diferentes e nessa
ordem: a `EffectiveEventProjection` (PR-05.1) decide o que era conhecível no
corte; a janela decide, entre os fatos visíveis, quais estão no intervalo. Uma
correção que chega perto do corte muda o VALOR do fato — o xG corrigido — e
nunca a posição dele na linha do tempo.

**2. A janela não atravessa o intervalo.** Aos 47 do segundo tempo, a janela de
cinco minutos enxerga o segundo tempo e nada mais — nem os 45+3 do primeiro.
Isso subconta quando a ação relevante está do outro lado do intervalo, e a
subcontagem é VISÍVEL e declarada. A alternativa seria uma contagem cujo erro
depende de uma duração fabricada.

**3. O eixo local existe apenas onde o cronômetro corre.** `MatchClock` já
recusa minuto diferente de zero em `HALF_TIME`, `PENALTY_SHOOTOUT` e
`FULL_TIME`. Num corte nesses períodos as features móveis são `NOT_APPLICABLE`:
uma janela de cinco minutos sobre um único ponto não mede nada, e responder
zero seria responder outra pergunta. `PRE_MATCH` é o caso limite e é
legítimo — antes do apito não houve fato nenhum, e zero é a resposta certa
quando `EVENT` está publicado.

**4. A duração entra na identidade da feature.** `window_seconds` é parâmetro
da `FeatureDefinition` e portanto da impressão dela. Trocar cinco por dez muda
a identidade, e o registro recusa duas definições com a mesma chave e conteúdos
diferentes. Sem isso, alguém ajustaria a janela e o histórico continuaria
comparando os dois números como se fossem a mesma feature.

**A unidade interna é o segundo inteiro.** `float` numa comparação de fronteira
traria `0.1 + 0.2` para dentro da decisão de qual evento entra. A resolução do
corpus continua sendo o minuto, e o construtor de `RollingWindow` recusa janela
que não seja múltipla de um minuto — uma janela de noventa segundos aparentaria
uma precisão que o dado não tem.

## Consequências

**Positivas.** Nenhum relógio é fabricado. A monotonicidade vale dentro de cada
período por construção — `minuto + acréscimo` é crescente ali, e nenhum minuto
regular colide com um de acréscimo no mesmo período. A fronteira é uma
convenção só, testada dos dois lados. E a correção tardia não pode inventar
atividade recente, que é o vazamento mais sutil que este PR podia produzir.

**Negativas, e assumidas.** Uma janela de dez minutos aos 3 do segundo tempo
enxerga três minutos de jogo, e não dez. O número é honesto e é menor do que um
leitor desatento espera. A alternativa — atravessar o intervalo — exigiria
saber quanto ele durou, e produziria um número que parece mais completo e é
inventado. Documentado em `ROLLING_WINDOW_SEMANTICS_V1.md`.

**O que esta decisão NÃO fecha.** Uma janela cross-period continua possível no
dia em que o corpus publicar duração de período ou carimbo de parede por
evento. Ela será uma FAMÍLIA NOVA de features, com chave e versão próprias —
e não uma reinterpretação silenciosa das existentes.

## Alternativas consideradas

**Minuto global contínuo (`45+3 = 48`).** Rejeitada: quebra monotonicidade e
inventa a duração do intervalo.

**Janela por número de eventos («os últimos 20 fatos»).** Rejeitada: a
densidade de eventos é uma propriedade do PROVEDOR, não do jogo. A mesma janela
cobriria dois minutos num provedor detalhado e quinze noutro.

**Janela por relógio de parede.** Rejeitada: o corpus histórico não tem
carimbo de observação por evento — o `ObservationTimes` dos eventos canônicos
guarda o instante de INGESTÃO, que não é o de ocorrência.

**`[t-w, t]` (início inclusivo).** Rejeitada por consistência, não por mérito.
A escolha aberta-fechada faz janelas adjacentes particionarem o tempo sem
sobreposição — `(50,55]` e `(55,60]` não compartilham nenhum instante —, o que
importa no dia em que alguém somar janelas.

## Referências

- ADR-0029 — features usam semântica temporal `AS_KNOWN`
- ADR-0030 — definições e espaços de feature são contratos versionados
- ADR-0031 — o estado histórico é reconstruído e nunca armazenado
- `docs/features/ROLLING_WINDOW_SEMANTICS_V1.md`
- `docs/features/RAW_FEATURE_CATALOG_V1.md`
- `docs/features/MATCH_FEATURE_EXTRACTION.md`
