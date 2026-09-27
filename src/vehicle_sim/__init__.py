"""Xe ảo (digital twin) — process riêng, subscribe lệnh và publish trạng thái.

Hợp đồng: docs/mqtt_spec.md. Quyết định kiến trúc: ADR-004.
"""

from src.vehicle_sim.state import ExecutionOutcome, VehicleSimulator

__all__ = ["ExecutionOutcome", "VehicleSimulator"]
