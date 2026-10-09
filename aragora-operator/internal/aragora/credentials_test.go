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

package aragora

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/sony/gobreaker/v2"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"

	"github.com/synaptent/aragora-operator/internal/httpclient"
)

// The tests in this file read what the shared API clients log through
// controller-runtime's global logger. That logger honours only the first
// SetLogger call in a process, so one capturing logger is installed lazily
// (a test binary run for other tests keeps its own logger) and these tests
// must not run in parallel with each other or with tests that set it.
var (
	clientLogsOnce sync.Once
	clientLogs     lockedBuffer
)

type lockedBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *lockedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *lockedBuffer) drain() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	s := b.buf.String()
	b.buf.Reset()
	return s
}

// captureClientLogs starts collecting the clients' JSON log lines and returns
// a function that reports what was logged since.
func captureClientLogs(t *testing.T) func() string {
	t.Helper()
	clientLogsOnce.Do(func() {
		logf.SetLogger(zap.New(zap.UseDevMode(true), zap.JSONEncoder(), zap.WriteTo(&clientLogs)))
	})
	clientLogs.drain()
	return clientLogs.drain
}

const syntheticUser = "synthetic-user"

// secretEndpoint is a control-plane endpoint that carries synthetic
// credentials in its userinfo and query.
type secretEndpoint struct {
	url        string
	label      string // the credential-free breaker label it must be logged as
	password   string
	queryToken string
}

func newSecretEndpoint(t *testing.T, serverURL string) secretEndpoint {
	t.Helper()
	u, err := url.Parse(serverURL)
	if err != nil {
		t.Fatalf("parse %q: %v", serverURL, err)
	}
	ep := secretEndpoint{
		label:      u.String(),
		password:   "SYNTHETIC_PASSWORD_" + rand.Text(),
		queryToken: "SYNTHETIC_QUERY_TOKEN_" + rand.Text(),
	}
	u.User = url.UserPassword(syntheticUser, ep.password)
	u.RawQuery = url.Values{"token": {ep.queryToken}}.Encode()
	ep.url = u.String()
	return ep
}

// assertAbsent fails t if text contains the endpoint's password, username or
// query token.
func (ep secretEndpoint) assertAbsent(t *testing.T, what, text string) {
	t.Helper()
	for _, secret := range []struct{ name, value string }{
		{"password", ep.password},
		{"username", syntheticUser},
		{"query token", ep.queryToken},
	} {
		if strings.Contains(text, secret.value) {
			t.Errorf("the endpoint %s appears in %s:\n%s", secret.name, what, text)
		}
	}
}

// checkClientLogs fails t if the logs reveal the endpoint's credentials, if a
// client log line lacks the credential-free breaker label, or if no line
// carries one of msgs. It returns the client's log lines.
func checkClientLogs(t *testing.T, logs string, ep secretEndpoint, msgs ...string) []map[string]any {
	t.Helper()
	ep.assertAbsent(t, "the client logs", logs)
	var lines []map[string]any
	seen := map[string]bool{}
	for _, raw := range strings.Split(strings.TrimSpace(logs), "\n") {
		var line map[string]any
		if err := json.Unmarshal([]byte(raw), &line); err != nil {
			t.Fatalf("log line is not JSON (%v): %q", err, raw)
		}
		if line["logger"] != "aragora-client" {
			continue
		}
		lines = append(lines, line)
		seen[fmt.Sprint(line["msg"])] = true
		if line["breaker"] != ep.label {
			t.Errorf("%q log line has breaker=%v, want %q", line["msg"], line["breaker"], ep.label)
		}
	}
	for _, msg := range msgs {
		if !seen[msg] {
			t.Errorf("no %q line in the client logs:\n%s", msg, logs)
		}
	}
	return lines
}

// scriptedControlPlane answers the i-th request with statuses[i] and repeats
// the last status after that. 503 answers carry Retry-After: 0, so retries
// do not wait.
func scriptedControlPlane(t *testing.T, statuses ...int) (*httptest.Server, *atomic.Int32) {
	t.Helper()
	var hits atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		status := statuses[min(int(hits.Add(1)), len(statuses))-1]
		if status == http.StatusServiceUnavailable {
			w.Header().Set("Retry-After", "0")
		}
		w.WriteHeader(status)
		if status == http.StatusOK {
			_, _ = io.WriteString(w, "[]")
		}
	}))
	t.Cleanup(srv.Close)
	return srv, &hits
}

