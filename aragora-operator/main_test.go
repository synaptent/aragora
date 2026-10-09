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
	"bytes"
	"context"
	"crypto/rand"
	"errors"
	"flag"
	"strings"
	"sync"
	"testing"
	"time"

	"k8s.io/client-go/rest"
)

// flagHelpBlock returns the lines --help prints for one flag: its "  -name"
// line and the indented usage lines under it.
func flagHelpBlock(help, name string) string {
	var block []string
	in := false
	for _, line := range strings.Split(help, "\n") {
		switch {
		case strings.HasPrefix(line, "  -"+name+" ") || line == "  -"+name:
			in = true
		case strings.HasPrefix(line, "  -"):
			in = false
		}
		if in {
			block = append(block, line)
		}
	}
	return strings.Join(block, "\n")
}

func TestHelpListsPprofAddrWithEmptyDefault(t *testing.T) {
	fs := flag.NewFlagSet("aragora-operator", flag.ContinueOnError)
	var out bytes.Buffer
	fs.SetOutput(&out)
	bindFlags(fs)

	if err := fs.Parse([]string{"--help"}); !errors.Is(err, flag.ErrHelp) {
		t.Fatalf("Parse(--help) = %v, want flag.ErrHelp", err)
	}
	help := out.String()

	for _, name := range []string{"pprof-addr", "metrics-bind-address", "health-probe-bind-address", "kubeconfig-wait"} {
		if flagHelpBlock(help, name) == "" {
			t.Fatalf("--help does not list -%s:\n%s", name, help)
		}
	}
	pprof := flagHelpBlock(help, "pprof-addr")
	if strings.Contains(pprof, "(default") {
		t.Fatalf("-pprof-addr shows a default, want none (empty = off):\n%s", pprof)
	}
	if f := fs.Lookup("pprof-addr"); f == nil || f.DefValue != "" {
		t.Fatalf("-pprof-addr default = %+v, want empty", f)
	}
	t.Logf("--help lists:\n%s", pprof)
}

func TestPprofAddrFlagAcceptsBothSpellings(t *testing.T) {
	for _, arg := range []string{"--pprof-addr=127.0.0.1:6060", "-pprof-addr=127.0.0.1:6060"} {
		fs := flag.NewFlagSet("aragora-operator", flag.ContinueOnError)
		o := bindFlags(fs)
		if err := fs.Parse([]string{arg}); err != nil {
			t.Fatalf("Parse(%s): %v", arg, err)
		}
		if o.pprofAddr != "127.0.0.1:6060" {
			t.Fatalf("Parse(%s): pprofAddr = %q", arg, o.pprofAddr)
		}
	}
}

func TestWaitForKubeConfigReturnsOnceAvailable(t *testing.T) {
	want := &rest.Config{Host: "https://example.invalid"}
	calls := 0
	load := func() (*rest.Config, error) {
		calls++
		if calls < 3 {
			return nil, errors.New("no kubeconfig yet")
		}
		return want, nil
	}

	got, err := waitForKubeConfig(context.Background(), load, time.Second, time.Millisecond)
	if err != nil || got != want {
		t.Fatalf("waitForKubeConfig = %v, %v; want the config on the third attempt", got, err)
	}
	if calls != 3 {
		t.Fatalf("loader called %d times, want 3", calls)
	}
}

func TestWaitForKubeConfigGivesUpAfterWait(t *testing.T) {
	loadErr := errors.New("no configuration has been provided")
	calls := 0
	load := func() (*rest.Config, error) {
		calls++
		return nil, loadErr
	}

	start := time.Now()
	_, err := waitForKubeConfig(context.Background(), load, 50*time.Millisecond, 10*time.Millisecond)
	if !errors.Is(err, loadErr) {
		t.Fatalf("waitForKubeConfig error = %v, want it to wrap the last load error", err)
	}
	if calls < 2 {
		t.Fatalf("loader called %d times, want retries within the wait", calls)
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Fatalf("waitForKubeConfig took %s, want about the 50ms wait", elapsed)
	}
}

