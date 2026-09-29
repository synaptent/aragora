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
	"errors"
	"fmt"
	"net/http"
	"os"
	"sync/atomic"

	"github.com/go-logr/logr"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.40.0"
)

const otlpEndpointEnv = "OTEL_EXPORTER_OTLP_ENDPOINT"

// tracerProvider is the provider SetupTracing installed, or nil when tracing
// is off. WrapTransport reads it.
var tracerProvider atomic.Pointer[sdktrace.TracerProvider]

// SetupTracing turns on OpenTelemetry tracing when OTEL_EXPORTER_OTLP_ENDPOINT
// is set: it installs a global tracer provider that batches spans to an
// OTLP/HTTP exporter (configured by the standard OTEL_EXPORTER_OTLP_*
// variables) under the service name "aragora-operator", and W3C trace-context
// propagation. Without the variable it installs nothing. It logs one line
// saying whether tracing is enabled.
//
// The returned function flushes pending spans and shuts the provider down;
// call it before the process exits. It is a no-op when tracing is off.
func SetupTracing(ctx context.Context, log logr.Logger) (func(context.Context) error, error) {
	if os.Getenv(otlpEndpointEnv) == "" {
		log.Info("OpenTelemetry tracing disabled: OTEL_EXPORTER_OTLP_ENDPOINT not set")
		return func(context.Context) error { return nil }, nil
	}

	exporter, err := otlptracehttp.New(ctx)
	if err != nil {
		return nil, fmt.Errorf("create OTLP trace exporter: %w", err)
	}
	res, err := resource.New(ctx,
		resource.WithTelemetrySDK(),
		resource.WithAttributes(semconv.ServiceName(ServiceName), semconv.ServiceVersion(Version())),
	)
	if err != nil {
		return nil, errors.Join(fmt.Errorf("build trace resource: %w", err), exporter.Shutdown(ctx))
	}
	tp := sdktrace.NewTracerProvider(sdktrace.WithBatcher(exporter), sdktrace.WithResource(res))

	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(propagation.TraceContext{}, propagation.Baggage{}))
	tracerProvider.Store(tp)
	log.Info("OpenTelemetry tracing enabled", "service", ServiceName, "exporter", "otlp/http")

	return func(ctx context.Context) error {
		tracerProvider.CompareAndSwap(tp, nil)
		return errors.Join(tp.ForceFlush(ctx), tp.Shutdown(ctx))
	}, nil
}

// WrapTransport returns base instrumented with otelhttp, so every outbound
// request becomes a client span and carries trace context, when SetupTracing
// has enabled tracing. Otherwise it returns base unchanged. A nil base means
// http.DefaultTransport. The choice is made once, so call it after
// SetupTracing.
func WrapTransport(base http.RoundTripper) http.RoundTripper {
	tp := tracerProvider.Load()
	if tp == nil {
		return base
	}
	return otelhttp.NewTransport(base,
		otelhttp.WithTracerProvider(tp),
		otelhttp.WithPropagators(otel.GetTextMapPropagator()),
	)
}
