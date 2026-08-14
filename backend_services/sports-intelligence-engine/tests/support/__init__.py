"""Aparato de teste compartilhado entre integração e performance.

NÃO É CÓDIGO DE PRODUÇÃO E NÃO PODE VIRAR UM (§44). O que mora aqui existe
para MEDIR e para MONTAR CENÁRIO: gerador determinístico de corpus, semeadura
do registro canônico, contador de consultas. Nada disso deve aparecer em
`domain/` ou `application/` — instrumentação de benchmark dentro do domínio é
uma dependência que fica para sempre e que ninguém consegue justificar depois.

Fica em `tests/support/` e não em `tests/performance/` porque o mesmo cenário
serve aos dois lados: o benchmark de cem mil registros e a integração
multi-fonte precisam do MESMO registro canônico, e duas cópias divergiriam.
"""
