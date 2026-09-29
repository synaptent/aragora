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

package controllers

import (
	"context"
	"fmt"
	"sort"
	"time"

	"github.com/go-logr/logr"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/tools/record"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	aragorav1alpha1 "github.com/synaptent/aragora-operator/api/v1alpha1"
	"github.com/synaptent/aragora-operator/internal/aragora"
	"github.com/synaptent/aragora-operator/internal/metrics"
)

const (
	policyFinalizer = "aragora.ai/policy-finalizer"
)

// AragoraPolicyReconciler reconciles an AragoraPolicy object
type AragoraPolicyReconciler struct {
	client.Client
	Scheme           *runtime.Scheme
	Recorder         record.EventRecorder
	APIEndpoint      string
	APIToken         string
	MetricsCollector *metrics.Collector
}

// +kubebuilder:rbac:groups=aragora.ai,resources=aragorapolicies,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=aragora.ai,resources=aragorapolicies/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=aragora.ai,resources=aragorapolicies/finalizers,verbs=update

// Reconcile reconciles the AragoraPolicy resource
func (r *AragoraPolicyReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := ctrl.LoggerFrom(ctx)

	// Fetch the AragoraPolicy instance
	policy := &aragorav1alpha1.AragoraPolicy{}
	if err := r.Get(ctx, req.NamespacedName, policy); err != nil {
		if errors.IsNotFound(err) {
			log.Info("AragoraPolicy resource not found, ignoring")
			return ctrl.Result{}, nil
		}
		log.Error(err, "Failed to get AragoraPolicy")
		return ctrl.Result{}, err
	}

	// Record reconciliation metrics
	r.MetricsCollector.RecordReconciliation("AragoraPolicy", policy.Name)

	// Handle deletion
	if !policy.ObjectMeta.DeletionTimestamp.IsZero() {
		return r.reconcileDelete(ctx, log, policy)
	}

	// Add finalizer if not present
	if !controllerutil.ContainsFinalizer(policy, policyFinalizer) {
		controllerutil.AddFinalizer(policy, policyFinalizer)
		if err := r.Update(ctx, policy); err != nil {
			return ctrl.Result{}, err
		}
	}

	// Verify cluster reference exists
	cluster := &aragorav1alpha1.AragoraCluster{}
	if err := r.Get(ctx, types.NamespacedName{Name: policy.Spec.ClusterRef, Namespace: policy.Namespace}, cluster); err != nil {
		if errors.IsNotFound(err) {
			r.setCondition(policy, "ClusterRef", metav1.ConditionFalse, "ClusterNotFound",
				fmt.Sprintf("Referenced cluster %s not found", policy.Spec.ClusterRef))
			policy.Status.Phase = aragorav1alpha1.PolicyPhaseError
			if err := r.Status().Update(ctx, policy); err != nil {
				return ctrl.Result{}, err
			}
			return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
		}
		return ctrl.Result{}, err
	}

	// Reconcile the policy
	result, err := r.reconcilePolicy(ctx, log, policy, cluster)
	if err != nil {
		r.MetricsCollector.RecordError("AragoraPolicy", policy.Name, err)
		r.Recorder.Event(policy, corev1.EventTypeWarning, "ReconcileError", err.Error())
		return result, err
	}

	return result, nil
}

