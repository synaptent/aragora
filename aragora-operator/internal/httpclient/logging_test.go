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
	"crypto/rand"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"github.com/sony/gobreaker/v2"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
)

// TestHTTPClientLogsAndErrorsOmitURLCredentials sends requests whose URL
// carries a username, password and query token to a closed port. Every
// attempt fails to connect, which is the path where retryablehttp logs the
// transport error and the URL, and the breaker (FailMax 1) then opens. None
// of the credentials may reach the logs or the returned errors, while every
// log line keeps the breaker label.
func TestHTTPClientLogsAndErrorsOmitURLCredentials(t *testing.T) {
	srv := httptest.NewServer(http.NotFoundHandler())
	srv.Close()
	target, err := url.Parse(srv.URL + "/api/control-plane/health")
	if err != nil {
		t.Fatal(err)
	}
	password := "SYNTHETIC_PASSWORD_" + rand.Text()
	queryToken := "SYNTHETIC_QUERY_TOKEN_" + rand.Text()
	target.User = url.UserPassword("synthetic-user", password)
	target.RawQuery = url.Values{"token": {queryToken}}.Encode()

	var logs bytes.Buffer
	cfg := fastConfig(t)
	cfg.FailMax = 1
	cfg.Logger = zap.New(zap.UseDevMode(true), zap.WriteTo(&logs))
	c := New(cfg)

	_, failed := get(t, c, target.String())
	if failed == nil || errors.Is(failed, gobreaker.ErrOpenState) {
		t.Fatalf("call to a closed port: err = %v, want a connection failure", failed)
	}
	_, open := get(t, c, target.String())
	if !errors.Is(open, gobreaker.ErrOpenState) {
		t.Fatalf("call with the breaker open: err = %v, want ErrOpenState", open)
	}

	text := logs.String()
	for _, msg := range []string{"request failed", "retrying request", "circuit breaker state changed"} {
		if !strings.Contains(text, msg) {
			t.Errorf("no %q line in the logs:\n%s", msg, text)
		}
	}
	if want := `"breaker": "` + cfg.Name + `"`; strings.Count(text, want) != strings.Count(text, "\n") {
		t.Errorf("not every log line carries %s:\n%s", want, text)
	}
	for what, got := range map[string]string{"logs": text, "connection error": failed.Error(), "open-breaker error": open.Error()} {
		for _, secret := range []string{password, "synthetic-user", queryToken} {
			if strings.Contains(got, secret) {
				t.Errorf("%q from the request URL appears in the %s:\n%s", secret, what, got)
			}
		}
	}
}
