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
	"net/http"
	"net/url"
	"strings"
	"testing"
)

// TestClientRefusesEndpointWithQueryOrFragment checks that a Client whose
// endpoint has a query or a fragment, even an empty one, sends nothing. The
// client appends each API path to the endpoint as text, so the path would
// land inside the query or fragment. The errors and the logs must not reveal
// what the endpoint holds.
func TestClientRefusesEndpointWithQueryOrFragment(t *testing.T) {
	read := captureClientLogs(t)
	srv, hits := scriptedControlPlane(t, http.StatusOK)
	marker := "SYNTHETIC_MARKER_" + rand.Text()
	password := "SYNTHETIC_PASSWORD_" + rand.Text()
	u, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	withUserinfo := u.Scheme + "://" + syntheticUser + ":" + password + "@" + u.Host

	for _, tc := range []struct{ name, endpoint string }{
		{"query", srv.URL + "/?token=" + marker},
		{"query after a quoted value", srv.URL + "/base?filter='all'&token=" + marker},
		{"bare question mark", srv.URL + "/base?"},
		{"fragment", srv.URL + "/base#" + marker},
		{"bare hash", srv.URL + "/base#"},
		{"userinfo and query", withUserinfo + "/?token=" + marker},
		{"userinfo and fragment", withUserinfo + "/base#" + marker},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := NewClient(tc.endpoint, "")
			_, getErr := c.GetAgentStatus(context.Background())
			applyErr := c.ApplyPolicy(context.Background(), &Policy{ID: "synthetic-policy"})
			for call, err := range map[string]error{"GetAgentStatus": getErr, "ApplyPolicy": applyErr} {
				if err == nil {
					t.Errorf("%s succeeded through an endpoint with a query or fragment", call)
					continue
				}
				for _, secret := range []string{marker, password, syntheticUser} {
					if strings.Contains(err.Error(), secret) {
						t.Errorf("the %s error reveals %q from the endpoint: %v", call, secret, err)
					}
				}
			}
		})
	}

	if n := hits.Load(); n != 0 {
		t.Errorf("the control plane saw %d requests through refused endpoints, want none", n)
	}
	logs := read()
	for _, secret := range []string{marker, password, syntheticUser} {
		if strings.Contains(logs, secret) {
			t.Errorf("the client logs reveal %q from a refused endpoint:\n%s", secret, logs)
		}
	}
}
