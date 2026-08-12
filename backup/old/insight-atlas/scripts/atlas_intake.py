"""Ingestão de partidas no Atlas, pela linha de comando.

    python -m scripts.atlas_intake --database-url <url> --operador ninja \
        arquivo1.jsonl arquivo2.jsonl

    python -m scripts.atlas_intake --contrato        # mostra o contrato
    python -m scripts.atlas_intake ... --simular     # valida sem gravar

Os arquivos são JSONL: um registro `atlas.match.v1` por linha. Nomeie quais
entram — não existe pasta observada, e nada é ingerido por estar em algum
lugar.

A MESMA VALIDAÇÃO E A MESMA BASE DA API. Este comando não sabe as regras;
ele lê arquivos e chama `atlas.intake.service.ingest`, igual ao endpoint
HTTP. É o que garante que as duas portas não divirjam.

--simular existe porque a alternativa, num arquivo montado à mão, é
descobrir os erros gravando metade dele.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from atlas.intake.contract import example
from atlas.intake.repository import IntakeRepository
from atlas.intake.service import (
    IngestReport,
    SimulacaoRepository,
    ingest,
    read_jsonl,
)
from atlas.registry import build_engine, build_session_factory


def _render(report: IngestReport, *, simulado: bool, verbose: bool) -> None:
    cabecalho = "SIMULAÇÃO (nada foi gravado)" if simulado else "INGESTÃO"
    print(f"\n{cabecalho}")
    print(f"  enviados .......... {report.submitted}")
    print(f"  aceitos ........... {report.accepted}")
    if not simulado:
        print(f"     novos .......... {report.added}")
        print(f"     atualizados .... {report.replaced}")
        if report.pending:
            print(f"     aguardando ..... {report.pending}  (falta bloco)")
    print(f"  recusados ......... {report.rejected}")

    if not simulado:
        print(f"\n  partidas no Atlas: {report.total_before} → {report.total_after} "
              f"({report.total_after - report.total_before:+d})")

    if report.missing_blocks:
        print("\n  BLOCOS QUE FALTAM — o que buscar na próxima fonte")
        for bloco, quantas in report.missing_blocks.items():
            print(f"     {quantas:>6}  {bloco}")
        print("     Estas contribuições foram gravadas, não recusadas: a")
        print("     composição espera outra fonte trazer o que falta.")

    if report.by_field:
        print("\n  RECUSAS POR CAMPO")
        for campo, quantas in report.by_field.items():
            print(f"     {quantas:>6}  {campo}")

    recusadas = [linha for linha in report.lines if not linha.accepted]
    if recusadas:
        mostrar = recusadas if verbose else recusadas[:10]
        print(f"\n  DETALHE ({len(mostrar)} de {len(recusadas)} recusas)")
        for linha in mostrar:
            print(f"     linha {linha.index + 1}: {linha.label}")
            for erro in linha.errors:
                print(f"        {erro}")
        if len(recusadas) > len(mostrar):
            print(f"     ... mais {len(recusadas) - len(mostrar)}. Use --tudo para ver todas.")
    print()


async def _run(args) -> int:
    caminhos = [Path(p) for p in args.arquivos]
    ausentes = [str(p) for p in caminhos if not p.is_file()]
    if ausentes:
        print(f"arquivo não encontrado: {', '.join(ausentes)}", file=sys.stderr)
        return 1

    registros: list = []
    for caminho in caminhos:
        registros.extend(read_jsonl(caminho.read_text(encoding="utf-8")))
    if not registros:
        print("nenhum registro nos arquivos informados", file=sys.stderr)
        return 1

    engine = build_engine(args.database_url)
    try:
        repositorio = IntakeRepository(build_session_factory(engine))
        total = await repositorio.count()
        alvo = SimulacaoRepository(total) if args.simular else repositorio
        report = await ingest(
            registros, alvo, via="cli", by=args.operador
        )
    finally:
        await engine.dispose()

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        _render(report, simulado=args.simular, verbose=args.tudo)

    # Sai diferente de zero quando algo foi recusado, para que um pipeline
    # que chama isto perceba sem ter de ler a saída.
    return 0 if report.rejected == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arquivos", nargs="*", help="arquivos .jsonl")
    parser.add_argument("--database-url")
    parser.add_argument(
        "--operador", default="", help="quem está ingerindo; fica gravado na linha"
    )
    parser.add_argument("--simular", action="store_true", help="valida sem gravar")
    parser.add_argument("--tudo", action="store_true", help="mostra todas as recusas")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--contrato", action="store_true", help="imprime um registro de exemplo"
    )
    args = parser.parse_args()

    if args.contrato:
        print(json.dumps(example(), ensure_ascii=False, indent=2))
        return 0
    if not args.arquivos:
        parser.error("informe pelo menos um arquivo .jsonl (ou use --contrato)")
    if not args.database_url:
        parser.error("--database-url é obrigatório")
    if not args.operador.strip():
        # Igual à API: sem isto, `ingested_by` vira "cli" para todo mundo e
        # "quem colocou isto aqui" deixa de ter resposta.
        parser.error("--operador é obrigatório: identifica quem ingeriu")

    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
