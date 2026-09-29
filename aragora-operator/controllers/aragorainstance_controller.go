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
	"time"

	"github.com/go-logr/logr"
	appsv1 "k8s.io/api/apps/v1"
	autoscalingv2 "k8s.io/api/autoscaling/v2"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	"k8s.io/client-go/tools/record"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	aragorav1alpha1 "github.com/synaptent/aragora-operator/api/v1alpha1"
	"github.com/synaptent/aragora-operator/internal/metrics"
)

const (
	instanceFinalizer = "aragora.ai/instance-finalizer"
)

// AragoraInstanceReconciler reconciles an AragoraInstance object
type AragoraInstanceReconciler struct {
	client.Client
	Scheme           *runtime.Scheme
	Recorder         record.EventRecorder
	MetricsCollector *metrics.Collector
}

// +kubebuilder:rbac:groups=aragora.ai,resources=aragorainstances,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=aragora.ai,resources=aragorainstances/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=aragora.ai,resources=aragorainstances/finalizers,verbs=update
// +kubebuilder:rbac:groups=aragora.ai,resources=aragorainstances/scale,verbs=get;update;patch
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=autoscaling,resources=horizontalpodautoscalers,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=pods,verbs=get;list;watch

// Reconcile reconciles the AragoraInstance resource
func (r *AragoraInstanceReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := ctrl.LoggerFrom(ctx)

	// Fetch the AragoraInstance instance
	instance := &aragorav1alpha1.AragoraInstance{}
	if err := r.Get(ctx, req.NamespacedName, instance); err != nil {
		if errors.IsNotFound(err) {
			log.Info("AragoraInstance resource not found, ignoring")
			return ctrl.Result{}, nil
		}
		log.Error(err, "Failed to get AragoraInstance")
		return ctrl.Result{}, err
	}

	// Record reconciliation metrics
	r.MetricsCollector.RecordReconciliation("AragoraInstance", instance.Name)

	// Handle deletion
	if !instance.DeletionTimestamp.IsZero() {
		return r.reconcileDelete(ctx, log, instance)
	}

	// Add finalizer if not present
	if !controllerutil.ContainsFinalizer(instance, instanceFinalizer) {
		controllerutil.AddFinalizer(instance, instanceFinalizer)
		if err := r.Update(ctx, instance); err != nil {
			return ctrl.Result{}, err
		}
	}

	// Verify cluster reference exists
	cluster := &aragorav1alpha1.AragoraCluster{}
	if err := r.Get(ctx, types.NamespacedName{Name: instance.Spec.ClusterRef, Namespace: instance.Namespace}, cluster); err != nil {
		if errors.IsNotFound(err) {
			r.setCondition(instance, "ClusterRef", metav1.ConditionFalse, "ClusterNotFound",
				fmt.Sprintf("Referenced cluster %s not found", instance.Spec.ClusterRef))
			if err := r.Status().Update(ctx, instance); err != nil {
				return ctrl.Result{}, err
			}
			return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
		}
		return ctrl.Result{}, err
	}

	// Reconcile the instance
	result, err := r.reconcileInstance(ctx, log, instance, cluster)
	if err != nil {
		r.MetricsCollector.RecordError("AragoraInstance", instance.Name, err)
		r.Recorder.Event(instance, corev1.EventTypeWarning, "ReconcileError", err.Error())
		return result, err
	}

	return result, nil
}

func (r *AragoraInstanceReconciler) reconcileInstance(ctx context.Context, log logr.Logger, instance *aragorav1alpha1.AragoraInstance, cluster *aragorav1alpha1.AragoraCluster) (ctrl.Result, error) {
	// Update status to Starting if Pending
	if instance.Status.Phase == "" || instance.Status.Phase == aragorav1alpha1.InstancePhasePending {
		instance.Status.Phase = aragorav1alpha1.InstancePhaseStarting
		if err := r.Status().Update(ctx, instance); err != nil {
			return ctrl.Result{}, err
		}
		r.Recorder.Event(instance, corev1.EventTypeNormal, "Starting", "Instance starting")
	}

	// Reconcile Deployment
	if err := r.reconcileDeployment(ctx, log, instance, cluster); err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to reconcile Deployment: %w", err)
	}

	// Reconcile HPA if scaling is enabled
	if instance.Spec.Scaling != nil && instance.Spec.Scaling.Enabled {
		if err := r.reconcileHPA(ctx, log, instance); err != nil {
			return ctrl.Result{}, fmt.Errorf("failed to reconcile HPA: %w", err)
		}
	} else {
		// Delete HPA if it exists but scaling is disabled
		if err := r.deleteHPAIfExists(ctx, instance); err != nil {
			return ctrl.Result{}, err
		}
	}

	// Update instance status
	if err := r.updateStatus(ctx, log, instance); err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to update status: %w", err)
	}

	// Requeue after 30 seconds to check status
	return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
}

