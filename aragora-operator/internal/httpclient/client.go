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

// Package httpclient provides the resilient HTTP client the operator uses for
// outbound calls: bounded retries with exponential backoff
// (hashicorp/go-retryablehttp) behind a circuit breaker (sony/gobreaker).
package httpclient

import (
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/go-logr/logr"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/sony/gobreaker/v2"
)

// Config tunes a Client. DefaultConfig returns the operator's production
// values.
type Config struct {
	// Name identifies the breaker in logs.
	Name string
	// Timeout bounds each attempt, not the whole call.
	Timeout time.Duration
	// RetryMax is the number of retries after the first attempt.
	RetryMax int
	// RetryWaitMin and RetryWaitMax bound the exponential backoff between
	// attempts. A Retry-After header on 429 and 503 answers takes precedence.
	RetryWaitMin time.Duration
	RetryWaitMax time.Duration
	// FailMax is the number of consecutive failed calls (each after its
	// retries) that opens the breaker.
	FailMax uint32
	// ResetTimeout is how long the breaker stays open before it lets one
	// trial call through (half-open).
	ResetTimeout time.Duration
	// Transport sends each attempt; nil means http.DefaultTransport.
	Transport http.RoundTripper
	// Logger receives retry and breaker state-change messages.
	Logger logr.Logger
}

// DefaultConfig returns the production settings: 30 s per attempt, up to 3
// retries with 500 ms to 5 s backoff, and a breaker that opens after 5
// consecutive failed calls and half-opens after 30 s.
func DefaultConfig(name string) Config {
	return Config{
		Name:         name,
		Timeout:      30 * time.Second,
		RetryMax:     3,
		RetryWaitMin: 500 * time.Millisecond,
		RetryWaitMax: 5 * time.Second,
		FailMax:      5,
		ResetTimeout: 30 * time.Second,
		Logger:       logr.Discard(),
	}
}

// Client sends requests with retries behind a circuit breaker. It is safe
// for concurrent use.
type Client struct {
	retry   *retryablehttp.Client
	breaker *gobreaker.CircuitBreaker[*http.Response]
}

// New returns a Client configured by cfg.
func New(cfg Config) *Client {
	log := cfg.Logger.WithValues("breaker", cfg.Name)

	retry := retryablehttp.NewClient()
	retry.HTTPClient = &http.Client{Timeout: cfg.Timeout, Transport: cfg.Transport}
	retry.RetryMax = cfg.RetryMax
	retry.RetryWaitMin = cfg.RetryWaitMin
	retry.RetryWaitMax = cfg.RetryWaitMax
	retry.CheckRetry = retryablehttp.ErrorPropagatedRetryPolicy
	retry.Logger = leveledLogger{log}

	failMax := cfg.FailMax
	breaker := gobreaker.NewCircuitBreaker[*http.Response](gobreaker.Settings{
		Name:        cfg.Name,
		MaxRequests: 1,
		Timeout:     cfg.ResetTimeout,
		ReadyToTrip: func(counts gobreaker.Counts) bool {
			return counts.ConsecutiveFailures >= failMax
		},
		IsExcluded: func(err error) bool {
			var gone *callerGoneError
			return errors.As(err, &gone)
		},
		OnStateChange: func(name string, from, to gobreaker.State) {
			log.Info("circuit breaker state changed", "from", from.String(), "to", to.String())
		},
	})

	return &Client{retry: retry, breaker: breaker}
}

// Do sends req, retrying transient failures (connection errors, 429 and
// 5xx answers other than 501). Any other answer, including 4xx, is returned
// as is. A call that still fails after its retries returns an error and
// counts against the breaker; while the breaker is open, Do returns an error
// wrapping gobreaker.ErrOpenState without sending anything.
func (c *Client) Do(req *http.Request) (*http.Response, error) {
	rreq, err := retryablehttp.FromRequest(req)
	if err != nil {
		return nil, fmt.Errorf("prepare request: %w", err)
	}
	resp, err := c.breaker.Execute(func() (*http.Response, error) {
		resp, err := c.retry.Do(rreq)
		if err != nil && req.Context().Err() != nil {
			return nil, &callerGoneError{err: err}
		}
		return resp, err
	})
	if errors.Is(err, gobreaker.ErrOpenState) || errors.Is(err, gobreaker.ErrTooManyRequests) {
		return nil, fmt.Errorf("%s %s: %w", req.Method, req.URL.Redacted(), err)
	}
	return resp, err
}

// State reports the breaker state.
func (c *Client) State() gobreaker.State {
	return c.breaker.State()
}

// callerGoneError marks a failure caused by the caller canceling the request
// or letting its deadline pass. Such calls say nothing about the server, so
// the breaker ignores them.
type callerGoneError struct {
	err error
}

func (e *callerGoneError) Error() string { return e.err.Error() }
func (e *callerGoneError) Unwrap() error { return e.err }

// leveledLogger adapts logr to retryablehttp.LeveledLogger. Per-request
// chatter goes to V(1); a failed attempt is logged at the default level.
type leveledLogger struct {
	log logr.Logger
}

func (l leveledLogger) Error(msg string, keysAndValues ...interface{}) {
	l.log.Info(msg, keysAndValues...)
}

func (l leveledLogger) Warn(msg string, keysAndValues ...interface{}) {
	l.log.Info(msg, keysAndValues...)
}

func (l leveledLogger) Info(msg string, keysAndValues ...interface{}) {
	l.log.V(1).Info(msg, keysAndValues...)
}

func (l leveledLogger) Debug(msg string, keysAndValues ...interface{}) {
	l.log.V(1).Info(msg, keysAndValues...)
}