func (r *AragoraPolicyReconciler) reconcilePolicy(ctx context.Context, log logr.Logger, policy *aragorav1alpha1.AragoraPolicy, cluster *aragorav1alpha1.AragoraCluster) (ctrl.Result, error) {
	// Check if policy is disabled
	if !policy.Spec.Enabled {
		policy.Status.Phase = aragorav1alpha1.PolicyPhaseDisabled
		policy.Status.Applied = false
		r.setCondition(policy, "Applied", metav1.ConditionFalse, "PolicyDisabled", "Policy is disabled")
		if err := r.Status().Update(ctx, policy); err != nil {
			return ctrl.Result{}, err
		}
		return ctrl.Result{}, nil
	}

	// Check for conflicts with other policies
	conflicts, err := r.detectConflicts(ctx, policy)
	if err != nil {
		return ctrl.Result{}, err
	}
	policy.Status.Conflicts = conflicts

	if len(conflicts) > 0 {
		r.setCondition(policy, "NoConflicts", metav1.ConditionFalse, "ConflictsDetected",
			fmt.Sprintf("Conflicts with %d other policies", len(conflicts)))
		r.Recorder.Event(policy, corev1.EventTypeWarning, "ConflictsDetected",
			fmt.Sprintf("Policy conflicts detected: %v", conflicts))
	} else {
		r.setCondition(policy, "NoConflicts", metav1.ConditionTrue, "NoConflicts", "No policy conflicts detected")
	}

	// Apply policy to Aragora control plane
	if err := r.applyPolicy(ctx, log, policy, cluster); err != nil {
		policy.Status.Phase = aragorav1alpha1.PolicyPhaseError
		policy.Status.Applied = false
		r.setCondition(policy, "Applied", metav1.ConditionFalse, "ApplyFailed", err.Error())
		if err := r.Status().Update(ctx, policy); err != nil {
			return ctrl.Result{}, err
		}
		return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
	}

	// Update status
	policy.Status.Phase = aragorav1alpha1.PolicyPhaseActive
	policy.Status.Applied = true
	policy.Status.LastAppliedTime = &metav1.Time{Time: time.Now()}
	policy.Status.ObservedGeneration = policy.Generation
	r.setCondition(policy, "Applied", metav1.ConditionTrue, "PolicyApplied", "Policy applied successfully")

	// Get affected workspaces
	affectedWorkspaces, err := r.getAffectedWorkspaces(ctx, policy)
	if err != nil {
		log.Error(err, "Failed to get affected workspaces")
	} else {
		policy.Status.AffectedWorkspaces = affectedWorkspaces
	}

	if err := r.Status().Update(ctx, policy); err != nil {
		return ctrl.Result{}, err
	}

	r.Recorder.Event(policy, corev1.EventTypeNormal, "Applied", "Policy applied successfully")
	r.MetricsCollector.RecordPolicyStatus(policy.Name, string(policy.Status.Phase))

	// Requeue to check for violations
	return ctrl.Result{RequeueAfter: 60 * time.Second}, nil
}

func (r *AragoraPolicyReconciler) detectConflicts(ctx context.Context, policy *aragorav1alpha1.AragoraPolicy) ([]aragorav1alpha1.PolicyConflict, error) {
	var conflicts []aragorav1alpha1.PolicyConflict

	// List all policies for the same cluster
	policyList := &aragorav1alpha1.AragoraPolicyList{}
	if err := r.List(ctx, policyList, client.InNamespace(policy.Namespace)); err != nil {
		return nil, err
	}

	for _, other := range policyList.Items {
		// Skip self and policies for different clusters
		if other.Name == policy.Name || other.Spec.ClusterRef != policy.Spec.ClusterRef {
			continue
		}

		// Skip disabled policies
		if !other.Spec.Enabled {
			continue
		}

		// Check for cost limit conflicts
		if policy.Spec.CostLimits != nil && other.Spec.CostLimits != nil {
			if conflict := r.checkCostLimitConflict(policy, &other); conflict != nil {
				conflicts = append(conflicts, *conflict)
			}
		}

		// Check for model restriction conflicts
		if len(policy.Spec.ModelRestrictions) > 0 && len(other.Spec.ModelRestrictions) > 0 {
			if conflict := r.checkModelRestrictionConflict(policy, &other); conflict != nil {
				conflicts = append(conflicts, *conflict)
			}
		}

		// Check for rate limit conflicts
		if policy.Spec.RateLimits != nil && other.Spec.RateLimits != nil {
			if conflict := r.checkRateLimitConflict(policy, &other); conflict != nil {
				conflicts = append(conflicts, *conflict)
			}
		}
	}

	return conflicts, nil
}

func (r *AragoraPolicyReconciler) checkCostLimitConflict(policy *aragorav1alpha1.AragoraPolicy, other *aragorav1alpha1.AragoraPolicy) *aragorav1alpha1.PolicyConflict {
	// Check if both policies have overlapping selectors
	if !r.selectorsOverlap(policy.Spec.Selector, other.Spec.Selector) {
		return nil
	}

	// Check for conflicting daily limits
	if policy.Spec.CostLimits.DailyLimitUSD != nil && other.Spec.CostLimits.DailyLimitUSD != nil {
		policyLimit := policy.Spec.CostLimits.DailyLimitUSD.AsApproximateFloat64()
		otherLimit := other.Spec.CostLimits.DailyLimitUSD.AsApproximateFloat64()
		if policyLimit != otherLimit {
			return &aragorav1alpha1.PolicyConflict{
				PolicyName:   other.Name,
				ConflictType: "cost_limit",
				Description:  fmt.Sprintf("Conflicting daily cost limits: %v vs %v", policyLimit, otherLimit),
			}
		}
	}

	return nil
}