func (r *AragoraInstanceReconciler) reconcileDeployment(ctx context.Context, log logr.Logger, instance *aragorav1alpha1.AragoraInstance, cluster *aragorav1alpha1.AragoraCluster) error {
	deploy := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      instance.Name,
			Namespace: instance.Namespace,
		},
	}

	op, err := controllerutil.CreateOrUpdate(ctx, r.Client, deploy, func() error {
		replicas := instance.Spec.Scaling.MinReplicas
		if replicas == 0 {
			replicas = 1
		}

		image := cluster.Spec.Image
		if image == "" {
			image = defaultImage
		}

		labels := map[string]string{
			"app.kubernetes.io/name":       "aragora",
			"app.kubernetes.io/instance":   instance.Name,
			"app.kubernetes.io/component":  string(instance.Spec.Role),
			"app.kubernetes.io/managed-by": "aragora-operator",
			"aragora.ai/cluster":           instance.Spec.ClusterRef,
		}

		// Add user-defined labels
		for k, v := range instance.Spec.Labels {
			labels[k] = v
		}

		// Use instance resources or fall back to cluster resources
		resources := cluster.Spec.Resources
		if instance.Spec.Resources != nil {
			resources = *instance.Spec.Resources
		}

		deploy.Spec = appsv1.DeploymentSpec{
			Replicas: &replicas,
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
					Annotations: map[string]string{
						"prometheus.io/scrape": "true",
						"prometheus.io/port":   "9090",
					},
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: cluster.Spec.ServiceAccountName,
					ImagePullSecrets:   cluster.Spec.ImagePullSecrets,
					NodeSelector:       r.mergeNodeSelector(cluster.Spec.NodeSelector, instance.Spec.NodeSelector),
					Tolerations:        r.mergeTolerations(cluster.Spec.Tolerations, instance.Spec.Tolerations),
					Affinity:           r.buildAffinity(instance, cluster),
					Containers: []corev1.Container{
						{
							Name:  "aragora-worker",
							Image: image,
							Args:  r.getContainerArgs(instance),
							Ports: []corev1.ContainerPort{
								{Name: "http", ContainerPort: 8080, Protocol: corev1.ProtocolTCP},
								{Name: "metrics", ContainerPort: 9090, Protocol: corev1.ProtocolTCP},
							},
							Resources: corev1.ResourceRequirements{
								Limits: corev1.ResourceList{
									corev1.ResourceMemory: resources.Memory,
									corev1.ResourceCPU:    resources.CPU,
								},
								Requests: r.getResourceRequests(&resources),
							},
							Env: r.getWorkerEnv(instance, cluster),
							LivenessProbe: &corev1.Probe{
								ProbeHandler: corev1.ProbeHandler{
									HTTPGet: &corev1.HTTPGetAction{
										Path: "/health",
										Port: intstr.FromInt(8080),
									},
								},
								InitialDelaySeconds: 10,
								PeriodSeconds:       10,
							},
							ReadinessProbe: &corev1.Probe{
								ProbeHandler: corev1.ProbeHandler{
									HTTPGet: &corev1.HTTPGetAction{
										Path: "/ready",
										Port: intstr.FromInt(8080),
									},
								},
								InitialDelaySeconds: 5,
								PeriodSeconds:       5,
							},
						},
					},
				},
			},
			Strategy: appsv1.DeploymentStrategy{
				Type: appsv1.RollingUpdateDeploymentStrategyType,
				RollingUpdate: &appsv1.RollingUpdateDeployment{
					MaxUnavailable: &intstr.IntOrString{Type: intstr.Int, IntVal: 1},
					MaxSurge:       &intstr.IntOrString{Type: intstr.Int, IntVal: 1},
				},
			},
		}

		return controllerutil.SetControllerReference(instance, deploy, r.Scheme)
	})

	if err != nil {
		return err
	}

	log.Info("Deployment reconciled", "operation", op)
	return nil
}

