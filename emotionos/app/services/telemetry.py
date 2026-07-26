from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Protocol

from emotionos.app.core.config import Settings


class TraceSpan(Protocol):
    def set_outputs(self, outputs: Any) -> None: ...

    def set_attribute(self, key: str, value: Any) -> None: ...


class _NoopSpan:
    def set_outputs(self, outputs: Any) -> None:
        del outputs

    def set_attribute(self, key: str, value: Any) -> None:
        del key, value


class SceneTelemetry:
    """Lazy MLflow tracing that never records dialogue or private memories."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._configured = False

    @property
    def enabled(self) -> bool:
        return bool(self.settings.mlflow_experiment_id.strip())

    @contextmanager
    def span(
        self,
        name: str,
        *,
        span_type: str,
        inputs: dict[str, Any],
    ) -> Iterator[TraceSpan]:
        if not self.enabled:
            yield _NoopSpan()
            return

        try:
            import mlflow
        except (ImportError, AttributeError):
            yield _NoopSpan()
            return

        if not self._configured:
            mlflow.set_tracking_uri("databricks")
            mlflow.set_experiment(experiment_id=self.settings.mlflow_experiment_id)
            self._configured = True

        with mlflow.start_span(name=name, span_type=span_type) as span:
            span.set_inputs(inputs)
            yield span
