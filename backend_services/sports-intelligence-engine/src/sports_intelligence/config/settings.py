"""Configuração tipada, e o que decide quando cada peça é exigida.

DUAS REGRAS GOVERNAM ESTE MÓDULO.

A PRIMEIRA: nenhum segredo tem default. Uma senha com valor padrão sobrevive
ao desenvolvimento, atravessa o staging e chega em produção sem que ninguém
tenha decidido usá-la — e o dia em que alguém percebe é o dia em que já foi
usada. `SecretStr` sem default falha na hora de construir, com o nome da
variável que falta.

A SEGUNDA: as configurações de infraestrutura NÃO são construídas junto com a
aplicação. `AppSettings` sobe sem Postgres, sem ClickHouse e sem Redis, porque
o PR-00 não fala com nenhum dos três. Cada grupo é construído por quem precisa
dele, na hora em que precisa, e `engine doctor` tenta construir todos para
reportar o que está configurado e o que não está — sem exigir que a
infraestrutura inteira exista para o processo iniciar.

O caminho oposto é comum e caro: um `Settings` monolítico que valida tudo no
import faz o serviço morrer no boot por causa de uma dependência que aquele
processo nunca usaria.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Prefixo único para toda variável de ambiente do motor. Sem ele, `HOST` e
#: `PORT` colidem com o que quer que mais esteja rodando no mesmo contêiner.
ENV_PREFIX: Final = "ENGINE_"


class Environment(StrEnum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production_like(self) -> bool:
        """Onde um default frouxo deixa de ser conveniência e vira risco."""
        return self in (Environment.STAGING, Environment.PRODUCTION)


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class _Base(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )


class AppSettings(_Base):
    """O que todo processo precisa saber sobre si mesmo.

    Nada aqui exige rede. Um processo que não consegue construir isto está
    mal configurado de verdade, não apenas sem uma dependência opcional.
    """

    environment: Environment = Environment.LOCAL
    service_name: str = "sports-intelligence-engine"
    version: str = "0.1.0"
    log_level: LogLevel = LogLevel.INFO

    control_api_host: str = "127.0.0.1"
    control_api_port: int = Field(default=8080, ge=1, le=65535)
    query_api_host: str = "127.0.0.1"
    query_api_port: int = Field(default=8081, ge=1, le=65535)

    @field_validator("service_name")
    @classmethod
    def _nome_nao_vazio(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("service_name não pode ser vazio: ele identifica o processo nos logs")
        return valor.strip()


class PostgresSettings(_Base):
    """Metadados, entidades e estado transacional. Ver ADR-0004."""

    model_config = SettingsConfigDict(
        **{**_Base.model_config, "env_prefix": f"{ENV_PREFIX}POSTGRES_"}
    )

    host: str
    port: int = Field(default=5432, ge=1, le=65535)
    database: str
    user: str
    password: SecretStr
    pool_min_size: int = Field(default=1, ge=0)
    pool_max_size: int = Field(default=10, ge=1)

    @field_validator("pool_max_size")
    @classmethod
    def _pool_coerente(cls, valor: int, info: object) -> int:
        # `pool_max_size` menor que o mínimo produz um pool que nunca serve
        # ninguém, e o sintoma é timeout — nunca "configuração inválida".
        minimo = getattr(info, "data", {}).get("pool_min_size", 0)
        if valor < minimo:
            raise ValueError(f"pool_max_size ({valor}) é menor que pool_min_size ({minimo})")
        return valor


class ClickHouseSettings(_Base):
    """Eventos, snapshots e séries temporais de alto volume. Ver ADR-0004."""

    model_config = SettingsConfigDict(
        **{**_Base.model_config, "env_prefix": f"{ENV_PREFIX}CLICKHOUSE_"}
    )

    host: str
    port: int = Field(default=8123, ge=1, le=65535)
    database: str
    user: str
    password: SecretStr


class RedisSettings(_Base):
    """Estado quente, janelas móveis, Streams e a inteligência materializada."""

    model_config = SettingsConfigDict(
        **{**_Base.model_config, "env_prefix": f"{ENV_PREFIX}REDIS_"}
    )

    host: str
    port: int = Field(default=6379, ge=1, le=65535)
    database: int = Field(default=0, ge=0)
    password: SecretStr | None = None


class ObjectStoreSettings(_Base):
    """S3 ou MinIO: o bruto imutável e os arquivos reconstruíveis."""

    model_config = SettingsConfigDict(
        **{**_Base.model_config, "env_prefix": f"{ENV_PREFIX}OBJECT_STORE_"}
    )

    endpoint_url: str | None = None
    region: str = "us-east-1"
    bucket: str
    access_key_id: SecretStr
    secret_access_key: SecretStr


class ObservabilitySettings(_Base):
    model_config = SettingsConfigDict(
        **{**_Base.model_config, "env_prefix": f"{ENV_PREFIX}OTEL_"}
    )

    #: Sem endpoint, o motor não exporta traços e diz isso no `doctor` — em
    #: vez de tentar exportar para lugar nenhum e engolir o erro por tick.
    exporter_endpoint: str | None = None
    traces_enabled: bool = False
    metrics_enabled: bool = True


class SecuritySettings(_Base):
    """Segredos de fronteira. Nenhum default, em nenhum ambiente."""

    model_config = SettingsConfigDict(
        **{**_Base.model_config, "env_prefix": f"{ENV_PREFIX}SECURITY_"}
    )

    #: Autentica chamadas entre serviços do Insight. Sem default: um token
    #: padrão é um token público.
    internal_token: SecretStr
    #: Origens permitidas no CORS. Vazio = nenhuma, que é o certo para uma
    #: API interna; `*` só é aceito fora de produção.
    allowed_origins: tuple[str, ...] = ()

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _lista_de_origens(cls, valor: object) -> object:
        if isinstance(valor, str):
            return tuple(p.strip() for p in valor.split(",") if p.strip())
        return valor