func TestWaitForKubeConfigZeroWaitTriesOnce(t *testing.T) {
	calls := 0
	load := func() (*rest.Config, error) {
		calls++
		return nil, errors.New("missing")
	}
	if _, err := waitForKubeConfig(context.Background(), load, 0, time.Millisecond); err == nil {
		t.Fatal("waitForKubeConfig succeeded, want an error")
	}
	if calls != 1 {
		t.Fatalf("loader called %d times with a zero wait, want 1", calls)
	}
}

func TestWaitForKubeConfigStopsOnCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	calls := 0
	load := func() (*rest.Config, error) {
		calls++
		cancel()
		return nil, errors.New("missing")
	}
	start := time.Now()
	if _, err := waitForKubeConfig(ctx, load, time.Minute, 10*time.Second); err == nil {
		t.Fatal("waitForKubeConfig succeeded, want an error")
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Fatalf("waitForKubeConfig ignored cancellation for %s", elapsed)
	}
}

// runLogs receives the log output of every run call in this package. run
// installs the process-wide logger and controller-runtime keeps only the
// first one it is given, so every test calls run through runOperator, which
// points the logger here, and none of them may run in parallel.
var runLogs syncBuffer

type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *syncBuffer) drain() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	s := b.buf.String()
	b.buf.Reset()
	return s
}

// operatorRun is what one call to run did.
type operatorRun struct {
	code            int
	logs            string
	kubeconfigLoads int
}

// runOperator calls run with the given command-line flags and reports its
// exit code, its log output and how often it tried to load a kubeconfig.
// The kubeconfig loader always fails and --kubeconfig-wait is 0, so a run
// that gets past its endpoint checks stops there, before it creates a
// manager or any API client.
func runOperator(t *testing.T, args ...string) operatorRun {
	t.Helper()
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
	t.Setenv("SENTRY_DSN", "")
	signalHandler, kubeConfig := setupSignalHandler, loadKubeConfig
	t.Cleanup(func() { setupSignalHandler, loadKubeConfig = signalHandler, kubeConfig })
	var r operatorRun
	setupSignalHandler = t.Context
	loadKubeConfig = func() (*rest.Config, error) {
		r.kubeconfigLoads++
		return nil, errors.New("no kubeconfig in unit tests")
	}

	fs := flag.NewFlagSet("aragora-operator", flag.ContinueOnError)
	o := bindFlags(fs)
	if err := fs.Parse(append([]string{"--kubeconfig-wait=0"}, args...)); err != nil {
		t.Fatalf("parse flags: %v", err)
	}
	o.zap.DestWriter = &runLogs
	runLogs.drain()
	r.code = run(o)
	r.logs = runLogs.drain()
	return r
}

// errorLines returns the error entries in development-mode zap output.
func errorLines(logs string) []string {
	var out []string
	for _, line := range strings.Split(logs, "\n") {
		if strings.Contains(line, "\tERROR\t") {
			out = append(out, line)
		}
	}
	return out
}

// TestRunRefusesUnusableAPIEndpoints checks the startup refusal of control-
// plane endpoints the API client cannot address the API through: with a
// query or fragment (even an empty one) the API path would land inside it,
// and the client only speaks http(s) to a host. run must exit 1 before it
// loads a kubeconfig, so no manager or client exists yet, and log one error
// that names the endpoint only by its credential-free label.
func TestRunRefusesUnusableAPIEndpoints(t *testing.T) {
	marker := "SYNTHETIC_MARKER_" + rand.Text()
	password := "SYNTHETIC_PASSWORD_" + rand.Text()
	userinfo := "synthetic-user:" + password + "@"
	for _, tc := range []struct{ name, endpoint, label string }{
		{"query", "https://cp.invalid:8443/?token=" + marker, "https://cp.invalid:8443/"},
		{"query after a quoted value", "https://cp.invalid:8443/base?filter='all'&token=" + marker, "https://cp.invalid:8443/base"},
		{"bare question mark", "https://cp.invalid:8443/base?", "https://cp.invalid:8443/base"},
		{"fragment", "https://cp.invalid:8443/base#" + marker, "https://cp.invalid:8443/base"},
		{"bare hash", "https://cp.invalid:8443/base#", "https://cp.invalid:8443/base"},
		{"userinfo and query", "https://" + userinfo + "cp.invalid:8443/?token=" + marker, "https://cp.invalid:8443/"},
		{"userinfo and fragment", "https://" + userinfo + "cp.invalid:8443/base#" + marker, "https://cp.invalid:8443/base"},
		{"no host", "https://" + userinfo + "/base", "(unparsable URL)"},
		{"no scheme", "cp.invalid:8443/" + marker, "(unparsable URL)"},
		{"non-http scheme", "ftp://" + userinfo + "cp.invalid:8443/base", "ftp://cp.invalid:8443/base"},
		{"unparsable", "https://" + userinfo + "[::1", "(unparsable URL)"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := runOperator(t, "--aragora-api-endpoint="+tc.endpoint)
			if r.code != 1 {
				t.Errorf("run = %d, want 1", r.code)
			}
			if r.kubeconfigLoads != 0 {
				t.Errorf("run went on to load a kubeconfig (%d times), so it would create a manager and clients", r.kubeconfigLoads)
			}
			errs := errorLines(r.logs)
			if len(errs) != 1 || !strings.Contains(errs[0], "refusing invalid Aragora API endpoint") ||
				!strings.Contains(errs[0], `"endpoint": "`+tc.label+`"`) {
				t.Errorf("want one error refusing the endpoint with label %q, got:\n%s", tc.label, r.logs)
			}
			for _, secret := range []string{marker, password, "synthetic-user"} {
				if strings.Contains(r.logs, secret) {
					t.Errorf("the startup log reveals %q from the endpoint:\n%s", secret, r.logs)
				}
			}
		})
	}
}

