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

package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"sigs.k8s.io/controller-runtime/pkg/metrics"
)

// Collector holds all Prometheus metrics for the Aragora operator
type Collector struct {
	// Reconciliation metrics
	reconciliationsTotal *prometheus.CounterVec
	reconcileErrors      *prometheus.CounterVec
	reconcileDuration    *prometheus.HistogramVec

	// Cluster metrics
	clusterStatus        *prometheus.GaugeVec
	clusterReadyReplicas *prometheus.GaugeVec
	clusterInfo          *prometheus.GaugeVec

	// Instance metrics
	instanceStatus   *prometheus.GaugeVec
	instanceReplicas *prometheus.GaugeVec
	instanceDebates  *prometheus.GaugeVec

	// Policy metrics
	policyStatus     *prometheus.GaugeVec
	policyViolations *prometheus.GaugeVec
	policyConflicts  *prometheus.GaugeVec

	// Control plane communication metrics
	apiRequestsTotal   *prometheus.CounterVec
	apiRequestDuration *prometheus.HistogramVec
	apiRequestErrors   *prometheus.CounterVec
}

// NewCollector creates a new metrics collector
func NewCollector() *Collector {
	return &Collector{
		reconciliationsTotal: prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Namespace: "aragora_operator",
				Name:      "reconciliations_total",
				Help:      "Total number of reconciliations per resource type",
			},
			[]string{"resource_type", "resource_name"},
		),
		reconcileErrors: prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Namespace: "aragora_operator",
				Name:      "reconcile_errors_total",
				Help:      "Total number of reconciliation errors per resource type",
			},
			[]string{"resource_type", "resource_name", "error_type"},
		),
		reconcileDuration: prometheus.NewHistogramVec(
			prometheus.HistogramOpts{
				Namespace: "aragora_operator",
				Name:      "reconcile_duration_seconds",
				Help:      "Duration of reconciliation in seconds",
				Buckets:   prometheus.ExponentialBuckets(0.001, 2, 15),
			},
			[]string{"resource_type"},
		),
		clusterStatus: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "aragora_operator",
				Name:      "cluster_status",
				Help:      "Status of AragoraCluster (1=Running, 0=Not Running)",
			},
			[]string{"cluster", "phase"},
		),
		clusterReadyReplicas: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "aragora_operator",
				Name:      "cluster_ready_replicas",
				Help:      "Number of ready replicas in an AragoraCluster",
			},
			[]string{"cluster"},
		),
		clusterInfo: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "aragora_operator",
				Name:      "cluster_info",
				Help:      "Information about AragoraCluster",
			},
			[]string{"cluster", "version", "namespace"},
		),
		instanceStatus: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "aragora_operator",
				Name:      "instance_status",
				Help:      "Status of AragoraInstance (1=Running, 0=Not Running)",
			},
			[]string{"instance", "cluster", "phase", "role"},
		),
		instanceReplicas: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "aragora_operator",
				Name:      "instance_replicas",
				Help:      "Number of replicas for an AragoraInstance",
			},
			[]string{"instance", "type"},
		),
		instanceDebates: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "aragora_operator",
				Name:      "instance_active_debates",
				Help:      "Number of active debates on an AragoraInstance",
			},
			[]string{"instance"},
		),
		policyStatus: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "aragora_operator",
				Name:      "policy_status",
				Help:      "Status of AragoraPolicy (1=Active, 0=Not Active)",
			},
			[]string{"policy", "cluster", "phase"},
		),
		policyViolations: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "aragora_operator",
				Name:      "policy_violations",
				Help:      "Number of policy violations",
			},
			[]string{"policy", "severity"},
		),
		policyConflicts: prometheus.NewGaugeVec(
			prometheus.GaugeOpts{
				Namespace: "aragora_operator",
				Name:      "policy_conflicts",
				Help:      "Number of policy conflicts",
			},
			[]string{"policy"},
		),
		apiRequestsTotal: prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Namespace: "aragora_operator",
				Name:      "api_requests_total",
				Help:      "Total number of API requests to control plane",
			},
			[]string{"method", "endpoint", "status"},
		),
		apiRequestDuration: prometheus.NewHistogramVec(
			prometheus.HistogramOpts{
				Namespace: "aragora_operator",
				Name:      "api_request_duration_seconds",
				Help:      "Duration of API requests to control plane",
				Buckets:   prometheus.ExponentialBuckets(0.01, 2, 10),
			},
			[]string{"method", "endpoint"},
		),
		apiRequestErrors: prometheus.NewCounterVec(
			prometheus.CounterOpts{
				Namespace: "aragora_operator",
				Name:      "api_request_errors_total",
				Help:      "Total number of API request errors",
			},
			[]string{"method", "endpoint", "error_type"},
		),
	}
}