func (r *AragoraInstanceReconciler) getContainerArgs(instance *aragorav1alpha1.AragoraInstance) []string {
	args := []string{
		"--role", string(instance.Spec.Role),
		"--max-concurrent-debates", fmt.Sprintf("%d", instance.Spec.MaxConcurrentDebates),
		"--priority", fmt.Sprintf("%d", instance.Spec.Priority),
	}

	if len(instance.Spec.Capabilities) > 0 {
		for _, cap := range instance.Spec.Capabilities {
			args = append(args, "--capability", cap)
		}
	}

	return args
}

func (r *AragoraInstanceReconciler) getWorkerEnv(instance *aragorav1alpha1.AragoraInstance, cluster *aragorav1alpha1.AragoraCluster) []corev1.EnvVar {
	env := []corev1.EnvVar{
		{
			Name:  "ARAGORA_CLUSTER",
			Value: cluster.Name,
		},
		{
			Name:  "ARAGORA_INSTANCE",
			Value: instance.Name,
		},
		{
			Name:  "ARAGORA_ROLE",
			Value: string(instance.Spec.Role),
		},
		{
			Name:  "ARAGORA_CONTROL_PLANE_URL",
			Value: fmt.Sprintf("http://%s.%s.svc.cluster.local:8080", cluster.Name, cluster.Namespace),
		},
		{
			Name: "POD_NAME",
			ValueFrom: &corev1.EnvVarSource{
				FieldRef: &corev1.ObjectFieldSelector{
					FieldPath: "metadata.name",
				},
			},
		},
		{
			Name: "POD_IP",
			ValueFrom: &corev1.EnvVarSource{
				FieldRef: &corev1.ObjectFieldSelector{
					FieldPath: "status.podIP",
				},
			},
		},
	}

	// Add API keys from cluster secret
	if cluster.Spec.SecretRef != nil {
		for _, key := range []string{"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"} {
			env = append(env, corev1.EnvVar{
				Name: key,
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: &corev1.SecretKeySelector{
						LocalObjectReference: corev1.LocalObjectReference{
							Name: cluster.Spec.SecretRef.Name,
						},
						Key:      key,
						Optional: boolPtr(true),
					},
				},
			})
		}
	}

	return env
}

func (r *AragoraInstanceReconciler) reconcileHPA(ctx context.Context, log logr.Logger, instance *aragorav1alpha1.AragoraInstance) error {
	hpa := &autoscalingv2.HorizontalPodAutoscaler{
		ObjectMeta: metav1.ObjectMeta{
			Name:      instance.Name,
			Namespace: instance.Namespace,
		},
	}

	op, err := controllerutil.CreateOrUpdate(ctx, r.Client, hpa, func() error {
		scaling := instance.Spec.Scaling
		minReplicas := scaling.MinReplicas
		maxReplicas := scaling.MaxReplicas

		if minReplicas == 0 {
			minReplicas = 1
		}
		if maxReplicas == 0 {
			maxReplicas = 10
		}

		hpa.Spec = autoscalingv2.HorizontalPodAutoscalerSpec{
			ScaleTargetRef: autoscalingv2.CrossVersionObjectReference{
				APIVersion: "apps/v1",
				Kind:       "Deployment",
				Name:       instance.Name,
			},
			MinReplicas: &minReplicas,
			MaxReplicas: maxReplicas,
			Metrics:     r.getHPAMetrics(scaling),
			Behavior:    r.getHPABehavior(scaling),
		}

		return controllerutil.SetControllerReference(instance, hpa, r.Scheme)
	})

	if err != nil {
		return err
	}

	log.Info("HPA reconciled", "operation", op)
	return nil
}

