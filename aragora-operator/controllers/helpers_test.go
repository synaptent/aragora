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
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/rest"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/cache"
	"sigs.k8s.io/controller-runtime/pkg/client"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	aragorav1alpha1 "github.com/synaptent/aragora-operator/api/v1alpha1"
)

const (
	// eventuallyTimeout bounds every wait for a reconciler to act.
	eventuallyTimeout  = 30 * time.Second
	pollInterval       = 100 * time.Millisecond
	managerStopTimeout = 30 * time.Second
)

// fakeControlPlane stands in for the Aragora control-plane API that the
// reconcilers call at --aragora-api-endpoint, so the tests make no outbound
// network calls. It records every request as "METHOD /path".
type fakeControlPlane struct {
	*httptest.Server

	mu       sync.Mutex
	requests []string
}

const (
	agentsPath   = "/api/control-plane/agents"
	policiesPath = "/api/control-plane/policies/"
	// fakeWorkspace is what the fake reports as affected by every policy.
	fakeWorkspace = "ws-envtest"
	// fakeAgent is the one agent the fake reports as available.
	fakeAgent = "anthropic"
)

func newFakeControlPlane(t *testing.T) *fakeControlPlane {
	t.Helper()
	f := &fakeControlPlane{}
	f.Server = httptest.NewServer(http.HandlerFunc(f.serve))
	t.Cleanup(f.Close)
	return f
}

func (f *fakeControlPlane) serve(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	f.requests = append(f.requests, r.Method+" "+r.URL.Path)
	f.mu.Unlock()

	switch {
	case r.Method == http.MethodGet && r.URL.Path == agentsPath:
		writeJSON(w, []map[string]any{{
			"name":                fakeAgent,
			"available":           true,
			"last_heartbeat":      "2026-01-02T03:04:05Z",
			"requests_per_minute": 12.5,
		}})
	case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, policiesPath) &&
		strings.HasSuffix(r.URL.Path, "/workspaces"):
		writeJSON(w, map[string][]string{"workspaces": {fakeWorkspace}})
	case r.Method == http.MethodPut && strings.HasPrefix(r.URL.Path, policiesPath):
		w.WriteHeader(http.StatusOK)
	case r.Method == http.MethodDelete && strings.HasPrefix(r.URL.Path, policiesPath):
		w.WriteHeader(http.StatusNoContent)
	default:
		http.NotFound(w, r)
	}
}

func writeJSON(w http.ResponseWriter, body any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(body)
}

// received reports whether the fake has served a request, e.g. "GET /api/...".
func (f *fakeControlPlane) received(request string) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return slices.Contains(f.requests, request)
}

// newManager returns a manager for the envtest API server that watches only
// namespace, so objects left behind by other tests are never reconciled. Its
// metrics and health-probe servers stay off unless opts enables them, and a
// panicking reconciler becomes a reconcile error instead of crashing the test
// binary.
func newManager(t *testing.T, cfg *rest.Config, namespace string, opts ctrl.Options) ctrl.Manager {
	t.Helper()
	opts.Scheme = testScheme
	opts.Cache = cache.Options{DefaultNamespaces: map[string]cache.Config{namespace: {}}}
	if opts.Metrics.BindAddress == "" {
		opts.Metrics = metricsserver.Options{BindAddress: "0"}
	}
	if opts.HealthProbeBindAddress == "" {
		opts.HealthProbeBindAddress = "0"
	}
	opts.Controller.RecoverPanic = boolPtr(true)
	shutdownTimeout := 10 * time.Second
	opts.GracefulShutdownTimeout = &shutdownTimeout

	mgr, err := ctrl.NewManager(cfg, opts)
	if err != nil {
		t.Fatalf("create manager: %v", err)
	}
	return mgr
}

func setupClusterReconciler(t *testing.T, mgr ctrl.Manager, apiEndpoint string) {
	t.Helper()
	err := (&AragoraClusterReconciler{
		Client:           mgr.GetClient(),
		Scheme:           mgr.GetScheme(),
		Recorder:         mgr.GetEventRecorderFor("aragoracluster-controller"),
		APIEndpoint:      apiEndpoint,
		MetricsCollector: testCollector(),
	}).SetupWithManager(mgr)
	if err != nil {
		t.Fatalf("set up the AragoraCluster reconciler: %v", err)
	}
}

func setupInstanceReconciler(t *testing.T, mgr ctrl.Manager) {
	t.Helper()
	err := (&AragoraInstanceReconciler{
		Client:           mgr.GetClient(),
		Scheme:           mgr.GetScheme(),
		Recorder:         mgr.GetEventRecorderFor("aragorainstance-controller"),
		MetricsCollector: testCollector(),
	}).SetupWithManager(mgr)
	if err != nil {
		t.Fatalf("set up the AragoraInstance reconciler: %v", err)
	}
}

func setupPolicyReconciler(t *testing.T, mgr ctrl.Manager, apiEndpoint string) {
	t.Helper()
	err := (&AragoraPolicyReconciler{
		Client:           mgr.GetClient(),
		Scheme:           mgr.GetScheme(),
		Recorder:         mgr.GetEventRecorderFor("aragorapolicy-controller"),
		APIEndpoint:      apiEndpoint,
		MetricsCollector: testCollector(),
	}).SetupWithManager(mgr)
	if err != nil {
		t.Fatalf("set up the AragoraPolicy reconciler: %v", err)
	}
}

// managerRun tracks a manager started by startManager. done closes when Start
// returns; err is Start's result and may be read only after done has closed.
type managerRun struct {
	done chan struct{}
	err  error
}

