"""A recuperação histórica — quem pode ser candidato, e qual é o exato.

ESTE PACOTE RESPONDE DUAS PERGUNTAS, e nenhuma terceira:

    quem pode ser candidato histórico?     candidate_policy.py, candidate.py
    qual é o top-K exato sobre eles?       distance.py, exact.py

O QUE ELE NÃO É. Não é o motor de inteligência: não há tendência, resultado
final, próximo gol, rótulo, probabilidade nem confiança. Não é o índice
aproximado: não há pgvector, HNSW, IVFFlat nem ANN. Ele é o ORÁCULO contra o
qual esses dois terão de provar correção depois.

    exact.py é a autoridade. Um índice aproximado só é aceitável quando
    alguém consegue medir `Recall@K` contra o que este pacote produz.

A DISTÂNCIA DAQUI É DIAGNÓSTICA, e o nome dela diz isso por extenso:
`ROBUST_COMPLETE_CASE_EXACT_BASELINE_V1`. Ela não é a similaridade final do
Insight — o PR-05.5.2 mediu que 40,7 % das células dos eixos robustos saem sem
escala, e uma distância de produção precisa decidir formalmente o que fazer com
isso. Essa decisão é do PR-06.2, e improvisá-la aqui produziria um número que
parece uma resposta.
"""