func (r *AragoraInstanceReconciler) getHPAMetrics(scaling *aragorav1alpha1.ScalingConfig) []autoscalingv2.MetricSpec {
	var metrics []autoscalingv2.MetricSpec

	switch scaling.Metric {
	case aragorav1alpha1.ScalingMetricCPU:
		targetUtilization := int32(scaling.Target)
		if targetUtilization == 0 {
			targetUtilization = 70
		}
		metrics = append(metrics, autoscalingv2.MetricSpec{
			Type: autoscalingv2.ResourceMetricSourceType,
			Resource: &autoscalingv2.ResourceMetricSource{
				Name: corev1.ResourceCPU,
				Target: autoscalingv2.MetricTarget{
					Type:               autoscalingv2.UtilizationMetricType,
					AverageUtilization: &targetUtilization,
				},
			},
		})
	case aragorav1alpha1.ScalingMetricMemory:
		targetUtilization := int32(scaling.Target)
		if targetUtilization == 0 {
			targetUtilization = 70
		}
		metrics = append(metrics, autoscalingv2.MetricSpec{
			Type: autoscalingv2.ResourceMetricSourceType,
			Resource: &autoscalingv2.ResourceMetricSource{
				Name: corev1.ResourceMemory,
				Target: autoscalingv2.MetricTarget{
					Type:               autoscalingv2.UtilizationMetricType,
					AverageUtilization: &targetUtilization,
				},
			},
		})
	case aragorav1alpha1.ScalingMetricDebatesPerSecond, aragorav1alpha1.ScalingMetricQueueDepth:
		// Custom metrics for Aragora-specific scaling
		targetValue := int64(scaling.Target)
		if targetValue == 0 {
			targetValue = 10
		}
		metrics = append(metrics, autoscalingv2.MetricSpec{
			Type: autoscalingv2.PodsMetricSourceType,
			Pods: &autoscalingv2.PodsMetricSource{
				Metric: autoscalingv2.MetricIdentifier{
					Name: "aragora_" + string(scaling.Metric),
				},
				Target: autoscalingv2.MetricTarget{
					Type:         autoscalingv2.AverageValueMetricType,
					AverageValue: resourceQuantityPtr(targetValue),
				},
			},
		})
	}

	return metrics
}

func (r *AragoraInstanceReconciler) getHPABehavior(scaling *aragorav1alpha1.ScalingConfig) *autoscalingv2.HorizontalPodAutoscalerBehavior {
	behavior := &autoscalingv2.HorizontalPodAutoscalerBehavior{}

	// Set default scale down stabilization window
	stabilizationWindowSeconds := scaling.ScaleDownStabilizationWindowSeconds
	if stabilizationWindowSeconds == 0 {
		stabilizationWindowSeconds = 300
	}

	behavior.ScaleDown = &autoscalingv2.HPAScalingRules{
		StabilizationWindowSeconds: &stabilizationWindowSeconds,
		Policies: []autoscalingv2.HPAScalingPolicy{
			{
				Type:          autoscalingv2.PodsScalingPolicy,
				Value:         1,
				PeriodSeconds: 60,
			},
		},
	}

	behavior.ScaleUp = &autoscalingv2.HPAScalingRules{
		Policies: []autoscalingv2.HPAScalingPolicy{
			{
				Type:          autoscalingv2.PodsScalingPolicy,
				Value:         4,
				PeriodSeconds: 60,
			},
			{
				Type:          autoscalingv2.PercentScalingPolicy,
				Value:         100,
				PeriodSeconds: 60,
			},
		},
		SelectPolicy: scaleSelectPolicyPtr(autoscalingv2.MaxChangePolicySelect),
	}

	// Apply custom behavior if specified
	if scaling.Behavior != nil {
		if scaling.Behavior.ScaleDown != nil {
			behavior.ScaleDown.StabilizationWindowSeconds = &scaling.Behavior.ScaleDown.StabilizationWindowSeconds
		}
		if scaling.Behavior.ScaleUp != nil {
			behavior.ScaleUp.StabilizationWindowSeconds = &scaling.Behavior.ScaleUp.StabilizationWindowSeconds
		}
	}

	return behavior
}

