# libs/platform_contracts/metrics.py
"""
Prometheus Metrics Engine for KarobarOne Microservices.
RULES.md §12: Prometheus /metrics (internal only; route-template labels, never tenant/store/customer ids).
DEPLOY.md §6: bounded labels (route template, status class, event type), outbox lag, dead events, scheduler lateness.
"""
from collections import defaultdict
import threading
from typing import Dict, Tuple


class MetricsRegistry:
    def __init__(self, service_name: str = "karobarone"):
        self.service_name = service_name
        self._lock = threading.Lock()
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}

    def inc_counter(self, name: str, amount: float = 1.0, **labels) -> None:
        """Increments a counter by amount with bounded label key/values."""
        lbl_tuple = tuple(sorted(labels.items()))
        with self._lock:
            self._counters[(name, lbl_tuple)] += amount

    def set_gauge(self, name: str, value: float, **labels) -> None:
        """Sets a gauge value with bounded label key/values."""
        lbl_tuple = tuple(sorted(labels.items()))
        with self._lock:
            self._gauges[(name, lbl_tuple)] = value

    def format_labels(self, labels: Tuple[Tuple[str, str], ...]) -> str:
        all_labels = [("service", self.service_name)] + list(labels)
        formatted = ",".join(f'{k}="{v}"' for k, v in sorted(all_labels))
        return f"{{{formatted}}}"

    def render_prometheus_text(self) -> str:
        """Renders standard Prometheus text exposition format (version 0.0.4)."""
        lines = []
        with self._lock:
            # Counters
            counter_groups = defaultdict(list)
            for (name, lbls), val in self._counters.items():
                counter_groups[name].append((lbls, val))

            for name, items in sorted(counter_groups.items()):
                lines.append(f"# TYPE {name} counter")
                for lbls, val in items:
                    lines.append(f"{name}{self.format_labels(lbls)} {val}")

            # Gauges
            gauge_groups = defaultdict(list)
            for (name, lbls), val in self._gauges.items():
                gauge_groups[name].append((lbls, val))

            for name, items in sorted(gauge_groups.items()):
                lines.append(f"# TYPE {name} gauge")
                for lbls, val in items:
                    lines.append(f"{name}{self.format_labels(lbls)} {val}")

        return "\n".join(lines) + "\n" if lines else ""


# Global singleton per process
metrics = MetricsRegistry()
