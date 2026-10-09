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

package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"k8s.io/client-go/rest"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	aragorav1alpha1 "github.com/synaptent/aragora-operator/api/v1alpha1"
	"github.com/synaptent/aragora-operator/controllers"
	"github.com/synaptent/aragora-operator/internal/aragora"
	"github.com/synaptent/aragora-operator/internal/httpclient"
	"github.com/synaptent/aragora-operator/internal/metrics"
	"github.com/synaptent/aragora-operator/internal/observability"
)

var (
	scheme   = runtime.NewScheme()
	setupLog = ctrl.Log.WithName("setup")
)

// Tests replace these: controller-runtime allows one signal handler per
// process, and a test must not load the kubeconfig of the machine it runs on.
var (
	setupSignalHandler = ctrl.SetupSignalHandler
	loadKubeConfig     = ctrl.GetConfig
)

const (
	kubeconfigRetryInterval = 5 * time.Second
	telemetryFlushTimeout   = 5 * time.Second
)

func init() {
	utilruntime.Must(clientgoscheme.AddToScheme(scheme))
	utilruntime.Must(aragorav1alpha1.AddToScheme(scheme))
}

type options struct {
	metricsAddr               string
	probeAddr                 string
	pprofAddr                 string
	enableLeaderElection      bool
	aragoraAPIEndpoint        string
	aragoraAPIToken           string
	allowInsecureControlPlane bool
	kubeconfigWait            time.Duration
	zap                       zap.Options
}

// bindFlags registers the operator's flags on fs.
func bindFlags(fs *flag.FlagSet) *options {
	o := &options{zap: zap.Options{Development: true}}
	fs.StringVar(&o.metricsAddr, "metrics-bind-address", ":8080", "The address the metric endpoint binds to.")
	fs.StringVar(&o.probeAddr, "health-probe-bind-address", ":8081", "The address the probe endpoint binds to.")
	fs.StringVar(&o.pprofAddr, "pprof-addr", "",
		"The address the net/http/pprof endpoint (/debug/pprof/) binds to, for example 127.0.0.1:6060. "+
			"Empty (the default) disables it. It starts before the kubeconfig is loaded.")
	fs.BoolVar(&o.enableLeaderElection, "leader-elect", false,
		"Enable leader election for controller manager. "+
			"Enabling this will ensure there is only one active controller manager.")
	fs.StringVar(&o.aragoraAPIEndpoint, "aragora-api-endpoint", "https://aragora-control-plane:8443",
		"The Aragora control plane API endpoint: an absolute http(s) URL without a query or fragment.")
	fs.StringVar(&o.aragoraAPIToken, "aragora-api-token", "",
		"The Aragora API token for authentication.")
	fs.BoolVar(&o.allowInsecureControlPlane, "allow-insecure-control-plane", false,
		"Allow http:// Aragora control plane endpoints. Disabled by default.")
	fs.DurationVar(&o.kubeconfigWait, "kubeconfig-wait", 30*time.Second,
		"How long to keep retrying when no kubeconfig or in-cluster config can be loaded before exiting. "+
			"0 exits on the first failure.")
	o.zap.BindFlags(fs)
	return o
}

func main() {
	o := bindFlags(flag.CommandLine)
	flag.Parse()
	os.Exit(run(o))
}

// run starts the operator and returns the process exit code. Telemetry is
// flushed on every return path.
func run(o *options) int {
	ctrl.SetLogger(zap.New(zap.UseFlagOptions(&o.zap)))

	endpointLabel := httpclient.EndpointLabel(o.aragoraAPIEndpoint, "(unparsable URL)")
	if strings.HasPrefix(strings.ToLower(strings.TrimSpace(o.aragoraAPIEndpoint)), "http://") && !o.allowInsecureControlPlane {
		setupLog.Error(nil, "refusing insecure Aragora API endpoint without explicit opt-in", "endpoint", endpointLabel)
		return 1
	}
	// An empty endpoint turns control-plane calls off in every reconciler.
	if o.aragoraAPIEndpoint != "" {
		if err := aragora.ValidateEndpoint(o.aragoraAPIEndpoint); err != nil {
			setupLog.Error(err, "refusing invalid Aragora API endpoint", "endpoint", endpointLabel)
			return 1
		}
	}

	ctx := setupSignalHandler()

	if o.pprofAddr != "" {
		if _, err := observability.StartPprof(o.pprofAddr, setupLog); err != nil {
			setupLog.Error(err, "unable to start pprof server")
			return 1
		}
	}

	stopTelemetry := setupTelemetry(ctx)
	defer stopTelemetry()

	cfg, err := waitForKubeConfig(ctx, loadKubeConfig, o.kubeconfigWait, kubeconfigRetryInterval)
	if err != nil {
		return fail(err, "unable to get kubeconfig")
	}

	// Initialize metrics collector
	metricsCollector := metrics.NewCollector()
	metricsCollector.Register()

	mgr, err := ctrl.NewManager(cfg, ctrl.Options{
		Scheme: scheme,
		Metrics: metricsserver.Options{
			BindAddress: o.metricsAddr,
		},
		HealthProbeBindAddress: o.probeAddr,
		LeaderElection:         o.enableLeaderElection,
		LeaderElectionID:       "aragora-operator-leader-election",
	})
	if err != nil {
		return fail(err, "unable to start manager")
	}

	if err := setupControllers(mgr, o, metricsCollector); err != nil {
		return fail(err, "unable to create controller")
	}

	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		return fail(err, "unable to set up health check")
	}
	if err := mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {
		return fail(err, "unable to set up ready check")
	}

	setupLog.Info("starting manager")
	if err := mgr.Start(ctx); err != nil {
		return fail(err, "problem running manager")
	}
	return 0
}

