"""Coordenadas dos clubes, para a dimensão de distância de viagem.

POR QUE ISTO EXISTE. Grêmio–Fortaleza são 3.500 km; Arsenal–Chelsea são 8. O
Brasil é continental e as ligas europeias são compactas, e a viagem é um
fator físico real que hoje não existe em dimensão nenhuma — nem no mercado,
que precifica qualidade e não desgaste.

É o candidato mais promissor justamente por não ter análogo europeu: medido,
o mercado separa as partidas argentinas 38% menos que as inglesas, então o
que falta na América do Sul é um sinal que NÃO venha do mercado.

PRECISÃO DE CIDADE, E NÃO DE ESTÁDIO. A pergunta é "viagem longa ou curta",
e a diferença entre dois estádios da mesma cidade é ruído nessa escala. Usar
a cidade também torna a lista conferível: qualquer pessoa sabe onde fica
Porto Alegre, e ninguém sabe de cabeça a latitude do Beira-Rio.

CLUBES DA MESMA CIDADE FICAM COM AS MESMAS COORDENADAS de propósito —
Flamengo, Fluminense, Botafogo e Vasco são todos o Rio. A distância entre
eles é zero, e zero é a resposta certa: um clássico carioca não tem viagem.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

#: club_id → (latitude, longitude, cidade). A cidade fica junto para que a
#: linha seja conferível a olho — um par de números sozinho não denuncia o
#: erro de sinal que põe um clube brasileiro no hemisfério norte.
COORDENADAS: dict[str, tuple[float, float, str]] = {
    # --- Brasil ---
    "america_mineiro": (-19.92, -43.94, "Belo Horizonte"),
    "athletico_paranaense": (-25.43, -49.27, "Curitiba"),
    "atletico_goianiense": (-16.69, -49.26, "Goiânia"),
    "atletico_mineiro": (-19.92, -43.94, "Belo Horizonte"),
    "avai": (-27.60, -48.55, "Florianópolis"),
    "bahia": (-12.97, -38.50, "Salvador"),
    "botafogo": (-22.91, -43.17, "Rio de Janeiro"),
    "bragantino": (-22.95, -46.54, "Bragança Paulista"),
    "ceara": (-3.73, -38.52, "Fortaleza"),
    "chapecoense": (-27.10, -52.62, "Chapecó"),
    "corinthians": (-23.55, -46.63, "São Paulo"),
    "coritiba": (-25.43, -49.27, "Curitiba"),
    "criciuma": (-28.68, -49.37, "Criciúma"),
    "cruzeiro": (-19.92, -43.94, "Belo Horizonte"),
    "csa": (-9.67, -35.74, "Maceió"),
    "cuiaba": (-15.60, -56.10, "Cuiabá"),
    "figueirense": (-27.60, -48.55, "Florianópolis"),
    "flamengo": (-22.91, -43.17, "Rio de Janeiro"),
    "fluminense": (-22.91, -43.17, "Rio de Janeiro"),
    "fortaleza": (-3.73, -38.52, "Fortaleza"),
    "goias": (-16.69, -49.26, "Goiânia"),
    "gremio": (-30.03, -51.23, "Porto Alegre"),
    "internacional": (-30.03, -51.23, "Porto Alegre"),
    "joinville": (-26.30, -48.85, "Joinville"),
    "juventude": (-29.17, -51.18, "Caxias do Sul"),
    "mirassol": (-20.82, -49.52, "Mirassol"),
    "nautico": (-8.05, -34.90, "Recife"),
    "palmeiras": (-23.55, -46.63, "São Paulo"),
    "parana": (-25.43, -49.27, "Curitiba"),
    "ponte_preta": (-22.91, -47.06, "Campinas"),
    "portuguesa": (-23.55, -46.63, "São Paulo"),
    "remo": (-1.46, -48.50, "Belém"),
    "santa_cruz": (-8.05, -34.90, "Recife"),
    "santos": (-23.96, -46.33, "Santos"),
    "sao_paulo": (-23.55, -46.63, "São Paulo"),
    "sport_recife": (-8.05, -34.90, "Recife"),
    "vasco_da_gama": (-22.91, -43.17, "Rio de Janeiro"),
    "vitoria": (-12.97, -38.50, "Salvador"),
    # --- Argentina ---
    "aldosivi": (-38.00, -57.56, "Mar del Plata"),
    "all_boys": (-34.61, -58.38, "Buenos Aires"),
    "argentinos_juniors": (-34.61, -58.38, "Buenos Aires"),
    "atletico_rafaela": (-31.25, -61.49, "Rafaela"),
    "atletico_tucuman": (-26.82, -65.22, "San Miguel de Tucumán"),
    "banfield": (-34.74, -58.39, "Banfield"),
    "barracas_central": (-34.65, -58.38, "Buenos Aires"),
    "belgrano": (-31.42, -64.18, "Córdoba"),
    "boca_juniors": (-34.64, -58.36, "Buenos Aires"),
    "central_cordoba_santiago_del_estero": (-27.78, -64.26, "Santiago del Estero"),
    "chacarita_juniors": (-34.58, -58.52, "Buenos Aires"),
    "colon_santa_fe": (-31.63, -60.70, "Santa Fe"),
    "crucero_del_norte": (-27.48, -55.83, "Garupá"),
    "defensa_y_justicia": (-34.79, -58.28, "Florencio Varela"),
    "deportivo_riestra": (-34.66, -58.44, "Buenos Aires"),
    "estudiantes": (-34.92, -57.95, "La Plata"),
    "gimnasia_la_plata": (-34.92, -57.95, "La Plata"),
    "gimnasia_mendoza": (-32.89, -68.84, "Mendoza"),
    "godoy_cruz": (-32.89, -68.84, "Mendoza"),
    "huracan": (-34.64, -58.40, "Buenos Aires"),
    "independiente": (-34.67, -58.37, "Avellaneda"),
    "independiente_rivadavia": (-32.89, -68.84, "Mendoza"),
    "instituto": (-31.42, -64.18, "Córdoba"),
    "lanus": (-34.70, -58.39, "Lanús"),
    "newells_old_boys": (-32.95, -60.65, "Rosario"),
    "nueva_chicago": (-34.67, -58.47, "Buenos Aires"),
    "patronato": (-31.73, -60.53, "Paraná"),
    "platense": (-34.53, -58.48, "Vicente López"),
    "quilmes": (-34.72, -58.25, "Quilmes"),
    "racing_club": (-34.67, -58.37, "Avellaneda"),
    "river_plate": (-34.55, -58.45, "Buenos Aires"),
    "rosario_central": (-32.95, -60.65, "Rosario"),
    "san_lorenzo": (-34.65, -58.44, "Buenos Aires"),
    "san_martin_san_juan": (-31.54, -68.53, "San Juan"),
    "san_martin_tucuman": (-26.82, -65.22, "San Miguel de Tucumán"),
    "sarmiento_junin": (-34.59, -60.94, "Junín"),
    "talleres": (-31.42, -64.18, "Córdoba"),
    "temperley": (-34.77, -58.40, "Temperley"),
    "tigre": (-34.44, -58.53, "Victoria"),
    "union_santa_fe": (-31.63, -60.70, "Santa Fe"),
    "velez_sarsfield": (-34.64, -58.52, "Buenos Aires"),
    # --- Inglaterra ---
    "afc_bournemouth": (50.73, -1.84, "Bournemouth"),
    "arsenal": (51.55, -0.11, "Londres"),
    "aston_villa": (52.51, -1.88, "Birmingham"),
    "brentford": (51.49, -0.29, "Londres"),
    "brighton_hove_albion": (50.86, -0.08, "Brighton"),
    "burnley": (53.79, -2.23, "Burnley"),
    "chelsea": (51.48, -0.19, "Londres"),
    "crystal_palace": (51.40, -0.09, "Londres"),
    "everton": (53.44, -2.97, "Liverpool"),
    "fulham": (51.47, -0.22, "Londres"),
    "ipswich_town": (52.06, 1.14, "Ipswich"),
    "leeds_united": (53.78, -1.57, "Leeds"),
    "leicester_city": (52.62, -1.14, "Leicester"),
    "liverpool": (53.43, -2.96, "Liverpool"),
    "luton_town": (51.88, -0.43, "Luton"),
    "manchester_city": (53.48, -2.20, "Manchester"),
    "manchester_united": (53.46, -2.29, "Manchester"),
    "newcastle_united": (54.98, -1.62, "Newcastle"),
    "norwich_city": (52.62, 1.31, "Norwich"),
    "nottingham_forest": (52.94, -1.13, "Nottingham"),
    "sheffield_united": (53.37, -1.47, "Sheffield"),
    "southampton": (50.91, -1.39, "Southampton"),
    "tottenham_hotspur": (51.60, -0.07, "Londres"),
    "watford": (51.65, -0.40, "Watford"),
    "west_bromwich_albion": (52.51, -1.96, "West Bromwich"),
    "west_ham_united": (51.54, -0.02, "Londres"),
    "wolverhampton_wanderers": (52.59, -2.13, "Wolverhampton"),
    # --- Espanha ---
    "alaves": (42.85, -2.67, "Vitoria-Gasteiz"),
    "almeria": (36.84, -2.44, "Almería"),
    "athletic_bilbao": (43.26, -2.95, "Bilbao"),
    "atletico_madrid": (40.44, -3.60, "Madri"),
    "barcelona": (41.38, 2.12, "Barcelona"),
    "cadiz": (36.50, -6.27, "Cádis"),
    "celta_vigo": (42.21, -8.74, "Vigo"),
    "eibar": (43.18, -2.48, "Eibar"),
    "elche": (38.27, -0.66, "Elche"),
    "espanyol": (41.35, 2.07, "Barcelona"),
    "getafe": (40.33, -3.71, "Getafe"),
    "girona": (41.96, 2.83, "Girona"),
    "granada": (37.15, -3.60, "Granada"),
    "huesca": (42.13, -0.41, "Huesca"),
    # Ilhas Canárias: a viagem mais longa da liga espanhola, e a única que a
    # geografia do continente não explica.
    "las_palmas": (28.10, -15.46, "Las Palmas"),
    "leganes": (40.34, -3.76, "Leganés"),
    "levante": (39.49, -0.36, "Valência"),
    "mallorca": (39.59, 2.63, "Palma"),
    "osasuna": (42.80, -1.64, "Pamplona"),
    "rayo_vallecano": (40.39, -3.65, "Madri"),
    "real_betis": (37.36, -5.98, "Sevilha"),
    "real_madrid": (40.45, -3.69, "Madri"),
    "real_sociedad": (43.30, -1.97, "San Sebastián"),
    "real_valladolid": (41.64, -4.76, "Valladolid"),
    "sevilla": (37.38, -5.97, "Sevilha"),
    "valencia": (39.47, -0.36, "Valência"),
    "villarreal": (39.94, -0.10, "Villarreal"),
}


def aplicar(registro: dict) -> tuple[int, list[str]]:
    por_id = {c["club_id"]: c for c in registro["clubs"]}
    marcados = 0
    ausentes = []
    for club_id, (lat, lon, cidade) in COORDENADAS.items():
        clube = por_id.get(club_id)
        if clube is None:
            ausentes.append(club_id)
            continue
        clube["latitude"] = lat
        clube["longitude"] = lon
        clube["city"] = cidade
        marcados += 1
    return marcados, ausentes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    caminho = Path(args.registry)
    registro = json.loads(caminho.read_text(encoding="utf-8"))
    marcados, ausentes = aplicar(registro)

    Path(args.out).write_text(
        json.dumps(registro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    com_coord = sum(1 for c in registro["clubs"] if c.get("latitude") is not None)
    print(f"coordenadas gravadas: {marcados}")
    print(f"clubes com coordenada no registro: {com_coord} de {len(registro['clubs'])}")
    if ausentes:
        print(f"ids que não existem no registro: {', '.join(ausentes)}")
    return 1 if ausentes else 0


if __name__ == "__main__":
    raise SystemExit(main())
