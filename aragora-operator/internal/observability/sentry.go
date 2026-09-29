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
	"fmt"
	"os"
	"time"

	"github.com/getsentry/sentry-go"
	"github.com/go-logr/logr"
)

const (
	sentryDSNEnv             = "SENTRY_DSN"
	sentryEnvironmentEnv     = "SENTRY_ENVIRONMENT"
	defaultSentryEnvironment = "development"
)

// InitSentry initialises the global Sentry client when SENTRY_DSN is set and
// reports whether it did. The release is "aragora-operator@<version>" and the
// environment comes from SENTRY_ENVIRONMENT (default "development"). It logs
// one line saying whether Sentry is enabled.
func InitSentry(log logr.Logger) (bool, error) {
	dsn := os.Getenv(sentryDSNEnv)
	if dsn == "" {
		log.Info("Sentry disabled: SENTRY_DSN not set")
		return false, nil
	}

	environment := os.Getenv(sentryEnvironmentEnv)
	if environment == "" {
		environment = defaultSentryEnvironment
	}
	opts := sentry.ClientOptions{
		Dsn:         dsn,
		Release:     ServiceName + "@" + Version(),
		Environment: environment,
	}
	if err := sentry.Init(opts); err != nil {
		return false, fmt.Errorf("initialise Sentry: %w", err)
	}
	log.Info("Sentry enabled", "release", opts.Release, "environment", opts.Environment)
	return true, nil
}

// CaptureError reports err to Sentry. It does nothing when Sentry is not
// initialised.
func CaptureError(err error) {
	if err != nil {
		sentry.CaptureException(err)
	}
}

// FlushSentry waits up to timeout for queued Sentry events to be sent. It
// returns at once when Sentry is not initialised.
func FlushSentry(timeout time.Duration) {
	sentry.Flush(timeout)
}
