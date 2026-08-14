"""Qualidade histórica, cobertura e elegibilidade de uso.

TRÊS CONCEITOS QUE NÃO SÃO O MESMO, e o pacote existe para mantê-los
separados no tipo, não só na intenção:

    QualityVector      posso confiar no que está aqui?
    CoverageReport     o que está aqui?
    UsageVerdict       tenho direito de usar isto, e para quê?

Um score único responderia mal às três. Uma fonte pública de futebol é
tipicamente de alta qualidade, baixa cobertura e licença de atribuição — e
qualquer colapso dessas dimensões num número faria dela «média».
"""
