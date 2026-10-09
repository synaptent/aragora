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
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	logf "sigs.k8s.io/controller-runtime/pkg/log"

	aragorav1alpha1 "github.com/synaptent/aragora-operator/api/v1alpha1"
	"github.com/synaptent/aragora-operator/internal/httpclient"
	"github.com/synaptent/aragora-operator/internal/observability"
)

// Client is the Aragora control plane API client
type Client struct {
	endpoint string
	token    string
	http     *httpclient.Client
	// endpointErr is ValidateEndpoint's verdict on endpoint. When it is set,
	// every call returns it without sending anything.
	endpointErr error
}

// NewClient creates a new Aragora API client. Requests are retried with
// backoff and pass through a circuit breaker shared by every Client for the
// same endpoint, and they are traced when OpenTelemetry is enabled. If
// ValidateEndpoint refuses endpoint, every call fails with its error and
// sends nothing.
func NewClient(endpoint, token string) *Client {
	c := newClient(endpoint, token, nil)
	if c.endpointErr == nil {
		c.http = sharedHTTPClient(endpoint)
	}
	return c
}

func newClient(endpoint, token string, hc *httpclient.Client) *Client {
	return &Client{endpoint: endpoint, token: token, http: hc, endpointErr: ValidateEndpoint(endpoint)}
}

// The reconcilers build a Client for every call, so the HTTP client (and its
// breaker state) lives here, one per endpoint, for the life of the process.
var (
	sharedHTTPClientsMu sync.Mutex
	sharedHTTPClients   = map[string]*httpclient.Client{}
)

func sharedHTTPClient(endpoint string) *httpclient.Client {
	sharedHTTPClientsMu.Lock()
	defer sharedHTTPClientsMu.Unlock()
	if hc, ok := sharedHTTPClients[endpoint]; ok {
		return hc
	}
	// The breaker label is logged with every request, so it must not carry
	// the credentials an endpoint URL can hold.
	cfg := httpclient.DefaultConfig(httpclient.EndpointLabel(endpoint, "aragora-api"))
	cfg.Transport = observability.WrapTransport(nil)
	cfg.Logger = logf.Log.WithName("aragora-client")
	hc := httpclient.New(cfg)
	sharedHTTPClients[endpoint] = hc
	return hc
}

// Policy represents an Aragora policy in API format
type Policy struct {
	ID                string             `json:"id"`
	Name              string             `json:"name"`
	Priority          int                `json:"priority"`
	Enabled           bool               `json:"enabled"`
	CostLimits        *CostLimits        `json:"cost_limits,omitempty"`
	ModelRestrictions []ModelRestriction `json:"model_restrictions,omitempty"`
	RateLimits        *RateLimits        `json:"rate_limits,omitempty"`
	Selector          *PolicySelector    `json:"selector,omitempty"`
}

// CostLimits represents cost control settings
type CostLimits struct {
	DailyLimitUSD         *float64 `json:"daily_limit_usd,omitempty"`
	MonthlyLimitUSD       *float64 `json:"monthly_limit_usd,omitempty"`
	AlertThresholdPercent int      `json:"alert_threshold_percent"`
	HardLimit             bool     `json:"hard_limit"`
}

// ModelRestriction represents model usage restrictions
type ModelRestriction struct {
	Name                string   `json:"name"`
	Allowed             bool     `json:"allowed"`
	MaxRequestsPerHour  *int     `json:"max_requests_per_hour,omitempty"`
	MaxTokensPerRequest *int     `json:"max_tokens_per_request,omitempty"`
	AllowedOperations   []string `json:"allowed_operations,omitempty"`
}

// RateLimits represents rate limiting settings
type RateLimits struct {
	DebatesPerMinute  *int `json:"debates_per_minute,omitempty"`
	RequestsPerMinute *int `json:"requests_per_minute,omitempty"`
	TokensPerMinute   *int `json:"tokens_per_minute,omitempty"`
	ConcurrentDebates *int `json:"concurrent_debates,omitempty"`
	BurstLimit        *int `json:"burst_limit,omitempty"`
	PerWorkspace      bool `json:"per_workspace"`
}

