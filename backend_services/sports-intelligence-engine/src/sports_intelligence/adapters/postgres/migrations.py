"""O aplicador de migrations — arquivos `.sql` numerados, e nada mais.

POR QUE NÃO ALEMBIC. Ele traria autogeração a partir de modelos SQLAlchemy — e
não há modelos SQLAlchemy, porque não há ORM (ADR-0003). O que sobraria dele
seria o rastreamento de versão e o comando de upgrade, que são cem linhas.
Cem linhas legíveis valem mais que uma dependência cuja principal função a
base não usa.

O CHECKSUM É A PARTE QUE IMPORTA. Cada migration aplicada guarda o SHA-256 do
arquivo. Se o arquivo mudar depois de aplicado, o aplicador RECUSA em vez de
seguir em frente — porque nesse ponto o banco e o repositório discordam sobre
o que existe, e a discordância é silenciosa: o schema real tem a versão antiga,
o código espera a nova, e a falha aparece na primeira consulta que usa a coluna
que ninguém criou.

TRANSACIONAL POR MIGRATION. O PostgreSQL suporta DDL transacional, então uma
migration que falha no meio não deixa metade das tabelas criadas. É a
diferença entre "rode de novo" e "descubra o que ficou e conserte à mão".

SEM `down`. Rollback automático de migration é uma promessa que quase nunca se
cumpre: reverter um `DROP COLUMN` exige o dado que ele apagou. O caminho de
volta é uma migration nova, escrita sabendo o que precisa ser preservado.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.shared.errors import DependencyError

#: Onde os arquivos moram, a partir da raiz do serviço.
MIGRATIONS_DIR: Final[Path] = Path(__file__).resolve().parents[3].parent / "migrations"

_TABELA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    checksum    text NOT NULL
)
"""


@final
@dataclass(frozen=True, slots=True)
class Migration:
    """Um arquivo de migration, com a impressão do que ele contém."""

    version: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

    def __str__(self) -> str:
        return f"{self.version} ({self.path.name})"


@final
@dataclass(frozen=True, slots=True)
class MigrationStatus:
    version: str
    applied: bool
    applied_at: str | None
    checksum_matches: bool


def discover(directory: Path | None = None) -> tuple[Migration, ...]:
    """Os arquivos `NNNN_nome.sql`, em ordem numérica.

    ORDEM PELO NOME DO ARQUIVO, e é por isso que o prefixo é numérico e com
    zeros à esquerda: `10_x.sql` ordenado como texto vem antes de `9_x.sql`, e
    a migration 10 rodaria antes da 9 sem que nada avisasse.
    """
    base = directory or MIGRATIONS_DIR
    if not base.is_dir():
        raise DependencyError(
            f"diretório de migrations não encontrado: {base}",
            context={"path": str(base)},
        )
    arquivos = sorted(base.glob("*.sql"))
    migrations: list[Migration] = []
    for arquivo in arquivos:
        versao = arquivo.stem.split("_", 1)[0]
        if not versao.isdigit():
            raise DependencyError(
                f"migration {arquivo.name!r} não começa com um número — "
                "a ordem de aplicação viria do alfabeto, e ela precisa vir da sequência"
            )
        migrations.append(
            Migration(version=versao, path=arquivo, sql=arquivo.read_text(encoding="utf-8"))
        )
    vistas = [m.version for m in migrations]
    duplicadas = {v for v in vistas if vistas.count(v) > 1}
    if duplicadas:
        raise DependencyError(f"versões de migration repetidas: {sorted(duplicadas)}")
    return tuple(migrations)


async def status(database: Database, directory: Path | None = None) -> tuple[MigrationStatus, ...]:
    """O que está aplicado, o que falta, e o que mudou depois de aplicado."""
    migrations = discover(directory)
    async with database.acquire() as conexao:
        await conexao.execute(_TABELA)
        linhas = await conexao.fetch("SELECT version, checksum, applied_at FROM schema_migrations")
    aplicadas = {linha["version"]: (linha["checksum"], linha["applied_at"]) for linha in linhas}
    return tuple(
        MigrationStatus(
            version=m.version,
            applied=m.version in aplicadas,
            applied_at=(aplicadas[m.version][1].isoformat() if m.version in aplicadas else None),
            checksum_matches=(
                aplicadas[m.version][0] == m.checksum if m.version in aplicadas else True
            ),
        )
        for m in migrations
    )


async def migrate(database: Database, directory: Path | None = None) -> tuple[str, ...]:
    """Aplica o que falta, em ordem. Devolve as versões aplicadas agora.

    RECUSA ANTES DE APLICAR QUALQUER COISA quando encontra uma migration já
    aplicada cujo arquivo mudou. Aplicar as seguintes por cima de um schema
    que discorda do repositório é como um banco fica num estado que nenhuma
    sequência de migrations reproduz.
    """
    migrations = discover(directory)
    aplicadas_agora: list[str] = []

    async with database.acquire() as conexao:
        await conexao.execute(_TABELA)
        registradas = {
            linha["version"]: linha["checksum"]
            for linha in await conexao.fetch("SELECT version, checksum FROM schema_migrations")
        }

        divergentes = [
            m
            for m in migrations
            if m.version in registradas and registradas[m.version] != m.checksum
        ]
        if divergentes:
            nomes = ", ".join(str(m) for m in divergentes)
            raise DependencyError(
                f"migration já aplicada foi modificada: {nomes}. O banco tem o schema "
                "antigo e o repositório descreve outro — a divergência é silenciosa até "
                "a primeira consulta usar o que não foi criado. Escreva uma migration "
                "nova em vez de editar uma aplicada.",
                context={"versions": [m.version for m in divergentes]},
            )

        for migration in migrations:
            if migration.version in registradas:
                continue
            # UMA TRANSAÇÃO POR MIGRATION. DDL é transacional no PostgreSQL,
            # então uma que falha no meio não deixa metade das tabelas de pé.
            async with conexao.transaction():
                await conexao.execute(migration.sql)
                await conexao.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
                    migration.version,
                    migration.checksum,
                )
            aplicadas_agora.append(migration.version)

    return tuple(aplicadas_agora)


async def ensure_schema(database: Database, directory: Path | None = None) -> None:
    """Aplica o que falta e não diz nada quando não há nada a fazer.

    Para os testes de integração, onde o schema precisa existir e o ruído de
    "0 migrations aplicadas" a cada teste não ajuda ninguém.
    """
    await migrate(database, directory)
