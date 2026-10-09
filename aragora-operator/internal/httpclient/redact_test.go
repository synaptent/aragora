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

// TestRedactionKeepsNoTokenAfterQuotedQueryValues puts a request URL whose
// raw query holds a token after a quoted or punctuated value (an
// apostrophe-quoted one first) in every form in which retryablehttp and
// net/http log or return it: the url field, the retry message, the giving-up
// error with net/http's *url.Error inside, and that error flattened to text.
// Go keeps such a query as is, so none of these characters may end the part
// that is redacted.
func TestRedactionKeepsNoTokenAfterQuotedQueryValues(t *testing.T) {
	const token = "SYNTHETIC_QUERY_TOKEN_redact"
	const label = "http://127.0.0.1:3140/api/control-plane/agents"
	for _, value := range []string{`'all'`, `('all')`, `a!b*c`, `$a,b;c`, `~a@b:c`, `"all"`} {
		t.Run(value, func(t *testing.T) {
			raw := label + "?filter=" + value + "&token=" + token
			masked := strings.Replace(raw, "http://", "http://synthetic-user:xxxxx@", 1)
			urlErr := &url.Error{Op: "Get", URL: raw, Err: errors.New("connection refused")}
			giveUp := fmt.Errorf("GET %s giving up after 4 attempt(s): %w", masked, urlErr)

			values := redactLogValues([]interface{}{
				"url", masked,
				"request", "GET " + masked + " (status: 503)",
				"error", urlErr,
				"error", giveUp,
				"error", errors.New(giveUp.Error()),
			})
			if values[1] != label {
				t.Errorf("url value = %q, want the label %q", values[1], label)
			}
			for i := 1; i < len(values); i += 2 {
				text := fmt.Sprint(values[i])
				for _, secret := range []string{token, "synthetic-user", "filter="} {
					if strings.Contains(text, secret) {
						t.Errorf("redacted %s value %q still holds %q", values[i-1], text, secret)
					}
				}
				if !strings.Contains(text, label) {
					t.Errorf("redacted %s value %q lost the label %q", values[i-1], text, label)
				}
			}
			for _, i := range []int{5, 7} {
				var got *url.Error
				if !errors.As(values[i].(error), &got) || got != urlErr {
					t.Errorf("redacted error %d no longer wraps the *url.Error", i)
				}
			}
		})
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