func (r *AragoraPolicyReconciler) checkModelRestrictionConflict(policy *aragorav1alpha1.AragoraPolicy, other *aragorav1alpha1.AragoraPolicy) *aragorav1alpha1.PolicyConflict {
	// Check for conflicting allowed status for same model
	policyModels := make(map[string]bool)
	for _, model := range policy.Spec.ModelRestrictions {
		policyModels[model.Name] = model.Allowed
	}

	for _, model := range other.Spec.ModelRestrictions {
		if allowed, exists := policyModels[model.Name]; exists {
			if allowed != model.Allowed {
				return &aragorav1alpha1.PolicyConflict{
					PolicyName:   other.Name,
					ConflictType: "model_restriction",
					Description:  fmt.Sprintf("Conflicting allowed status for model %s", model.Name),
				}
			}
		}
	}

	return nil
}

func (r *AragoraPolicyReconciler) checkRateLimitConflict(policy *aragorav1alpha1.AragoraPolicy, other *aragorav1alpha1.AragoraPolicy) *aragorav1alpha1.PolicyConflict {
	if !r.selectorsOverlap(policy.Spec.Selector, other.Spec.Selector) {
		return nil
	}

	// Check for conflicting rate limits
	if policy.Spec.RateLimits.DebatesPerMinute != nil && other.Spec.RateLimits.DebatesPerMinute != nil {
		if *policy.Spec.RateLimits.DebatesPerMinute != *other.Spec.RateLimits.DebatesPerMinute {
			return &aragorav1alpha1.PolicyConflict{
				PolicyName:   other.Name,
				ConflictType: "rate_limit",
				Description:  fmt.Sprintf("Conflicting debates per minute limits"),
			}
		}
	}

	return nil
}

func (r *AragoraPolicyReconciler) selectorsOverlap(s1, s2 *aragorav1alpha1.PolicySelector) bool {
	// If either selector matches all, they overlap
	if (s1 != nil && s1.MatchAll) || (s2 != nil && s2.MatchAll) {
		return true
	}

	// If both are nil, they match all (overlap)
	if s1 == nil && s2 == nil {
		return true
	}

	// If one is nil (matches all), they overlap
	if s1 == nil || s2 == nil {
		return true
	}

	// Check workspace overlap
	for _, ws1 := range s1.Workspaces {
		for _, ws2 := range s2.Workspaces {
			if ws1 == ws2 {
				return true
			}
		}
	}

	// Check tenant overlap
	for _, t1 := range s1.Tenants {
		for _, t2 := range s2.Tenants {
			if t1 == t2 {
				return true
			}
		}
	}

	return false
}

func (r *AragoraPolicyReconciler) applyPolicy(ctx context.Context, log logr.Logger, policy *aragorav1alpha1.AragoraPolicy, cluster *aragorav1alpha1.AragoraCluster) error {
	if r.APIEndpoint == "" {
		log.Info("No API endpoint configured, skipping policy sync")
		return nil
	}

	client := aragora.NewClient(r.APIEndpoint, r.APIToken)

	// Convert K8s policy to Aragora API format
	apiPolicy := r.convertToAPIPolicy(policy)

	// Send to Aragora control plane
	if err := client.ApplyPolicy(ctx, apiPolicy); err != nil {
		return fmt.Errorf("failed to apply policy to control plane: %w", err)
	}

	log.Info("Policy applied to control plane", "policy", policy.Name)
	return nil
}

