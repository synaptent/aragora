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

package observability_test

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/otel"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	coltracepb "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	tracepb "go.opentelemetry.io/proto/otlp/trace/v1"
	"google.golang.org/protobuf/proto"

	"github.com/synaptent/aragora-operator/internal/aragora"
	"github.com/synaptent/aragora-operator/internal/observability"
)

const otlpEndpointEnv = "OTEL_EXPORTER_OTLP_ENDPOINT"

// controlPlane is a stand-in Aragora API that records whether requests carry
// a W3C traceparent header, which only the otelhttp transport adds.
type controlPlane struct {
	*httptest.Server
	mu           sync.Mutex
	traceparents []string
}

func newControlPlane(t *testing.T) *controlPlane {
	t.Helper()
	cp := &controlPlane{}
	cp.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		cp.mu.Lock()
		cp.traceparents = append(cp.traceparents, r.Header.Get("Traceparent"))
		cp.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"healthy":true,"version":"test"}`)
	}))
	t.Cleanup(cp.Close)
	return cp
}

func (cp *controlPlane) seen() []string {
	cp.mu.Lock()
	defer cp.mu.Unlock()
	return append([]string(nil), cp.traceparents...)
}

// otlpReceiver is an in-process OTLP/HTTP trace endpoint that decodes every
// export request it receives.
type otlpReceiver struct {
	*httptest.Server
	mu       sync.Mutex
	requests []*coltracepb.ExportTraceServiceRequest
}

func newOTLPReceiver(t *testing.T) *otlpReceiver {
	t.Helper()
	rcv := &otlpReceiver{}
	rcv.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/traces" {
			http.NotFound(w, r)
			return
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		req := &coltracepb.ExportTraceServiceRequest{}
		if err := proto.Unmarshal(body, req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		rcv.mu.Lock()
		rcv.requests = append(rcv.requests, req)
		rcv.mu.Unlock()
		w.Header().Set("Content-Type", "application/x-protobuf")
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(rcv.Close)
	return rcv
}

// spansByService returns every received span grouped by the service.name
// resource attribute of its batch.
func (rcv *otlpReceiver) spansByService() map[string][]*tracepb.Span {
	rcv.mu.Lock()
	defer rcv.mu.Unlock()
	out := map[string][]*tracepb.Span{}
	for _, req := range rcv.requests {
		for _, rs := range req.GetResourceSpans() {
			service := ""
			for _, kv := range rs.GetResource().GetAttributes() {
				if kv.GetKey() == "service.name" {
					service = kv.GetValue().GetStringValue()
				}
			}
			for _, ss := range rs.GetScopeSpans() {
				out[service] = append(out[service], ss.GetSpans()...)
			}
		}
	}
	return out
}

// TestOTelExporterOnlyWithEndpoint checks both directions of the
// OTEL_EXPORTER_OTLP_ENDPOINT gate on the Aragora API client.
//
// Without the variable, SetupTracing installs nothing: no SDK tracer
// provider, the transport is left alone, and API requests carry no trace
// context. With it, one Aragora API call produces one client span from the
// "aragora-operator" service, and the provider is flushed and shut down
// before the test returns, so the span has reached the endpoint.
//
// When OTEL_EXPORTER_OTLP_ENDPOINT is already set (for example to a local
// collector at http://localhost:4318), the span goes there. Otherwise it goes
// to an in-process receiver that the test inspects, and nothing is sent
// anywhere else.
func TestOTelExporterOnlyWithEndpoint(t *testing.T) {
	configured := os.Getenv(otlpEndpointEnv)
	t.Run("unset", testTracingWithoutEndpoint)
	t.Run("set", func(t *testing.T) { testTracingWithEndpoint(t, configured) })
}

func testTracingWithoutEndpoint(t *testing.T) {
	observability.UnsetEnv(t, otlpEndpointEnv)
	var log observability.LogLines
	shutdown, err := observability.SetupTracing(context.Background(), log.Logger())
	if err != nil {
		t.Fatalf("SetupTracing: %v", err)
	}
	if _, ok := otel.GetTracerProvider().(*sdktrace.TracerProvider); ok {
		t.Fatal("an SDK tracer provider is installed without OTEL_EXPORTER_OTLP_ENDPOINT")
	}
	if rt := observability.WrapTransport(http.DefaultTransport); rt != http.DefaultTransport {
		t.Fatalf("WrapTransport wrapped the transport without OTEL_EXPORTER_OTLP_ENDPOINT: %T", rt)
	}

	cp := newControlPlane(t)
	if _, err := aragora.NewClient(cp.URL, "").GetHealth(context.Background()); err != nil {
		t.Fatalf("GetHealth: %v", err)
	}
	if got := cp.seen(); len(got) != 1 || got[0] != "" {
		t.Fatalf("traceparent headers = %q, want one request without trace context", got)
	}
	if err := shutdown(context.Background()); err != nil {
		t.Fatalf("shutdown: %v", err)
	}
	log.AssertOne(t, "tracing disabled")
}

// testTracingWithEndpoint exports to configured when it is non-empty and to
// an in-process receiver otherwise.
func testTracingWithEndpoint(t *testing.T, configured string) {
	endpoint := configured
	var rcv *otlpReceiver
	if endpoint == "" {
		rcv = newOTLPReceiver(t)
		endpoint = rcv.URL
	}
	t.Setenv(otlpEndpointEnv, endpoint)

	var log observability.LogLines
	shutdown, err := observability.SetupTracing(context.Background(), log.Logger())
	if err != nil {
		t.Fatalf("SetupTracing: %v", err)
	}
	log.AssertOne(t, "tracing enabled")

	cp := newControlPlane(t)
	if _, err := aragora.NewClient(cp.URL, "").GetHealth(context.Background()); err != nil {
		t.Fatalf("GetHealth: %v", err)
	}
	if got := cp.seen(); len(got) != 1 || got[0] == "" {
		t.Fatalf("traceparent headers = %q, want one request carrying trace context", got)
	}

	// shutdown force-flushes before it shuts the provider down; ForceFlush
	// returns the exporter's error, so nil means the endpoint accepted the
	// span.
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := shutdown(ctx); err != nil {
		t.Fatalf("flush and shut down the tracer provider (endpoint %s): %v", endpoint, err)
	}
	t.Logf("exported the Aragora API client span to %s", endpoint)

	if rcv != nil {
		assertOneClientSpan(t, rcv)
	}
}

func assertOneClientSpan(t *testing.T, rcv *otlpReceiver) {
	t.Helper()
	byService := rcv.spansByService()
	spans := byService[observability.ServiceName]
	if len(byService) != 1 || len(spans) != 1 {
		t.Fatalf("received spans by service = %v, want exactly one %q span", byService, observability.ServiceName)
	}
	if spans[0].GetKind() != tracepb.Span_SPAN_KIND_CLIENT {
		t.Fatalf("span kind = %s, want CLIENT", spans[0].GetKind())
	}
	t.Logf("receiver got span %q (kind %s) from service %q", spans[0].GetName(), spans[0].GetKind(), observability.ServiceName)
}
