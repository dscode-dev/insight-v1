"""Os clubes argentinos que o ARG.csv nomeia e o registro não conhece.

MEDIDO ANTES DE ESCREVER: convertendo BRA.csv e ARG.csv contra o registro de
307 clubes, 4.567 linhas caem por clube não resolvido — praticamente todas
argentinas. O Brasileirão resolve 5.534 de 5.535 (a única perda é uma linha
sem placar). Então o que falta é isto, e só isto.

O RISCO DESTE ARQUIVO É O APELIDO ERRADO, NÃO O CLUBE FALTANDO. Um clube
ausente é recusado por nome e aparece no relatório; um apelido errado une
duas histórias diferentes em silêncio e o número continua fechando. Já
aconteceu duas vezes aqui: `Ath Madrid` foi para `athletic_bilbao`, e
`Parana` quase virou `athletico_paranaense`.

OS TRÊS PARES QUE PARECEM O MESMO CLUBE E NÃO SÃO:

    San Martin S.J.   San Martín de San Juan
    San Martin T.     San Martín de Tucumán     — cidades diferentes

    Independiente     CA Independiente, Avellaneda
    Ind. Rivadavia    Independiente Rivadavia, Mendoza

    Gimnasia L.P.     Gimnasia y Esgrima La Plata
    Gimnasia Mendoza  Gimnasia y Esgrima de Mendoza

Cada um tem teste próprio em `tests/test_clubs_argentina.py`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

#: Nome no CSV → clube que JÁ EXISTE no registro. Só apelido, nada novo.
APELIDOS = {
    "Argentinos Jrs": "argentinos_juniors",
    "Atl. Tucuman": "atletico_tucuman",
}

#: Clubes que o registro não tem. `(club_id, nome, apelidos no CSV)`.
#:
#: Todos da primeira divisão argentina em alguma temporada de 2012 a 2026 —
#: o arquivo cobre subidas e descidas, então há clubes que passaram poucas
#: temporadas na elite e ainda assim aparecem em centenas de linhas.
NOVOS: list[tuple[str, str, list[str]]] = [
    ("newells_old_boys", "Newell's Old Boys", ["Newells Old Boys", "Newell's Old Boys"]),
    ("lanus", "Club Atlético Lanús", ["Lanus", "Lanús"]),
    # Avellaneda. NÃO é o Independiente Rivadavia, de Mendoza, logo abaixo.
    ("independiente", "Club Atlético Independiente", ["Independiente"]),
    ("independiente_rivadavia", "Independiente Rivadavia", ["Ind. Rivadavia"]),
    # La Plata. NÃO é o Gimnasia de Mendoza, logo abaixo.
    ("gimnasia_la_plata", "Gimnasia y Esgrima La Plata", ["Gimnasia L.P."]),
    ("gimnasia_mendoza", "Gimnasia y Esgrima de Mendoza", ["Gimnasia Mendoza"]),
    # San Juan. NÃO é o San Martín de Tucumán, logo abaixo.
    ("san_martin_san_juan", "San Martín de San Juan", ["San Martin S.J."]),
    ("san_martin_tucuman", "San Martín de Tucumán", ["San Martin T."]),
    ("union_santa_fe", "Unión de Santa Fe", ["Union de Santa Fe"]),
    ("banfield", "Club Atlético Banfield", ["Banfield"]),
    ("belgrano", "Club Atlético Belgrano", ["Belgrano"]),
    ("sarmiento_junin", "Sarmiento de Junín", ["Sarmiento Junin"]),
    ("aldosivi", "Club Atlético Aldosivi", ["Aldosivi"]),
    ("platense", "Club Atlético Platense", ["Platense"]),
    ("barracas_central", "Barracas Central", ["Barracas Central"]),
    ("atletico_rafaela", "Atlético de Rafaela", ["Atl. Rafaela"]),
    ("quilmes", "Quilmes Atlético Club", ["Quilmes"]),
    ("instituto", "Instituto Atlético Central Córdoba", ["Instituto"]),
    ("temperley", "Club Atlético Temperley", ["Temperley"]),
    ("deportivo_riestra", "Deportivo Riestra", ["Dep. Riestra"]),
    ("all_boys", "Club Atlético All Boys", ["All Boys"]),
    ("nueva_chicago", "Nueva Chicago", ["Nueva Chicago"]),
    ("chacarita_juniors", "Chacarita Juniors", ["Chacarita Juniors"]),
    ("crucero_del_norte", "Crucero del Norte", ["Crucero del Norte"]),
]

COMPETICOES = ["argentina_liga_profesional", "argentina_copa_liga_profesional"]


def aplicar(registro: dict) -> tuple[dict, list[str], list[str]]:
    """Devolve o registro novo, os ids criados e os apelidos acrescentados."""
    por_id = {c["club_id"]: c for c in registro["clubs"]}
    criados: list[str] = []
    apelidados: list[str] = []

    for club_id, nome, apelidos in NOVOS:
        if club_id in por_id:
            # Já existe: só completa os apelidos, nunca troca o nome nem o
            # país de um clube que outra competição já usa.
            alvo = por_id[club_id]
            for apelido in apelidos:
                if apelido not in alvo.setdefault("aliases", []):
                    alvo["aliases"].append(apelido)
                    apelidados.append(f"{apelido} -> {club_id}")
            continue
        registro["clubs"].append(
            {
                "club_id": club_id,
                "name": nome,
                "country": "AR",
                "competition": COMPETICOES[0],
                "competitions": list(COMPETICOES),
                "logo_path": None,
                "aliases": list(dict.fromkeys(apelidos + [nome])),
            }
        )
        por_id[club_id] = registro["clubs"][-1]
        criados.append(club_id)

    for apelido, club_id in APELIDOS.items():
        alvo = por_id.get(club_id)
        if alvo is None:
            raise SystemExit(
                f"apelido {apelido!r} aponta para {club_id!r}, que não existe — "
                "um apelido para um id inexistente resolveria para None em "
                "silêncio"
            )
        if apelido not in alvo.setdefault("aliases", []):
            alvo["aliases"].append(apelido)
            apelidados.append(f"{apelido} -> {club_id}")

    registro["count"] = len(registro["clubs"])
    return registro, criados, apelidados


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    caminho = Path(args.registry)
    registro = json.loads(caminho.read_text(encoding="utf-8"))
    antes = len(registro["clubs"])

    registro, criados, apelidados = aplicar(registro)

    Path(args.out).write_text(
        json.dumps(registro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"clubes: {antes} -> {len(registro['clubs'])}")
    print(f"criados ({len(criados)}): {', '.join(criados)}")
    print(f"apelidos ({len(apelidados)}): {', '.join(apelidados)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
