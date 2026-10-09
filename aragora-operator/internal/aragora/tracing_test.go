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
	"crypto/rand"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/go-logr/logr"
	coltracepb "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	tracepb "go.opentelemetry.io/proto/otlp/trace/v1"
	"google.golang.org/protobuf/encoding/prototext"
	"google.golang.org/protobuf/proto"

	"github.com/synaptent/aragora-operator/internal/observability"
)

// otlpReceiver is a local OTLP/HTTP trace endpoint that keeps every export
// request it receives.
type otlpReceiver struct {
	*httptest.Server
	mu       sync.Mutex
	requests []*coltracepb.ExportTraceServiceRequest
}

func newOTLPReceiver(t *testing.T) *otlpReceiver {
	t.Helper()
	rcv := &otlpReceiver{}
	rcv.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		req := &coltracepb.ExportTraceServiceRequest{}
		if err == nil {
			err = proto.Unmarshal(body, req)
		}
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		rcv.mu.Lock()
		rcv.requests = append(rcv.requests, req)
		rcv.mu.Unlock()
		w.Header().Set("Content-Type", "application/x-protobuf")
	}))
	t.Cleanup(rcv.Close)
	return rcv
}

// exported returns every received span and the text form of everything that
// was exported, resources and attributes included.
func (rcv *otlpReceiver) exported() ([]*tracepb.Span, string) {
	rcv.mu.Lock()
	defer rcv.mu.Unlock()
	var spans []*tracepb.Span
	var text strings.Builder
	for _, req := range rcv.requests {
		text.WriteString(prototext.Format(req))
		for _, rs := range req.GetResourceSpans() {
			for _, ss := range rs.GetScopeSpans() {
				spans = append(spans, ss.GetSpans()...)
			}
		}
	}
	return spans, text.String()
}

// TestTracedRequestsOmitEndpointCredentials turns tracing on with a local
// OTLP receiver. A call through an endpoint with a username and password
// yields one client span, and nothing exported holds either of them. Calls
// through the same endpoint with a query or fragment send no request, so
// they yield no span.
func TestTracedRequestsOmitEndpointCredentials(t *testing.T) {
	read := captureClientLogs(t)
	rcv := newOTLPReceiver(t)
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", rcv.URL)
	shutdown, err := observability.SetupTracing(context.Background(), logr.Discard())
	if err != nil {
		t.Fatalf("SetupTracing: %v", err)
	}
	flushed := false
	t.Cleanup(func() {
		if !flushed {
			_ = shutdown(context.Background())
		}
	})

	srv, hits := scriptedControlPlane(t, http.StatusOK)
	ep := newSecretEndpoint(t, srv.URL+"/base")
	marker := "SYNTHETIC_MARKER_" + rand.Text()
	for _, refused := range []string{ep.url + "?token=" + marker, ep.url + "#" + marker} {
		if _, err := NewClient(refused, "").GetAgentStatus(context.Background()); err == nil {
			t.Error("a call through an endpoint with a query or fragment succeeded")
		}
	}
	if n := hits.Load(); n != 0 {
		t.Errorf("the control plane saw %d requests through refused endpoints, want none", n)
	}
	if _, err := NewClient(ep.url, "").GetAgentStatus(context.Background()); err != nil {
		t.Fatalf("GetAgentStatus through the userinfo endpoint: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	flushed = true
	if err := shutdown(ctx); err != nil {
		t.Fatalf("flush the spans to the local receiver: %v", err)
	}

	spans, text := rcv.exported()
	if len(spans) != 1 {
		t.Errorf("exported %d spans, want one, for the call through the accepted endpoint:\n%s", len(spans), text)
	}
	var fullURLs []string
	for _, span := range spans {
		for _, kv := range span.GetAttributes() {
			if kv.GetKey() == "url.full" {
				fullURLs = append(fullURLs, kv.GetValue().GetStringValue())
			}
		}
	}
	if want := ep.label + "/api/control-plane/agents"; len(fullURLs) != 1 || fullURLs[0] != want {
		t.Errorf("exported url.full = %q, want [%q]", fullURLs, want)
	}
	ep.assertAbsent(t, "the exported spans", text)
	if strings.Contains(text, marker) {
		t.Errorf("the exported spans reveal the query or fragment of a refused endpoint:\n%s", text)
	}

	logs := read()
	checkClientLogs(t, logs, ep, "performing request")
	if strings.Contains(logs, marker) {
		t.Errorf("the client logs reveal the query or fragment of a refused endpoint:\n%s", logs)
	}
}
