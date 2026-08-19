"""A canonicalização histórica de eventos — do registro da fonte ao canônico.

    domain/events        O QUE um evento é: taxonomia, detalhes, revisão
    historical/events    COMO uma linha de fonte vira um evento canônico

A separação é a mesma de `domain/build` e `historical/build`, e pela mesma
razão: o domínio precisa ser testável sem banco e sem object store.

ONDE ESTE PACOTE COMEÇA E TERMINA (PR-04.4.1 §80). Ele começa nos registros de
evento já lidos e termina no registro canônico do PostgreSQL. Ele NÃO publica:
pertinência no corpus, `events.parquet` e contagem no manifesto são o
PR-04.4.2, e antecipá-los faria eventos entrarem numa versão publicada sem
passar pelo gate que existe para isso.
"""