func (r *AragoraPolicyReconciler) convertToAPIPolicy(policy *aragorav1alpha1.AragoraPolicy) *aragora.Policy {
	apiPolicy := &aragora.Policy{
		ID:       string(policy.UID),
		Name:     policy.Name,
		Priority: policy.Spec.Priority,
		Enabled:  policy.Spec.Enabled,
	}

	// Convert cost limits
	if policy.Spec.CostLimits != nil {
		apiPolicy.CostLimits = &aragora.CostLimits{
			AlertThresholdPercent: policy.Spec.CostLimits.AlertThresholdPercent,
			HardLimit:             policy.Spec.CostLimits.HardLimit,
		}
		if policy.Spec.CostLimits.DailyLimitUSD != nil {
			val := policy.Spec.CostLimits.DailyLimitUSD.AsApproximateFloat64()
			apiPolicy.CostLimits.DailyLimitUSD = &val
		}
		if policy.Spec.CostLimits.MonthlyLimitUSD != nil {
			val := policy.Spec.CostLimits.MonthlyLimitUSD.AsApproximateFloat64()
			apiPolicy.CostLimits.MonthlyLimitUSD = &val
		}
	}

	// Convert model restrictions
	for _, mr := range policy.Spec.ModelRestrictions {
		apiPolicy.ModelRestrictions = append(apiPolicy.ModelRestrictions, aragora.ModelRestriction{
			Name:                mr.Name,
			Allowed:             mr.Allowed,
			MaxRequestsPerHour:  mr.MaxRequestsPerHour,
			MaxTokensPerRequest: mr.MaxTokensPerRequest,
			AllowedOperations:   mr.AllowedOperations,
		})
	}

	// Convert rate limits
	if policy.Spec.RateLimits != nil {
		apiPolicy.RateLimits = &aragora.RateLimits{
			DebatesPerMinute:  policy.Spec.RateLimits.DebatesPerMinute,
			RequestsPerMinute: policy.Spec.RateLimits.RequestsPerMinute,
			TokensPerMinute:   policy.Spec.RateLimits.TokensPerMinute,
			ConcurrentDebates: policy.Spec.RateLimits.ConcurrentDebates,
			BurstLimit:        policy.Spec.RateLimits.BurstLimit,
			PerWorkspace:      policy.Spec.RateLimits.PerWorkspace,
		}
	}

	// Convert selector
	if policy.Spec.Selector != nil {
		apiPolicy.Selector = &aragora.PolicySelector{
			Workspaces: policy.Spec.Selector.Workspaces,
			Tenants:    policy.Spec.Selector.Tenants,
			MatchAll:   policy.Spec.Selector.MatchAll,
		}
	}

	return apiPolicy
}

func (r *AragoraPolicyReconciler) getAffectedWorkspaces(ctx context.Context, policy *aragorav1alpha1.AragoraPolicy) ([]string, error) {
	if r.APIEndpoint == "" {
		return nil, nil
	}

	client := aragora.NewClient(r.APIEndpoint, r.APIToken)
	return client.GetAffectedWorkspaces(ctx, string(policy.UID))
}

func (r *AragoraPolicyReconciler) setCondition(policy *aragorav1alpha1.AragoraPolicy, conditionType string, status metav1.ConditionStatus, reason, message string) {
	condition := metav1.Condition{
		Type:               conditionType,
		Status:             status,
		ObservedGeneration: policy.Generation,
		LastTransitionTime: metav1.Now(),
		Reason:             reason,
		Message:            message,
	}

	for i, existing := range policy.Status.Conditions {
		if existing.Type == conditionType {
			if existing.Status != status {
				policy.Status.Conditions[i] = condition
			}
			return
		}
	}
	policy.Status.Conditions = append(policy.Status.Conditions, condition)
}

func (r *AragoraPolicyReconciler) reconcileDelete(ctx context.Context, log logr.Logger, policy *aragorav1alpha1.AragoraPolicy) (ctrl.Result, error) {
	log.Info("Reconciling policy deletion")

	// Remove policy from control plane
	if r.APIEndpoint != "" {
		client := aragora.NewClient(r.APIEndpoint, r.APIToken)
		if err := client.DeletePolicy(ctx, string(policy.UID)); err != nil {
			log.Error(err, "Failed to delete policy from control plane")
			// Continue with deletion even if control plane sync fails
		}
	}

	// Remove finalizer
	controllerutil.RemoveFinalizer(policy, policyFinalizer)
	if err := r.Update(ctx, policy); err != nil {
		return ctrl.Result{}, err
	}

	r.Recorder.Event(policy, corev1.EventTypeNormal, "Deleted", "Policy deleted successfully")
	return ctrl.Result{}, nil
}

// SetupWithManager sets up the controller with the Manager
func (r *AragoraPolicyReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&aragorav1alpha1.AragoraPolicy{}).
		Complete(r)
}

// GetOrderedPolicies returns policies ordered by priority (highest first)
func GetOrderedPolicies(policies []aragorav1alpha1.AragoraPolicy) []aragorav1alpha1.AragoraPolicy {
	sorted := make([]aragorav1alpha1.AragoraPolicy, len(policies))
	copy(sorted, policies)
	sort.Slice(sorted, func(i, j int) bool {
		return sorted[i].Spec.Priority > sorted[j].Spec.Priority
	})
	return sorted
}
