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
	"testing"

	"github.com/getsentry/sentry-go"
)

// closedPortDSN is a syntactically valid DSN whose host refuses connections.
const closedPortDSN = "http://public@127.0.0.1:9/1"

// TestSentryInitOnlyWithDSN checks both directions of the SENTRY_DSN gate.
// Without the variable no Sentry client exists. With it, the global client is
// initialised with the build's release and the SENTRY_ENVIRONMENT value,
// which defaults to "development". Nothing goes over the network: sentry-go
// only contacts the DSN when an event is captured, and none is.
func TestSentryInitOnlyWithDSN(t *testing.T) {
	t.Cleanup(func() { sentry.CurrentHub().BindClient(nil) })

	t.Run("unset", func(t *testing.T) {
		UnsetEnv(t, sentryDSNEnv)
		var log LogLines
		enabled, err := InitSentry(log.Logger())
		if err != nil {
			t.Fatalf("InitSentry: %v", err)
		}
		if enabled {
			t.Fatal("InitSentry reported enabled without SENTRY_DSN")
		}
		if c := sentry.CurrentHub().Client(); c != nil {
			t.Fatalf("a Sentry client exists without SENTRY_DSN: %+v", c.Options())
		}
		log.AssertOne(t, "Sentry disabled")
	})

	t.Run("set with default environment", func(t *testing.T) {
		t.Setenv(sentryDSNEnv, closedPortDSN)
		UnsetEnv(t, sentryEnvironmentEnv)
		var log LogLines
		enabled, err := InitSentry(log.Logger())
		if err != nil {
			t.Fatalf("InitSentry: %v", err)
		}
		if !enabled {
			t.Fatal("InitSentry reported disabled with SENTRY_DSN set")
		}
		c := sentry.CurrentHub().Client()
		if c == nil {
			t.Fatal("no Sentry client after InitSentry with SENTRY_DSN set")
		}
		opts := c.Options()
		if opts.Release == "" {
			t.Fatal("ClientOptions.Release is empty")
		}
		if want := ServiceName + "@" + Version(); opts.Release != want {
			t.Fatalf("ClientOptions.Release = %q, want %q", opts.Release, want)
		}
		if opts.Environment != "development" {
			t.Fatalf("ClientOptions.Environment = %q, want development", opts.Environment)
		}
		log.AssertOne(t, "Sentry enabled")
		t.Logf("Sentry client: release=%q environment=%q", opts.Release, opts.Environment)
	})

	t.Run("set with SENTRY_ENVIRONMENT", func(t *testing.T) {
		t.Setenv(sentryDSNEnv, closedPortDSN)
		t.Setenv(sentryEnvironmentEnv, "staging")
		var log LogLines
		if _, err := InitSentry(log.Logger()); err != nil {
			t.Fatalf("InitSentry: %v", err)
		}
		if got := sentry.CurrentHub().Client().Options().Environment; got != "staging" {
			t.Fatalf("ClientOptions.Environment = %q, want staging", got)
		}
	})

	t.Run("invalid DSN", func(t *testing.T) {
		sentry.CurrentHub().BindClient(nil)
		t.Setenv(sentryDSNEnv, "not a dsn")
		var log LogLines
		enabled, err := InitSentry(log.Logger())
		if err == nil || enabled {
			t.Fatalf("InitSentry with an invalid DSN: enabled=%v err=%v, want an error", enabled, err)
		}
		if c := sentry.CurrentHub().Client(); c != nil {
			t.Fatal("a Sentry client exists after a failed init")
		}
	})
}
