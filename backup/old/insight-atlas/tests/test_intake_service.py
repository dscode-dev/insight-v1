"""O núcleo compartilhado pelas duas portas.

O que estes testes travam não é "a ingestão funciona" — é que ela **conta e
explica**. O ponto de partida desta reconstrução foi um pipeline que aceitava
dados sem dizer quantos, recusava sem dizer por quê, e respondia "deu certo"
sem medir diferença nenhuma.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from atlas.intake.composition import Contribuicao, compor, exigencia
from atlas.intake.contract import example, example_parcial
from atlas.intake.repository import Gravacao
from atlas.intake.service import (
    MalformedLine,
    SimulacaoRepository,
    ingest,
    read_jsonl,
)

REGISTRO = frozenset({"arsenal", "chelsea", "liverpool", "everton"})


class RepositorioFalso:
    """Guarda em memória, com a mesma interface do real.

    Compõe de verdade, e não só guarda o último registro: a regra que decide
    se uma contribuição vira partida é o que o serviço reporta, e um falso que
    aceitasse tudo faria os testes de contagem passarem justamente quando ela
    quebrasse.
    """

    def __init__(self) -> None:
        self.registros: dict[str, object] = {}
        self.contribuicoes: dict[tuple[str, str], Contribuicao] = {}
        self.recusas: list[dict] = []

    async def count(self) -> int:
        return len(self.registros)

    async def upsert(self, record, *, via: str, by: str) -> Gravacao:
        existia = record.uid in self.registros
        documento = json.loads(record.model_dump_json())
        self.contribuicoes[(record.uid, record.provenance.source)] = Contribuicao(
            source=record.provenance.source, profile=(), document=documento
        )
        composicao = compor(
            c for (uid, _), c in self.contribuicoes.items() if uid == record.uid
        )
        # A EXIGÊNCIA DA COMPETIÇÃO, não a lista inteira de blocos. Usar
        # `BLOCOS` aqui faria o falso cobrar `market_totals` do Brasileirão,
        # onde a coluna não existe em fonte nenhuma — e os testes passariam
        # exatamente quando a regra real quebrasse.
        exigidos = exigencia(record.identity.competition)
        faltando = (
            exigidos
            if composicao is None
            else tuple(b for b in exigidos if b not in composicao.perfil)
        )
        if not faltando:
            self.registros[record.uid] = (record, via, by)
        return Gravacao(existia, faltando)

    async def record_rejection(self, *, payload, errors, via, by) -> None:
        self.recusas.append(
            {"payload": payload, "errors": list(errors), "via": via, "by": by}
        )


def _outra_partida(**mudancas) -> dict:
    payload = copy.deepcopy(example())
    payload["identity"].update(mudancas)
    return payload


@pytest.mark.asyncio
class TestCruzamentoDeFontes:
    """O caso que a composição existe para atender, ponta a ponta.

    Duas fontes públicas, nenhuma completa sozinha, uma partida no fim. E o
    relatório dizendo em qual dos dois estados cada linha parou — porque
    "aceita" sem isso significaria coisas diferentes para as duas.
    """

    async def test_uma_parcial_sozinha_e_aceita_mas_nao_vira_partida(self):
        repo = RepositorioFalso()
        csv_publico, _ = example_parcial()
        report = await ingest([csv_publico], repo, via="cli", by="darlan",
                              registry=REGISTRO)

        assert report.accepted == 1
        assert report.rejected == 0
        # E, principalmente: não entrou no corpus.
        assert report.pending == 1
        assert report.added == 0
        assert report.total_after == report.total_before
        assert report.missing_blocks == {"stats": 1}
        assert report.lines[0].missing_blocks == ("stats",)

    async def test_a_segunda_fonte_completa_a_partida(self):
        repo = RepositorioFalso()
        csv_publico, raspagem = example_parcial()

        await ingest([csv_publico], repo, via="cli", by="darlan", registry=REGISTRO)
        report = await ingest([raspagem], repo, via="api", by="darlan",
                              registry=REGISTRO)

        assert report.pending == 0
        assert report.added == 1
        assert report.total_after - report.total_before == 1
        assert report.lines[0].missing_blocks == ()

    async def test_a_ordem_de_chegada_nao_importa(self):
        """Se importasse, ingerir os arquivos na ordem errada perderia
        partidas em silêncio — que é o modo de falha que a composição
        substituiu, reaparecendo por outra porta."""
        csv_publico, raspagem = example_parcial()

        primeiro = RepositorioFalso()
        await ingest([csv_publico, raspagem], primeiro, via="cli", by="d",
                     registry=REGISTRO)
        segundo = RepositorioFalso()
        await ingest([raspagem, csv_publico], segundo, via="cli", by="d",
                     registry=REGISTRO)

        assert len(primeiro.registros) == len(segundo.registros) == 1
        assert set(primeiro.registros) == set(segundo.registros)

    async def test_reingerir_a_mesma_fonte_nao_desmonta_a_partida(self):
        """Substituir a contribuição de uma fonte não pode remover o bloco
        que a outra trouxe — era o defeito original, e reingestão é
        exatamente quando ele apareceria."""
        repo = RepositorioFalso()
        csv_publico, raspagem = example_parcial()
        await ingest([csv_publico, raspagem], repo, via="cli", by="d",
                     registry=REGISTRO)

        report = await ingest([csv_publico], repo, via="cli", by="d",
                              registry=REGISTRO)

        assert report.pending == 0
        assert report.replaced == 1
        assert len(repo.registros) == 1


class TestContagem:
    async def test_relata_a_diferenca_medida_e_nao_so_um_ok(self):
        """'Deu certo' sem antes e depois é uma afirmação sem medida."""
        repo = RepositorioFalso()
        report = await ingest(
            [example()], repo, via="cli", by="ninja", registry=REGISTRO
        )
        assert report.total_before == 0
        assert report.total_after == 1
        assert report.as_dict()["delta"] == 1

    async def test_separa_novas_de_atualizadas(self):
        """Reenviar o mesmo arquivo e ingerir 3.000 partidas novas dariam
        relatórios idênticos sem esta distinção."""
        repo = RepositorioFalso()
        await ingest([example()], repo, via="cli", by="ninja", registry=REGISTRO)
        report = await ingest(
            [example()], repo, via="cli", by="ninja", registry=REGISTRO
        )
        assert report.accepted == 1
        assert report.replaced == 1
        assert report.added == 0
        assert report.total_after == report.total_before == 1

    async def test_a_identidade_e_que_deduplica_nao_o_id_da_fonte(self):
        """Mesma partida, ids de fonte diferentes: uma linha só. Foi keyear
        no id da fonte que fez 1.554 partidas serem contadas em triplicata."""
        repo = RepositorioFalso()
        a = copy.deepcopy(example())
        b = copy.deepcopy(example())
        b["provenance"]["source"] = "openfootball"
        b["provenance"]["source_match_id"] = "of-en.1-2023-24-0075"
        report = await ingest([a, b], repo, via="cli", by="ninja", registry=REGISTRO)
        assert report.accepted == 2
        assert report.added == 1 and report.replaced == 1
        assert report.total_after == 1


@pytest.mark.asyncio
class TestLoteParcial:
    async def test_uma_linha_ruim_nao_derruba_o_arquivo(self):
        """5.000 partidas com uma linha errada devem gravar 4.999. Um
        carregamento tudo-ou-nada obriga o operador a descobrir qual das
        5.000 quebrou."""
        repo = RepositorioFalso()
        ruim = copy.deepcopy(example())
        del ruim["market"]
        lote = [
            example(),
            ruim,
            _outra_partida(home_club_id="liverpool", away_club_id="everton"),
        ]
        report = await ingest(lote, repo, via="cli", by="ninja", registry=REGISTRO)
        assert report.accepted == 2
        assert report.rejected == 1
        assert report.total_after == 2

    async def test_a_recusa_fica_gravada_e_nao_so_devolvida(self):
        """Quem chamou pode ignorar a resposta; sem isto, 'o Atlas não tem
        essa partida' vira mistério em vez de consulta."""
        repo = RepositorioFalso()
        ruim = copy.deepcopy(example())
        del ruim["stats"]
        await ingest([ruim], repo, via="api", by="console", registry=REGISTRO)
        assert len(repo.recusas) == 1
        assert repo.recusas[0]["via"] == "api"
        assert repo.recusas[0]["by"] == "console"
        assert any(e.field == "stats" for e in repo.recusas[0]["errors"])

    async def test_agrupa_as_recusas_por_campo(self):
        """400 recusas viram uma frase sobre o que está errado no arquivo."""
        repo = RepositorioFalso()
        lote = []
        for i in range(5):
            ruim = copy.deepcopy(example())
            del ruim["market"]
            ruim["identity"]["home_club_id"] = ["arsenal", "liverpool"][i % 2]
            ruim["identity"]["away_club_id"] = ["chelsea", "everton"][i % 2]
            lote.append(ruim)
        report = await ingest(lote, repo, via="cli", by="ninja", registry=REGISTRO)
        # O perfil declara as duas metades do mercado, e as duas sumiram —
        # agrupadas pelo campo que o remetente edita, não por "market".
        assert report.by_field["market.closing"] == 5
        assert report.by_field["market.opening"] == 5


