"""Dois clubes que o registro engoliu em outro continente.

ENCONTRADOS POR ACIDENTE, e vale registrar como: a dimensão de distância de
viagem do passo 4 reportou `argentina_liga_profesional` com máximo de 11.524
km. A Argentina inteira tem 3.700 km de extensão. O número impossível
denunciou o que o "100% de clubes resolvidos" tinha escondido.

    'Arsenal Sarandi'      ->  arsenal   (Arsenal FC, Londres)   352 partidas
    'Portuguesa'           ->  portuguesa (Portuguesa FC, VE)      76 partidas
    'Olimpo Bahia Blanca'  ->  bahia     (EC Bahia, Salvador)     ver abaixo

O TERCEIRO ESCAPOU DA PRIMEIRA VARREDURA, e o motivo importa: eu procurei
nomes sul-americanos resolvendo para clubes fora de BR e AR. Um clube
argentino virando brasileiro passa nesse filtro. A varredura certa é por
ARQUIVO — nome do ARG.csv tem de virar clube argentino, nome do BRA.csv tem
de virar brasileiro — e é ela que está no teste.

POR QUE O RESOLVEDOR ACEITOU. Ele tem um fallback por subconjunto de tokens,
para grafias que DECORAM um nome do registro: "Real Betis Balompié" contém
{real, betis} e resolve para `real_betis`. Ele já recusa quando dois clubes
explicam o nome igualmente bem — foi assim que o Espanyol parou de virar
Barcelona. Mas {arsenal} é subconjunto de {arsenal, sarandi} e é o ÚNICO
candidato, então não há ambiguidade a detectar: ele resolve, com confiança, e
erra. "Balompié" é decoração; "Sarandí" é o que distingue dois clubes.

A CORREÇÃO É NO REGISTRO, e é suficiente porque o casamento exato vem antes
do fallback: com `arsenal_sarandi` cadastrado sob o alias "Arsenal Sarandi",
a busca acerta na primeira linha e nunca chega ao subconjunto.

O CASO DA PORTUGUESA É PIOR E MERECE NOTA. O registro tinha UMA `portuguesa`,
a venezuelana, cadastrada para Libertadores/Sudamericana. As 76 partidas da
Portuguesa de Desportos (São Paulo) no Brasileirão de 2012-2013 foram para
ela. E o script de coordenadas do passo 4 gravou São Paulo na entrada
venezuelana — deixando o dado brasileiro plausível e a entrada errada.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

#: Clubes que faltavam, e que por faltarem foram absorvidos por outro.
NOVOS = [
    {
        "club_id": "arsenal_sarandi",
        "name": "Arsenal de Sarandí",
        "country": "AR",
        "competition": "argentina_liga_profesional",
        "competitions": ["argentina_liga_profesional", "argentina_copa_liga_profesional"],
        "logo_path": None,
        "aliases": ["Arsenal Sarandi", "Arsenal de Sarandí", "Arsenal de Sarandi"],
        "latitude": -34.68,
        "longitude": -58.34,
        "city": "Sarandí",
    },
    {
        "club_id": "olimpo",
        "name": "Club Olimpo",
        "country": "AR",
        "competition": "argentina_liga_profesional",
        "competitions": ["argentina_liga_profesional"],
        "logo_path": None,
        "aliases": ["Olimpo Bahia Blanca", "Olimpo", "Club Olimpo"],
        "latitude": -38.72,
        "longitude": -62.27,
        "city": "Bahía Blanca",
    },
    {
        # A VENEZUELANA GANHA UM ID PRÓPRIO, e a brasileira FICA com o id nu.
        #
        # Parece o contrário do intuitivo, e é a escolha certa: `club_id`
        # também é chave de busca (`cid.replace("_", " ")`), então enquanto a
        # venezuelana for `portuguesa` ela vence o nome nu por construção,
        # aconteça o que acontecer com nome e apelidos. E as 76 partidas que
        # já estão gravadas sob `portuguesa` são, todas elas, da brasileira —
        # corrigir o significado do id em vez de mover as linhas deixa o dado
        # certo sem reingestão nenhuma.
        "club_id": "portuguesa_acarigua",
        "name": "Portuguesa FC",
        "country": "VE",
        "competition": "libertadores",
        "competitions": ["libertadores", "sudamericana"],
        "logo_path": "/clubs/portuguesa.png",
        "aliases": ["Portuguesa FC", "Portuguesa Acarigua"],
        "latitude": 9.55,
        "longitude": -69.20,
        "city": "Acarigua",
    },
]

#: Correções em entradas existentes: o alias que precisa sair, e a coordenada
#: que foi gravada na entrada errada.
#: País dos clubes que estavam cadastrados sem ele.
#:
#: Sem `country` a varredura de colisão não tem como julgar, e foi
#: exatamente por isso que `Olimpo Bahia Blanca -> bahia` sobreviveu à
#: primeira passada: o filtro aceitava BR e AR juntos.
PAISES_FALTANDO = {
    "central_cordoba_santiago_del_estero": "AR",
    "colon_santa_fe": "AR",
    "san_lorenzo": "AR",
    "atletico_goianiense": "BR",
}

CORRECOES = {
    # `portuguesa` deixa de ser a venezuelana e passa a ser a brasileira, que
    # é o que 100% das partidas gravadas sob este id sempre foram.
    "portuguesa": {
        "name": "Associação Portuguesa de Desportos",
        "country": "BR",
        "competition": "brasileirao",
        "competitions": ["brasileirao"],
        "aliases": ["Portuguesa", "Portuguesa de Desportos", "Lusa"],
        "latitude": -23.55,
        "longitude": -46.63,
        "city": "São Paulo",
    },
}


def aplicar(registro: dict) -> tuple[list[str], list[str]]:
    por_id = {c["club_id"]: c for c in registro["clubs"]}
    criados, corrigidos = [], []

    for novo in NOVOS:
        if novo["club_id"] in por_id:
            continue
        registro["clubs"].append(dict(novo))
        por_id[novo["club_id"]] = registro["clubs"][-1]
        criados.append(novo["club_id"])

    for club_id, pais in PAISES_FALTANDO.items():
        clube = por_id.get(club_id)
        if clube is not None and not clube.get("country"):
            clube["country"] = pais
            corrigidos.append(f"{club_id} (país)")

    for club_id, mudanca in CORRECOES.items():
        clube = por_id.get(club_id)
        if clube is None:
            continue
        for chave, valor in mudanca.items():
            clube[chave] = valor
        corrigidos.append(club_id)

    registro["count"] = len(registro["clubs"])
    return criados, corrigidos


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    registro = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    antes = len(registro["clubs"])
    criados, corrigidos = aplicar(registro)

    Path(args.out).write_text(
        json.dumps(registro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"clubes: {antes} -> {len(registro['clubs'])}")
    print(f"criados: {', '.join(criados) or '(nenhum)'}")
    print(f"corrigidos: {', '.join(corrigidos) or '(nenhum)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
