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

// Package observability holds the operator's opt-in telemetry: OpenTelemetry
// tracing (OTEL_EXPORTER_OTLP_ENDPOINT), Sentry error reporting (SENTRY_DSN)
// and the pprof server (--pprof-addr). Each stays off unless configured.
package observability

// ServiceName is the service.name tracing resource attribute and the Sentry
// release prefix.
const ServiceName = "aragora-operator"

// version is the build version. Release builds set it with
//
//	go build -ldflags "-X github.com/synaptent/aragora-operator/internal/observability.version=v1.2.3"
var version = "dev"

// Version returns the build version ("dev" unless set at link time).
func Version() string {
	return version
}
