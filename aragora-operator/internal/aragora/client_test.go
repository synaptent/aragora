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
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/sony/gobreaker/v2"

	"github.com/synaptent/aragora-operator/internal/httpclient"
)

// flakyControlPlane fails the first `failures` requests with 500 and then
// answers the health endpoint.
func flakyControlPlane(t *testing.T, failures int32) (*httptest.Server, *atomic.Int32) {
	t.Helper()
	var hits atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if hits.Add(1) <= failures {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"healthy":true,"version":"1.2.3"}`)
	}))
	t.Cleanup(srv.Close)
	return srv, &hits
}

func fastHTTPClient(t *testing.T) *httpclient.Client {
	t.Helper()
	cfg := httpclient.DefaultConfig(t.Name())
	cfg.RetryWaitMin = time.Millisecond
	cfg.RetryWaitMax = 5 * time.Millisecond
	return httpclient.New(cfg)
}

// TestClientRetryRecoversAfterServerErrors checks the Aragora API client end
// to end: three 500 answers followed by a 200 still yield the health status.
func TestClientRetryRecoversAfterServerErrors(t *testing.T) {
	srv, hits := flakyControlPlane(t, 3)
	c := newClient(srv.URL, "token", fastHTTPClient(t))

	health, err := c.GetHealth(context.Background())
	if err != nil {
		t.Fatalf("GetHealth: %v", err)
	}
	if !health.Healthy || health.Version != "1.2.3" {
		t.Fatalf("GetHealth = %+v, want healthy 1.2.3", health)
	}
	if hits.Load() != 4 {
		t.Fatalf("control plane saw %d requests, want 4", hits.Load())
	}
}

// TestClientBreakerFailsFastWhenControlPlaneIsDown checks that once the
// breaker opens, API calls fail with ErrOpenState and send nothing.
func TestClientBreakerFailsFastWhenControlPlaneIsDown(t *testing.T) {
	srv, hits := flakyControlPlane(t, 1<<30)
	cfg := httpclient.DefaultConfig(t.Name())
	cfg.RetryMax = 0
	cfg.FailMax = 2
	c := newClient(srv.URL, "", httpclient.New(cfg))

	for i := 0; i < int(cfg.FailMax); i++ {
		if err := c.DeletePolicy(context.Background(), "p1"); err == nil {
			t.Fatalf("DeletePolicy %d succeeded against a failing control plane", i)
		}
	}
	before := hits.Load()
	err := c.DeletePolicy(context.Background(), "p1")
	if !errors.Is(err, gobreaker.ErrOpenState) {
		t.Fatalf("DeletePolicy with the breaker open: %v, want ErrOpenState", err)
	}
	if hits.Load() != before {
		t.Fatalf("control plane saw %d more requests with the breaker open", hits.Load()-before)
	}
}

// TestNewClientSharesHTTPClientPerEndpoint checks that the reconcilers, which
// build a Client per call, still share one breaker per control-plane endpoint.
func TestNewClientSharesHTTPClientPerEndpoint(t *testing.T) {
	a1 := NewClient("https://cp-a.example.invalid", "t1")
	a2 := NewClient("https://cp-a.example.invalid", "t2")
	b := NewClient("https://cp-b.example.invalid", "t1")
	if a1.http != a2.http {
		t.Fatal("two clients for the same endpoint use different HTTP clients (and breakers)")
	}
	if a1.http == b.http {
		t.Fatal("clients for different endpoints share an HTTP client")
	}
}
