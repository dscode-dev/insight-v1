"""Configuração comum da suíte.

POR QUE ESTE ARQUIVO EXISTE. `tests/support/` guarda duplos compartilhados
entre os testes de unidade e os de integração — os mesmos duplos, para que
uma diferença de comportamento entre eles seja um bug do duplo e não uma
divergência entre dois duplos parecidos.

Para importá-los como `tests.support.registry_fakes`, a raiz do serviço
precisa estar no `sys.path`. O pacote instalado em modo editável expõe
`src/sports_intelligence` e `apps` — nunca `tests`, e nem deveria: código de
teste não é distribuído.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
