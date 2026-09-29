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

package observability

import (
	"context"
	"net"
	"net/http"
	"testing"
)

func TestStartPprofServesIndex(t *testing.T) {
	var log LogLines
	srv, err := StartPprof("127.0.0.1:0", log.Logger())
	if err != nil {
		t.Fatalf("StartPprof: %v", err)
	}
	t.Cleanup(func() { _ = srv.Close() })

	for _, path := range []string{"/debug/pprof/", "/debug/pprof/goroutine?debug=1", "/debug/pprof/cmdline"} {
		req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, "http://"+srv.Addr+path, nil)
		if err != nil {
			t.Fatalf("build request: %v", err)
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatalf("GET %s: %v", path, err)
		}
		_ = resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			t.Fatalf("GET %s = %d, want 200", path, resp.StatusCode)
		}
	}
	log.AssertOne(t, srv.Addr)
}

func TestStartPprofFailsOnBusyAddress(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	t.Cleanup(func() { _ = ln.Close() })

	var log LogLines
	if srv, err := StartPprof(ln.Addr().String(), log.Logger()); err == nil {
		_ = srv.Close()
		t.Fatalf("StartPprof on the busy address %s succeeded, want an error", ln.Addr())
	}
}