// startManager runs mgr until the test ends and then waits for it to stop, so
// its listeners and leader lease are released before the next test starts.
func startManager(t *testing.T, mgr ctrl.Manager) *managerRun {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	run := &managerRun{done: make(chan struct{})}
	go func() {
		defer close(run.done)
		run.err = mgr.Start(ctx)
	}()
	t.Cleanup(func() {
		cancel()
		select {
		case <-run.done:
			if run.err != nil {
				t.Errorf("manager stopped with an error: %v", run.err)
			}
		case <-time.After(managerStopTimeout):
			t.Errorf("manager did not stop within %v", managerStopTimeout)
		}
	})
	return run
}

// eventually polls check until it returns nil, failing the test with the last
// error once eventuallyTimeout has passed.
func eventually(t *testing.T, what string, check func(ctx context.Context) error) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), eventuallyTimeout)
	defer cancel()
	began := time.Now()
	for {
		err := check(ctx)
		if err == nil {
			t.Logf("%s (after %v)", what, time.Since(began).Round(time.Millisecond))
			return
		}
		select {
		case <-ctx.Done():
			t.Fatalf("%s: still false after %v: %v", what, eventuallyTimeout, err)
		case <-time.After(pollInterval):
		}
	}
}

// eventuallyDeleted waits until obj is gone, which requires its reconciler to
// have removed the finalizer.
func eventuallyDeleted(t *testing.T, c client.Client, obj client.Object) {
	t.Helper()
	key := client.ObjectKeyFromObject(obj)
	eventually(t, fmt.Sprintf("%T %s deleted", obj, key), func(ctx context.Context) error {
		err := c.Get(ctx, key, obj)
		switch {
		case apierrors.IsNotFound(err):
			return nil
		case err != nil:
			return err
		default:
			return fmt.Errorf("still present with finalizers %v", obj.GetFinalizers())
		}
	})
}

// waitForCondition waits until obj carries condType with the given status and
// reason, and leaves the latest version of obj in place.
func waitForCondition(t *testing.T, c client.Client, obj client.Object,
	condType string, status metav1.ConditionStatus, reason string) {
	t.Helper()
	key := client.ObjectKeyFromObject(obj)
	what := fmt.Sprintf("%T %s has condition %s=%s/%s", obj, key, condType, status, reason)
	eventually(t, what, func(ctx context.Context) error {
		if err := c.Get(ctx, key, obj); err != nil {
			return err
		}
		conditions := conditionsOf(obj)
		cond := meta.FindStatusCondition(conditions, condType)
		if cond == nil || cond.Status != status || cond.Reason != reason {
			return fmt.Errorf("conditions are %+v", conditions)
		}
		return nil
	})
}

func conditionsOf(obj client.Object) []metav1.Condition {
	switch o := obj.(type) {
	case *aragorav1alpha1.AragoraCluster:
		return o.Status.Conditions
	case *aragorav1alpha1.AragoraInstance:
		return o.Status.Conditions
	case *aragorav1alpha1.AragoraPolicy:
		return o.Status.Conditions
	default:
		panic(fmt.Sprintf("conditionsOf: unsupported type %T", obj))
	}
}

// newNamespace creates a uniquely named namespace. envtest runs no namespace
// controller, so namespaces are never deleted; unique names keep tests apart.
func newNamespace(t *testing.T, c client.Client) string {
	t.Helper()
	ns := &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{GenerateName: "aragora-test-"}}
	if err := c.Create(context.Background(), ns); err != nil {
		t.Fatalf("create namespace: %v", err)
	}
	return ns.Name
}

func create(t *testing.T, c client.Client, obj client.Object) {
	t.Helper()
	if err := c.Create(context.Background(), obj); err != nil {
		t.Fatalf("create %T %s/%s: %v", obj, obj.GetNamespace(), obj.GetName(), err)
	}
	t.Logf("created %T %s/%s", obj, obj.GetNamespace(), obj.GetName())
}

// newTestCluster sets every resource quantity explicitly: the zero-valued
// Quantity fields serialize as "0", so the CRD defaults never apply.
func newTestCluster(namespace, name string) *aragorav1alpha1.AragoraCluster {
	requestsCPU := resource.MustParse("100m")
	requestsMemory := resource.MustParse("128Mi")
	return &aragorav1alpha1.AragoraCluster{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
		Spec: aragorav1alpha1.AragoraClusterSpec{
			Version:  "1.0.0",
			Replicas: 1,
			Resources: aragorav1alpha1.ResourceRequirements{
				Memory:         resource.MustParse("512Mi"),
				CPU:            resource.MustParse("500m"),
				RequestsCPU:    &requestsCPU,
				RequestsMemory: &requestsMemory,
			},
			Storage: aragorav1alpha1.StorageConfig{Size: resource.MustParse("1Gi")},
		},
	}
}

// assertControlledBy checks that a reconciler created obj, named name in the
// owner's namespace, with owner as its controller so garbage collection
// removes it with the owner.
func assertControlledBy(t *testing.T, c client.Client, owner client.Object, name string, obj client.Object) {
	t.Helper()
	key := client.ObjectKey{Namespace: owner.GetNamespace(), Name: name}
	if err := c.Get(context.Background(), key, obj); err != nil {
		t.Errorf("get %T %s: %v", obj, key, err)
		return
	}
	ref := metav1.GetControllerOf(obj)
	if ref == nil || ref.UID != owner.GetUID() {
		t.Errorf("%T %s is not controlled by %T %s: owners %v",
			obj, key, owner, owner.GetName(), obj.GetOwnerReferences())
	}
}
