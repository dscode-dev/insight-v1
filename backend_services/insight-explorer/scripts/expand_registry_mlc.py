"""ML-C Part 1 — Club Registry expansion.

Adds CONMEBOL club + national-team coverage so South American competitions
(Libertadores / Sudamericana) and the World Cups resolve deterministically.
The club list is data-driven: every name below was observed UNRESOLVED in the
Explorer's collected Libertadores data on Robozão.

Merges into both the vendored Explorer registry and the canonical proto
registry (idempotent: dedup by club_id). Run: `python scripts/expand_registry_mlc.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

# (club_id, canonical name, short, country, aliases) — name/aliases chosen so
# the deterministic resolver matches the ESPN display names exactly.
CLUBS = [
    ("alianza_lima", "Alianza Lima", "ALI", "PE", []),
    ("always_ready", "Always Ready", "ALW", "BO", []),
    ("junior", "Atlético Junior", "JUN", "CO", ["Junior", "Junior Barranquilla", "CD Popular Junior"]),
    ("atletico_nacional", "Atlético Nacional", "NAC", "CO", []),
    ("aucas", "Aucas", "AUC", "EC", ["SD Aucas"]),
    ("aurora", "Aurora", "AUR", "BO", ["Club Aurora"]),
    ("bolivar", "Bolívar", "BOL", "BO", ["Club Bolívar"]),
    ("boston_river", "Boston River", "BOS", "UY", []),
    ("caracas", "Caracas FC", "CAR", "VE", ["Caracas"]),
    ("cerro_porteno", "Cerro Porteño", "CER", "PY", []),
    ("cobresal", "Cobresal", "COB", "CL", ["CD Cobresal"]),
    ("colo_colo", "Colo Colo", "COL", "CL", ["Colo-Colo"]),
    ("curico_unido", "Curicó Unido", "CUR", "CL", ["Provincial Curicó Unido"]),
    ("defensor_sporting", "Defensor Sporting", "DEF", "UY", []),
    ("deportes_tolima", "Deportes Tolima", "TOL", "CO", []),
    ("deportivo_tachira", "Deportivo Táchira", "TAC", "VE", []),
    ("el_nacional", "El Nacional", "ELN", "EC", ["CD El Nacional"]),
    ("estudiantes", "Estudiantes de La Plata", "EST", "AR", ["Estudiantes", "Estudiantes LP"]),
    ("godoy_cruz", "Godoy Cruz Antonio Tomba", "GOD", "AR", ["Godoy Cruz"]),
    ("huachipato", "Huachipato", "HUA", "CL", ["CD Huachipato"]),
    ("independiente_medellin", "Independiente Medellín", "DIM", "CO", ["DIM", "Medellín"]),
    ("independiente_del_valle", "Independiente del Valle", "IDV", "EC", ["IDV"]),
    ("libertad", "Libertad", "LIB", "PY", ["Club Libertad"]),
    ("ldu_quito", "Liga de Quito", "LDU", "EC", ["LDU Quito", "LDU", "Liga Deportiva Universitaria"]),
    ("macara", "Macará", "MAC", "EC", ["CSD Macará"]),
    ("melgar", "Melgar", "MEL", "PE", ["FBC Melgar"]),
    ("millonarios", "Millonarios", "MIL", "CO", ["Millonarios FC"]),
    ("nacional", "Nacional", "NAC", "UY", ["Club Nacional de Football", "Nacional Montevideo"]),
    ("nacional_asuncion", "Nacional Asunción", "NAS", "PY", ["Nacional (Paraguay)"]),
    ("nacional_potosi", "Nacional Potosí", "NPO", "BO", []),
    ("palestino", "Palestino", "PAL", "CL", ["CD Palestino"]),
    ("penarol", "Peñarol", "PEN", "UY", ["CA Peñarol"]),
    ("portuguesa", "Portuguesa", "POR", "VE", ["Portuguesa FC"]),
    ("river_plate", "River Plate", "RIV", "AR", ["CA River Plate"]),
    ("rosario_central", "Rosario Central", "ROS", "AR", []),
    ("sporting_cristal", "Sporting Cristal", "CRI", "PE", ["Club Sporting Cristal"]),
    ("sportivo_trinidense", "Sportivo Trinidense", "TRI", "PY", []),
    ("talleres", "Talleres (Córdoba)", "TAL", "AR", ["Talleres", "Talleres de Córdoba"]),
    ("the_strongest", "The Strongest", "STR", "BO", ["Club The Strongest"]),
    ("universidad_de_chile", "Universidad de Chile", "UCH", "CL", ["U de Chile", "Universidad Chile"]),
    ("universitario", "Universitario", "UNI", "PE", ["Universitario de Deportes"]),
    ("zamora", "Zamora FC", "ZAM", "VE", ["Zamora"]),
    ("aguilas_doradas", "Águilas Doradas", "AGU", "CO", ["Rionegro Águilas", "Aguilas Doradas"]),
    ("academia_puerto_cabello", "Academia Puerto Cabello", "APC", "VE", ["Puerto Cabello"]),
    # Batch 2 — surfaced from deeper Libertadores 2023/2024 coverage.
    ("argentinos_juniors", "Argentinos Juniors", "ARG", "AR", ["AA Argentinos Juniors"]),
    ("atletico_tucuman", "Atlético Tucumán", "ATU", "AR", []),
    ("boca_juniors", "Boca Juniors", "BOC", "AR", ["CA Boca Juniors", "Boca"]),
    ("carabobo", "Carabobo", "CBO", "VE", ["Carabobo FC"]),
    ("cerro_largo", "Cerro Largo", "CLA", "UY", []),
    ("olimpia", "Club Olimpia", "OLI", "PY", ["Olimpia", "Olimpia Asunción"]),
    ("cesar_vallejo", "César Vallejo", "CVA", "PE", ["Universidad César Vallejo"]),
    ("deportivo_lara", "Deportivo Lara", "DLA", "VE", []),
    ("deportivo_maldonado", "Deportivo Maldonado", "DMA", "UY", []),
    ("deportivo_pereira", "Deportivo Pereira", "DPE", "CO", []),
    ("guarani_py", "Guaraní", "GUA", "PY", ["Club Guaraní", "Guarani (Paraguay)"]),
    ("huracan", "Huracán", "HUR", "AR", ["CA Huracán"]),
    ("magallanes", "Magallanes", "MAG", "CL", []),
    ("metropolitanos", "Metropolitanos", "MET", "VE", ["Metropolitanos FC"]),
    ("monagas", "Monagas SC", "MON", "VE", ["Monagas"]),
    ("montevideo_city_torque", "Montevideo City Torque", "MCT", "UY", ["City Torque"]),
    ("patronato", "Patronato", "PAT", "AR", []),
    ("plaza_colonia", "Plaza Colonia", "PLA", "UY", []),
    ("racing_club", "Racing Club", "RAC", "AR", ["Racing", "Racing Club de Avellaneda"]),
    ("royal_pari", "Royal Pari", "ROY", "BO", []),
    ("universidad_catolica_quito", "Universidad Católica (Quito)", "UCQ", "EC",
     ["U. Católica (Ecuador)"]),
    ("nublense", "Ñublense", "NUB", "CL", ["Nublense"]),
    # Batch 3 — long tail from full Libertadores coverage.
    ("america_de_cali", "América de Cali", "AME", "CO", ["America de Cali"]),
    ("audax_italiano", "Audax Italiano", "AUD", "CL", []),
    ("ayacucho", "Ayacucho FC", "AYA", "PE", ["Ayacucho"]),
    ("defensa_y_justicia", "Defensa y Justicia", "DYJ", "AR", []),
    ("delfin", "Delfín", "DEL", "EC", ["Delfin SC"]),
    ("binacional", "Deportivo Binacional", "BIN", "PE", ["Binacional"]),
    ("montevideo_wanderers", "Montevideo Wanderers", "MWA", "UY", ["Wanderers"]),
    ("tigre", "Tigre", "TIG", "AR", ["CA Tigre"]),
    ("universidad_catolica", "Universidad Católica", "UCA", "CL",
     ["U. Católica", "Universidad Católica (Chile)"]),
    ("union_espanola", "Unión Española", "UES", "CL", ["Union Espanola"]),
    ("velez_sarsfield", "Vélez Sarsfield", "VEL", "AR", ["Vélez", "Velez Sarsfield"]),
    ("jorge_wilstermann", "Wilstermann", "WIL", "BO", ["Jorge Wilstermann"]),
]

# CONMEBOL national teams + the World Cup 2018/2022 field (entity resolution for
# national-team competitions). ESPN uses plain country names.
NATIONS = [
    ("ar_nt", "Argentina"), ("br_nt", "Brazil"), ("uy_nt", "Uruguay"),
    ("cl_nt", "Chile"), ("co_nt", "Colombia"), ("pe_nt", "Peru"),
    ("ec_nt", "Ecuador"), ("py_nt", "Paraguay"), ("bo_nt", "Bolivia"),
    ("ve_nt", "Venezuela"),
    ("fr_nt", "France"), ("de_nt", "Germany"), ("es_nt", "Spain"),
    ("pt_nt", "Portugal"), ("en_nt", "England"), ("nl_nt", "Netherlands"),
    ("hr_nt", "Croatia"), ("be_nt", "Belgium"), ("it_nt", "Italy"),
    ("mx_nt", "Mexico"), ("us_nt", "United States"), ("jp_nt", "Japan"),
    ("kr_nt", "South Korea"), ("ma_nt", "Morocco"), ("sn_nt", "Senegal"),
    ("gh_nt", "Ghana"), ("ng_nt", "Nigeria"), ("au_nt", "Australia"),
    ("ca_nt", "Canada"), ("ch_nt", "Switzerland"), ("dk_nt", "Denmark"),
    ("pl_nt", "Poland"), ("rs_nt", "Serbia"), ("sa_nt", "Saudi Arabia"),
    ("qa_nt", "Qatar"), ("ir_nt", "Iran"), ("cr_nt", "Costa Rica"),
    ("tn_nt", "Tunisia"), ("cm_nt", "Cameroon"), ("wal_nt", "Wales"),
]

_TARGETS = [
    Path(__file__).resolve().parents[1] / "vendor" / "club_registry.json",
    Path(__file__).resolve().parents[2] / "insight-protos/contracts/clubs/club_registry.json",
]


def _entries() -> list[dict]:
    out = []
    for cid, name, short, country, aliases in CLUBS:
        out.append({"club_id": cid, "name": name, "short_name": short, "country": country,
                    "competition": "libertadores", "competitions": ["libertadores", "sudamericana"],
                    "logo_path": f"/clubs/{cid}.png",
                    "aliases": list(dict.fromkeys([name, *aliases]))})
    for cid, name in NATIONS:
        out.append({"club_id": cid, "name": name, "short_name": name[:3].upper(),
                    "country": "INT", "competition": "world_cup", "competitions": ["world_cup"],
                    "logo_path": f"/clubs/{cid}.png", "aliases": [name]})
    return out


def merge(path: Path, new: list[dict]) -> tuple[int, int]:
    data = json.loads(path.read_text("utf-8"))
    existing = {c["club_id"] for c in data["clubs"]}
    added = 0
    for entry in new:
        if entry["club_id"] not in existing:
            data["clubs"].append(entry)
            existing.add(entry["club_id"])
            added += 1
    data["count"] = len(data["clubs"])
    data["generated_by"] = data.get("generated_by", "") + " +ml-c-conmebol"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    return added, data["count"]


def main() -> None:
    new = _entries()
    for path in _TARGETS:
        if path.exists():
            added, total = merge(path, new)
            print(f"{path}: +{added} → {total} clubs")
        else:
            print(f"SKIP (missing): {path}")


if __name__ == "__main__":
    main()
