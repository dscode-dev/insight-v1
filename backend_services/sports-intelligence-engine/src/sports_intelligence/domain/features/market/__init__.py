"""O consenso de mercado — nivel, dispersao e suporte, sem previsao.

    market_level       mediana das cotacoes elegiveis
    market_dispersion  IQR das mesmas
    market_support     quantas casas de aposta as sustentam

A DIMENSAO E FIXA (PR-05.4 §45): os mercados canonicos sao declarados por
extenso, e a casa de aposta nunca vira eixo do espaco.

O QUE NAO MORA AQUI: probabilidade implicita, remocao de margem, movimento de
linha, peso por casa. Cada um exige uma politica propria, e escondê-los numa
feature aparentemente simples faria quatro decisoes passarem por uma.
"""
