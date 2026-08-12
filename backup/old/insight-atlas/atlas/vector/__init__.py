"""A memória vetorial do Atlas — uma versão, um espaço, um caminho.

    atlas.match_record  →  features walk-forward  →  espaço padronizado
                        →  atlas.match_vector

Substitui `atlas.vector_memory`, que codificava a partir do lake em duas
versões simultâneas (32 e 37 dimensões) das quais 14 eram constantes e 2
duplicadas. O que mudou não foi o tamanho: foi a fonte (tabela, não pasta),
a escala (padronizada, não confinada ao octante positivo) e o fato de o
mercado existir.
"""

from atlas.vector.features import FEATURES, NOMES, Linha, construir
from atlas.vector.space import VERSAO, EspacoVetorial, ajustar

__all__ = [
    "FEATURES",
    "NOMES",
    "VERSAO",
    "EspacoVetorial",
    "Linha",
    "ajustar",
    "construir",
]
