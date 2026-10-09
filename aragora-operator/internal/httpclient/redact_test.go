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
	"context"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"testing"
)

func TestEndpointLabel(t *testing.T) {
	const fallback = "aragora-api"
	for _, tc := range []struct{ name, endpoint, want string }{
		{"plain", "https://control-plane:8443", "https://control-plane:8443"},
		{"path kept", "https://control-plane:8443/api/v1", "https://control-plane:8443/api/v1"},
		{"user and password", "https://synthetic-user:synthetic-password@control-plane:8443", "https://control-plane:8443"},
		{"user only", "https://synthetic-user@control-plane:8443/base", "https://control-plane:8443/base"},
		{"query", "https://control-plane:8443/base?token=synthetic-token", "https://control-plane:8443/base"},
		{"fragment", "https://control-plane:8443/base#synthetic-fragment", "https://control-plane:8443/base"},
		{"all of them", "http://synthetic-user:synthetic-password@127.0.0.1:3140/base?token=synthetic-token#f", "http://127.0.0.1:3140/base"},
		{"ipv6 host", "https://synthetic-user:synthetic-password@[::1]:8443", "https://[::1]:8443"},
		{"unparsable host", "https://synthetic-user:synthetic-password@[::1", fallback},
		{"unparsable escape", "https://control-plane:8443/%zz", fallback},
		{"no scheme", "synthetic-user:synthetic-password@control-plane:8443", fallback},
		{"no host", "/api/control-plane", fallback},
		{"empty", "", fallback},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := EndpointLabel(tc.endpoint, fallback); got != tc.want {
				t.Errorf("EndpointLabel(%q) = %q, want %q", tc.endpoint, got, tc.want)
			}
		})
	}
}

// TestRedactErrorKeepsTheErrorChain checks that removing URL credentials from
// an error message does not hide the wrapped error from errors.Is.
func TestRedactErrorKeepsTheErrorChain(t *testing.T) {
	err := fmt.Errorf(`Get "http://synthetic-user:synthetic-password@127.0.0.1:3140/?token=synthetic-token": %w`, context.Canceled)
	got := RedactError(err)
	if want := `Get "http://127.0.0.1:3140/": context canceled`; got.Error() != want {
		t.Errorf("RedactError = %q, want %q", got.Error(), want)
	}
	if !errors.Is(got, context.Canceled) {
		t.Error("the redacted error no longer wraps context.Canceled")
	}
	if plain := errors.New("no URL here"); RedactError(plain) != plain {
		t.Error("RedactError replaced an error that holds no URL")
	}
	if RedactError(nil) != nil {
		t.Error("RedactError(nil) != nil")
	}
}

// TestRedactErrorHidesTheRawInputOfURLParseErrors covers url.Parse errors,
// which quote the raw input. A space or quote in an unescaped password would
// end a URL match in the message part way through the password.
func TestRedactErrorHidesTheRawInputOfURLParseErrors(t *testing.T) {
	for _, raw := range []string{
		"https://synthetic-user:synthetic pass word@control-plane:8443/base",
		`https://synthetic-user:synthetic"pass"word@control-plane:8443/base`,
		"https://synthetic-user:synthetic-pass-word@[::1/base",
	} {
		_, err := url.Parse(raw)
		if err == nil {
			t.Fatalf("url.Parse(%q) succeeded, want an error", raw)
		}
		got := RedactError(err).Error()
		for _, part := range []string{"synthetic", "pass", "word"} {
			if strings.Contains(got, part) {
				t.Errorf("RedactError(url.Parse(%q)) = %q, still holds %q", raw, got, part)
			}
		}
	}
}
