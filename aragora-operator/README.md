# aragora-operator

## Overview

A Kubernetes operator for Aragora, built with controller-runtime v0.17 and
Kubernetes 1.29 client libraries. It reconciles three custom resources in the
`aragora.ai/v1alpha1` API group:

| Kind | Controller | What it manages |
|------|------------|-----------------|
| `AragoraCluster` | `controllers/aragoracluster_controller.go` | The control-plane StatefulSet, its Services and ConfigMap, and the `Ready` condition |
| `AragoraInstance` | `controllers/aragorainstance_controller.go` | A worker Deployment (and HPA when scaling is enabled) for a cluster |
| `AragoraPolicy` | `controllers/aragorapolicy_controller.go` | Syncs cost, model, and rate-limit policies to the Aragora control-plane API |

The CRDs are generated into `config/crd/bases/` (`make manifests`) and copied
into the Helm chart's `crds/` directory. The chart lives in
`helm/aragora-operator/`.

| Path | Contents |
|------|----------|
| `main.go` | Flags, telemetry setup, and the controller manager |
| `api/v1alpha1/` | CRD types and the generated `zz_generated.deepcopy.go` |
| `controllers/` | The three reconcilers and their envtest suite |
| `internal/aragora/` | Client for the Aragora control-plane API |
| `internal/httpclient/` | Retrying, circuit-breaking HTTP client used by that API client |
| `internal/observability/` | OpenTelemetry, Sentry, pprof, and the build version |
| `config/` | Generated CRDs and RBAC role |
| `helm/aragora-operator/` | Helm chart, including the optional `PrometheusRule` |

## Setup

You need Go (the version in `go.mod` or newer; with the default
`GOTOOLCHAIN=auto` an older `go` downloads the right toolchain itself). Docker
is only needed to build the container image.

From this directory, one command downloads the Go modules, installs the pinned
tools into `bin/` (controller-gen v0.22.0, golangci-lint v2.13.2, and the
latest `setup-envtest`), and downloads the Kubernetes 1.29 envtest binaries
(kube-apiserver, etcd, kubectl) into `bin/k8s/`:

```bash
make setup
```

It prints the `export KUBEBUILDER_ASSETS=...` line the controller tests need.
To use the installed tools directly, put `bin/` on your `PATH`:

```bash
export PATH="$PWD/bin:$PATH"
export KUBEBUILDER_ASSETS="$(bin/setup-envtest use 1.29.x --bin-dir "$PWD/bin" -p path)"
```

`bin/` is gitignored. The versions are pinned in the `Makefile`
(`ENVTEST_K8S_VERSION` at the top; `CONTROLLER_TOOLS_VERSION`,
`ENVTEST_VERSION`, and `GOLANGCI_LINT_VERSION` near the bottom). An existing
binary in `bin/` is reused as is, so delete it to pick up a new pin.

## Build

```bash
go build ./...                      # compile every package
make build                          # regenerate, go fmt, go vet, then build bin/manager
```

Generated code is checked in. After changing the API types or the kubebuilder
markers, regenerate it and commit the result:

```bash
make generate manifests
```

`make generate` rewrites `api/v1alpha1/zz_generated.deepcopy.go`;
`make manifests` rewrites the CRDs in `config/crd/bases/`, the RBAC role in
`config/rbac/role.yaml`, and the copies in `helm/aragora-operator/crds/`. CI
fails when either command changes a tracked file.

The version reported to Sentry and on trace spans is `dev` unless the binary is
built with:

```bash
go build -ldflags "-X github.com/synaptent/aragora-operator/internal/observability.version=v1.2.3" -o bin/manager main.go
```

The container image uses the `golang:1.25.0` builder, which matches the `go`
line in `go.mod`; change both together. To build and smoke-test it:

```bash
docker build -t aragora-operator:dev .
docker run --rm aragora-operator:dev --help
```

`--help` exits 0 and lists every flag, including `-pprof-addr`. The
`build-operator` job in `.github/workflows/docker.yml` runs the same smoke test
on the image it builds.

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
   in the `Makefile`. (`make setup` does the same into `bin/`.)

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

CI (`.github/workflows/operator-ci.yml`) runs the same suite with
`gotestsum --junitfile operator-junit.xml -- ./... -count=1` and uploads the
JUnit and `go test -json` files (per-test timings) as the
`operator-test-results` artifact. It caches the envtest binaries, keyed on the
Kubernetes version.

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

## Lint

```bash
make lint                           # installs golangci-lint v2.13.2 into bin/ and runs it
golangci-lint run ./...             # the same, with a golangci-lint already on PATH
```

