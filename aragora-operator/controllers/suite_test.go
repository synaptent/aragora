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
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"sync"
	"syscall"
	"testing"
	"time"

	"github.com/go-logr/logr"
	"github.com/go-logr/logr/funcr"
	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"k8s.io/client-go/rest"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/envtest"

	aragorav1alpha1 "github.com/synaptent/aragora-operator/api/v1alpha1"
	"github.com/synaptent/aragora-operator/internal/metrics"
)

// testEnv owns the single kube-apiserver and etcd pair shared by every test in
// this package. It starts on first use, so `go test -list`, `-short` runs and
// runs that select no envtest test never launch a control plane.
var testEnv controlPlane

type controlPlane struct {
	mu      sync.Mutex
	env     *envtest.Environment
	cfg     *rest.Config
	client  client.Client
	err     error
	stopped bool
}

var (
	testScheme = runtime.NewScheme()

	collectorOnce sync.Once
	collector     *metrics.Collector
)

func init() {
	utilruntime.Must(clientgoscheme.AddToScheme(testScheme))
	utilruntime.Must(aragorav1alpha1.AddToScheme(testScheme))
}

func TestMain(m *testing.M) {
	os.Exit(runTests(m))
}

func runTests(m *testing.M) int {
	flag.Parse()
	ctrl.SetLogger(errorLogger())

	// envtest starts kube-apiserver and etcd in their own process group, so
	// nothing else stops them when this binary exits. Stop them on every exit
	// path the binary can observe: a normal return (passing or failing tests),
	// SIGINT/SIGTERM, a panicking test (see stopControlPlaneOnPanic), and
	// shortly before the -timeout alarm panics.
	defer testEnv.Stop()
	cancelSignals := stopOnSignal()
	defer cancelSignals()
	cancelTimeoutGuard := stopBeforeTimeout()
	defer cancelTimeoutGuard()

	return m.Run()
}

// requireEnvtest skips the calling test under -short and otherwise returns the
// shared envtest API server, starting it on first use.
func requireEnvtest(t *testing.T) (*rest.Config, client.Client) {
	t.Helper()
	if testing.Short() {
		t.Skip("envtest test skipped in -short mode")
	}
	cfg, c, err := testEnv.Start()
	if err != nil {
		t.Fatal(err)
	}
	return cfg, c
}

// stopControlPlaneOnPanic must be deferred by every test that uses envtest: a
// panicking test crashes the binary without running TestMain's deferred Stop.
func stopControlPlaneOnPanic() {
	if r := recover(); r != nil {
		testEnv.Stop()
		panic(r)
	}
}

func (p *controlPlane) Start() (*rest.Config, client.Client, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	switch {
	case p.stopped:
		return nil, nil, errors.New("the envtest control plane has already been stopped")
	case p.err != nil:
		return nil, nil, p.err
	case p.client != nil:
		return p.cfg, p.client, nil
	}

	assets := os.Getenv("KUBEBUILDER_ASSETS")
	if assets == "" {
		p.err = errors.New("KUBEBUILDER_ASSETS is not set: point it at the setup-envtest 1.29.x binaries " +
			"(see README.md, Test) or pass -short to skip the envtest tests")
		return nil, nil, p.err
	}
	p.env = &envtest.Environment{
		BinaryAssetsDirectory: assets,
		CRDDirectoryPaths:     []string{filepath.Join("..", "config", "crd", "bases")},
		ErrorIfCRDPathMissing: true,
		Scheme:                testScheme,
	}
	began := time.Now()
	cfg, err := p.env.Start()
	if err != nil {
		p.err = fmt.Errorf("start the envtest control plane from %s: %w", assets, err)
		return nil, nil, p.err
	}
	c, err := client.New(cfg, client.Options{Scheme: testScheme})
	if err != nil {
		p.err = fmt.Errorf("create a client for the envtest API server: %w", err)
		return nil, nil, p.err
	}
	fmt.Fprintf(os.Stderr, "envtest: control plane from %s up in %v at %s\n",
		assets, time.Since(began).Round(time.Millisecond), cfg.Host)
	p.cfg, p.client = cfg, c
	return cfg, c, nil
}

// Stop is idempotent and safe to call from any goroutine. It also cleans up
// after a Start that failed half way, for example while installing CRDs.
func (p *controlPlane) Stop() {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.stopped {
		return
	}
	p.stopped = true
	if p.env == nil {
		return
	}
	began := time.Now()
	if err := stopEnvironment(p.env); err != nil {
		fmt.Fprintf(os.Stderr, "envtest: stopping the control plane: %v\n", err)
		return
	}
	fmt.Fprintf(os.Stderr, "envtest: control plane stopped in %v\n", time.Since(began).Round(time.Millisecond))
}

// stopEnvironment turns a panic into an error: envtest's Stop dereferences the
// etcd process state, which is nil when etcd never launched.
func stopEnvironment(env *envtest.Environment) (err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("envtest Stop panicked: %v", r)
		}
	}()
	return env.Stop()
}

func stopOnSignal() (cancel func()) {
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	done := make(chan struct{})
	go func() {
		select {
		case sig := <-signals:
			fmt.Fprintf(os.Stderr, "envtest: received %v, stopping the control plane\n", sig)
			testEnv.Stop()
			os.Exit(1)
		case <-done:
		}
	}()
	return func() {
		signal.Stop(signals)
		close(done)
	}
}

// stopBeforeTimeout stops the control plane shortly before the testing
// package's -timeout alarm panics, because that panic exits without running
// defers. A graceful stop takes about a second; the margin leaves room for a
// slow one without cutting long runs short.
func stopBeforeTimeout() (cancel func()) {
	timeout := testTimeout()
	if timeout <= 0 {
		return func() {}
	}
	margin := min(max(timeout/20, 5*time.Second), 15*time.Second, timeout/2)
	timer := time.AfterFunc(timeout-margin, func() {
		fmt.Fprintf(os.Stderr, "envtest: -timeout %v is about to expire, stopping the control plane\n", timeout)
		testEnv.Stop()
	})
	return func() { timer.Stop() }
}

func testTimeout() time.Duration {
	f := flag.Lookup("test.timeout")
	if f == nil {
		return 0
	}
	getter, ok := f.Value.(flag.Getter)
	if !ok {
		return 0
	}
	timeout, _ := getter.Get().(time.Duration)
	return timeout
}

// errorLogger keeps controller-runtime's per-reconcile info logs out of the
// verbose test output and still prints every logged error.
func errorLogger() logr.Logger {
	sink := funcr.New(func(prefix, args string) {
		fmt.Fprintln(os.Stderr, prefix, args)
	}, funcr.Options{}).GetSink()
	return logr.New(errorsOnlySink{sink})
}

type errorsOnlySink struct{ logr.LogSink }

func (errorsOnlySink) Enabled(int) bool { return false }

func (s errorsOnlySink) WithValues(keysAndValues ...any) logr.LogSink {
	return errorsOnlySink{s.LogSink.WithValues(keysAndValues...)}
}

func (s errorsOnlySink) WithName(name string) logr.LogSink {
	return errorsOnlySink{s.LogSink.WithName(name)}
}

// testCollector returns the operator's Prometheus collector, registered once
// with controller-runtime's global registry (registering twice panics).
func testCollector() *metrics.Collector {
	collectorOnce.Do(func() {
		collector = metrics.NewCollector()
		collector.Register()
	})
	return collector
}