// setupTelemetry turns on Sentry and OpenTelemetry tracing when their
// environment variables are set. A telemetry failure is logged and the
// operator runs without it. The returned function flushes and stops both.
func setupTelemetry(ctx context.Context) func() {
	if _, err := observability.InitSentry(setupLog); err != nil {
		setupLog.Error(err, "Sentry disabled: initialisation failed")
	}
	shutdownTracing, err := observability.SetupTracing(ctx, setupLog)
	if err != nil {
		setupLog.Error(err, "OpenTelemetry tracing disabled: setup failed")
		shutdownTracing = func(context.Context) error { return nil }
	}
	return func() {
		flushCtx, cancel := context.WithTimeout(context.Background(), telemetryFlushTimeout)
		defer cancel()
		if err := shutdownTracing(flushCtx); err != nil {
			setupLog.Error(err, "flushing traces failed")
		}
		observability.FlushSentry(telemetryFlushTimeout)
	}
}

func setupControllers(mgr ctrl.Manager, o *options, metricsCollector *metrics.Collector) error {
	if err := (&controllers.AragoraClusterReconciler{
		Client:           mgr.GetClient(),
		Scheme:           mgr.GetScheme(),
		Recorder:         mgr.GetEventRecorderFor("aragoracluster-controller"),
		APIEndpoint:      o.aragoraAPIEndpoint,
		APIToken:         o.aragoraAPIToken,
		MetricsCollector: metricsCollector,
	}).SetupWithManager(mgr); err != nil {
		return fmt.Errorf("AragoraCluster: %w", err)
	}

	if err := (&controllers.AragoraInstanceReconciler{
		Client:           mgr.GetClient(),
		Scheme:           mgr.GetScheme(),
		Recorder:         mgr.GetEventRecorderFor("aragorainstance-controller"),
		MetricsCollector: metricsCollector,
	}).SetupWithManager(mgr); err != nil {
		return fmt.Errorf("AragoraInstance: %w", err)
	}

	if err := (&controllers.AragoraPolicyReconciler{
		Client:           mgr.GetClient(),
		Scheme:           mgr.GetScheme(),
		Recorder:         mgr.GetEventRecorderFor("aragorapolicy-controller"),
		APIEndpoint:      o.aragoraAPIEndpoint,
		APIToken:         o.aragoraAPIToken,
		MetricsCollector: metricsCollector,
	}).SetupWithManager(mgr); err != nil {
		return fmt.Errorf("AragoraPolicy: %w", err)
	}
	return nil
}

// fail logs err, reports it to Sentry (when enabled) and returns exit code 1.
func fail(err error, msg string) int {
	setupLog.Error(err, msg)
	observability.CaptureError(fmt.Errorf("%s: %w", msg, err))
	return 1
}

// waitForKubeConfig calls load until it returns a config, retrying every
// interval for up to wait. It gives up early when ctx is done. Listeners
// started before it, such as the pprof server, keep serving meanwhile, so the
// process can be inspected even when it has no cluster to talk to.
func waitForKubeConfig(ctx context.Context, load func() (*rest.Config, error), wait, interval time.Duration) (*rest.Config, error) {
	deadline := time.Now().Add(wait)
	for attempt := 1; ; attempt++ {
		cfg, err := load()
		if err == nil {
			return cfg, nil
		}
		remaining := time.Until(deadline)
		if remaining <= 0 || ctx.Err() != nil {
			return nil, fmt.Errorf("no kubeconfig after %d attempt(s) in %s: %w", attempt, wait, err)
		}
		setupLog.Info("kubeconfig not available, retrying", "error", err.Error(), "retryIn", interval.String(), "giveUpIn", remaining.Round(time.Second).String())
		timer := time.NewTimer(min(interval, remaining))
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil, errors.Join(fmt.Errorf("no kubeconfig after %d attempt(s): %w", attempt, err), ctx.Err())
		case <-timer.C:
		}
	}
}
