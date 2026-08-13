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

    def dsn(self) -> str:
        """A URL de conexão, com a senha revelada.

        UM MÉTODO E NÃO UMA PROPRIEDADE, de propósito. Propriedade convida a
        aparecer em f-string de log e em `repr` de debug, e o que sairia dali
        é a senha em claro. Uma chamada explícita é visível na revisão.
        """
        return (
            f"postgresql://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.database}"
        )


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


class ObjectStoreBackend(StrEnum):
    """Qual implementação de object store este processo usa.

    `FILESYSTEM` EXISTE E É RESTRITO. Ele torna o teste unitário e o
    desenvolvimento sem Docker possíveis, e por isso vale. O que ele não pode
    é chegar em produção por descuido: um "object store" que é uma pasta local
    perde tudo quando o contêiner é recriado, e a perda é do ARQUIVO BRUTO —
    a única camada que não se reconstrói. `ObjectStoreSettings` recusa a
    combinação em ambiente produtivo.
    """

    S3 = "s3"
    FILESYSTEM = "filesystem"


class ObjectStoreSettings(_Base):
    """S3 ou MinIO: o bruto imutável e os arquivos reconstruíveis."""

    model_config = SettingsConfigDict(
        **{**_Base.model_config, "env_prefix": f"{ENV_PREFIX}OBJECT_STORE_"}
    )

    backend: ObjectStoreBackend = ObjectStoreBackend.S3
    endpoint_url: str | None = None
    region: str = "us-east-1"
    bucket: str
    access_key_id: SecretStr
    secret_access_key: SecretStr
    #: Raiz do backend de arquivos. Só usada quando `backend=filesystem`.
    root_path: str | None = None
    #: TLS. `False` é o normal para MinIO local e nunca deveria ser o de um
    #: endpoint remoto — a checagem de ambiente abaixo cobra isso.
    secure: bool = True

    @field_validator("bucket")
    @classmethod
    def _bucket_valido(cls, valor: str) -> str:
        # As regras de nome de bucket do S3, cobradas aqui: descobri-las na
        # primeira gravação significa descobri-las em produção.
        texto = valor.strip().lower()
        if not 3 <= len(texto) <= 63 or not texto.replace("-", "").replace(".", "").isalnum():
            raise ValueError(
                f"bucket {valor!r} inválido: 3 a 63 caracteres, minúsculas, dígitos, "
                "hífen e ponto"
            )
        return texto


class IntakeSettings(_Base):
    """Os limites da ingestão histórica manual.

    ELES SÃO CONFIGURAÇÃO E NÃO CONSTANTE DE CÓDIGO por um motivo operacional:
    o limite certo depende da máquina e do disco de quem opera, e um número
    fixo no código obriga um deploy para ajustá-lo — o que, na prática,
    significa que ninguém ajusta e alguém contorna.

    Todos têm default, e nenhum é segredo: são tetos de proteção, não
    credenciais.
    """

    model_config = SettingsConfigDict(
        **{**_Base.model_config, "env_prefix": f"{ENV_PREFIX}INTAKE_"}
    )

    #: 2 GiB. Cobre com folga um dump de temporada em Parquet e recusa o
    #: acidente — o backup de um banco inteiro enviado por engano.
    max_file_size_bytes: int = Field(default=2 * 1024 * 1024 * 1024, ge=1)
    max_files_per_dataset: int = Field(default=200, ge=1)
    #: Teto de linhas por arquivo. Existe para o caso patológico: um CSV com
    #: 500 milhões de linhas não é um dataset de futebol, é um engano.
    max_rows_per_file: int = Field(default=50_000_000, ge=1)
    #: Quantas issues são GUARDADAS. O total continua sendo contado.
    max_validation_issues: int = Field(default=200, ge=1)
    #: Acima disto o buffer de upload vai para disco em vez de RAM.
    upload_spool_threshold_bytes: int = Field(default=8 * 1024 * 1024, ge=0)


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


def assert_object_store_is_durable(
    store: ObjectStoreSettings, environment: Environment
) -> None:
    """Recusa um arquivo bruto que não sobrevive ao contêiner.

    A CHECAGEM MORA NUMA FUNÇÃO E NÃO NUM VALIDADOR porque ela cruza dois
    grupos de settings — `ObjectStoreSettings` não conhece o ambiente, e
    fazê-la conhecer amarraria os dois. Ela é chamada na composição de cada
    processo, que é onde os dois já estão em mãos.

    O QUE ELA PROTEGE: o arquivo bruto é a ÚNICA camada que não se reconstrói
    (ADR-0004). Um backend de sistema de arquivos dentro de um contêiner é
    uma pasta que some no próximo deploy, e a perda seria de evidência
    primária — não de cache.
    """
    if not environment.is_production_like:
        return
    if store.backend is ObjectStoreBackend.FILESYSTEM:
        raise ValueError(
            f"object store 'filesystem' em ambiente {environment.value}: o arquivo bruto "
            "é a única camada que não se reconstrói, e uma pasta local não sobrevive "
            "ao contêiner. Configure S3 ou MinIO."
        )
    if store.endpoint_url and not store.secure:
        raise ValueError(
            f"object store sem TLS em ambiente {environment.value}: as credenciais e o "
            "conteúdo trafegariam em claro"
        )
