"""Vários builds sobre a mesma partida — os quatro casos do PR-04.3.1.

O QUE ESTES TESTES PROTEGEM. O PR-04.3 usava `DISTINCT ON (match_id)` e, ao
deduplicar, escolhia um build vencedor. Estes testes fixam as quatro respostas
que a escolha arbitrária não sabia dar:

    identidade repetida      um membro, e não dois
    fato EQUIVALENTE         um membro, DUAS linhagens — nenhum vence
    famílias COMPLEMENTARES  a UNIÃO, e não a escolha
    fato CONFLITANTE         NADA é publicado; alguém decide

E o quinto, que é o motivo de os outros quatro importarem: a ordem em que os
builds chegam não muda nada (§37).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from sports_intelligence.domain.corpus.composition import (
    ComposedMatchCorpusFacts,
    compose,
    divergences,
)
from sports_intelligence.domain.corpus.facts import MatchCorpusFacts
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import TeamId
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.teams.models import Team
from tests.support.corpus_fixtures import BUILD_RUN, fatos

OUTRO_BUILD = "77777777-7777-4777-8777-777777777777"
OUTRA_AVALIACAO = "88888888-8888-4888-8888-888888888888"


def _do_outro_build(base: MatchCorpusFacts, **ajustes: object) -> MatchCorpusFacts:
    """A MESMA partida, vista por outra execução de construção."""
    return replace(
        base,
        build_run_id=OUTRO_BUILD,
        quality_assessment_id=OUTRA_AVALIACAO,
        **ajustes,  # type: ignore[arg-type]
    )


class TestCasoA_FatoEquivalente:
    """§24. Dois builds afirmam o MESMO. Um membro, duas linhagens."""

    def test_produz_um_membro_so(self) -> None:
        a = fatos(0)
        b = _do_outro_build(a)
        composta = compose((a, b))
        assert composta.match_id == a.match.id
        assert composta.included_families == a.included_families

    def test_preserva_as_duas_linhagens(self) -> None:
        """§33. NENHUM BUILD VENCE. Guardar um só apagaria metade da resposta
        para «por que esta partida está no corpus» — e a metade apagada era
        tão verdadeira quanto a que ficou."""
        composta = compose((fatos(0), _do_outro_build(fatos(0))))
        assert len(composta.contributions) == 2
        assert {c.build_run_id for c in composta.contributions} == {
            BUILD_RUN,
            OUTRO_BUILD,
        }
        assert {c.quality_assessment_id for c in composta.contributions} == {
            fatos(0).quality_assessment_id,
            OUTRA_AVALIACAO,
        }

    def test_o_membro_carrega_as_duas(self) -> None:
        membro = compose((fatos(0), _do_outro_build(fatos(0)))).as_member()
        assert membro.build_run_ids == (BUILD_RUN, OUTRO_BUILD)

    def test_a_impressao_do_conteudo_ignora_de_quantos_builds_veio(self) -> None:
        """A linhagem não é conteúdo: o mesmo fato produzido por um build ou
        por dois é o mesmo fato (§31)."""
        de_um = compose((fatos(0),))
        de_dois = compose((fatos(0), _do_outro_build(fatos(0))))
        assert de_um.content_fingerprint() == de_dois.content_fingerprint()
        assert de_um.as_member().as_canonical() == de_dois.as_member().as_canonical()


class TestCasoB_FamiliasComplementares:
    """§25, §35. A trouxe ODDS, B trouxe LINEUP. O corpus recebe as duas."""

    @staticmethod
    def _complementares() -> tuple[MatchCorpusFacts, MatchCorpusFacts]:
        com_odds = fatos(0, families=(CoverageFamily.MATCH, CoverageFamily.ODDS))
        com_lineup = _do_outro_build(
            fatos(0),
            included_families=(CoverageFamily.MATCH, CoverageFamily.LINEUP),
            lineups=_uma_escalacao(),
        )
        return com_odds, com_lineup

    def test_a_uniao_das_familias_entra(self) -> None:
        composta = compose(self._complementares())
        assert composta.included_families == (
            CoverageFamily.MATCH,
            CoverageFamily.LINEUP,
            CoverageFamily.ODDS,
        )

    def test_nenhuma_familia_se_perde_na_deduplicacao(self) -> None:
        """O DEFEITO QUE O `DISTINCT ON` CAUSAVA: com ele, a linha escolhida
        levava as famílias dela e as do outro build sumiam em silêncio."""
        composta = compose(self._complementares())
        assert composta.rows_for(CoverageFamily.ODDS)
        assert composta.rows_for(CoverageFamily.LINEUP)
        assert composta.rows_for(CoverageFamily.MATCH)

    def test_a_parcela_de_cada_build_fica_registrada(self) -> None:
        """A união é o que o corpus publica; a parcela é o que cada build
        trouxe. As duas coisas importam e são diferentes."""
        composta = compose(self._complementares())
        por_build = {c.build_run_id: set(c.included_families) for c in composta.contributions}
        assert por_build[BUILD_RUN] == {CoverageFamily.MATCH, CoverageFamily.ODDS}
        assert por_build[OUTRO_BUILD] == {CoverageFamily.MATCH, CoverageFamily.LINEUP}

    def test_a_uniao_muda_a_impressao_do_conteudo(self) -> None:
        so_odds = compose((self._complementares()[0],))
        as_duas = compose(self._complementares())
        assert so_odds.content_fingerprint() != as_duas.content_fingerprint()


class TestCasoC_FatoConflitante:
    """§26. Dois builds afirmam coisas DIFERENTES. Nada é publicado."""

    @staticmethod
    def _conflitantes() -> tuple[MatchCorpusFacts, MatchCorpusFacts]:
        a = fatos(0)
        outro_horario = replace(
            a.match,
            scheduled_kickoff=instant(a.match.scheduled_kickoff + timedelta(hours=3)),
        )
        return a, _do_outro_build(a, match=outro_horario)

    def test_o_conflito_bloqueia_a_composicao(self) -> None:
        with pytest.raises(ConflictError, match="divergência"):
            compose(self._conflitantes())

    def test_nenhum_build_vence_por_ser_mais_recente(self) -> None:
        """A MENSAGEM É A REGRA: escolher um seria o motor decidindo no lugar
        de quem responde pelo dado."""
        with pytest.raises(ConflictError, match="Nenhum build vence"):
            compose(self._conflitantes())

    def test_a_divergencia_diz_ONDE_e_de_QUEM(self) -> None:
        """«kickoff conflitante» manda alguém abrir dois bancos; «A diz isto, B
        diz aquilo» já é a investigação."""
        a, b = self._conflitantes()
        encontradas = divergences(a, b)
        assert len(encontradas) == 1
        assert encontradas[0].aspect == "match"
        assert encontradas[0].left_build_run_id == BUILD_RUN
        assert encontradas[0].right_build_run_id == OUTRO_BUILD
        assert encontradas[0].left_digest != encontradas[0].right_digest

    def test_placar_divergente_tambem_conflita(self) -> None:
        a = fatos(0, home=2, away=1)
        b = _do_outro_build(fatos(0, home=3, away=1))
        with pytest.raises(ConflictError):
            compose((a, b))

    def test_odds_divergentes_conflitam_quando_os_dois_incluem_odds(self) -> None:
        from decimal import Decimal

        a = fatos(0, families=(CoverageFamily.MATCH, CoverageFamily.ODDS))
        alterada = replace(a.odds[0], decimal_odds=Decimal("9.99"))
        b = _do_outro_build(a, odds=(alterada,))
        with pytest.raises(ConflictError, match="odds"):
            compose((a, b))


class TestOSilencioNaoDiscorda:
    """§32. Complementaridade não pode ser lida como conflito."""

    def test_familia_ausente_num_build_nao_gera_divergencia(self) -> None:
        """B não disse nada sobre odds. Silêncio não discorda de afirmação —
        e comparar o silêncio como valor transformaria toda composição
        complementar em conflito."""
        com_odds = fatos(0, families=(CoverageFamily.MATCH, CoverageFamily.ODDS))
        sem_odds = _do_outro_build(fatos(0), included_families=(CoverageFamily.MATCH,), odds=())
        assert divergences(com_odds, sem_odds) == ()

    def test_rotulo_de_identidade_nao_e_fato(self) -> None:
        """PR-04.2.1. `Man City` e `Manchester City` já terminaram no mesmo
        `TeamId`, e é o `TeamId` que a forma factual carrega — a grafia não
        aparece nela, então não há o que divergir."""
        a = fatos(0)
        forma = a.factual_form()
        serializado = str(forma)
        assert str(a.match.home_team_id) in serializado
        assert "Manchester" not in serializado
        assert "Blackmoor" not in serializado


class TestDeterminismoDaComposicao:
    """§37. Inverter a ordem dos builds não muda nada."""

    def test_a_ordem_da_entrada_nao_muda_o_resultado(self) -> None:
        a = fatos(0, families=(CoverageFamily.MATCH, CoverageFamily.ODDS))
        b = _do_outro_build(
            fatos(0),
            included_families=(CoverageFamily.MATCH, CoverageFamily.LINEUP),
            lineups=_uma_escalacao(),
        )
        direta, invertida = compose((a, b)), compose((b, a))
        assert direta.included_families == invertida.included_families
        assert direta.contributions == invertida.contributions
        assert direta.content_fingerprint() == invertida.content_fingerprint()
        assert direta.as_member().as_canonical() == invertida.as_member().as_canonical()

    def test_a_ordem_da_entrada_nao_muda_a_recusa(self) -> None:
        a, b = TestCasoC_FatoConflitante._conflitantes()
        with pytest.raises(ConflictError):
            compose((a, b))
        with pytest.raises(ConflictError):
            compose((b, a))


class TestGuardasDaComposicao:
    def test_composicao_vazia_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="sem contribuição"):
            compose(())

    def test_composicao_sobre_partidas_diferentes_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="partidas diferentes"):
            compose((fatos(0), fatos(1)))

    def test_o_membro_exige_pelo_menos_um_contribuinte(self) -> None:
        composta = ComposedMatchCorpusFacts.of(fatos(0))
        with pytest.raises(ValidationError, match="contribuinte"):
            replace(composta, contributions=())

    def test_a_uniao_precisa_bater_com_os_fatos_carregados(self) -> None:
        """Se a união declarasse mais do que os fatos carregam, o Parquet
        escreveria uma coisa e o manifesto prometeria outra."""
        composta = ComposedMatchCorpusFacts.of(fatos(0))
        with pytest.raises(ValidationError, match="a união declara"):
            replace(
                composta,
                included_families=(CoverageFamily.MATCH, CoverageFamily.ODDS),
            )


def _uma_escalacao() -> tuple[object, ...]:
    """Uma escalação mínima e válida para a partida do cenário."""
    from sports_intelligence.domain.matches.lineup import (
        Lineup,
        LineupEntry,
        LineupStatus,
    )
    from sports_intelligence.domain.shared.identity import PlayerId

    base = fatos(0)
    return (
        Lineup(
            match_id=base.match.id,
            team_id=base.match.home_team_id,
            entries=tuple(
                LineupEntry(
                    player_id=PlayerId.derive("pr0431", f"jogador-{i}"),
                    status=LineupStatus.STARTER,
                    shirt_number=i + 1,
                )
                for i in range(11)
            ),
        ),
    )


def test_o_time_do_cenario_continua_o_mesmo() -> None:
    """Guarda de sanidade sobre o fixture compartilhado."""
    assert isinstance(Team(id=TeamId.derive("x", "y"), canonical_name="X", country="GB"), Team)
