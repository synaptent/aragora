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

package httpclient

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/sony/gobreaker/v2"
)

// fastConfig keeps the production retry and breaker logic but shrinks every
// wait so the tests run in milliseconds.
func fastConfig(t *testing.T) Config {
	t.Helper()
	cfg := DefaultConfig(t.Name())
	cfg.RetryWaitMin = time.Millisecond
	cfg.RetryWaitMax = 5 * time.Millisecond
	cfg.ResetTimeout = 200 * time.Millisecond
	return cfg
}

// scriptedServer answers with statuses[i] on the i-th request and with the
// last status after that. It counts every request that reaches it.
type scriptedServer struct {
	*httptest.Server
	hits atomic.Int32

	mu       sync.Mutex
	statuses []int
	bodies   []string
}

func newScriptedServer(t *testing.T, statuses ...int) *scriptedServer {
	t.Helper()
	s := &scriptedServer{statuses: statuses}
	s.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := int(s.hits.Add(1))
		body, _ := io.ReadAll(r.Body)
		s.mu.Lock()
		s.bodies = append(s.bodies, string(body))
		status := s.statuses[min(n, len(s.statuses))-1]
		s.mu.Unlock()
		w.WriteHeader(status)
		_, _ = w.Write([]byte(http.StatusText(status)))
	}))
	t.Cleanup(s.Close)
	return s
}

func (s *scriptedServer) setStatuses(statuses ...int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.statuses = statuses
	s.hits.Store(0)
}

func get(t *testing.T, c *Client, url string) (*http.Response, error) {
	t.Helper()
	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, url, nil)
	if err != nil {
		t.Fatalf("build request: %v", err)
	}
	resp, err := c.Do(req)
	if resp != nil {
		t.Cleanup(func() { _ = resp.Body.Close() })
	}
	return resp, err
}

// TestHTTPClientRetryRecoversAfter503 checks that transient server errors are
// retried with backoff: the server fails three times and then answers 200,
// and the caller only sees the 200.
func TestHTTPClientRetryRecoversAfter503(t *testing.T) {
	for _, status := range []int{http.StatusInternalServerError, http.StatusServiceUnavailable} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			srv := newScriptedServer(t, status, status, status, http.StatusOK)
			c := New(fastConfig(t))

			resp, err := get(t, c, srv.URL+"/api/control-plane/health")
			if err != nil {
				t.Fatalf("Do after three %d responses: %v", status, err)
			}
			if resp.StatusCode != http.StatusOK {
				t.Fatalf("status = %d, want 200", resp.StatusCode)
			}
			if got := srv.hits.Load(); got != 4 {
				t.Fatalf("server saw %d requests, want 4 (3 failures + 1 success)", got)
			}
			if got := c.State(); got != gobreaker.StateClosed {
				t.Fatalf("breaker state = %s after a recovered call, want closed", got)
			}
			t.Logf("%d x3 then 200: recovered after %d attempts", status, srv.hits.Load())
		})
	}
}

// TestHTTPClientRetryResendsBody checks that a retried PUT sends the same body
// on every attempt.
func TestHTTPClientRetryResendsBody(t *testing.T) {
	srv := newScriptedServer(t, http.StatusBadGateway, http.StatusOK)
	c := New(fastConfig(t))

	const payload = `{"id":"policy-1"}`
	req, err := http.NewRequestWithContext(context.Background(), http.MethodPut, srv.URL+"/api/control-plane/policies/policy-1", bytes.NewBufferString(payload))
	if err != nil {
		t.Fatalf("build request: %v", err)
	}
	resp, err := c.Do(req)
	if err != nil {
		t.Fatalf("Do: %v", err)
	}
	_ = resp.Body.Close()

	srv.mu.Lock()
	defer srv.mu.Unlock()
	if len(srv.bodies) != 2 || srv.bodies[0] != payload || srv.bodies[1] != payload {
		t.Fatalf("bodies received = %q, want the payload twice", srv.bodies)
	}
}

// TestHTTPClientRetryGivesUpAfterRetryMax checks that retries are bounded: a
// server that always fails sees exactly RetryMax+1 requests per call and the
// caller gets an error, not the 500 response.
func TestHTTPClientRetryGivesUpAfterRetryMax(t *testing.T) {
	srv := newScriptedServer(t, http.StatusInternalServerError)
	cfg := fastConfig(t)
	c := New(cfg)

	resp, err := get(t, c, srv.URL)
	if err == nil {
		t.Fatalf("Do succeeded with status %d, want an error", resp.StatusCode)
	}
	if want := int32(cfg.RetryMax + 1); srv.hits.Load() != want {
		t.Fatalf("server saw %d requests, want %d", srv.hits.Load(), want)
	}
	t.Logf("gave up with: %v", err)
}