// TestRunAcceptsPlainAndUserinfoAPIEndpoints checks that the endpoint forms
// the operator supports still pass the startup checks and reach the next
// step, loading the kubeconfig. An empty endpoint turns control-plane calls
// off in every reconciler.
func TestRunAcceptsPlainAndUserinfoAPIEndpoints(t *testing.T) {
	password := "SYNTHETIC_PASSWORD_" + rand.Text()
	for _, tc := range []struct {
		name string
		args []string
	}{
		{"plain", []string{"--aragora-api-endpoint=https://cp.invalid:8443/base"}},
		{"userinfo", []string{"--aragora-api-endpoint=https://synthetic-user:" + password + "@cp.invalid:8443/base"}},
		{"insecure with opt-in", []string{"--aragora-api-endpoint=http://cp.invalid:8080/base", "--allow-insecure-control-plane"}},
		{"empty", []string{"--aragora-api-endpoint="}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := runOperator(t, tc.args...)
			if r.code != 1 || r.kubeconfigLoads != 1 || !strings.Contains(r.logs, "unable to get kubeconfig") {
				t.Errorf("run = %d after %d kubeconfig loads, want 1 after the failed load:\n%s", r.code, r.kubeconfigLoads, r.logs)
			}
			if strings.Contains(r.logs, "refusing") {
				t.Errorf("run refused an accepted endpoint:\n%s", r.logs)
			}
			for _, secret := range []string{password, "synthetic-user"} {
				if strings.Contains(r.logs, secret) {
					t.Errorf("the startup log reveals %q from the endpoint:\n%s", secret, r.logs)
				}
			}
		})
	}
}

// TestRunRefusesInsecureEndpointWithoutLoggingCredentials runs the operator
// with an http:// endpoint that carries synthetic credentials.
func TestRunRefusesInsecureEndpointWithoutLoggingCredentials(t *testing.T) {
	const password, queryToken = "SYNTHETIC_PASSWORD_main_8d1f", "SYNTHETIC_QUERY_TOKEN_main_8d1f"
	r := runOperator(t, "--aragora-api-endpoint=http://synthetic-user:"+password+"@control-plane.invalid:8080/base?token="+queryToken)

	if r.code != 1 {
		t.Fatalf("run with an insecure endpoint = %d, want 1", r.code)
	}
	text := r.logs
	for _, want := range []string{"refusing insecure Aragora API endpoint", `"endpoint": "http://control-plane.invalid:8080/base"`} {
		if !strings.Contains(text, want) {
			t.Errorf("the startup log lacks %s:\n%s", want, text)
		}
	}
	for _, secret := range []string{password, "synthetic-user", queryToken} {
		if strings.Contains(text, secret) {
			t.Errorf("the startup log reveals %q from the endpoint:\n%s", secret, text)
		}
	}
}
