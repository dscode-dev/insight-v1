"""A régua e o mapa do Atlas. Somente leitura — não altera nada.

    python -m scripts.atlas_diagnose vetores  --database-url <url> [--dataset <matches.jsonl>]
    python -m scripts.atlas_diagnose modulos  [--root <caminho>]
    python -m scripts.atlas_diagnose cobertura --lake-dir <validated> [--raw-dir <raw>]

Rode antes e depois de cada mudança. Um número desta saída só significa
alguma coisa ao lado do mesmo número de antes — foi a falta disso que fez
"similaridade 0,886" ser reportada como bom resultado quando o par mediano
tirado ao acaso já dava 0,807.

`--json` imprime a leitura inteira em JSON, para guardar e comparar depois.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import text

from atlas.diagnostics import map_modules, map_tables, measure_coverage
from atlas.diagnostics.vector_report import (
    VectorReport,
    load_outcomes,
    measure_dimensions,
    measure_retrieval,
    measure_similarity,
    standardise,
)
from atlas.registry import build_engine, build_session_factory
from atlas.vector_memory.embedding import layout_v1, layout_v2

_LAYOUTS = {
    "atlas-memory-embedding-v1": (layout_v1, "embedding", 31),
    "atlas-memory-embedding-v2": (layout_v2, "embedding_v2", 36),
}


async def _read_new_space(database_url: str):
    """A memória vetorial nova: vetor, rótulo e nomes de dimensão, tudo da
    mesma tabela.

    Mais simples que a antiga de propósito — o desfecho fica ao lado do vetor
    em vez de num arquivo de dataset separado, então a recuperação passa a ser
    mensurável sem depender de um corpus publicado em disco existir.
    """
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    try:
        async with session_factory() as session:
            espaco = await session.execute(
                text("SELECT dimensions, matches FROM atlas.vector_space WHERE version = :v"),
                {"v": "atlas.vector.v1"},
            )
            linha = espaco.first()
            if linha is None:
                return None, [], {}
            nomes = tuple(linha[0])
            resultado = await session.execute(
                text(
                    "SELECT uid, kickoff_utc, label, embedding::text "
                    "FROM atlas.match_vector ORDER BY kickoff_utc, uid"
                )
            )
            entradas, desfechos = [], {}
            for uid, kickoff, label, vetor in resultado.fetchall():
                entradas.append((str(kickoff), str(uid), json.loads(vetor)))
                desfechos[str(uid)] = str(label)
            return nomes, entradas, desfechos
    finally:
        await engine.dispose()


async def _read_vectors(database_url: str, version: str, column: str):
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    try:
        async with session_factory() as session:
            result = await session.execute(
                text(
                    f"SELECT source_match_id, created_at, {column}::text "
                    "FROM atlas.atlas_vector_memory "
                    f"WHERE embedding_version = :v AND {column} IS NOT NULL "
                    "ORDER BY created_at, source_match_id"
                ),
                {"v": version},
            )
            return [
                (str(row[1]), str(row[0]), json.loads(row[2]))
                for row in result.fetchall()
            ]
    finally:
        await engine.dispose()


def _vectors(args) -> int:
    version = args.embedding_version
    if version == "atlas.vector.v1":
        return _new_space(args)
    if version in _LAYOUTS:
        print(
            f"'{version}' vivia em atlas.atlas_vector_memory, removida pela "
            "migração 0025. O espaço vigente é atlas.vector.v1 — rode sem "
            "--embedding-version."
        )
        return 1
    print(f"versão desconhecida: {version} — o espaço vigente é atlas.vector.v1")
    return 1


def _new_space(args) -> int:
    """A régua sobre a memória vetorial nova.

    Sem o bloco de "dims padronizadas" que a antiga imprimia: aqui o vetor JÁ
    nasce padronizado, então a comparação seria consigo mesmo.
    """
    nomes, entradas, desfechos = asyncio.run(_read_new_space(args.database_url))
    if not entradas:
        print("nenhum vetor em atlas.match_vector — rode scripts.atlas_vector_build")
        return 1
    vetores = [v for _, _, v in entradas]

    report = VectorReport(embedding_version="atlas.vector.v1", rows=len(vetores))
    # Sem termo de viés: ele existia para o formato antigo e era, ele mesmo,
    # uma das 14 constantes. Aqui a constância é medida pelo desvio direto,
    # que basta porque não há normalização escondendo um valor fixo.
    report.dimensions = measure_dimensions(vetores, nomes, bias_index=None)
    report.similarity.append(
        measure_similarity(vetores, label="espaço padronizado", pairs=args.pairs)
    )
    report.retrieval = measure_retrieval(entradas, desfechos, queries=args.queries)

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return 0

    print(
        f"\nVETORES · atlas.vector.v1 · {report.rows} partidas · "
        f"{len(nomes)} dimensões\n"
    )
    print(f"{'':>4} {'DIMENSÃO':<24} {'DESVIO':>8} {'DISTINTOS':>10}")
    print("-" * 52)
    for d in report.dimensions:
        print(f"{d.index:>4} {d.name:<24} {d.stdev:>8.4f} {d.distinct:>10}")
    constantes = [d.name for d in report.dimensions if d.distinct <= 1]
    print(f"\n  {len(report.dimensions)} dimensões · {len(constantes)} constantes")
    if constantes:
        print("  constantes:", ", ".join(constantes))

    print("\nSIMILARIDADE ENTRE PARES SORTEADOS AO ACASO")
    for s in report.similarity:
        print(
            f"  {s.label:<24} mediana {s.median:>7.3f} | p05 {s.p05:>7.3f} | "
            f"p95 {s.p95:>7.3f} | desvio {s.stdev:.3f} | >0,90 {s.above_090:.1%}"
        )

    if report.retrieval:
        print("\nRECUPERAÇÃO — os vizinhos carregam informação?")
        print(f"  {'K':>4} {'concordância':>14} {'taxa base':>11} {'ganho':>8} {'margem':>8} {'sim. 1º viz.':>14}")
        for r in report.retrieval:
            marca = "" if r.conclusive else "   dentro da margem"
            print(
                f"  {r.k:>4} {r.agreement:>13.1%} {r.base_rate:>11.1%} "
                f"{r.lift:>+8.1%} {r.margin:>7.1%}  {r.top_similarity:>13.3f}{marca}"
            )
    print()
    return 0


def _modules(args) -> int:
    mapa = map_modules(Path(args.root))
    if args.json:
        print(json.dumps(mapa.as_dict(), ensure_ascii=False, indent=2))
        return 0

    print(
        f"\nMÓDULOS · {mapa.total_modules} arquivos · {mapa.total_lines} linhas · "
        f"{len(mapa.packages)} pacotes\n"
    )
    print(f"{'PACOTE':<26} {'MÓD':>4} {'LINHAS':>7}  {'SITUAÇÃO':<10} QUEM IMPORTA")
    print("-" * 100)
    for p in mapa.packages:
        quem = ", ".join(p.imported_by[:4]) or "—"
        if len(p.imported_by) > 4:
            quem += f" (+{len(p.imported_by) - 4})"
        print(f"{p.name:<26} {p.modules:>4} {p.lines:>7}  {p.verdict:<10} {quem}")

    mortos = mapa.dead_packages
    print(
        f"\n  {len(mortos)} pacotes que nada importa, somando {mapa.dead_lines} linhas."
    )
    if mortos:
        print("  Candidatos a remoção (passo 7, depois do vetor novo):")
        for p in mortos:
            print(f"     {p.name}  ({p.lines} linhas)")
    print(
        "\n  'morto' quer dizer que NENHUM import foi encontrado, não que seja\n"
        "  comprovadamente inalcançável: import montado por string em tempo de\n"
        "  execução não aparece aqui. Confira antes de apagar."
    )
    return 0


async def _read_row_counts(database_url: str) -> dict[str, int]:
    """Contagem EXATA por tabela, uma consulta por tabela.

    `pg_stat_user_tables.n_live_tup` é estimativa do coletor de estatísticas
    e erra: com ele, `strength_processed_matches` apareceu com 7.213 linhas
    quando tem 7.127, e `match_rejection` com 2 quando tem 1. Para "quantas
    linhas mais ou menos" seria suficiente; para uma lista que decide o que
    vai ser APAGADO, não é — uma tabela com dados que a estimativa reporte
    como vazia é exatamente o erro que não se pode cometer aqui.

    Custa uma varredura por tabela. Com 31 tabelas e a maior tendo 14 mil
    linhas, é instantâneo; se deixar de ser, a saída é amostrar as grandes e
    contar exato só as candidatas a vazia.
    """
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    try:
        async with session_factory() as session:
            nomes = await session.execute(
                text(
                    "SELECT schemaname || '.' || relname "
                    "FROM pg_stat_user_tables WHERE schemaname = 'atlas' "
                    "ORDER BY relname"
                )
            )
            contagens: dict[str, int] = {}
            for (tabela,) in nomes.fetchall():
                # O nome vem do catálogo do próprio Postgres, não da entrada
                # de ninguém — não há string de usuário nesta interpolação.
                total = await session.execute(text(f"SELECT count(*) FROM {tabela}"))
                contagens[str(tabela)] = int(total.scalar_one())
            return contagens
    finally:
        await engine.dispose()


def _tables(args) -> int:
    counts = asyncio.run(_read_row_counts(args.database_url))
    uses = map_tables(Path(args.root), counts)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "table": u.table, "rows": u.rows,
                        "referenced_by": list(u.referenced_by),
                        "decorative": u.decorative,
                    }
                    for u in uses
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    vazias = [u for u in uses if u.rows == 0]
    decorativas = [u for u in uses if u.decorative]
    print(f"\nTABELAS · {len(uses)} no schema atlas · {len(vazias)} vazias\n")
    print(f"{'TABELA':<40} {'LINHAS':>9}  PACOTES QUE A CITAM")
    print("-" * 96)
    for u in uses:
        quem = ", ".join(u.referenced_by[:5]) or "nenhum"
        if len(u.referenced_by) > 5:
            quem += f" (+{len(u.referenced_by) - 5})"
        print(f"{u.table:<40} {u.rows:>9}  {quem}")
    print(
        f"\n  {len(decorativas)} tabelas VAZIAS com código que as escreve — "
        "funcionalidade que roda e não produz nada."
    )
    print(
        f"  {len(vazias) - len(decorativas)} tabelas vazias sem nenhum código as citando — "
        "sobra de migration."
    )
    print(
        "\n  A busca é textual: o nome citado num comentário conta como\n"
        "  referência. É o lado seguro de errar, já que esta lista decide o\n"
        "  que vai ser APAGADO no passo 7."
    )
    return 0


def _coverage(args) -> int:
    report = measure_coverage(args.lake_dir, args.raw_dir)
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        return 0

    print(f"\nCOBERTURA · {report.total_matches} partidas distintas\n")
    print(f"{'BLOCO':<22} {'PARTIDAS':>9} {'DO TOTAL':>10}")
    print("-" * 44)
    for bloco, n in report.blocks.items():
        parte = n / report.total_matches if report.total_matches else 0.0
        print(f"{bloco:<22} {n:>9} {parte:>9.1%}")
    completas = (
        f"{report.complete} ({report.complete / report.total_matches:.1%})"
        if report.total_matches
        else "0"
    )
    print(f"\n  COMPLETAS (todos os blocos): {completas}")
    if report.side_files:
        print("\n  Blocos que TEMOS mas que ainda não se ligam à partida:")
        for bloco, n in report.side_files.items():
            print(f"     {bloco:<8} {n:>7} registros, chaveados pelo id da fonte")
        print(
            "     Contados à parte de propósito: há vários por partida (um por\n"
            "     casa de aposta) e coletas repetidas, então não formam uma taxa\n"
            "     de cobertura. O contrato novo precisa trazê-los junto do jogo."
        )
    print(
        "\n  É este o número que decide o contrato: com 'todo campo obrigatório',\n"
        "  só as partidas COMPLETAS seriam aceitas."
    )
    if report.source_native:
        print(
            f"\n  {report.source_native} registros ainda no formato ORIGINAL da fonte\n"
            "  (linha de CSV do football-data, com odds de várias casas, chutes,\n"
            "  escanteios e cartões). Não são inválidos — são os registros mais\n"
            "  COMPLETOS do lake, e é deles que os blocos market e stats saem."
        )
    if report.malformed_lines:
        print(
            f"\n  linhas que não casaram com nenhum formato conhecido: {report.malformed_lines}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)

    vetores = sub.add_parser("vetores", help="variância, similaridade e recuperação")
    vetores.add_argument("--database-url", required=True)
    # O espaço vigente, e o único que existe: a migração 0025 removeu
    # `atlas.atlas_vector_memory`, onde viviam as versões antigas. O padrão
    # apontava para lá e a régua morria com um stack trace de tabela
    # inexistente — a ferramenta de diagnóstico sendo a última a saber que o
    # que ela media foi apagado.
    vetores.add_argument("--embedding-version", default="atlas.vector.v1")
    vetores.add_argument("--dataset", default="/var/atlas/datasets/current/matches.jsonl")
    vetores.add_argument("--pairs", type=int, default=60_000)
    vetores.add_argument("--queries", type=int, default=400)
    vetores.add_argument("--json", action="store_true")
    vetores.set_defaults(func=_vectors)

    modulos = sub.add_parser("modulos", help="mapa dos pacotes e o que está morto")
    modulos.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    modulos.add_argument("--json", action="store_true")
    modulos.set_defaults(func=_modules)

    tabelas = sub.add_parser("tabelas", help="tabelas vazias x codigo que as escreve")
    tabelas.add_argument("--database-url", required=True)
    tabelas.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    tabelas.add_argument("--json", action="store_true")
    tabelas.set_defaults(func=_tables)

    cobertura = sub.add_parser("cobertura", help="quais blocos cada partida tem")
    cobertura.add_argument("--lake-dir", default="/var/atlas/explorer/validated")
    cobertura.add_argument("--raw-dir", default="/var/atlas/explorer/raw")
    cobertura.add_argument("--json", action="store_true")
    cobertura.set_defaults(func=_coverage)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