// TestHTTPClientDoesNotRetryClientErrors checks that a 4xx answer is returned
// as is, sent once, and does not count against the breaker.
func TestHTTPClientDoesNotRetryClientErrors(t *testing.T) {
	srv := newScriptedServer(t, http.StatusNotFound)
	cfg := fastConfig(t)
	c := New(cfg)

	for i := 0; i < int(cfg.FailMax)+1; i++ {
		resp, err := get(t, c, srv.URL)
		if err != nil {
			t.Fatalf("call %d: Do returned %v, want the 404 response", i, err)
		}
		if resp.StatusCode != http.StatusNotFound {
			t.Fatalf("call %d: status = %d, want 404", i, resp.StatusCode)
		}
	}
	if want := cfg.FailMax + 1; srv.hits.Load() != int32(want) {
		t.Fatalf("server saw %d requests, want %d (no retries)", srv.hits.Load(), want)
	}
	if got := c.State(); got != gobreaker.StateClosed {
		t.Fatalf("breaker state = %s after 4xx answers, want closed", got)
	}
}

// TestHTTPClientBreakerOpensAfterFailMax checks the circuit breaker: after
// FailMax failed calls against a server that always answers 500 the breaker
// opens, and the next call fails fast with gobreaker.ErrOpenState without any
// request reaching the server. After the reset timeout it lets one trial call
// through and closes again when that call succeeds.
func TestHTTPClientBreakerOpensAfterFailMax(t *testing.T) {
	srv := newScriptedServer(t, http.StatusInternalServerError)
	cfg := fastConfig(t)
	cfg.FailMax = 3
	c := New(cfg)

	for i := 1; i <= int(cfg.FailMax); i++ {
		if _, err := get(t, c, srv.URL); err == nil || errors.Is(err, gobreaker.ErrOpenState) {
			t.Fatalf("call %d: err = %v, want a request failure", i, err)
		}
	}
	if got := c.State(); got != gobreaker.StateOpen {
		t.Fatalf("breaker state = %s after %d failed calls, want open", got, cfg.FailMax)
	}
	hitsWhenOpened := srv.hits.Load()
	if want := int32(cfg.FailMax) * int32(cfg.RetryMax+1); hitsWhenOpened != want {
		t.Fatalf("server saw %d requests before the breaker opened, want %d", hitsWhenOpened, want)
	}

	start := time.Now()
	_, err := get(t, c, srv.URL)
	if !errors.Is(err, gobreaker.ErrOpenState) {
		t.Fatalf("call with the breaker open: err = %v, want ErrOpenState", err)
	}
	if got := srv.hits.Load(); got != hitsWhenOpened {
		t.Fatalf("server saw %d requests after the breaker opened, want %d (fast fail)", got, hitsWhenOpened)
	}
	t.Logf("open breaker failed fast in %s with: %v", time.Since(start), err)

	srv.setStatuses(http.StatusOK)
	time.Sleep(cfg.ResetTimeout + 50*time.Millisecond)
	if got := c.State(); got != gobreaker.StateHalfOpen {
		t.Fatalf("breaker state = %s after the reset timeout, want half-open", got)
	}
	resp, err := get(t, c, srv.URL)
	if err != nil || resp.StatusCode != http.StatusOK {
		t.Fatalf("trial call in half-open state: resp=%v err=%v, want 200", resp, err)
	}
	if got := c.State(); got != gobreaker.StateClosed {
		t.Fatalf("breaker state = %s after a successful trial call, want closed", got)
	}
}

// TestHTTPClientCanceledContextDoesNotTripBreaker checks that calls the caller
// abandons are not blamed on the server.
func TestHTTPClientCanceledContextDoesNotTripBreaker(t *testing.T) {
	srv := newScriptedServer(t, http.StatusOK)
	cfg := fastConfig(t)
	cfg.FailMax = 1
	c := New(cfg)

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, srv.URL, nil)
	if err != nil {
		t.Fatalf("build request: %v", err)
	}
	if _, err := c.Do(req); !errors.Is(err, context.Canceled) {
		t.Fatalf("Do with a canceled context: err = %v, want context.Canceled", err)
	}
	if got := c.State(); got != gobreaker.StateClosed {
		t.Fatalf("breaker state = %s after a canceled call, want closed", got)
	}
}
