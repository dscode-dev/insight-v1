"""Eventos DENTRO do corpus publicado — PR-04.4.2.

O QUE ESTES TESTES DE FATO PROTEGEM, e nenhum deles é «cobertura»:

    pertinência EXPLÍCITA      a versão declara quais eventos publica; não se
                               deriva de «a partida está no corpus» (§5)
    impressão SENSÍVEL         um evento a mais, a menos, ou uma revisão nova
                               produzem corpus DIFERENTE (§12 ao §15)
    impressão INDIFERENTE      ao lote e à ordem de leitura (§16, §17)
    ausente ≠ zero             no Parquet e no manifesto (§23, §24)
    denominador HONESTO        cobertura espacial sobre eventos que ACONTECEM
                               num ponto do campo (§27, §28)
    conflito RECUSADO          mesma identidade, conteúdo diferente: nada é
                               publicado (§69)
    versões antigas INTACTAS   um corpus sem eventos imprime hoje o que
                               imprimia antes deste PR (§62, §117)
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sports_intelligence.domain.corpus.composition import (
    ComposedMatchCorpusFacts,
    PublishedEvent,
    compose_events,
)
from sports_intelligence.domain.corpus.facts import (
    MATERIALIZABLE_FAMILIES,
    MatchCorpusFacts,
)
from sports_intelligence.domain.corpus.fingerprint import fingerprint_of
from sports_intelligence.domain.corpus.membership import CorpusMember, EventCorpusCounts
from sports_intelligence.domain.events.canonical import EventStatus
from sports_intelligence.domain.events.canonical_form import (
    EVENT_DETAIL_SCHEMA_VERSION,
    event_content_digest,
    event_content_form,
)
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from tests.support.corpus_fixtures import (
    EVENT_RUN,
    OUTRA_EVENT_RUN,
    escopo,
    evento_canonico,
    eventos_de,
    fatos,
    fatos_com_eventos,
    publicado,
)


def _membros(*compostos: ComposedMatchCorpusFacts) -> tuple[CorpusMember, ...]:
    return tuple(c.as_member() for c in compostos)


class TestAPertinenciaDeEvento:
    """§5, §6, §7. A pertinência é gravada, e a autoridade é o id canônico."""

    def test_a_familia_event_e_materializavel(self) -> None:
        """Ela deixou de ser a família que o motor não sabia escrever."""
        assert CoverageFamily.EVENT in MATERIALIZABLE_FAMILIES

    def test_anexar_eventos_declara_a_familia(self) -> None:
        composto = fatos_com_eventos(0, quantos=3)
        assert CoverageFamily.EVENT in composto.included_families
        assert len(composto.events) == 3

    def test_sem_eventos_o_objeto_e_o_mesmo(self) -> None:
        """§52. Uma versão sem eventos continua sendo um corpus válido, e o
        caminho dela é literalmente o de antes deste PR."""
        composto = ComposedMatchCorpusFacts.of(fatos(0))
        assert composto.with_events(()) is composto
        assert CoverageFamily.EVENT not in composto.included_families

    def test_a_pertinencia_aponta_para_o_evento_e_para_a_partida(self) -> None:
        composto = fatos_com_eventos(0, quantos=3)
        membros = composto.event_members()
        assert len(membros) == 3
        assert {m.match_id for m in membros} == {composto.match_id}
        assert {m.event_id for m in membros} == {e.id for e in composto.events}

    def test_dois_eventos_do_mesmo_jogador_no_mesmo_minuto_sao_dois(self) -> None:
        """§7. A autoridade é o `CanonicalEventId`. Colapsá-los por «mesma
        partida, mesmo jogador, mesmo minuto» apagaria um fato que aconteceu."""
        primeiro = evento_canonico(n=1, minuto=41, sequencia=0, source_key="a")
        segundo = evento_canonico(n=2, minuto=41, sequencia=1, source_key="b")
        assert primeiro.id != segundo.id
        composto = ComposedMatchCorpusFacts.of(fatos(0)).with_events(
            (publicado(primeiro), publicado(segundo))
        )
        assert len({m.event_id for m in composto.event_members()}) == 2

    def test_evento_de_outra_partida_e_recusado(self) -> None:
        """Um evento pendurado na partida errada atribui o fato a quem não o
        praticou — e a travessia «versão → evento → partida» quebraria."""
        de_outra = evento_canonico(n=0, match=1)
        with pytest.raises(ValidationError, match="recebeu evento de"):
            ComposedMatchCorpusFacts.of(fatos(0)).with_events((publicado(de_outra),))

    def test_a_familia_declarada_sem_evento_e_recusada(self) -> None:
        """§52. A família é a promessa; vazia, ela mente no manifesto."""
        with pytest.raises(ValidationError, match="não traz evento nenhum"):
            MatchCorpusFacts(
                match=fatos(0).match,
                competition=fatos(0).competition,
                season_label=fatos(0).season_label,
                included_families=(CoverageFamily.MATCH, CoverageFamily.EVENT),
                build_run_id="x",
                quality_assessment_id="y",
            )


class TestARevisaoNoCorpus:
    """§8. O histórico de revisão continua rastreável dentro do corpus."""

    def test_predecessor_corrigido_e_sucessor_convivem(self) -> None:
        """Publicar só o `ACTIVE` final apagaria «o que sabíamos antes» — que é
        a pergunta inteira do ADR-0013."""
        anterior = evento_canonico(n=1, source_key="k", status=EventStatus.CORRECTED)
        sucessor = evento_canonico(
            n=1, source_key="k", revision=2, supersedes=anterior.id, minuto=24
        )
        composto = ComposedMatchCorpusFacts.of(fatos(0)).with_events(
            (publicado(anterior), publicado(sucessor))
        )
        assert len(composto.events) == 2
        linhas = composto.rows_for(CoverageFamily.EVENT)
        estados = {linha["status"] for linha in linhas}
        assert estados == {"CORRECTED", "ACTIVE"}
        assert any(linha["supersedes_event_id"] == str(anterior.id) for linha in linhas)

    def test_cancelado_continua_publicado(self) -> None:
        """Um gol anulado é um fato: ele foi marcado e foi anulado. Sumir com
        ele faria o corpus não ter como explicar a anulação."""
        cancelado = evento_canonico(n=1, status=EventStatus.CANCELLED)
        composto = ComposedMatchCorpusFacts.of(fatos(0)).with_events((publicado(cancelado),))
        assert composto.event_counts().by_status == {"CANCELLED": 1}


class TestAImpressaoComEventos:
    """§10 ao §17. A impressão do corpus passa a enxergar eventos."""

    def test_evento_a_mais_muda_a_impressao(self) -> None:
        """§12. As mesmas partidas com um evento a mais não são o mesmo corpus."""
        dez = fatos_com_eventos(0, quantos=3)
        onze = fatos_com_eventos(0, quantos=4)
        assert dez.content_fingerprint() != onze.content_fingerprint()
        assert fingerprint_of(_membros(dez), scope=escopo()) != fingerprint_of(
            _membros(onze), scope=escopo()
        )

    def test_evento_a_menos_muda_a_impressao(self) -> None:
        """§13. E é a mesma propriedade vista do outro lado."""
        completo = fatos_com_eventos(0, quantos=4)
        podado = ComposedMatchCorpusFacts.of(fatos(0)).with_events(
            eventos_de(0, quantos=4)[:3]
        )
        assert completo.content_fingerprint() != podado.content_fingerprint()

    def test_fato_do_evento_diferente_muda_a_impressao(self) -> None:
        """§14. Mesmo id, conteúdo diferente — a impressão precisa enxergar."""
        original = evento_canonico(n=1, minuto=23)
        deslocado = replace(original, clock=replace(original.clock, minute=24))
        assert original.id == deslocado.id
        um = ComposedMatchCorpusFacts.of(fatos(0)).with_events((publicado(original),))
        outro = ComposedMatchCorpusFacts.of(fatos(0)).with_events((publicado(deslocado),))
        assert um.content_fingerprint() != outro.content_fingerprint()

    def test_revisao_nova_muda_a_impressao(self) -> None:
        """§15. Uma correção legítima mudou o histórico canônico — e o corpus
        que a publica não é o corpus que não a tinha."""
        base = evento_canonico(n=1, source_key="k")
        corrigido = replace(base, status=EventStatus.CORRECTED)
        sucessor = evento_canonico(
            n=1, source_key="k", revision=2, supersedes=base.id, minuto=24
        )
        antes = ComposedMatchCorpusFacts.of(fatos(0)).with_events((publicado(base),))
        depois = ComposedMatchCorpusFacts.of(fatos(0)).with_events(
            (publicado(corrigido), publicado(sucessor))
        )
        assert antes.content_fingerprint() != depois.content_fingerprint()

    def test_a_ordem_de_leitura_nao_muda_a_impressao(self) -> None:
        """§17. A ordem canônica é imposta na serialização, e não herdada do
        `ORDER BY` — senão a impressão mudaria com o plano de consulta."""
        eventos = eventos_de(0, quantos=5)
        direto = ComposedMatchCorpusFacts.of(fatos(0)).with_events(eventos)
        invertido = ComposedMatchCorpusFacts.of(fatos(0)).with_events(tuple(reversed(eventos)))
        assert direto.content_fingerprint() == invertido.content_fingerprint()
        assert direto.rows_for(CoverageFamily.EVENT) == invertido.rows_for(CoverageFamily.EVENT)

    def test_corpus_sem_evento_imprime_como_antes(self) -> None:
        """§62, §117. Uma versão publicada antes desta capacidade continua
        reproduzível: o conteúdo dela não ganhou chave nenhuma."""
        antigo = ComposedMatchCorpusFacts.of(fatos(0))
        assert "events" not in antigo.facts.content_form()
        assert "events" not in antigo.as_member().as_canonical()

    def test_o_rodape_da_impressao_so_conta_evento_quando_ha_evento(self) -> None:
        """A contagem de evento entra no rodapé quando existe, e a chave nem
        aparece quando não existe — é isso que preserva a impressão antiga."""
        from sports_intelligence.domain.corpus.membership import MembershipCounts

        vazio = MembershipCounts(matches=1)
        assert "events" not in vazio.as_canonical()
        com_evento = vazio.with_events(EventCorpusCounts(total=3))
        assert com_evento.as_canonical()["events"]["total"] == 3  # type: ignore[index]


class TestAComposicaoDeEventos:
    """§66 ao §70. Duas execuções, um evento, duas linhagens — ou conflito."""

    def test_o_mesmo_evento_de_duas_execucoes_e_um_membro(self) -> None:
        """§68. Reprocessar não duplica: o id é derivado, então é o MESMO
        evento — e as duas linhagens são igualmente verdadeiras."""
        evento = evento_canonico(n=1)
        composto = compose_events(
            (
                publicado(evento, runs=(EVENT_RUN,)),
                publicado(evento, runs=(OUTRA_EVENT_RUN,)),
            )
        )
        assert len(composto) == 1
        assert composto[0].build_run_ids == tuple(sorted((EVENT_RUN, OUTRA_EVENT_RUN)))

    def test_a_ordem_da_entrada_nao_muda_a_composicao(self) -> None:
        """§17. O lote não vaza para o resultado."""
        candidatos = [publicado(e.event) for e in eventos_de(0, quantos=4)]
        assert [p.event.id for p in compose_events(candidatos)] == [
            p.event.id for p in compose_events(list(reversed(candidatos)))
        ]

    def test_conteudo_conflitante_bloqueia_a_publicacao(self) -> None:
        """§69. A identidade diz «é o mesmo evento» e o conteúdo diz que não.
        Escolher um seria o motor decidindo qual história é verdade."""
        original = evento_canonico(n=1, minuto=23)
        divergente = replace(original, clock=replace(original.clock, minute=77))
        assert original.id == divergente.id
        with pytest.raises(ConflictError, match="afirmando fatos diferentes"):
            compose_events(
                (
                    publicado(original, runs=(EVENT_RUN,)),
                    publicado(divergente, runs=(OUTRA_EVENT_RUN,)),
                )
            )

    def test_eventos_distintos_nao_sao_deduplicados(self) -> None:
        """§70. A publicação não tenta adivinhar que dois eventos são o mesmo."""
        assert len(compose_events([publicado(e.event) for e in eventos_de(0, quantos=5)])) == 5

    def test_evento_sem_execucao_de_origem_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="sem execução de origem"):
            PublishedEvent(event=evento_canonico(), build_run_ids=())


class TestAsLinhasDoParquet:
    """§19 ao §25. O que de fato é escrito, coluna a coluna."""

    def test_uma_linha_por_evento(self) -> None:
        composto = fatos_com_eventos(0, quantos=5)
        assert len(composto.rows_for(CoverageFamily.EVENT)) == 5

    def test_familia_ausente_nao_produz_linha(self) -> None:
        assert ComposedMatchCorpusFacts.of(fatos(0)).rows_for(CoverageFamily.EVENT) == []

    def test_coordenada_ausente_e_nula_nunca_zero(self) -> None:
        """§23. `0.0` é o canto do campo — uma posição perfeitamente válida."""
        sem_ponto = evento_canonico(n=1, tipo=EventType.CARD, ponto=None)
        linha = (
            ComposedMatchCorpusFacts.of(fatos(0))
            .with_events((publicado(sem_ponto),))
            .rows_for(CoverageFamily.EVENT)[0]
        )
        assert linha["start_x"] is None
        assert linha["start_y"] is None
        assert linha["coordinate_frame"] is None

    def test_jogador_ausente_e_nulo(self) -> None:
        estrutural = evento_canonico(
            n=1, tipo=EventType.PERIOD_END, jogador=False, time=False, ponto=None
        )
        linha = (
            ComposedMatchCorpusFacts.of(fatos(0))
            .with_events((publicado(estrutural),))
            .rows_for(CoverageFamily.EVENT)[0]
        )
        assert linha["player_id"] is None
        assert linha["team_id"] is None

    def test_xg_zero_nao_e_xg_ausente(self) -> None:
        """§24. Um chute medido como quase impossível e um chute não medido são
        fatos diferentes — colapsá-los envenena qualquer média."""
        zero = evento_canonico(n=1, xg="0")
        ausente = evento_canonico(n=2, xg_indisponivel=True)
        linhas = (
            ComposedMatchCorpusFacts.of(fatos(0))
            .with_events((publicado(zero), publicado(ausente)))
            .rows_for(CoverageFamily.EVENT)
        )
        por_id = {linha["event_id"]: linha for linha in linhas}
        do_zero = por_id[str(zero.id)]
        do_ausente = por_id[str(ausente.id)]
        assert do_zero["xg"] == 0
        assert do_zero["xg_unavailable_reason"] is None
        assert do_ausente["xg"] is None
        assert do_ausente["xg_unavailable_reason"] == "NOT_PUBLISHED"

    def test_o_detalhe_e_json_canonico_versionado(self) -> None:
        """§20. Nunca `repr()` de objeto Python: ele não é estável entre
        versões da linguagem, e um arquivo do corpus é lido daqui a anos."""
        linha = fatos_com_eventos(0, quantos=1).rows_for(CoverageFamily.EVENT)[0]
        assert linha["detail_kind"] == "SHOT"
        assert linha["detail_schema_version"] == EVENT_DETAIL_SCHEMA_VERSION
        assert str(linha["detail"]).startswith('{"body_part":')

    def test_a_licenca_do_evento_viaja_na_linha(self) -> None:
        linha = fatos_com_eventos(0, quantos=1).rows_for(CoverageFamily.EVENT)[0]
        assert linha["license_class"] == "PUBLIC_DOMAIN"

    def test_o_gol_do_evento_nao_e_o_placar(self) -> None:
        """§22. `GoalEvent ≠ MatchResult`. Os dois convivem e descrevem coisas
        diferentes: um diz «aos 23, este jogador marcou», o outro diz «o jogo
        terminou 2 a 1». Derivar o placar contando gols erraria sempre que a
        fonte de eventos estivesse incompleta — e é aí que ninguém percebe."""
        composto = fatos_com_eventos(0, quantos=5, families=(CoverageFamily.MATCH,))
        gols = [
            linha
            for linha in composto.rows_for(CoverageFamily.EVENT)
            if linha["event_type"] == "GOAL"
        ]
        assert gols
        da_partida = composto.rows_for(CoverageFamily.MATCH)[0]
        # O placar vem do `MatchResult` do fixture (2 a 1) e NÃO da contagem
        # de eventos `GOAL`, que é um só.
        assert da_partida["home_goals"] == 2
        assert da_partida["away_goals"] == 1
        assert len(gols) == 1

    def test_odds_nao_entram_nas_linhas_de_evento(self) -> None:
        """§21. Cada família tem granularidade própria."""
        composto = fatos_com_eventos(
            0, quantos=3, families=(CoverageFamily.MATCH, CoverageFamily.ODDS)
        )
        colunas = set(composto.rows_for(CoverageFamily.EVENT)[0])
        assert not (colunas & {"bookmaker", "market", "selection", "decimal_odds"})


class TestAsContagensDeEvento:
    """§31, §53, §54. Contagem do que foi publicado — nunca analítica."""

    def test_conta_por_tipo_e_por_estado(self) -> None:
        contagem = fatos_com_eventos(0, quantos=5).event_counts()
        assert contagem.total == 5
        assert contagem.by_type["SHOT"] == 1
        assert contagem.by_status["ACTIVE"] == 5

    def test_conta_com_jogador_e_com_coordenada(self) -> None:
        contagem = fatos_com_eventos(0, quantos=5).event_counts()
        assert contagem.with_player == 4  # o `PERIOD_END` não tem executante
        assert contagem.with_coordinates == 3

    def test_o_denominador_espacial_ignora_o_que_nao_acontece_num_ponto(self) -> None:
        """§27. Pôr o apito final e o cartão no denominador faria uma fonte
        espacialmente completa parecer ter 60% de cobertura."""
        contagem = fatos_com_eventos(0, quantos=5).event_counts()
        assert contagem.spatially_eligible == 3
        assert contagem.spatial_ratio == 1.0

    def test_sem_evento_elegivel_a_cobertura_espacial_e_indefinida(self) -> None:
        """§28. Não é 0% — é indefinida, e as duas pedem ações opostas."""
        estrutural = evento_canonico(
            n=1, tipo=EventType.PERIOD_END, jogador=False, time=False, ponto=None
        )
        composto = ComposedMatchCorpusFacts.of(fatos(0)).with_events((publicado(estrutural),))
        assert composto.event_counts().spatial_ratio is None

    def test_as_contagens_somam_entre_lotes(self) -> None:
        um = fatos_com_eventos(0, quantos=3).event_counts()
        outro = fatos_com_eventos(1, quantos=3).event_counts()
        somado = um.merged_with(outro)
        assert somado.total == 6
        assert somado.matches_with_events == 2


class TestAFormaCanonicaDoEvento:
    """§9, §11. Uma serialização só, para o registro e para o corpus."""

    def test_a_procedencia_de_execucao_nao_entra_no_conteudo(self) -> None:
        """Dois processamentos do mesmo evento têm procedências diferentes e
        são o mesmo fato — incluí-la faria reprocessamento virar conflito."""
        evento = evento_canonico(n=1)
        outro = replace(
            evento,
            provenance=replace(evento.provenance, source_record_id="linha-999"),
        )
        assert event_content_digest(evento) == event_content_digest(outro)

    def test_a_licenca_nao_entra_no_conteudo(self) -> None:
        """A licença decide se o evento PODE ser publicado num escopo, e não o
        que ele afirma. O mesmo gol sob duas licenças continua sendo um gol."""
        from sports_intelligence.domain.shared.provenance import LicenseClass

        evento = evento_canonico(n=1)
        restrito = replace(
            evento,
            provenance=replace(evento.provenance, license_class=LicenseClass.RESEARCH_ONLY),
        )
        assert event_content_digest(evento) == event_content_digest(restrito)

    def test_o_conteudo_cobre_relogio_posicao_e_detalhe(self) -> None:
        forma = event_content_form(evento_canonico(n=1))
        assert forma["minute"] == 23
        assert forma["period"] == "FIRST_HALF"
        assert forma["start_location"] == {"frame": "ATTACKING", "x": 0.88, "y": 0.51}
        assert forma["detail"]["kind"] == "SHOT"  # type: ignore[index]