func (r *AragoraInstanceReconciler) deleteHPAIfExists(ctx context.Context, instance *aragorav1alpha1.AragoraInstance) error {
	hpa := &autoscalingv2.HorizontalPodAutoscaler{}
	if err := r.Get(ctx, types.NamespacedName{Name: instance.Name, Namespace: instance.Namespace}, hpa); err != nil {
		if errors.IsNotFound(err) {
			return nil
		}
		return err
	}
	return r.Delete(ctx, hpa)
}

func (r *AragoraInstanceReconciler) updateStatus(ctx context.Context, log logr.Logger, instance *aragorav1alpha1.AragoraInstance) error {
	// Get the Deployment to check status
	deploy := &appsv1.Deployment{}
	if err := r.Get(ctx, types.NamespacedName{Name: instance.Name, Namespace: instance.Namespace}, deploy); err != nil {
		if !errors.IsNotFound(err) {
			return err
		}
	}

	// Get pods for detailed status
	podList := &corev1.PodList{}
	if err := r.List(ctx, podList, client.InNamespace(instance.Namespace), client.MatchingLabels{
		"app.kubernetes.io/instance": instance.Name,
	}); err != nil {
		return err
	}

	// Update pod statuses
	instance.Status.PodStatuses = []aragorav1alpha1.PodStatus{}
	for _, pod := range podList.Items {
		podStatus := aragorav1alpha1.PodStatus{
			Name:  pod.Name,
			Ready: isPodReady(&pod),
			IP:    pod.Status.PodIP,
			Node:  pod.Spec.NodeName,
		}
		instance.Status.PodStatuses = append(instance.Status.PodStatuses, podStatus)
	}

	// Update replica counts
	instance.Status.CurrentReplicas = deploy.Status.ReadyReplicas
	if instance.Spec.Scaling != nil {
		instance.Status.DesiredReplicas = instance.Spec.Scaling.MinReplicas
	} else {
		instance.Status.DesiredReplicas = 1
	}
	instance.Status.ObservedGeneration = instance.Generation

	// Determine phase
	if deploy.Status.ReadyReplicas > 0 && deploy.Status.ReadyReplicas == deploy.Status.Replicas {
		instance.Status.Phase = aragorav1alpha1.InstancePhaseRunning
		instance.Status.Ready = true
		r.setCondition(instance, "Ready", metav1.ConditionTrue, "InstanceReady", "All replicas are ready")
	} else if deploy.Status.ReadyReplicas > 0 {
		instance.Status.Phase = aragorav1alpha1.InstancePhaseStarting
		instance.Status.Ready = false
		r.setCondition(instance, "Ready", metav1.ConditionFalse, "PartiallyReady",
			fmt.Sprintf("%d/%d replicas ready", deploy.Status.ReadyReplicas, deploy.Status.Replicas))
	} else {
		instance.Status.Phase = aragorav1alpha1.InstancePhaseStarting
		instance.Status.Ready = false
		r.setCondition(instance, "Ready", metav1.ConditionFalse, "NotReady", "No replicas ready")
	}

	if err := r.Status().Update(ctx, instance); err != nil {
		return err
	}

	// Update metrics
	r.MetricsCollector.RecordInstanceStatus(instance.Name, string(instance.Status.Phase), int(instance.Status.CurrentReplicas))

	return nil
}

func (r *AragoraInstanceReconciler) setCondition(instance *aragorav1alpha1.AragoraInstance, conditionType string, status metav1.ConditionStatus, reason, message string) {
	condition := metav1.Condition{
		Type:               conditionType,
		Status:             status,
		ObservedGeneration: instance.Generation,
		LastTransitionTime: metav1.Now(),
		Reason:             reason,
		Message:            message,
	}

	for i, existing := range instance.Status.Conditions {
		if existing.Type == conditionType {
			if existing.Status != status {
				instance.Status.Conditions[i] = condition
			}
			return
		}
	}
	instance.Status.Conditions = append(instance.Status.Conditions, condition)
}