// Register registers all metrics with the controller-runtime metrics registry
func (c *Collector) Register() {
	metrics.Registry.MustRegister(
		c.reconciliationsTotal,
		c.reconcileErrors,
		c.reconcileDuration,
		c.clusterStatus,
		c.clusterReadyReplicas,
		c.clusterInfo,
		c.instanceStatus,
		c.instanceReplicas,
		c.instanceDebates,
		c.policyStatus,
		c.policyViolations,
		c.policyConflicts,
		c.apiRequestsTotal,
		c.apiRequestDuration,
		c.apiRequestErrors,
	)
}

// RecordReconciliation records a reconciliation event
func (c *Collector) RecordReconciliation(resourceType, resourceName string) {
	c.reconciliationsTotal.WithLabelValues(resourceType, resourceName).Inc()
}

// RecordError records a reconciliation error
func (c *Collector) RecordError(resourceType, resourceName string, err error) {
	errorType := "unknown"
	if err != nil {
		errorType = err.Error()
		if len(errorType) > 50 {
			errorType = errorType[:50]
		}
	}
	c.reconcileErrors.WithLabelValues(resourceType, resourceName, errorType).Inc()
}

// RecordClusterStatus records cluster status
func (c *Collector) RecordClusterStatus(clusterName, phase string, readyReplicas int) {
	// Reset all phase gauges for this cluster
	for _, p := range []string{"Pending", "Provisioning", "Running", "Failed", "Terminating"} {
		if p == phase {
			c.clusterStatus.WithLabelValues(clusterName, p).Set(1)
		} else {
			c.clusterStatus.WithLabelValues(clusterName, p).Set(0)
		}
	}
	c.clusterReadyReplicas.WithLabelValues(clusterName).Set(float64(readyReplicas))
}

// RecordInstanceStatus records instance status
func (c *Collector) RecordInstanceStatus(instanceName, phase string, replicas int) {
	// Reset all phase gauges for this instance
	for _, p := range []string{"Pending", "Starting", "Running", "Draining", "Terminated", "Failed"} {
		if p == phase {
			c.instanceStatus.WithLabelValues(instanceName, "", p, "").Set(1)
		} else {
			c.instanceStatus.WithLabelValues(instanceName, "", p, "").Set(0)
		}
	}
	c.instanceReplicas.WithLabelValues(instanceName, "current").Set(float64(replicas))
}

// RecordPolicyStatus records policy status
func (c *Collector) RecordPolicyStatus(policyName, phase string) {
	// Reset all phase gauges for this policy
	for _, p := range []string{"Pending", "Active", "Error", "Disabled"} {
		if p == phase {
			c.policyStatus.WithLabelValues(policyName, "", p).Set(1)
		} else {
			c.policyStatus.WithLabelValues(policyName, "", p).Set(0)
		}
	}
}

// RecordPolicyViolations records policy violations
func (c *Collector) RecordPolicyViolations(policyName string, violationsBySeverity map[string]int) {
	for severity, count := range violationsBySeverity {
		c.policyViolations.WithLabelValues(policyName, severity).Set(float64(count))
	}
}

// RecordPolicyConflicts records policy conflicts
func (c *Collector) RecordPolicyConflicts(policyName string, count int) {
	c.policyConflicts.WithLabelValues(policyName).Set(float64(count))
}

// RecordAPIRequest records an API request to the control plane
func (c *Collector) RecordAPIRequest(method, endpoint, status string, duration float64) {
	c.apiRequestsTotal.WithLabelValues(method, endpoint, status).Inc()
	c.apiRequestDuration.WithLabelValues(method, endpoint).Observe(duration)
}

// RecordAPIError records an API error
func (c *Collector) RecordAPIError(method, endpoint, errorType string) {
	c.apiRequestErrors.WithLabelValues(method, endpoint, errorType).Inc()
}

// ObserveReconcileDuration observes reconciliation duration
func (c *Collector) ObserveReconcileDuration(resourceType string, duration float64) {
	c.reconcileDuration.WithLabelValues(resourceType).Observe(duration)
}