func TestClientLogsOmitEndpointCredentialsOnSuccess(t *testing.T) {
	read := captureClientLogs(t)
	srv, _ := scriptedControlPlane(t, http.StatusOK)
	ep := newSecretEndpoint(t, srv.URL)

	if _, err := NewClient(ep.url, "").GetAgentStatus(context.Background()); err != nil {
		t.Fatalf("GetAgentStatus: %v", err)
	}
	checkClientLogs(t, read(), ep, "performing request")
}

func TestClientLogsOmitEndpointCredentialsOnRetry(t *testing.T) {
	read := captureClientLogs(t)
	srv, hits := scriptedControlPlane(t, http.StatusServiceUnavailable, http.StatusServiceUnavailable, http.StatusOK)
	ep := newSecretEndpoint(t, srv.URL)

	if _, err := NewClient(ep.url, "").GetAgentStatus(context.Background()); err != nil {
		t.Fatalf("GetAgentStatus after two 503 answers: %v", err)
	}
	if hits.Load() != 3 {
		t.Fatalf("control plane saw %d requests, want 3", hits.Load())
	}
	checkClientLogs(t, read(), ep, "performing request", "retrying request")
}

func TestClientLogsAndErrorsOmitEndpointCredentialsOnFailure(t *testing.T) {
	read := captureClientLogs(t)
	srv, hits := scriptedControlPlane(t, http.StatusServiceUnavailable)
	ep := newSecretEndpoint(t, srv.URL)

	_, err := NewClient(ep.url, "").GetAgentStatus(context.Background())
	if err == nil {
		t.Fatal("GetAgentStatus succeeded against a control plane that always answers 503")
	}
	if want := int32(httpclient.DefaultConfig("").RetryMax + 1); hits.Load() != want {
		t.Fatalf("control plane saw %d requests, want %d", hits.Load(), want)
	}
	// Reconcilers log this error and copy it into status conditions and events.
	ep.assertAbsent(t, "the returned error", err.Error())
	checkClientLogs(t, read(), ep, "performing request", "retrying request")
}

func TestClientLogsAndErrorsOmitEndpointCredentialsWhenBreakerOpens(t *testing.T) {
	read := captureClientLogs(t)
	srv, _ := scriptedControlPlane(t, http.StatusServiceUnavailable)
	ep := newSecretEndpoint(t, srv.URL)
	c := NewClient(ep.url, "")

	for i := 1; i <= int(httpclient.DefaultConfig("").FailMax); i++ {
		if _, err := c.GetAgentStatus(context.Background()); err == nil || errors.Is(err, gobreaker.ErrOpenState) {
			t.Fatalf("call %d: err = %v, want a request failure", i, err)
		}
	}
	_, err := c.GetAgentStatus(context.Background())
	if !errors.Is(err, gobreaker.ErrOpenState) {
		t.Fatalf("call with the breaker open: err = %v, want ErrOpenState", err)
	}
	ep.assertAbsent(t, "the open-breaker error", err.Error())

	opened := false
	for _, line := range checkClientLogs(t, read(), ep, "circuit breaker state changed") {
		if line["msg"] == "circuit breaker state changed" && line["to"] == "open" {
			opened = true
		}
	}
	if !opened {
		t.Error("no breaker state change to open was logged")
	}
}

// TestClientRequestErrorOmitsMalformedEndpointCredentials checks the error for
// an endpoint the request cannot even be built from: url.Parse quotes the
// whole raw URL, password included, in its error.
func TestClientRequestErrorOmitsMalformedEndpointCredentials(t *testing.T) {
	password := "SYNTHETIC_PASSWORD_" + rand.Text()
	endpoint := "https://" + syntheticUser + ":" + password + "@[::1"

	_, err := NewClient(endpoint, "").GetHealth(context.Background())
	if err == nil {
		t.Fatal("GetHealth succeeded with a malformed endpoint")
	}
	for _, secret := range []string{password, syntheticUser} {
		if strings.Contains(err.Error(), secret) {
			t.Errorf("the request error reveals %q from the endpoint: %v", secret, err)
		}
	}
}
