"""Os limites do corpus com eventos (PR-04.4.2 §39 ao §42, §96 ao §98).

O QUE ELES GUARDAM, e por que cada um importa agora mais do que antes:

    nada do PR-05          o corpus passou a carregar eventos, que são a
                           matéria-prima de xG por ação e de Tactical Graph.
                           A tentação de «já calcular na publicação» nasce
                           exatamente aqui

    publicar é LER         publicação não reconcilia evento, não reavalia
                           qualidade e não resolve jogador. Qualquer um dos
                           três faria o corpus MUDAR por ter sido publicado

    a autoridade é o       a publicação lê `CanonicalMatchEvent`, e nunca o
    registro canônico      registro de origem. Republicar a partir do bruto
                           seria reconstruir fatos — com resultado que pode
                           divergir do que já está gravado

    a seta tem UM sentido  o corpus não importa código de feature. O PR-05 vai
                           LER o corpus; o corpus não vai saber que ele existe
"""

from __future__ import annotations

import pytest

from tests.support.ast_checks import (
    INFRA_EXTERNA,
    external_violations,
    files_in,
    internal_violations,
)

pytestmark = pytest.mark.architecture

#: Os pacotes do corpus, incluindo o que este PR mexeu.
PACOTES_DO_CORPUS = ("domain/corpus", "historical/corpus")

#: O que NENHUM deles pode conhecer (§96).
PACOTES_FUTUROS = (
    "sports_intelligence.features",
    "sports_intelligence.engines",
    "sports_intelligence.ingestion.live",
    "sports_intelligence.adapters.pgvector",
    "sports_intelligence.adapters.clickhouse",
    "sports_intelligence.adapters.redis",
    "sports_intelligence.ports.vector_store",
    "sports_intelligence.ports.analytics_store",
    "sports_intelligence.ports.cache",
)


class TestOsLimitesDoCorpus:
    @pytest.mark.parametrize("pacote", list(PACOTES_DO_CORPUS))
    def test_nao_importa_o_futuro(self, pacote: str) -> None:
        """§96. Nem feature, nem engine, nem armazenamento de leitura rápida."""
        violacoes = internal_violations(files_in(pacote), PACOTES_FUTUROS)
        assert not violacoes, str(violacoes)

    def test_o_dominio_do_corpus_nao_importa_infraestrutura(self) -> None:
        violacoes = external_violations(files_in("domain/corpus"), INFRA_EXTERNA)
        assert not violacoes, str(violacoes)

    def test_o_corpus_conhece_evento_e_nao_o_contrario(self) -> None:
        """A SETA TEM UM SENTIDO SÓ, e ele é este: o corpus PUBLICA eventos, e
        por isso importa o domínio deles. O caminho inverso — evento importando
        corpus — significaria canonicalização sabendo de publicação, que é a
        confusão que o PR-04.4.1 §80 existiu para evitar.
        """
        do_corpus = internal_violations(
            files_in("domain/events", "historical/events"),
            ("sports_intelligence.domain.corpus", "sports_intelligence.historical.corpus"),
        )
        assert not do_corpus, str(do_corpus)


class TestPublicarELer:
    """§39, §40, §41. A publicação não refaz nada do que já foi decidido."""

    def test_a_publicacao_nao_reconcilia_evento(self) -> None:
        """§39. Resolução entre provedores é do PR-04.4.1 — e lá ela foi
        DECLARADA fora de escopo. Um reconciliador aqui decidiria, na hora de
        publicar, que dois eventos são o mesmo.
        """
        proibidos = {
            "EventReconciler",
            "reconcile_events",
            "merge_events",
            "same_event_probability",
        }
        encontrados: list[str] = []
        for arquivo in files_in("domain/corpus", "historical/corpus"):
            texto = arquivo.read_text(encoding="utf-8")
            encontrados.extend(f"{arquivo.name}: {n}" for n in proibidos if n in texto)
        assert not encontrados, "\n".join(encontrados)

    def test_a_publicacao_nao_reavalia_qualidade_nem_resolve_identidade(self) -> None:
        """§40, §41. Ela CONSOME vereditos e traduções já persistidos.

        A guarda é sobre os EXECUTORES, e não sobre os tipos: o acumulador lê
        `MatchQualityRecord` e o manifesto descreve `LicenseFootprint` — os dois
        são resultado. O que não pode aparecer é quem PRODUZ esse resultado.
        """
        proibidos = (
            "sports_intelligence.historical.quality.assessor",
            "sports_intelligence.ingestion.resolution",
            "sports_intelligence.ingestion.fusion",
            "sports_intelligence.historical.events.builder",
            "sports_intelligence.historical.events.eligibility",
        )
        violacoes = internal_violations(
            files_in("domain/corpus", "historical/corpus"), proibidos
        )
        assert not violacoes, str(violacoes)

    def test_a_composicao_le_o_registro_canonico_e_nao_o_bruto(self) -> None:
        """§42. `SourceRecord` e `HistoricalEventRecord` são a ENTRADA da
        canonicalização; o corpus publica a SAÍDA dela.
        """
        proibidos = (
            "sports_intelligence.domain.sources.records",
            "sports_intelligence.domain.events.records",
            "sports_intelligence.ingestion.historical.reader",
        )
        violacoes = internal_violations(
            files_in("domain/corpus", "historical/corpus"), proibidos
        )
        assert not violacoes, str(violacoes)


class TestAFronteiraComOPR05:
    """§97, §98. A entrada autorizada do PR-05 é a versão publicada."""

    def test_o_corpus_nao_importa_feature(self) -> None:
        """Escrito à parte do `test_nao_importa_o_futuro` porque a afirmação é
        diferente: aquele diz «ainda não existe», este diz «mesmo quando
        existir, a seta continua apontando do PR-05 para cá»."""
        violacoes = internal_violations(
            files_in(*PACOTES_DO_CORPUS, "application/use_cases"),
            ("sports_intelligence.features",),
        )
        assert not violacoes, str(violacoes)

    def test_a_versao_publicada_e_legivel_e_a_em_construcao_nao(self) -> None:
        """A entrada do PR-05 é uma versão `READY` ou `SUPERSEDED` — nunca uma
        em `BUILDING`, que pode estar com pertinência pela metade."""
        from sports_intelligence.domain.corpus.versions import DatasetVersionStatus

        legiveis = {
            estado for estado in DatasetVersionStatus if estado.is_readable_corpus
        }
        assert legiveis == {
            DatasetVersionStatus.READY,
            DatasetVersionStatus.SUPERSEDED,
        }

    def test_a_pertinencia_de_evento_existe_e_e_por_versao(self) -> None:
        """§98 em forma executável: perguntar «quais eventos esta versão
        publica» precisa ter resposta SEM ir ao registro global."""
        from sports_intelligence.ports.repositories.corpus import (
            CorpusMembershipRepositoryPort,
        )

        assert hasattr(CorpusMembershipRepositoryPort, "append_event_members")
        assert hasattr(CorpusMembershipRepositoryPort, "count_event_members")
        assert hasattr(CorpusMembershipRepositoryPort, "event_members_of_match")
