"""Time: identidade futebolística canônica, e nada além disso.

O QUE NÃO ESTÁ AQUI, E POR QUÊ.

**Aliases.** `Manchester City`, `Man City`, `Manchester City FC` e `MCI` são
grafias que provedores usam. Guardá-las na entidade faria a identidade
depender de quantas fontes já foram vistas — e um clube "mudaria" ao ganhar um
apelido novo. Elas pertencem ao Identity Resolution layer, num PR futuro.

**Ids de provedor.** Mesmo motivo, mais forte: um `ProviderRef` dentro do time
faria o domínio conhecer provedores.

**IDENTIDADE NÃO É DERIVADA DO NOME.** Este é o ponto mais importante do
módulo. `Team.register` SORTEIA o id; não existe `Team.derive("man city")`.
Derivar do nome faria três grafias virarem três clubes, cada um com um terço
do histórico — e o número continuaria fechando.

A ponte entre "o texto que a fonte mandou" e "qual clube é este" é resolução
de identidade: uma etapa explícita, com regras próprias, capaz de falhar e de
pedir revisão humana. Nunca um `uuid5` sobre um nome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self, final

from sports_intelligence.domain.shared.identity import TeamId


@final
@dataclass(frozen=True, slots=True)
class Team:
    """Um clube. Imutável; mudanças de estado passam por métodos explícitos."""

    id: TeamId
    canonical_name: str
    country: str
    short_name: str | None = None
    active: bool = True

    def __post_init__(self) -> None:
        if not self.canonical_name.strip():
            raise ValueError("time sem canonical_name")
        # ISO-3166 alpha-2. Curto e verificável; um país por extenso admitiria
        # "Brasil", "Brazil" e "BRA" para a mesma coisa.
        if len(self.country) != 2 or not self.country.isalpha():
            raise ValueError(
                f"country {self.country!r} inválido: use ISO-3166 alpha-2, por exemplo 'BR'"
            )
        if self.country != self.country.upper():
            raise ValueError(f"country {self.country!r} deve ser maiúsculo")
        if self.short_name is not None and not self.short_name.strip():
            raise ValueError("short_name vazio: omita em vez de mandar vazio")

    @classmethod
    def register(
        cls,
        *,
        canonical_name: str,
        country: str,
        short_name: str | None = None,
    ) -> Self:
        """Um clube novo, com id SORTEADO.

        Sorteado e não derivado do nome — ver o docstring do módulo. É a
        diferença entre "este clube é aquele que já conhecemos" (resolução) e
        "este texto vira uma identidade" (o defeito).
        """
        return cls(
            id=TeamId.new(),
            canonical_name=canonical_name.strip(),
            country=country,
            short_name=short_name.strip() if short_name else None,
        )

    def deactivate(self) -> Self:
        """Clube que deixou de existir ou de competir.

        Desativa, não apaga: o histórico dele continua sendo histórico, e
        remover a entidade orfanaria toda partida que ele jogou.
        """
        return type(self)(
            id=self.id,
            canonical_name=self.canonical_name,
            country=self.country,
            short_name=self.short_name,
            active=False,
        )

    def rename(self, canonical_name: str) -> Self:
        """Clube renomeado — e o id NÃO muda.

        É o teste vivo de que a identidade não depende do nome: o Red Bull
        Bragantino continua sendo o mesmo clube do Bragantino, com o mesmo
        histórico.
        """
        return type(self)(
            id=self.id,
            canonical_name=canonical_name.strip(),
            country=self.country,
            short_name=self.short_name,
            active=self.active,
        )
