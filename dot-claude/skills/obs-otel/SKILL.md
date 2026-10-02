---
name: obs-otel
description: Use for observability with OpenTelemetry — traces, metrics and logs, the Collector, RED/USE dashboards, SLO burn-rate alerts.
---
# Observability with OpenTelemetry

Part of `self-hosting-ops` (principles). Simple uptime and dead-man checks: `ops-runbooks`. OpenTelemetry Collector releases v0.162.0 is current (Verified 2026-10-02 `git ls-remote --tags https://github.com/open-telemetry/opentelemetry-collector-releases`).

## Instrumentation
- Signals: traces (request paths and latency), metrics (rates, saturation, business counters), logs (events with context). Correlate them through the trace context (trace id in every log line).
- Use the language SDK plus auto-instrumentation for HTTP, database and RPC libraries; add manual spans only around meaningful work. Follow the semantic conventions for attribute names.
- Configure through the standard environment variables: `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=prod,service.version=1.4.2`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`, `OTEL_TRACES_SAMPLER=parentbased_traceidratio`, `OTEL_TRACES_SAMPLER_ARG=0.1`.
- OTLP ports: 4317 gRPC, 4318 HTTP.
- Metric labels have bounded cardinality: never user ids, raw URLs, request ids or timestamps as label values (use span attributes for those).
- Never record secrets, tokens, full request bodies or personal data in attributes or logs.

## Collector
Apps send OTLP to a local Collector, which batches, filters and exports; changing a backend then touches one file.
```yaml
receivers:
  otlp:
    protocols: {grpc: {endpoint: 127.0.0.1:4317}, http: {endpoint: 127.0.0.1:4318}}
processors:
  memory_limiter: {check_interval: 1s, limit_percentage: 80, spike_limit_percentage: 20}
  batch: {}
exporters:
  otlphttp: {endpoint: https://otel.example.internal:4318}
service:
  pipelines:
    traces:  {receivers: [otlp], processors: [memory_limiter, batch], exporters: [otlphttp]}
    metrics: {receivers: [otlp], processors: [memory_limiter, batch], exporters: [otlphttp]}
    logs:    {receivers: [otlp], processors: [memory_limiter, batch], exporters: [otlphttp]}
```
- `memory_limiter` first, `batch` last in every pipeline; bind receivers to localhost unless other hosts must send.
- The contrib distribution (`otelcol-contrib`) carries most third-party receivers and exporters; check a config with `otelcol-contrib validate --config=config.yaml`.
- Backends for a personal setup: Prometheus or Mimir (metrics), Tempo or Jaeger (traces), Loki (logs), Grafana in front; or an all-in-one such as SigNoz.

## Dashboards and alerts
- Services: RED (rate, errors, duration as p50/p95/p99). Resources: USE (utilization, saturation, errors).
- Alert on symptoms users feel (error rate, latency, availability) through SLOs with multi-window burn-rate alerts, not on every cause; each alert links to a runbook (`ops-runbooks`).

## Verify
- A test request appears as one trace across services with matching log lines (same trace id); metrics show up with bounded label sets.
- `otelcol-contrib validate` passes; the Collector's own metrics show no dropped data; every alert has a runbook link and fired once in a test.
