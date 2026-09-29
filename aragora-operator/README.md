# aragora-operator

A Kubernetes operator for Aragora, built with controller-runtime v0.17 and
Kubernetes 1.29 client libraries. It reconciles three custom resources in the
`aragora.ai/v1alpha1` API group:

| Kind | Controller | What it manages |
|------|------------|-----------------|
| `AragoraCluster` | `controllers/aragoracluster_controller.go` | The control-plane StatefulSet, its Services and ConfigMap, and the `Ready` condition |
| `AragoraInstance` | `controllers/aragorainstance_controller.go` | A worker Deployment (and HPA when scaling is enabled) for a cluster |
| `AragoraPolicy` | `controllers/aragorapolicy_controller.go` | Syncs cost, model, and rate-limit policies to the Aragora control-plane API |

The CRDs are generated into `config/crd/bases/` (`make manifests`) and copied
into the Helm chart's `crds/` directory.

## Run

The operator is one binary. `go run ./main.go --help` lists every flag. The
main ones:

| Flag | Default | Purpose |
|------|---------|---------|
| `--metrics-bind-address` | `:8080` | Prometheus `/metrics` endpoint |
| `--health-probe-bind-address` | `:8081` | `/healthz` and `/readyz` probe endpoint |
| `--pprof-addr` | empty (off) | `net/http/pprof` endpoint under `/debug/pprof/`. Starts before the kubeconfig is loaded |
| `--leader-elect` | `false` | Leader election, for running more than one replica |
| `--aragora-api-endpoint` | `https://aragora-control-plane:8443` | Aragora control-plane API |
| `--aragora-api-token` | empty | Bearer token for that API |
| `--allow-insecure-control-plane` | `false` | Allow an `http://` control-plane endpoint |
| `--kubeconfig-wait` | `30s` | How long to keep retrying when no kubeconfig or in-cluster config loads. `0` exits on the first failure |
| `--kubeconfig` | none | Kubeconfig path (otherwise `KUBECONFIG`, the in-cluster config, then `~/.kube/config`) |

Both `-flag` and `--flag` spellings work. Bind to `127.0.0.1` when running
locally so nothing listens on every interface:

```bash
go run ./main.go --metrics-bind-address=127.0.0.1:3143 --health-probe-bind-address=127.0.0.1:3144 --pprof-addr=127.0.0.1:3145
```

With a reachable cluster this starts all three controllers. Without one (no
`KUBECONFIG`, no `~/.kube/config`, not in a pod), the pprof endpoint still
answers on `http://127.0.0.1:3145/debug/pprof/` while the operator retries the
kubeconfig for `--kubeconfig-wait`; then the process exits with status 1. The
metrics and probe endpoints only start once the manager has a cluster.

The Aragora control-plane API client retries connection errors, `429`, and
`5xx` answers (except `501`) up to 3 times with 0.5 to 5 s exponential backoff,
honouring `Retry-After`. Each attempt times out after 30 s. After 5 consecutive
failed calls to one endpoint a circuit breaker opens and calls fail at once
without reaching the API; after 30 s it lets one trial call through and closes
again if that call succeeds.

## Configuration

Telemetry is off unless its environment variable is set. The operator logs
one line at startup for each, saying whether it is enabled.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset (tracing off) | OTLP/HTTP collector base URL, for example `http://localhost:4318`. Spans go to `<endpoint>/v1/traces`. The other standard `OTEL_EXPORTER_OTLP_*` variables (headers, timeout, `..._TRACES_ENDPOINT`) apply too |
| `SENTRY_DSN` | unset (Sentry off) | Sentry project DSN |
| `SENTRY_ENVIRONMENT` | `development` | Sentry environment tag. Only read when `SENTRY_DSN` is set |

The service name is always `aragora-operator`. The version reported to Sentry
(`aragora-operator@<version>`) and on spans (`service.version`) is `dev` unless
the binary is built with:

```bash
go build -ldflags "-X github.com/synaptent/aragora-operator/internal/observability.version=v1.2.3" -o bin/manager main.go
```

## Observability

- **Metrics.** `/metrics` on `--metrics-bind-address` serves the
  controller-runtime metrics (`controller_runtime_reconcile_total`,
  `workqueue_depth`, `leader_election_master_status`, ...) and the operator's
  own `aragora_operator_*` metrics. `/healthz` and `/readyz` are on
  `--health-probe-bind-address`.
- **Alert rules.** The Helm chart can install a `PrometheusRule` (a
  Prometheus Operator resource) with one rule group, `aragora.operator`. It is
  off by default; enable it with `--set monitoring.alerts.enabled=true`, and
  put the labels your Prometheus `ruleSelector` matches under
  `monitoring.alerts.labels`. The alerts query only metric families that
  `/metrics` serves and `TestManagerHealthProbesAndMetrics` checks, limited to
  this operator's three controllers and its lease so that other
  controller-runtime operators in the cluster do not trigger them:
  - `AragoraOperatorReconcileErrors` (warning): a controller has kept
    returning reconcile errors for 15 minutes
    (`rate(controller_runtime_reconcile_errors_total[5m])`).
  - `AragoraOperatorWorkqueueDepth` (warning): a controller's work queue has
    held more than 10 items for 15 minutes (`workqueue_depth`).
  - `AragoraOperatorLeaderLost` (critical): for 5 minutes no replica has held
    the `aragora-operator-leader-election` lease, or no replica reports it
    (`leader_election_master_status`). Only rendered when
    `leaderElection.enabled` is true, because without leader election the
    operator never exports that metric.

  To see the rendered rule without a cluster:

  ```bash
  helm template aragora-operator helm/aragora-operator --set monitoring.alerts.enabled=true
  ```