@pytest.mark.asyncio
class TestLinhaIlegivel:
    async def test_json_quebrado_e_recusado_por_isso_e_nao_por_campo_faltando(self):
        """Um dicionário-sentinela teria listado os cinco blocos como
        ausentes, mandando o operador procurar o problema errado."""
        repo = RepositorioFalso()
        linhas = read_jsonl('{"identity": {\n' + "\n" + '{"a": 1}')
        assert any(isinstance(l, MalformedLine) for l in linhas)
        report = await ingest(linhas, repo, via="cli", by="ninja", registry=REGISTRO)
        primeira = report.lines[0]
        assert not primeira.accepted
        assert len(primeira.errors) == 1
        assert "não é JSON válido" in primeira.errors[0].reason

    async def test_arquivo_com_linha_truncada_ainda_reporta_o_resto(self):
        repo = RepositorioFalso()
        import json as _json

        texto = "\n".join([
            _json.dumps(example()),
            '{"identity": {"competition":',
            _json.dumps(_outra_partida(home_club_id="liverpool", away_club_id="everton")),
        ])
        report = await ingest(
            read_jsonl(texto), repo, via="cli", by="ninja", registry=REGISTRO
        )
        assert report.submitted == 3
        assert report.accepted == 2
        assert report.rejected == 1


