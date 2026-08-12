"""Reconstrói a memória vetorial a partir de atlas.match_record.

    python -m scripts.atlas_vector_build --database-url <url> [--medir]

Reconstrói tudo: as features são walk-forward, então uma partida no meio da
linha do tempo muda todas as posteriores. `--medir` roda a régua logo depois
e imprime o antes/depois — que é a única forma honesta de dizer "melhorou".
"""

from __future__ import annotations

import argparse
import asyncio
import json

from atlas.registry import build_engine, build_session_factory
from atlas.vector.builder import VectorBuilder


async def _run(args) -> int:
    engine = build_engine(args.database_url)
    try:
        builder = VectorBuilder(build_session_factory(engine))
        resultado = await builder.construir()
    finally:
        await engine.dispose()

    if args.json:
        print(json.dumps(resultado.as_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"\nMEMÓRIA VETORIAL · {resultado.versao}")
    print(f"  partidas ......... {resultado.partidas}")
    print(f"  dimensões ........ {resultado.dimensoes}")
    for bloco, quantas in sorted(resultado.por_bloco.items()):
        print(f"     {bloco:<12} {quantas}")
    if resultado.constantes:
        print(f"\n  CONSTANTES ({len(resultado.constantes)}) — não carregam informação:")
        for nome in resultado.constantes:
            print(f"     {nome}")
    else:
        print("\n  nenhuma dimensão constante")
    print()
    return 0 if resultado.partidas else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
