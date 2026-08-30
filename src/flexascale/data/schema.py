from dataclasses import dataclass


@dataclass
class ServiceState:
    timestamp: int
    service_id: str
    cpu_utilization: float
    memory_utilization: float
    replica_count: int
