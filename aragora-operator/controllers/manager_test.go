/*
Copyright 2024 Aragora.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controllers

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"
)

const (
	probeAddrEnv   = "ARAGORA_OPERATOR_TEST_PROBE_ADDR"
	metricsAddrEnv = "ARAGORA_OPERATOR_TEST_METRICS_ADDR"
	metricsOutEnv  = "ARAGORA_OPERATOR_TEST_METRICS_OUT"

	defaultTestAddr       = "127.0.0.1:0"
	defaultMetricsOutPath = "/tmp/aragora-readiness/operator-metrics.txt"

	leaderElectionNamespace = "default"
	leaderElectionID        = "aragora-operator-test"

	// The cluster reconciler ends every successful pass with RequeueAfter,
	// which controller-runtime counts as result="requeue_after".
	clusterSuccessSample = `controller_runtime_reconcile_total{controller="aragoracluster",result="requeue_after"}`
)

// requiredMetricFamilies are the metric families the operator's alert rules
// query; each must have at least one sample in the /metrics body.
var requiredMetricFamilies = []string{
	"controller_runtime_reconcile_total",
	"controller_runtime_reconcile_errors_total",
	"workqueue_depth",
	"leader_election_master_status",
}

// TestManagerHealthProbesAndMetrics wires the manager the way main.go does,
// with leader election on, and checks the health-probe and metrics endpoints.
func TestManagerHealthProbesAndMetrics(t *testing.T) {
	cfg, c := requireEnvtest(t)
	defer stopControlPlaneOnPanic()

	probeAddr := listenAddrFromEnv(t, probeAddrEnv)
	metricsAddr := listenAddrFromEnv(t, metricsAddrEnv)
	t.Logf("health probes on %s (%s), metrics on %s (%s)", probeAddr, probeAddrEnv, metricsAddr, metricsAddrEnv)

	namespace := newNamespace(t, c)
	api := newFakeControlPlane(t)
	mgr := newManager(t, cfg, namespace, ctrl.Options{
		Metrics:                       metricsserver.Options{BindAddress: metricsAddr},
		HealthProbeBindAddress:        probeAddr,
		LeaderElection:                true,
		LeaderElectionNamespace:       leaderElectionNamespace,
		LeaderElectionID:              leaderElectionID,
		LeaderElectionReleaseOnCancel: true,
	})
	setupClusterReconciler(t, mgr, api.URL)
	setupInstanceReconciler(t, mgr)
	setupPolicyReconciler(t, mgr, api.URL)
	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		t.Fatalf("add healthz check: %v", err)
	}
	if err := mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {
		t.Fatalf("add readyz check: %v", err)
	}
	run := startManager(t, mgr)

	select {
	case <-mgr.Elected():
		t.Logf("won leader election for lease %s/%s", leaderElectionNamespace, leaderElectionID)
	case <-run.done:
		t.Fatalf("manager stopped before winning leader election: %v", run.err)
	case <-time.After(eventuallyTimeout):
		t.Fatalf("manager did not win leader election within %v", eventuallyTimeout)
	}

	// Drive a successful reconcile so the controller metric families carry
	// samples from this manager, not only from earlier tests in the binary.
	cluster := newTestCluster(namespace, "aragora")
	create(t, c, cluster)
	waitForCondition(t, c, cluster, "Ready", metav1.ConditionFalse, "NotReady")

	httpClient := &http.Client{
		Timeout:   5 * time.Second,
		Transport: &http.Transport{DisableKeepAlives: true},
	}
	for _, path := range []string{"/healthz", "/readyz"} {
		url := "http://" + probeAddr + path
		eventually(t, "GET "+url+" returned 200", func(ctx context.Context) error {
			_, err := get(ctx, httpClient, url)
			return err
		})
	}

	metricsURL := "http://" + metricsAddr + "/metrics"
	var body string
	eventually(t, "GET "+metricsURL+" returned 200 with every required metric family", func(ctx context.Context) error {
		var err error
		if body, err = get(ctx, httpClient, metricsURL); err != nil {
			return err
		}
		for _, family := range requiredMetricFamilies {
			if len(samples(body, family)) == 0 {
				return fmt.Errorf("no %s samples yet", family)
			}
		}
		if !hasNonZeroSample(body, clusterSuccessSample) {
			return fmt.Errorf("no successful aragoracluster reconcile counted yet")
		}
		return nil
	})
	for _, family := range requiredMetricFamilies {
		lines := samples(body, family)
		t.Logf("%s: %d samples, e.g. %s", family, len(lines), lines[0])
	}
	t.Logf("successful AragoraCluster reconciles: %s", samples(body, clusterSuccessSample)[0])
	leaderSample := fmt.Sprintf("leader_election_master_status{name=%q} 1", leaderElectionID)
	if !strings.Contains(body, leaderSample+"\n") {
		t.Errorf("metrics body lacks %q", leaderSample)
	}
	saveMetrics(t, body)
}

// listenAddrFromEnv returns the address named by env, or 127.0.0.1:0. Port 0
// is resolved here: controller-runtime v0.17 does not expose the probe
// listener it binds, so the test reserves a free port, reads it back from
// that listener, and hands the concrete address to the manager.
func listenAddrFromEnv(t *testing.T, env string) string {
	t.Helper()
	addr := os.Getenv(env)
	if addr == "" {
		addr = defaultTestAddr
	}
	_, port, err := net.SplitHostPort(addr)
	if err != nil {
		t.Fatalf("%s=%q is not a host:port address: %v", env, addr, err)
	}
	if port != "0" {
		return addr
	}
	l, err := net.Listen("tcp", addr)
	if err != nil {
		t.Fatalf("reserve a port for %s=%q: %v", env, addr, err)
	}
	resolved := l.Addr().String()
	if err := l.Close(); err != nil {
		t.Fatalf("release the port reserved for %s: %v", env, err)
	}
	return resolved
}

// get returns the body of a 200 response and an error for any other status.
func get(ctx context.Context, c *http.Client, url string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	resp, err := c.Do(req)
	if err != nil {
		return "", err
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	if resp.StatusCode != http.StatusOK {
		return "", errors.New(resp.Status)
	}
	return string(body), nil
}

// samples returns the sample lines of a metric family in the Prometheus text
// format, skipping its HELP and TYPE comments.
func samples(body, family string) []string {
	var lines []string
	for _, line := range strings.Split(body, "\n") {
		if strings.HasPrefix(line, family+"{") || strings.HasPrefix(line, family+" ") {
			lines = append(lines, line)
		}
	}
	return lines
}

// hasNonZeroSample reports whether body has the sample series (metric name
// plus labels) with a value other than 0.
func hasNonZeroSample(body, series string) bool {
	for _, line := range strings.Split(body, "\n") {
		if value, ok := strings.CutPrefix(line, series+" "); ok {
			return value != "0"
		}
	}
	return false
}

// saveMetrics writes the /metrics body where the alert-rule cross-check reads
// it: $ARAGORA_OPERATOR_TEST_METRICS_OUT, or /tmp/aragora-readiness/operator-metrics.txt.
func saveMetrics(t *testing.T, body string) {
	t.Helper()
	path := os.Getenv(metricsOutEnv)
	if path == "" {
		path = defaultMetricsOutPath
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("create the directory for %s: %v", path, err)
	}
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatalf("write the metrics body: %v", err)
	}
	t.Logf("wrote the /metrics body (%d bytes) to %s", len(body), path)
}