// PolicySelector selects what a policy applies to
type PolicySelector struct {
	Workspaces []string `json:"workspaces,omitempty"`
	Tenants    []string `json:"tenants,omitempty"`
	MatchAll   bool     `json:"match_all"`
}

// AgentInfo represents agent status information
type AgentInfo struct {
	Name              string    `json:"name"`
	Available         bool      `json:"available"`
	LastHeartbeat     time.Time `json:"last_heartbeat"`
	RequestsPerMinute float64   `json:"requests_per_minute"`
	ErrorRate         float64   `json:"error_rate"`
}

// HealthStatus represents control plane health
type HealthStatus struct {
	Healthy    bool              `json:"healthy"`
	Version    string            `json:"version"`
	Uptime     time.Duration     `json:"uptime"`
	Components map[string]string `json:"components"`
}

// GetAgentStatus fetches agent status from the control plane
func (c *Client) GetAgentStatus(ctx context.Context) (map[string]aragorav1alpha1.AgentStatus, error) {
	resp, err := c.doRequest(ctx, "GET", "/api/control-plane/agents", nil)
	if err != nil {
		return nil, err
	}
	defer closeBody(resp.Body)

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	var agents []AgentInfo
	if err := json.NewDecoder(resp.Body).Decode(&agents); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	result := make(map[string]aragorav1alpha1.AgentStatus)
	for _, agent := range agents {
		result[agent.Name] = aragorav1alpha1.AgentStatus{
			Available:         agent.Available,
			LastHeartbeat:     &metav1.Time{Time: agent.LastHeartbeat},
			RequestsPerMinute: agent.RequestsPerMinute,
			ErrorRate:         agent.ErrorRate,
		}
	}

	return result, nil
}

// GetHealth fetches health status from the control plane
func (c *Client) GetHealth(ctx context.Context) (*HealthStatus, error) {
	resp, err := c.doRequest(ctx, "GET", "/api/control-plane/health", nil)
	if err != nil {
		return nil, err
	}
	defer closeBody(resp.Body)

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	var health HealthStatus
	if err := json.NewDecoder(resp.Body).Decode(&health); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return &health, nil
}

// ApplyPolicy applies a policy to the control plane
func (c *Client) ApplyPolicy(ctx context.Context, policy *Policy) error {
	body, err := json.Marshal(policy)
	if err != nil {
		return fmt.Errorf("failed to marshal policy: %w", err)
	}

	resp, err := c.doRequest(ctx, "PUT", "/api/control-plane/policies/"+policy.ID, body)
	if err != nil {
		return err
	}
	defer closeBody(resp.Body)

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("unexpected status code: %d, body: %s", resp.StatusCode, string(bodyBytes))
	}

	return nil
}