func (r *AragoraInstanceReconciler) reconcileDelete(ctx context.Context, log logr.Logger, instance *aragorav1alpha1.AragoraInstance) (ctrl.Result, error) {
	log.Info("Reconciling instance deletion")

	// Set draining phase
	if instance.Status.Phase != aragorav1alpha1.InstancePhaseDraining {
		instance.Status.Phase = aragorav1alpha1.InstancePhaseDraining
		if err := r.Status().Update(ctx, instance); err != nil {
			return ctrl.Result{}, err
		}
		r.Recorder.Event(instance, corev1.EventTypeNormal, "Draining", "Instance draining active debates")
		// Requeue to allow time for draining
		return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
	}

	// Check if draining is complete (no active debates)
	if instance.Status.ActiveDebates > 0 {
		log.Info("Waiting for debates to drain", "activeDebates", instance.Status.ActiveDebates)
		return ctrl.Result{RequeueAfter: 5 * time.Second}, nil
	}

	// Remove finalizer
	controllerutil.RemoveFinalizer(instance, instanceFinalizer)
	if err := r.Update(ctx, instance); err != nil {
		return ctrl.Result{}, err
	}

	r.Recorder.Event(instance, corev1.EventTypeNormal, "Deleted", "Instance deleted successfully")
	return ctrl.Result{}, nil
}

func (r *AragoraInstanceReconciler) mergeNodeSelector(cluster, instance map[string]string) map[string]string {
	if len(instance) == 0 {
		return cluster
	}
	merged := make(map[string]string)
	for k, v := range cluster {
		merged[k] = v
	}
	for k, v := range instance {
		merged[k] = v
	}
	return merged
}

func (r *AragoraInstanceReconciler) mergeTolerations(cluster, instance []corev1.Toleration) []corev1.Toleration {
	return append(cluster, instance...)
}

func (r *AragoraInstanceReconciler) buildAffinity(instance *aragorav1alpha1.AragoraInstance, cluster *aragorav1alpha1.AragoraCluster) *corev1.Affinity {
	affinity := cluster.Spec.Affinity
	if affinity == nil {
		affinity = &corev1.Affinity{}
	}

	// Add anti-affinity to spread worker pods across nodes
	if instance.Spec.Role == aragorav1alpha1.InstanceRoleWorker {
		affinity.PodAntiAffinity = &corev1.PodAntiAffinity{
			PreferredDuringSchedulingIgnoredDuringExecution: []corev1.WeightedPodAffinityTerm{
				{
					Weight: 100,
					PodAffinityTerm: corev1.PodAffinityTerm{
						LabelSelector: &metav1.LabelSelector{
							MatchLabels: map[string]string{
								"app.kubernetes.io/instance": instance.Name,
							},
						},
						TopologyKey: "kubernetes.io/hostname",
					},
				},
			},
		}
	}

	return affinity
}

func (r *AragoraInstanceReconciler) getResourceRequests(resources *aragorav1alpha1.ResourceRequirements) corev1.ResourceList {
	requests := corev1.ResourceList{}

	if resources.RequestsMemory != nil {
		requests[corev1.ResourceMemory] = *resources.RequestsMemory
	} else {
		mem := resources.Memory.DeepCopy()
		mem.Set(mem.Value() / 2)
		requests[corev1.ResourceMemory] = mem
	}

	if resources.RequestsCPU != nil {
		requests[corev1.ResourceCPU] = *resources.RequestsCPU
	} else {
		requests[corev1.ResourceCPU] = *resourceQuantityPtr(250)
	}

	return requests
}

// SetupWithManager sets up the controller with the Manager
func (r *AragoraInstanceReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&aragorav1alpha1.AragoraInstance{}).
		Owns(&appsv1.Deployment{}).
		Owns(&autoscalingv2.HorizontalPodAutoscaler{}).
		Complete(r)
}

func isPodReady(pod *corev1.Pod) bool {
	for _, condition := range pod.Status.Conditions {
		if condition.Type == corev1.PodReady && condition.Status == corev1.ConditionTrue {
			return true
		}
	}
	return false
}

func resourceQuantityPtr(value int64) *resource.Quantity {
	q := resource.NewQuantity(value, resource.DecimalSI)
	return q
}

func scaleSelectPolicyPtr(policy autoscalingv2.ScalingPolicySelect) *autoscalingv2.ScalingPolicySelect {
	return &policy
}