The configuration is `.golangci.yml` (golangci-lint v2 schema): the `standard`
linters (errcheck, govet, ineffassign, staticcheck, unused) plus dupl,
gocyclo (a function with a cyclomatic complexity above 16 fails), and
misspell, and the `gofmt` formatter. `make lint-fix` applies the fixes golangci-lint can make.

Formatting is plain `gofmt`. This must print nothing:

```bash
gofmt -l $(git ls-files '*.go')
```

`gofmt -w <file>` (or `make fmt`) fixes a file it lists. The other checks CI
runs are `go vet ./...` and `go mod tidy -diff` (no output means `go.mod` and
`go.sum` are tidy).

From the repository root, `make readiness-lint-operator` runs the gofmt check,
`go vet`, and the file-size ratchet (`scripts/ci/check_file_sizes.py --glob
'aragora-operator/**/*.go'`); `make readiness-typecheck-operator` runs
`go build ./...` and `go vet ./...`. The pre-push hook `operator-gofmt-vet` in
`.pre-commit-config.yaml` runs the gofmt check and `go vet` before a push that
changes Go files here (install it with
`pre-commit install --hook-type pre-push`). Each prints
`SKIP operator: go not found` and passes when Go is not installed.

## Run locally

The operator is one binary. Bind every endpoint to `127.0.0.1` so nothing
listens on every interface:

```bash
go run ./main.go --metrics-bind-address=127.0.0.1:3143 --health-probe-bind-address=127.0.0.1:3144 --pprof-addr=127.0.0.1:3145
```

(`make run` does the same after regenerating code, but with the default
`:8080`/`:8081` addresses and no pprof.)

With a reachable cluster (from `--kubeconfig`, `KUBECONFIG`, the in-cluster
config, or `~/.kube/config`) this starts all three controllers, `/metrics` on
`127.0.0.1:3143`, and `/healthz` and `/readyz` on `127.0.0.1:3144`.

Without a cluster (no kubeconfig at all, for example with
`KUBECONFIG=/nonexistent HOME=/tmp/no-such-home`), the pprof endpoint still
answers on `http://127.0.0.1:3145/debug/pprof/` as soon as the process has
started, because it starts before the kubeconfig is loaded. The operator retries the kubeconfig for
`--kubeconfig-wait` (30 s by default) and then exits with status 1. The metrics
and health endpoints do not start without a cluster, because controller-runtime
only serves them from a running manager.