// DeletePolicy deletes a policy from the control plane
func (c *Client) DeletePolicy(ctx context.Context, policyID string) error {
	resp, err := c.doRequest(ctx, "DELETE", "/api/control-plane/policies/"+policyID, nil)
	if err != nil {
		return err
	}
	defer closeBody(resp.Body)

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusNotFound {
		return fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	return nil
}

// GetAffectedWorkspaces gets workspaces affected by a policy
func (c *Client) GetAffectedWorkspaces(ctx context.Context, policyID string) ([]string, error) {
	resp, err := c.doRequest(ctx, "GET", "/api/control-plane/policies/"+policyID+"/workspaces", nil)
	if err != nil {
		return nil, err
	}
	defer closeBody(resp.Body)

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	var response struct {
		Workspaces []string `json:"workspaces"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return response.Workspaces, nil
}

// RegisterInstance registers a worker instance with the control plane
func (c *Client) RegisterInstance(ctx context.Context, instance *InstanceRegistration) error {
	body, err := json.Marshal(instance)
	if err != nil {
		return fmt.Errorf("failed to marshal instance: %w", err)
	}

	resp, err := c.doRequest(ctx, "POST", "/api/control-plane/instances", body)
	if err != nil {
		return err
	}
	defer closeBody(resp.Body)

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		return fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	return nil
}

// DeregisterInstance removes an instance from the control plane
func (c *Client) DeregisterInstance(ctx context.Context, instanceID string) error {
	resp, err := c.doRequest(ctx, "DELETE", "/api/control-plane/instances/"+instanceID, nil)
	if err != nil {
		return err
	}
	defer closeBody(resp.Body)

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusNotFound {
		return fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	return nil
}

// InstanceRegistration represents instance registration data
type InstanceRegistration struct {
	ID           string            `json:"id"`
	Name         string            `json:"name"`
	ClusterName  string            `json:"cluster_name"`
	Role         string            `json:"role"`
	Endpoint     string            `json:"endpoint"`
	Capabilities []string          `json:"capabilities"`
	Labels       map[string]string `json:"labels"`
}

// SendHeartbeat sends a heartbeat to the control plane
func (c *Client) SendHeartbeat(ctx context.Context, instanceID string, status *InstanceStatus) error {
	body, err := json.Marshal(status)
	if err != nil {
		return fmt.Errorf("failed to marshal status: %w", err)
	}

	resp, err := c.doRequest(ctx, "POST", "/api/control-plane/instances/"+instanceID+"/heartbeat", body)
	if err != nil {
		return err
	}
	defer closeBody(resp.Body)

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	return nil
}

// InstanceStatus represents instance status for heartbeat
type InstanceStatus struct {
	Ready          bool    `json:"ready"`
	ActiveDebates  int     `json:"active_debates"`
	DebatesPerSec  float64 `json:"debates_per_sec"`
	AvgLatencyMs   float64 `json:"avg_latency_ms"`
	ErrorRate      float64 `json:"error_rate"`
	MemoryUsageMB  int64   `json:"memory_usage_mb"`
	CPUUtilization float64 `json:"cpu_utilization"`
}

// GetClusterMetrics fetches cluster metrics from the control plane
func (c *Client) GetClusterMetrics(ctx context.Context, clusterName string) (*ClusterMetrics, error) {
	resp, err := c.doRequest(ctx, "GET", "/api/control-plane/clusters/"+clusterName+"/metrics", nil)
	if err != nil {
		return nil, err
	}
	defer closeBody(resp.Body)

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status code: %d", resp.StatusCode)
	}

	var metrics ClusterMetrics
	if err := json.NewDecoder(resp.Body).Decode(&metrics); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return &metrics, nil
}

// ClusterMetrics represents cluster-level metrics
type ClusterMetrics struct {
	TotalDebates         int64   `json:"total_debates"`
	ActiveDebates        int     `json:"active_debates"`
	DebatesPerSecond     float64 `json:"debates_per_second"`
	AvgLatencyMs         float64 `json:"avg_latency_ms"`
	TotalTokensProcessed int64   `json:"total_tokens_processed"`
	TotalCostUSD         float64 `json:"total_cost_usd"`
	ErrorRate            float64 `json:"error_rate"`
}

func (c *Client) doRequest(ctx context.Context, method, path string, body []byte) (*http.Response, error) {
	if c.endpointErr != nil {
		return nil, c.endpointErr
	}
	url := c.endpoint + path

	var bodyReader io.Reader
	if body != nil {
		bodyReader = bytes.NewReader(body)
	}

	req, err := http.NewRequestWithContext(ctx, method, url, bodyReader)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", httpclient.RedactError(err))
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")

	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}

	return c.http.Do(req)
}

// closeBody closes a response body from a deferred call. A close error cannot
// change the outcome of a request whose result is already decided, so it is
// discarded.
func closeBody(body io.Closer) {
	_ = body.Close()
}
