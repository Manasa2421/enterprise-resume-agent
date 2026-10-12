"""
Lightweight, dependency-free metrics registry exposed in Prometheus text format
at GET /metrics. In a larger deployment this could be swapped for
prometheus_client or OpenTelemetry without changing call sites.
"""

import threading
from collections import defaultdict

LabelKey = tuple[tuple[str, str], ...]

_DEFAULT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)


def _labels_key(labels: dict[str, str] | None) -> LabelKey:
    return tuple(sorted((labels or {}).items()))


def _fmt_labels(key: LabelKey, extra: dict[str, str] | None = None) -> str:
    items = list(key) + list((extra or {}).items())
    if not items:
        return ""
    return "{" + ",".join(f'{k}="{v}"' for k, v in items) + "}"


class MetricsRegistry:
    def __init__(self, buckets: tuple[float, ...] = _DEFAULT_BUCKETS) -> None:
        self._lock = threading.Lock()
        self._buckets = buckets
        self._counters: dict[str, dict[LabelKey, float]] = defaultdict(lambda: defaultdict(float))
        self._histograms: dict[str, dict[LabelKey, dict]] = defaultdict(dict)
        self._help: dict[str, str] = {}

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0, help_text: str = "") -> None:
        with self._lock:
            self._counters[name][_labels_key(labels)] += value
            if help_text:
                self._help[name] = help_text

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None, help_text: str = "") -> None:
        with self._lock:
            series = self._histograms[name].setdefault(
                _labels_key(labels), {"buckets": [0] * len(self._buckets), "sum": 0.0, "count": 0}
            )
            for i, bound in enumerate(self._buckets):
                if value <= bound:
                    series["buckets"][i] += 1
            series["sum"] += value
            series["count"] += 1
            if help_text:
                self._help[name] = help_text

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> float:
        with self._lock:
            return self._counters.get(name, {}).get(_labels_key(labels), 0.0)

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name, series in sorted(self._counters.items()):
                lines.append(f"# HELP {name} {self._help.get(name, name)}")
                lines.append(f"# TYPE {name} counter")
                for key, value in series.items():
                    lines.append(f"{name}{_fmt_labels(key)} {value}")
            for name, series in sorted(self._histograms.items()):
                lines.append(f"# HELP {name} {self._help.get(name, name)}")
                lines.append(f"# TYPE {name} histogram")
                for key, data in series.items():
                    for bound, count in zip(self._buckets, data["buckets"]):
                        lines.append(f"{name}_bucket{_fmt_labels(key, {'le': str(bound)})} {count}")
                    lines.append(f"{name}_bucket{_fmt_labels(key, {'le': '+Inf'})} {data['count']}")
                    lines.append(f"{name}_sum{_fmt_labels(key)} {round(data['sum'], 6)}")
                    lines.append(f"{name}_count{_fmt_labels(key)} {data['count']}")
        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()
