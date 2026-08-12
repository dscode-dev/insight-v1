"""Os três processos sobem e respondem. É tudo o que o PR-00 promete.

SMOKE E NÃO INTEGRAÇÃO DE VERDADE: não há infraestrutura para integrar. O que
estes testes provam é que a montagem funciona — que `create_app` produz uma
aplicação que atende, que as duas APIs são de fato duas, e que a CLI roda.
"""

from __future__ import annotations

import os
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

pytestmark = pytest.mark.smoke


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configuração mínima para o processo subir.

    `SECURITY_INTERNAL_TOKEN` não tem default por decisão (nenhum segredo tem),
    então o teste o fornece — que é exatamente o que produção também faz.
    """
    monkeypatch.setenv("ENGINE_ENVIRONMENT", "local")
    monkeypatch.setenv("ENGINE_SECURITY_INTERNAL_TOKEN", "token-de-teste")


def _cliente(modulo: ModuleType) -> TestClient:
    from importlib import reload

    return TestClient(reload(modulo).app)


class TestControlApi:
    def test_liveness_nao_depende_de_nada(self) -> None:
        """Um liveness que falha porque o banco caiu faz o orquestrador
        reiniciar um processo saudável — e reiniciar não conserta banco."""
        import apps.control_api.main as modulo

        resposta = _cliente(modulo).get("/health/live")
        assert resposta.status_code == 200
        assert resposta.json()["status"] == "ok"

    def test_readiness_reporta_dependencias(self) -> None:
        import apps.control_api.main as modulo

        resposta = _cliente(modulo).get("/health/ready")
        assert resposta.status_code == 200
        # Sem dependência externa no PR-00: a lista sai vazia e diz isso.
        assert resposta.json()["checks"] == {}

    def test_version_tem_contrato_tipado(self) -> None:
        import apps.control_api.main as modulo

        corpo = _cliente(modulo).get("/version").json()
        assert set(corpo) == {"service", "version", "environment"}


class TestQueryApi:
    def test_sobe_e_responde(self) -> None:
        import apps.query_api.main as modulo

        assert _cliente(modulo).get("/health/live").status_code == 200

    def test_e_uma_aplicacao_diferente_da_control(self) -> None:
        """A separação de planos é de PROCESSO, não só de rota (ADR-0002)."""
        import apps.control_api.main as control
        import apps.query_api.main as query

        assert control.app is not query.app
        assert control.app.title != query.app.title


class TestCorrelacao:
    def test_o_id_do_cliente_e_devolvido(self) -> None:
        """É o que amarra o rastro através dos serviços do Insight."""
        import apps.query_api.main as modulo

        resposta = _cliente(modulo).get(
            "/version", headers={"X-Correlation-Id": "abc-123"}
        )
        assert resposta.headers["X-Correlation-Id"] == "abc-123"

    def test_sem_id_do_cliente_um_e_gerado(self) -> None:
        import apps.query_api.main as modulo

        resposta = _cliente(modulo).get("/version")
        assert resposta.headers.get("X-Correlation-Id")


class TestCli:
    def test_version_roda(self) -> None:
        from apps.cli.main import app

        resultado = CliRunner().invoke(app, ["version"])
        assert resultado.exit_code == 0
        assert "sports-intelligence-engine" in resultado.stdout

    def test_doctor_relata_o_que_esta_configurado(self) -> None:
        from apps.cli.main import app

        resultado = CliRunner().invoke(app, ["doctor"])
        assert resultado.exit_code == 0
        assert "postgres" in resultado.stdout
        assert "não configurado" in resultado.stdout

    def test_doctor_falha_quando_falta_o_que_e_exigido(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem o token interno, o processo não deveria subir — e o doctor
        precisa dizer isso antes de alguém descobrir em produção."""
        monkeypatch.delenv("ENGINE_SECURITY_INTERNAL_TOKEN", raising=False)
        from apps.cli.main import app

        resultado = CliRunner().invoke(app, ["doctor"])
        assert resultado.exit_code == 1
        assert "exigida" in resultado.stdout

    def test_doctor_nao_morre_sem_infraestrutura(self) -> None:
        """Um doctor que morre porque não há Postgres é inútil justamente
        quando é mais necessário: antes de haver Postgres."""
        assert "ENGINE_POSTGRES_HOST" not in os.environ
        from apps.cli.main import app

        assert CliRunner().invoke(app, ["doctor"]).exit_code == 0