To check `/healthz`, `/readyz`, and `/metrics` without a cluster, run the
manager test against envtest (see [Test](#test)) with fixed addresses from the
two probe/metrics variables:

```bash
ARAGORA_OPERATOR_TEST_PROBE_ADDR=127.0.0.1:3144 \
ARAGORA_OPERATOR_TEST_METRICS_ADDR=127.0.0.1:3143 \
  go test ./controllers/ -run TestManagerHealthProbesAndMetrics -count=1 -v
```

It logs the addresses it bound and fails unless `/healthz` and `/readyz` return
200 and `/metrics` serves the controller-runtime families.

## Configuration

### Flags

`go run ./main.go --help` (or `docker run --rm <image> --help`) lists them.
Both `-flag` and `--flag` spellings work.

| Flag | Default | Purpose |
|------|---------|---------|
| `--metrics-bind-address` | `:8080` | Prometheus `/metrics` endpoint |
| `--health-probe-bind-address` | `:8081` | `/healthz` and `/readyz` probe endpoint |
| `--pprof-addr` | empty (off) | `net/http/pprof` endpoint under `/debug/pprof/`. Starts before the kubeconfig is loaded |
| `--leader-elect` | `false` | Leader election (lease `aragora-operator-leader-election`), for running more than one replica |
| `--aragora-api-endpoint` | `https://aragora-control-plane:8443` | Aragora control-plane API |
| `--aragora-api-token` | empty | Bearer token for that API |
| `--allow-insecure-control-plane` | `false` | Allow an `http://` control-plane endpoint |
| `--kubeconfig-wait` | `30s` | How long to keep retrying when no kubeconfig or in-cluster config loads. `0` exits on the first failure |
| `--kubeconfig` | none | Kubeconfig path (otherwise `KUBECONFIG`, the in-cluster config, then `~/.kube/config`) |
| `--zap-devel` | `true` | Development logging defaults (console encoder, debug level). `false` switches to JSON at info level |
| `--zap-encoder` | from `--zap-devel` | `json` or `console` |
| `--zap-log-level` | from `--zap-devel` | `debug`, `info`, `error`, or an integer verbosity |
| `--zap-stacktrace-level` | from `--zap-devel` | Level from which stack traces are logged: `info`, `error`, or `panic` |
| `--zap-time-encoding` | `epoch` | `epoch`, `millis`, `nano`, `iso8601`, `rfc3339`, or `rfc3339nano` |

`--aragora-api-endpoint` must be an absolute `http` or `https` URL without a
query or fragment; the operator exits at startup with an error otherwise.

The Aragora control-plane API client retries connection errors, `429`, and
`5xx` answers (except `501`) up to 3 times with 0.5 to 5 s exponential backoff,
or the `Retry-After` delay of a `429` or `503` answer. Each attempt times out
after 30 s. After 5 consecutive
failed calls to one endpoint a circuit breaker opens and calls fail at once
without reaching the API; after 30 s it lets one trial call through and closes
again if that call succeeds.

### Environment variables

Telemetry is off unless its environment variable is set. The operator logs
one line at startup for each, saying whether it is enabled.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset (tracing off) | OTLP/HTTP collector base URL, for example `http://localhost:4318`. Spans go to `<endpoint>/v1/traces`. The other standard `OTEL_EXPORTER_OTLP_*` variables (headers, timeout, `..._TRACES_ENDPOINT`) apply too |
| `SENTRY_DSN` | unset (Sentry off) | Sentry project DSN |
| `SENTRY_ENVIRONMENT` | `development` | Sentry environment tag. Only read when `SENTRY_DSN` is set |
| `KUBECONFIG` | unset | Kubeconfig path, when `--kubeconfig` is not given |

The service name is always `aragora-operator`. The version (`service.version`
on spans, `aragora-operator@<version>` in Sentry) is set at build time; see
[Build](#build). The test-only variables are listed under
[Test](#environment-variables).

### Helm values

The chart in `helm/aragora-operator/` renders the Deployment, RBAC, service
account, CRDs, and optionally a `PrometheusRule`. The values it reads:

| Value | Default | Purpose |
|-------|---------|---------|
| `image.repository`, `image.tag`, `image.pullPolicy` | `ghcr.io/synaptent/aragora-operator`, chart `appVersion`, `IfNotPresent` | Operator image |
| `imagePullSecrets` | `[]` | Pull secrets |
| `nameOverride`, `fullnameOverride` | empty | Override the generated resource names |
| `replicaCount` | `1` | Replicas; use 2 or more with leader election |
| `leaderElection.enabled` | `true` | Passes `--leader-elect` |
| `aragoraAPI.endpoint` | empty (flag default) | Passed as `--aragora-api-endpoint` when set |
| `aragoraAPI.allowInsecure` | `false` | Passes `--allow-insecure-control-plane` |
| `aragoraAPI.tokenSecretName`, `aragoraAPI.tokenSecretKey` | empty, `token` | Sets `ARAGORA_API_TOKEN` in the pod from that secret. The binary does not read this variable yet; it only takes `--aragora-api-token` |
| `metrics.port` | `8080` | `--metrics-bind-address` port and container port |
| `healthProbe.port` | `8081` | `--health-probe-bind-address` port, liveness and readiness probes |
| `podAnnotations` | `prometheus.io/scrape: "true"`, `prometheus.io/port: "8080"` | Pod annotations; scraping relies on these |
| `monitoring.alerts.enabled` | `false` | Render the `PrometheusRule` described under [Observability](#observability). Needs the Prometheus Operator CRDs in the cluster |
| `monitoring.alerts.labels` | `{}` | Extra labels on the `PrometheusRule`, for your Prometheus `ruleSelector` |
| `serviceAccount.create`, `.name`, `.annotations` | `true`, generated, `{}` | Service account |
| `rbac.create`, `rbac.clusterRole` | `true`, `true` | RBAC objects |
| `resources`, `nodeSelector`, `tolerations`, `affinity`, `topologySpreadConstraints`, `priorityClassName`, `podLabels`, `podSecurityContext`, `securityContext` | see `values.yaml` | Standard pod settings |

`values.yaml` also defines `metrics.enabled`, `metrics.serviceMonitor.*`,
`logging.*`, `crds.*`, `webhooks.*`, and `podDisruptionBudget.*`, but no
template reads them yet, so they have no effect. The chart has no value for
`--pprof-addr`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `SENTRY_DSN`, or
`SENTRY_ENVIRONMENT`; set those on the Deployment directly, for example with
`kubectl set env deployment/<operator-deployment> SENTRY_DSN=...`.

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
