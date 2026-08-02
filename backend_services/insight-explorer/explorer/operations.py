from __future__ import annotations

import os
import resource
import sys
import time
from concurrent import futures
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import grpc
from google.protobuf.timestamp_pb2 import Timestamp

_PROTO_PATH = Path(__file__).resolve().parents[2] / "insight-protos" / "gen" / "py"
if _PROTO_PATH.exists() and str(_PROTO_PATH) not in sys.path:
    sys.path.insert(0, str(_PROTO_PATH))

from operations.v1 import operations_pb2, operations_pb2_grpc  # noqa: E402


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    version: str = "v1"
    enabled: bool = True


@dataclass(frozen=True)
class Identity:
    service_id: str
    service_name: str
    service_type: int
    version: str
    environment: str
    tags: tuple[str, ...]


class OperationsService(operations_pb2_grpc.OperationsServiceServicer):
    def __init__(
        self,
        *,
        identity: Identity,
        capabilities: list[Capability],
        ready: Callable[[], bool],
        active_jobs: Callable[[], int],
    ) -> None:
        self.identity = identity
        self.capabilities = capabilities
        self.ready = ready
        self.active_jobs = active_jobs
        self.started_at = time.time()

    def Ping(self, request, context):  # noqa: N802, ANN001, ANN201
        now = time.time()
        sent = request.sent_at.ToSeconds() if request and request.HasField("sent_at") else 0
        latency_ms = max(0, int((now - sent) * 1000)) if sent else 0
        return operations_pb2.PingResponse(identity=self._identity_pb(), latency_ms=latency_ms, checked_at=_ts())

    def Health(self, request, context):  # noqa: N802, ANN001, ANN201
        healthy = self.ready()
        return operations_pb2.HealthResponse(
            identity=self._identity_pb(),
            status=_status(healthy),
            reason="ready" if healthy else "dependency_unavailable",
            checked_at=_ts(),
        )

    def Status(self, request, context):  # noqa: N802, ANN001, ANN201
        healthy = self.ready()
        return operations_pb2.StatusResponse(
            identity=self._identity_pb(),
            status=_status(healthy),
            uptime_seconds=int(time.time() - self.started_at),
            detail="ready" if healthy else "dependency_unavailable",
            checked_at=_ts(),
        )

    def Capabilities(self, request, context):  # noqa: N802, ANN001, ANN201
        return operations_pb2.CapabilitiesResponse(
            identity=self._identity_pb(),
            capabilities=[
                operations_pb2.Capability(
                    name=c.name,
                    version=c.version,
                    enabled=c.enabled,
                    description=c.description,
                )
                for c in self.capabilities
            ],
            checked_at=_ts(),
        )

    def Metrics(self, request, context):  # noqa: N802, ANN001, ANN201
        return operations_pb2.MetricsResponse(
            identity=self._identity_pb(),
            cpu_percent=_cpu_percent(),
            memory_mb=_memory_mb(),
            active_jobs=max(0, int(self.active_jobs())),
            uptime_seconds=int(time.time() - self.started_at),
            checked_at=_ts(),
        )

    def http_health(self) -> dict[str, object]:
        return {"service": self.identity.service_id, "status": "healthy" if self.ready() else "degraded"}

    def http_status(self) -> dict[str, object]:
        return {
            "service": self.identity.service_id,
            "version": self.identity.version,
            "uptime_seconds": int(time.time() - self.started_at),
            "status": "healthy" if self.ready() else "degraded",
            "identity": self.identity.__dict__,
        }

    def http_capabilities(self) -> dict[str, object]:
        return {"service": self.identity.service_id, "capabilities": [c.name for c in self.capabilities if c.enabled]}

    def http_metrics(self) -> dict[str, object]:
        return {
            "service": self.identity.service_id,
            "cpu_percent": _cpu_percent(),
            "memory_mb": _memory_mb(),
            "active_jobs": max(0, int(self.active_jobs())),
            "uptime_seconds": int(time.time() - self.started_at),
        }

    def _identity_pb(self):  # noqa: ANN202
        return operations_pb2.ServiceIdentity(
            service_id=self.identity.service_id,
            service_name=self.identity.service_name,
            service_type=self.identity.service_type,
            version=self.identity.version,
            environment=self.identity.environment,
            tags=list(self.identity.tags),
        )


def explorer_operations(ready: Callable[[], bool], active_jobs: Callable[[], int]) -> OperationsService:
    return OperationsService(
        identity=Identity(
            service_id="explorer",
            service_name="Insight Explorer",
            service_type=operations_pb2.SERVICE_TYPE_DATA_INGESTION,
            version="0.0.2",
            environment=os.getenv("INSIGHT_ENVIRONMENT", ""),
            tags=("recon", "discovery", "enumeration", "asset_analysis"),
        ),
        capabilities=[
            Capability("recon", "Reconciles collected football data across sources."),
            Capability("discovery", "Discovers datasets, jobs and source inventories."),
            Capability("enumeration", "Enumerates fixtures, sources, clubs and dataset records."),
            Capability("asset_analysis", "Surfaces data quality, duplicates and review backlogs."),
            Capability("metrics_generation", "Publishes Explorer runtime metrics."),
        ],
        ready=ready,
        active_jobs=active_jobs,
    )


def start_grpc_server(service: OperationsService, addr: str) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    operations_pb2_grpc.add_OperationsServiceServicer_to_server(service, server)
    server.add_insecure_port(addr)
    server.start()
    return server


def _status(healthy: bool) -> int:
    return (
        operations_pb2.OPERATIONAL_STATUS_HEALTHY
        if healthy
        else operations_pb2.OPERATIONAL_STATUS_DEGRADED
    )


def _ts() -> Timestamp:
    ts = Timestamp()
    ts.GetCurrentTime()
    return ts


def _memory_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return float(usage) / 1024


def _cpu_percent() -> float:
    try:
        return round(os.getloadavg()[0] / max(1, os.cpu_count() or 1) * 100, 2)
    except OSError:
        return 0.0