- **Profiling.** Set `--pprof-addr` and use the standard endpoints, for
  example `go tool pprof http://127.0.0.1:3145/debug/pprof/heap` or
  `curl 'http://127.0.0.1:3145/debug/pprof/goroutine?debug=1'`. Keep it on a
  loopback or cluster-internal address; it exposes the command line and
  process internals.
- **Tracing.** With `OTEL_EXPORTER_OTLP_ENDPOINT` set, every request to the
  Aragora control-plane API is a client span (via `otelhttp`) carrying W3C
  `traceparent` headers, batched to the collector over OTLP/HTTP. Pending
  spans are flushed when the operator exits. To send one span to a local
  collector listening on 4318 (for example the mission's
  `otel/opentelemetry-collector-contrib` container with a `debug` exporter),
  run from this directory:

  ```bash
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 go test ./internal/observability/ -run TestOTelExporterOnlyWithEndpoint -count=1 -v
  ```

  The collector then logs a span with `service.name: Str(aragora-operator)`.
  Without the variable the same test sends its span to an in-process receiver
  instead, and nothing leaves the machine.
- **Errors.** With `SENTRY_DSN` set, a fatal startup or manager error is sent
  to Sentry, tagged with the release and environment above, and flushed before
  the process exits.

## Test

There are two kinds of tests.

- **Unit tests** need only Go. `go test ./... -short` runs them and skips every
  test that needs a Kubernetes API server. The repository's
  `make readiness-test-operator` runs exactly this.
- **Controller tests** in `controllers/` run the real reconcilers against a
  local kube-apiserver and etcd started by controller-runtime's
  [envtest](https://book.kubebuilder.io/reference/envtest.html), with the CRDs
  from `config/crd/bases/`. Nothing talks to a real cluster or network: the
  Aragora control-plane API is an in-process `httptest` server.

### Running the controller tests

1. Install `setup-envtest` and download the Kubernetes 1.29 test binaries
   (kube-apiserver, etcd, kubectl). The version matches `ENVTEST_K8S_VERSION`
   in the `Makefile`.

   ```bash
   go install sigs.k8s.io/controller-runtime/tools/setup-envtest@latest
   export KUBEBUILDER_ASSETS="$(setup-envtest use 1.29.x -p path)"
   ```

2. Run the whole suite from this directory. It takes well under a minute.

   ```bash
   go test ./... -count=1
   ```

   For per-package coverage, add `-coverprofile=cover.out` (the file is
   gitignored) and read it with `go tool cover -func=cover.out`.

`make test` does both steps itself (it installs `setup-envtest` into `bin/`),
after regenerating the manifests and running `go fmt` and `go vet`. From the
repository root, `make readiness-heavy-operator` runs golangci-lint
and then this suite whenever `KUBEBUILDER_ASSETS` is set.

Without `KUBEBUILDER_ASSETS` (and without `-short`) the controller tests fail
with a message that points here, rather than passing without testing anything.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `KUBEBUILDER_ASSETS` | none (required) | Directory holding the envtest `kube-apiserver`, `etcd`, and `kubectl` binaries |
| `ARAGORA_OPERATOR_TEST_PROBE_ADDR` | `127.0.0.1:0` | Health-probe address for `TestManagerHealthProbesAndMetrics` |
| `ARAGORA_OPERATOR_TEST_METRICS_ADDR` | `127.0.0.1:0` | Metrics address for `TestManagerHealthProbesAndMetrics` |
| `ARAGORA_OPERATOR_TEST_METRICS_OUT` | `/tmp/aragora-readiness/operator-metrics.txt` | Where that test saves the `/metrics` body it scraped |

With port `0` the test picks a free port and logs the address it used. Set a
fixed `host:port` when something outside the test needs to know it in advance:

```bash
ARAGORA_OPERATOR_TEST_PROBE_ADDR=127.0.0.1:19081 \
ARAGORA_OPERATOR_TEST_METRICS_ADDR=127.0.0.1:19080 \
  go test ./controllers/ -run TestManagerHealthProbesAndMetrics -count=1 -v
```

### What the controller tests check

| Test | Checks |
|------|--------|
| `TestAragoraClusterReconcilerSetsReadyCondition` | Creating an `AragoraCluster` sets a `Ready` condition within 30 s. It is `False`/`NotReady` because envtest runs no kubelet, so no replica ever becomes ready. Also checks the owned StatefulSet, Services, and ConfigMap, the agent status read from the control-plane API, and that deletion removes the finalizer. |
| `TestAragoraInstanceReconcilerSetsStatus` | An instance whose cluster is missing gets `ClusterRef=False`; one with a cluster gets a Deployment it controls and status (`Starting`, `Ready=False`). |
| `TestAragoraPolicyReconcilerAppliesPolicy` | A policy is applied to the control-plane API (`Applied=True`, `Active`, affected workspaces), a policy without its cluster goes to `Error`, and deletion removes it from the API. |
| `TestManagerHealthProbesAndMetrics` | Starts the manager as `main.go` does, with all three reconcilers and leader election (lease `default/aragora-operator-test`). `GET /healthz` and `GET /readyz` return 200. `GET /metrics` returns 200 with samples for `controller_runtime_reconcile_total`, `controller_runtime_reconcile_errors_total`, `workqueue_depth`, and `leader_election_master_status`. |

The suite starts one kube-apiserver and etcd pair on first use and stops it
when the test binary exits: after passing or failing tests, on Ctrl-C or
SIGTERM, on a panicking test, and just before a `-timeout` expires. Only a hard
kill (`SIGKILL`) of `go test` can leave them running; check with
`pgrep -lf 'kube-apiserver|etcd'`.
