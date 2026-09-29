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