@pytest.mark.asyncio
class TestRastreio:
    async def test_registra_por_qual_porta_e_por_quem(self):
        """'Como isso entrou aqui' é a primeira pergunta quando um número
        não fecha."""
        repo = RepositorioFalso()
        await ingest([example()], repo, via="api", by="darlan", registry=REGISTRO)
        (_, via, by) = next(iter(repo.registros.values()))
        assert via == "api" and by == "darlan"

    async def test_cada_linha_carrega_um_rotulo_que_localiza_o_registro(self):
        repo = RepositorioFalso()
        report = await ingest([example()], repo, via="cli", by="ninja", registry=REGISTRO)
        assert "arsenal x chelsea" in report.lines[0].label

    async def test_registro_sem_identidade_ainda_e_localizavel(self):
        """Recusado justamente por não ter identidade — e mesmo assim
        precisa ser encontrável no arquivo que o operador enviou."""
        repo = RepositorioFalso()
        sem = copy.deepcopy(example())
        del sem["identity"]
        report = await ingest([sem], repo, via="cli", by="ninja", registry=REGISTRO)
        assert "fd-2324-E0-0000" in report.lines[0].label


class TestSimulacaoUnica:
    """As duas portas simulam com a MESMA classe, e isso é o teste.

    Eram duas cópias — uma na rota HTTP, uma no CLI — que tinham de mudar
    juntas toda vez que o repositório real mudasse de interface. Três vezes
    não mudaram. A última estourou na frente do operador, com `'bool' object
    has no attribute 'faltando'`, porque `--simular` do CLI não tinha teste e
    a rota tinha.

    Duas cópias não se mantêm sincronizadas por disciplina, então agora é uma.
    """

    @pytest.mark.asyncio
    async def test_simula_sem_gravar_e_relata_a_mesma_forma(self):
        falso = SimulacaoRepository(0)
        report = await ingest(
            [example()], falso, via="api", by="darlan", registry=REGISTRO
        )
        assert report.accepted == 1
        assert report.total_after == report.total_before == 0
        # Simular não compõe: dizer que falta um bloco exigiria ler a base que
        # a simulação promete não tocar.
        assert report.pending == 0
        assert report.missing_blocks == {}

    @pytest.mark.asyncio
    async def test_a_recusa_simulada_nao_vai_para_a_trilha(self):
        """Gravá-la encheria a auditoria com tentativas que ninguém fez."""
        ruim = copy.deepcopy(example())
        del ruim["stats"]
        report = await ingest(
            [ruim], SimulacaoRepository(0), via="cli", by="d", registry=REGISTRO
        )
        assert report.rejected == 1

    def test_as_duas_portas_usam_esta_classe_e_nao_uma_copia(self):
        """Lido do fonte, e não importado: `scripts/atlas_intake.py` puxa
        `atlas.registry`, que resolve os protos por caminho relativo ao
        `/opt/build` da imagem — e a rota HTTP puxa a mesma cadeia pelo
        contêiner de dependências. Importá-los aqui testaria o layout da
        imagem, não a ausência de cópia."""
        raiz = pathlib.Path(__file__).resolve().parents[1]
        for arquivo in ("scripts/atlas_intake.py", "atlas/api/routes/intake.py"):
            fonte = (raiz / arquivo).read_text(encoding="utf-8")
            assert "SimulacaoRepository" in fonte, arquivo
            assert "from atlas.intake.service import" in fonte, arquivo
            # A cópia que existia. Se voltar, volta o defeito.
            assert "async def upsert" not in fonte, (
                f"{arquivo} voltou a ter um repositório falso próprio"
            )
