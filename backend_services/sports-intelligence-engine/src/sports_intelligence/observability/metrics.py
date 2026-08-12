"""As quatro métricas do PR-00, e a decisão de não instalar Prometheus ainda.

POR QUE UM REGISTRO PRÓPRIO E NÃO `prometheus_client`. A dependência entra no
PR que expuser `/metrics` de verdade. Instalá-la agora para registrar quatro
contadores adiciona peso ao build e uma superfície que ninguém usa — e a
substituição depois é uma troca de implementação atrás desta mesma interface.

INSTRUMENTAR POUCO, DE PROPÓSITO. Métrica é custo permanente: cardinalidade
alta derruba o coletor, e um histograma por rota por status por provedor
explode sem que ninguém perceba até a conta chegar. Estas quatro respondem "o
processo subiu, atende, e com que latência" — o que basta para o PR-00.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Final, final


@final
@dataclass
class Counter:
    """Monotônico. Só sobe."""

    name: str
    help: str
    _values: dict[tuple[str, ...], float] = field(default_factory=lambda: defaultdict(float))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def inc(self, *labels: str, amount: float = 1.0) -> None:
        if amount < 0:
            raise ValueError(f"contador não decrementa: {self.name} recebeu {amount}")
        with self._lock:
            self._values[labels] += amount

    def value(self, *labels: str) -> float:
        with self._lock:
            return self._values[labels]


@final
@dataclass
class Histogram:
    """Distribuição por baldes cumulativos.

    Os baldes são declarados na construção porque a faixa útil depende do que
    se mede: latência de HTTP e latência de cálculo de estado não cabem na
    mesma régua.
    """

    name: str
    help: str
    buckets: tuple[float, ...]
    _counts: dict[tuple[str, ...], list[int]] = field(default_factory=dict)
    _sum: dict[tuple[str, ...], float] = field(default_factory=lambda: defaultdict(float))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, value: float, *labels: str) -> None:
        with self._lock:
            if labels not in self._counts:
                self._counts[labels] = [0] * (len(self.buckets) + 1)
            for i, limite in enumerate(self.buckets):
                if value <= limite:
                    self._counts[labels][i] += 1
                    break
            else:
                self._counts[labels][-1] += 1
            self._sum[labels] += value

    def snapshot(self, *labels: str) -> tuple[tuple[int, ...], float]:
        with self._lock:
            return tuple(self._counts.get(labels, [0] * (len(self.buckets) + 1))), self._sum[labels]


#: Segundos. A faixa cobre de resposta em cache (1ms) a chamada externa lenta
#: (10s); acima disso o balde `+Inf` já diz o que precisa ser dito.
_BALDES_HTTP: Final = (0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0)

APP_INFO: Final = Counter(
    "app_info", "Identificação do processo: sobe uma vez com service e version."
)
PROCESS_START: Final = Counter(
    "process_start_total", "Quantas vezes o processo iniciou. Reinícios ficam visíveis."
)
HTTP_REQUESTS: Final = Counter(
    "http_requests_total", "Requisições atendidas, por método, rota e status."
)
HTTP_DURATION: Final = Histogram(
    "http_request_duration_seconds", "Duração das requisições.", _BALDES_HTTP
)


def record_start(service_name: str, version: str) -> None:
    APP_INFO.inc(service_name, version)
    PROCESS_START.inc(service_name)


class Timer:
    """Mede um bloco e registra no histograma.

    `perf_counter` e não `time()`: o segundo pode andar para trás com ajuste
    de NTP, e uma duração negativa envenena o histograma.
    """

    def __init__(self, histogram: Histogram, *labels: str) -> None:
        self._histogram = histogram
        self._labels = labels
        self._start = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self._histogram.observe(time.perf_counter() - self._start, *self._labels)
