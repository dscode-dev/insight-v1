# Baseline do corpus histórico canônico

Medido no **PR-04.3**, em **2026-08-18**. Este documento existe para que a
próxima execução tenha contra o que comparar, e **não** para declarar SLO.

---

## O que estes números afirmam e o que não afirmam

**Afirmam** que a composição e a publicação de dez mil partidas acontecem com
memória constante e sem N+1, e dizem quanto isso custa nesta máquina.

**Não afirmam** nada sobre outra máquina. O que sobrevive à troca de hardware
são as **propriedades**:

```
as consultas crescem por LOTE            e não por partida
o pico de memória NÃO acompanha o corpus quadruplicar o volume não dobra o pico
a impressão NÃO depende do lote          250 e 2.000 dão o mesmo resultado
a publicação é O(1) em consultas         confere por agregação, não varre
```

---

## Ambiente

```
CPU               Intel Core i9-14900KF · 32 threads
RAM               31 GB
SO                Windows 11 (10.0.26200)
Python            3.14.6 (venv local)
PostgreSQL        17.11, em contêiner (`sie-postgres`, porta 5433)
object store      MinIO, mesmo host (porta 9000)
```

PostgreSQL em **configuração de fábrica**, deliberadamente. Um baseline medido
contra um banco ajustado à mão mede o ajuste; este mede o que qualquer pessoa
obtém subindo o `docker-compose` do repositório.

Banco e motor na mesma máquina: a latência por consulta é o **piso**. Num
ambiente com banco remoto, o número de consultas pesa muito mais que aqui — e é
por isso que ele é reportado separado do tempo.

---

## Cenário

Corpus sintético de `tests/support/corpus.py`, semente `20260813` — o mesmo do
PR-03 e do PR-04.2, de propósito: comparar entre fases exige o mesmo cenário.

**12.500 registros de fonte → 10.000 partidas no corpus.** O número de partidas
é CONSEQUÊNCIA da resolução, não um parâmetro: o corpus distribui os registros
entre caminhos de casamento diferentes, e os que não resolvem não chegam ao
corpus. A razão medida é de 0,8 partida por registro, e o benchmark **afirma o
piso de 10.000** em vez de confiar nela.

Todo o caminho é real: intake → resolução → fusão → qualidade → build →
composição → publicação, com PostgreSQL e MinIO de verdade. Um benchmark que
atalha o caminho mede o atalho.

---

## Resultado — 12.500 registros → 10.000 partidas

```
composição       17,2 s · 583 partidas/s · pico 11 MB
publicação        0,1 s ·                  pico  1 MB

partidas         10.000 em 20 lote(s) de 500
objetos             160 arquivos Parquet
linhas           10.000
bytes               1,5 MB  (156 B por partida, ZSTD)

consultas comp.     210  (10,5 por lote · 0,021 por partida)
consultas publ.       7

impressão        8a293fdf3858d7b27a484f5d79158a61219268c18cb0a4c12176143d7fd730d9
manifesto        fd0dc5646b03235e2f9468e035054482a5ecd5ecf613550707127386797130c9
estado           READY
```

### As consultas, por tabela e por lote

```
canonical_build_records            21     os fatos autorizados (a interseção)
canonical_build_family_decisions   20     o que ficou de fora, e por quê
canonical_odds_observations        20     as cotações do lote
lineups                            20     as escalações do lote
match_quality_assessments          20     os vereditos do lote
quality_assessment_coverage        20     a cobertura, por avaliação
quality_assessment_identity        20     as confianças de identidade
historical_canonical_members       20     a escrita da pertinência
```

**Vinte lotes, ~10,5 consultas por lote.** Com N+1 seriam ≥ 10.000 — a
diferença é grande demais para ser ruído. O teste afirma `< 0,5 por partida`; o
medido é `0,021`.

**Sete consultas para publicar.** A conferência lê contagem agregada e compara
impressões; ela não varre o corpus. O teste afirma `< 20`.

---

## Memória contra tamanho

```
 2.000 registros  →  pico 5,7 MB
 8.000 registros  →  pico 6,5 MB
```

Quadruplicar o volume aumentou o pico em **14%**. É a afirmação mais forte
deste arquivo e a mais fácil de perder: um `list(page_facts(...))` em qualquer
ponto satisfaz todos os testes funcionais e transforma o pico em função do
corpus — que é o defeito que o PR-03.2 já corrigiu uma vez, pela mesma porta.

O teste reprova acima de `pico(8.000) < 2,5 × pico(2.000)`.

---

## Determinismo contra o tamanho do lote

```
lote   250   e5e8ddbca79cdb16210ba6b1ec7c99313254b760411410143695c9660dfc340a
lote 2.000   e5e8ddbca79cdb16210ba6b1ec7c99313254b760411410143695c9660dfc340a
iguais       True
```

Sobre 4.000 partidas, com a MESMA identidade de dataset e versão nas duas
composições — nome e versão entram na impressão, então compor sob nomes
diferentes produziria impressões diferentes por um motivo que não é o lote.

É o `SetFingerprint` comutativo do PR-04.2 aplicado aos membros: XOR é
associativo, então a partição em lotes não vaza para o resultado. Sem essa
propriedade, a impressão não provaria reprodutibilidade nenhuma.

---

## O Parquet

```
160 arquivos · 1,5 MB · 156 B por partida
```

Um `part-NNNNN.parquet` por lote, por família e por partição
`competition=/season=`. **Um pedaço por lote, e não um arquivo por partição**:
acumular a partição inteira seria o corpus todo em memória quando ele cabe numa
competição só. Um diretório com vários `part-*` é exatamente o que os leitores
de Parquet esperam.

Compressão ZSTD, schema declarado, `decimal128(10,4)` nas odds, ausência como
`NULL` (ADR-0027).

---

## Como reproduzir

```bash
SIE_TEST_POSTGRES_DSN=postgresql://engine:engine_local@127.0.0.1:5433/sports_intelligence \
SIE_TEST_OBJECT_STORE_ENDPOINT=http://127.0.0.1:9000 \
SIE_TEST_OBJECT_STORE_BUCKET=sports-intelligence-raw \
PYTHONIOENCODING=utf-8 \
  pytest tests/performance/test_historical_corpus_scale.py -s
```

**Uma suíte de performance por banco, por vez.** `exclusividade_do_benchmark`
pega um lock consultivo de sessão; uma segunda execução espera e depois FALHA
com uma mensagem que diz que o conflito é do arnês. Ela existe porque já
aconteceu: duas suítes concorrentes produziram `ForeignKeyViolationError` que
se apresentou como regressão do produto.

`PYTHONIOENCODING=utf-8` é necessário no Windows: o relatório usa caracteres de
moldura que o console cp1252 não escreve.

---

## Comparação com as fases anteriores

| fase | escala | propriedade medida |
|------|--------|--------------------|
| PR-03.2 | 100.000 registros | resolução e fusão sem N+1, memória limitada |
| PR-04.2 | 5.000 registros → 4.000 partidas | qualidade e build por lote (7,0 e 15,0 consultas/lote) |
| **PR-04.3** | **12.500 registros → 10.000 partidas** | **composição e publicação por lote (10,5 consultas/lote), memória constante, impressão determinística** |
