"""O catálogo de definições de feature — declarativo, em memória, reproduzível.

POR QUE NÃO É UMA TABELA (§107, §121). Um catálogo em PostgreSQL responderia
«quais features existem» de um jeito que o código-fonte já responde, e
acrescentaria um estado que pode divergir do código: a linha diz janela de 5
minutos e a definição no código diz 10. O registro aqui é o próprio código —
reproduzível por construção, versionado pelo git, e sem uma segunda verdade.

O QUE ELE RECUSA (§108), e cada recusa é um defeito que sairia caro:

    chave/versão repetidas         duas definições disputando o mesmo nome
    identidade repetida            a mesma feature registrada duas vezes por
                                   caminhos diferentes
    mesma chave/versão, impressão  a pior de todas: alguém mudou a semântica e
    diferente                      manteve o nome. O número muda e o histórico
                                   não sabe
    dependência inexistente        feature que aponta para o vazio
    ciclo                          `A → B → A`

ELE NÃO TEM IMPRESSÃO PRÓPRIA (§109). A identidade de um CONJUNTO de features é
o `FeatureSpace`; um hash do registro seria um terceiro número para a mesma
pergunta, e o terceiro é sempre o que ninguém atualiza.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Self, final

from sports_intelligence.domain.features.definitions import FeatureDefinition
from sports_intelligence.domain.shared.errors import ValidationError


@final
@dataclass(frozen=True, slots=True)
class FeatureDefinitionRegistry:
    """As definições conhecidas, indexadas por `(chave, versão)`.

    ELE É IMUTÁVEL DEPOIS DE CONSTRUÍDO. Um registro que aceitasse registro
    tardio permitiria que a mesma execução visse conjuntos diferentes em
    momentos diferentes — e o espaço montado no início deixaria de descrever o
    que o cálculo do fim usou.
    """

    _por_identidade: dict[tuple[str, str], FeatureDefinition] = field(default_factory=dict)

    @classmethod
    def of(cls, definitions: Iterable[FeatureDefinition]) -> Self:
        registro: dict[tuple[str, str], FeatureDefinition] = {}
        for definicao in definitions:
            chave = (definicao.key, str(definicao.version))
            anterior = registro.get(chave)
            if anterior is not None:
                if anterior.fingerprint == definicao.fingerprint:
                    raise ValidationError(
                        f"a feature {definicao.identity} foi registrada duas vezes",
                        context={"key": definicao.key, "version": str(definicao.version)},
                    )
                # A PIOR DAS DUAS (§108). Mesmo nome, mesma versão, conteúdo
                # diferente: quem comparar dois números destes vai achar que
                # comparou a mesma feature.
                raise ValidationError(
                    f"duas definições de {definicao.key}@{definicao.version} com "
                    f"conteúdos diferentes ({anterior.fingerprint[:12]} contra "
                    f"{definicao.fingerprint[:12]}). Mudança de semântica exige "
                    "versão nova — manter o nome faria o histórico comparar coisas "
                    "diferentes achando que são a mesma (§33)",
                    context={
                        "key": definicao.key,
                        "version": str(definicao.version),
                        "left": anterior.fingerprint,
                        "right": definicao.fingerprint,
                    },
                )
            registro[chave] = definicao

        conhecidas = {k for k, _ in registro}
        for definicao in registro.values():
            faltando = [d for d in definicao.depends_on_features if d not in conhecidas]
            if faltando:
                raise ValidationError(
                    f"a feature {definicao.key} depende de {sorted(faltando)}, que não "
                    "está no registro",
                    context={"key": definicao.key, "missing": ", ".join(sorted(faltando))},
                )
        _recusar_ciclo(tuple(registro.values()))
        return cls(_por_identidade=registro)

    def get(self, key: str, version: str) -> FeatureDefinition:
        definicao = self._por_identidade.get((key, version))
        if definicao is None:
            raise ValidationError(
                f"feature {key}@{version} não registrada",
                context={"key": key, "version": version},
            )
        return definicao

    def latest(self, key: str) -> FeatureDefinition:
        """A versão mais alta daquela chave.

        «MAIS ALTA» É POR VERSÃO E NÃO POR ORDEM DE REGISTRO: registrar a 1.0
        depois da 2.0 não faz a 1.0 ser a atual.
        """
        candidatas = [d for (k, _), d in self._por_identidade.items() if k == key]
        if not candidatas:
            raise ValidationError(f"nenhuma versão registrada de {key!r}")
        return max(candidatas, key=lambda d: d.version)

    def __contains__(self, item: object) -> bool:
        if isinstance(item, FeatureDefinition):
            return (item.key, str(item.version)) in self._por_identidade
        return False

    def __iter__(self) -> Iterator[FeatureDefinition]:
        """Itera em ordem determinística — `(chave, versão)`.

        A ordem de inserção seria determinística também, e seria a errada: ela
        faria dois registros com as mesmas definições em ordens diferentes
        iterarem diferente, e qualquer coisa construída a partir da iteração
        herdaria a diferença.
        """
        for chave in sorted(self._por_identidade):
            yield self._por_identidade[chave]

    def __len__(self) -> int:
        return len(self._por_identidade)


def _recusar_ciclo(definitions: tuple[FeatureDefinition, ...]) -> None:
    from sports_intelligence.domain.features.space import _ciclo_em

    ciclo = _ciclo_em(definitions)
    if ciclo:
        raise ValidationError(
            f"dependência cíclica entre features: {' → '.join(ciclo)}",
            context={"cycle": " → ".join(ciclo)},
        )
