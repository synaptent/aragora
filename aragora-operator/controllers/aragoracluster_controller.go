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
	"github.com/synaptent/aragora-operator/internal/aragora"
	"github.com/synaptent/aragora-operator/internal/metrics"
)

const (
	clusterFinalizer = "aragora.ai/cluster-finalizer"
	defaultImage     = "ghcr.io/synaptent/aragora:latest"
)

// AragoraClusterReconciler reconciles an AragoraCluster object
type AragoraClusterReconciler struct {
	client.Client
	Scheme           *runtime.Scheme
	Recorder         record.EventRecorder
	APIEndpoint      string
	APIToken         string
	MetricsCollector *metrics.Collector
}

// +kubebuilder:rbac:groups=aragora.ai,resources=aragoraclusters,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=aragora.ai,resources=aragoraclusters/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=aragora.ai,resources=aragoraclusters/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=statefulsets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=secrets,verbs=get;list;watch
// +kubebuilder:rbac:groups=core,resources=persistentvolumeclaims,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=events,verbs=create;patch

// Reconcile reconciles the AragoraCluster resource
func (r *AragoraClusterReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := ctrl.LoggerFrom(ctx)

	// Fetch the AragoraCluster instance
	cluster := &aragorav1alpha1.AragoraCluster{}
	if err := r.Get(ctx, req.NamespacedName, cluster); err != nil {
		if errors.IsNotFound(err) {
			log.Info("AragoraCluster resource not found, ignoring")
			return ctrl.Result{}, nil
		}
		log.Error(err, "Failed to get AragoraCluster")
		return ctrl.Result{}, err
	}

	// Record reconciliation metrics
	r.MetricsCollector.RecordReconciliation("AragoraCluster", cluster.Name)

	// Handle deletion
	if !cluster.DeletionTimestamp.IsZero() {
		return r.reconcileDelete(ctx, log, cluster)
	}

	// Add finalizer if not present
	if !controllerutil.ContainsFinalizer(cluster, clusterFinalizer) {
		controllerutil.AddFinalizer(cluster, clusterFinalizer)
		if err := r.Update(ctx, cluster); err != nil {
			return ctrl.Result{}, err
		}
	}

	// Reconcile the cluster
	result, err := r.reconcileCluster(ctx, log, cluster)
	if err != nil {
		r.MetricsCollector.RecordError("AragoraCluster", cluster.Name, err)
		r.Recorder.Event(cluster, corev1.EventTypeWarning, "ReconcileError", err.Error())
		return result, err
	}

	return result, nil
}

func (r *AragoraClusterReconciler) reconcileCluster(ctx context.Context, log logr.Logger, cluster *aragorav1alpha1.AragoraCluster) (ctrl.Result, error) {
	// Update status to Provisioning if Pending
	if cluster.Status.Phase == "" || cluster.Status.Phase == aragorav1alpha1.ClusterPhasePending {
		cluster.Status.Phase = aragorav1alpha1.ClusterPhaseProvisioning
		if err := r.Status().Update(ctx, cluster); err != nil {
			return ctrl.Result{}, err
		}
		r.Recorder.Event(cluster, corev1.EventTypeNormal, "Provisioning", "Cluster provisioning started")
	}

	// Reconcile ConfigMap
	if err := r.reconcileConfigMap(ctx, log, cluster); err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to reconcile ConfigMap: %w", err)
	}

	// Reconcile StatefulSet
	if err := r.reconcileStatefulSet(ctx, log, cluster); err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to reconcile StatefulSet: %w", err)
	}

	// Reconcile Service
	if err := r.reconcileService(ctx, log, cluster); err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to reconcile Service: %w", err)
	}

	// Reconcile Headless Service (for StatefulSet)
	if err := r.reconcileHeadlessService(ctx, log, cluster); err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to reconcile Headless Service: %w", err)
	}

	// Update cluster status
	if err := r.updateStatus(ctx, log, cluster); err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to update status: %w", err)
	}

	// Requeue after 30 seconds to check health
	return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
}

func (r *AragoraClusterReconciler) reconcileConfigMap(ctx context.Context, log logr.Logger, cluster *aragorav1alpha1.AragoraCluster) error {
	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      cluster.Name + "-config",
			Namespace: cluster.Namespace,
		},
	}

	op, err := controllerutil.CreateOrUpdate(ctx, r.Client, cm, func() error {
		cm.Data = map[string]string{
			"config.yaml": r.generateConfig(cluster),
		}
		return controllerutil.SetControllerReference(cluster, cm, r.Scheme)
	})

	if err != nil {
		return err
	}

	log.Info("ConfigMap reconciled", "operation", op)
	return nil
}

func (r *AragoraClusterReconciler) generateConfig(cluster *aragorav1alpha1.AragoraCluster) string {
	// Generate Aragora configuration YAML
	config := fmt.Sprintf(`
server:
  port: 8080
  host: 0.0.0.0

agents:
  enabled: %v
  fallback: "%s"
  default_model: "%s"

memory:
  backend: "%s"
  tiers:
`,
		cluster.Spec.Agents.Enabled,
		cluster.Spec.Agents.Fallback,
		cluster.Spec.Agents.DefaultModel,
		cluster.Spec.Memory.Backend,
	)

	for tier, cfg := range cluster.Spec.Memory.Tiers {
		config += fmt.Sprintf(`    %s:
      ttl: "%s"
      max_size: "%s"
`, tier, cfg.TTL.Duration.String(), cfg.MaxSize.String())
	}

	return config
}

func (r *AragoraClusterReconciler) reconcileStatefulSet(ctx context.Context, log logr.Logger, cluster *aragorav1alpha1.AragoraCluster) error {
	sts := &appsv1.StatefulSet{
		ObjectMeta: metav1.ObjectMeta{
			Name:      cluster.Name,
			Namespace: cluster.Namespace,
		},
	}

	op, err := controllerutil.CreateOrUpdate(ctx, r.Client, sts, func() error {
		replicas := cluster.Spec.Replicas
		if replicas == 0 {
			replicas = 1
		}

		image := cluster.Spec.Image
		if image == "" {
			image = defaultImage
		}

		labels := map[string]string{
			"app.kubernetes.io/name":       "aragora",
			"app.kubernetes.io/instance":   cluster.Name,
			"app.kubernetes.io/component":  "control-plane",
			"app.kubernetes.io/managed-by": "aragora-operator",
		}

		sts.Spec = appsv1.StatefulSetSpec{
			Replicas:    &replicas,
			ServiceName: cluster.Name + "-headless",
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: corev1.PodSpec{
					ServiceAccountName: cluster.Spec.ServiceAccountName,
					ImagePullSecrets:   cluster.Spec.ImagePullSecrets,
					NodeSelector:       cluster.Spec.NodeSelector,
					Tolerations:        cluster.Spec.Tolerations,
					Affinity:           cluster.Spec.Affinity,
					Containers: []corev1.Container{
						{
							Name:  "aragora",
							Image: image,
							Ports: []corev1.ContainerPort{
								{Name: "http", ContainerPort: 8080, Protocol: corev1.ProtocolTCP},
								{Name: "metrics", ContainerPort: 9090, Protocol: corev1.ProtocolTCP},
							},
							Resources: corev1.ResourceRequirements{
								Limits: corev1.ResourceList{
									corev1.ResourceMemory: cluster.Spec.Resources.Memory,
									corev1.ResourceCPU:    cluster.Spec.Resources.CPU,
								},
								Requests: r.getResourceRequests(cluster),
							},
							Env: append(cluster.Spec.Env, r.getDefaultEnv(cluster)...),
							VolumeMounts: []corev1.VolumeMount{
								{
									Name:      "config",
									MountPath: "/etc/aragora",
								},
								{
									Name:      "data",
									MountPath: "/var/lib/aragora",
								},
							},
							LivenessProbe: &corev1.Probe{
								ProbeHandler: corev1.ProbeHandler{
									HTTPGet: &corev1.HTTPGetAction{
										Path: "/health",
										Port: intstr.FromInt(8080),
									},
								},
								InitialDelaySeconds: 30,
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
					Volumes: []corev1.Volume{
						{
							Name: "config",
							VolumeSource: corev1.VolumeSource{
								ConfigMap: &corev1.ConfigMapVolumeSource{
									LocalObjectReference: corev1.LocalObjectReference{
										Name: cluster.Name + "-config",
									},
								},
							},
						},
					},
				},
			},
			VolumeClaimTemplates: []corev1.PersistentVolumeClaim{
				{
					ObjectMeta: metav1.ObjectMeta{
						Name: "data",
					},
					Spec: corev1.PersistentVolumeClaimSpec{
						AccessModes: []corev1.PersistentVolumeAccessMode{
							corev1.ReadWriteOnce,
						},
						StorageClassName: r.getStorageClassName(cluster),
						Resources: corev1.VolumeResourceRequirements{
							Requests: corev1.ResourceList{
								corev1.ResourceStorage: cluster.Spec.Storage.Size,
							},
						},
					},
				},
			},
		}

		return controllerutil.SetControllerReference(cluster, sts, r.Scheme)
	})

	if err != nil {
		return err
	}

	log.Info("StatefulSet reconciled", "operation", op)
	return nil
}

func (r *AragoraClusterReconciler) getResourceRequests(cluster *aragorav1alpha1.AragoraCluster) corev1.ResourceList {
	requests := corev1.ResourceList{}

	if cluster.Spec.Resources.RequestsMemory != nil {
		requests[corev1.ResourceMemory] = *cluster.Spec.Resources.RequestsMemory
	} else {
		// Default to half of limit
		mem := cluster.Spec.Resources.Memory.DeepCopy()
		mem.Set(mem.Value() / 2)
		requests[corev1.ResourceMemory] = mem
	}

	if cluster.Spec.Resources.RequestsCPU != nil {
		requests[corev1.ResourceCPU] = *cluster.Spec.Resources.RequestsCPU
	} else {
		// Default to half of limit
		requests[corev1.ResourceCPU] = resource.MustParse("500m")
	}

	return requests
}

func (r *AragoraClusterReconciler) getStorageClassName(cluster *aragorav1alpha1.AragoraCluster) *string {
	if cluster.Spec.Storage.StorageClassName != "" {
		return &cluster.Spec.Storage.StorageClassName
	}
	return nil
}

func (r *AragoraClusterReconciler) getDefaultEnv(cluster *aragorav1alpha1.AragoraCluster) []corev1.EnvVar {
	env := []corev1.EnvVar{
		{
			Name:  "ARAGORA_CONFIG_PATH",
			Value: "/etc/aragora/config.yaml",
		},
		{
			Name:  "ARAGORA_DATA_PATH",
			Value: "/var/lib/aragora",
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
			Name: "POD_NAMESPACE",
			ValueFrom: &corev1.EnvVarSource{
				FieldRef: &corev1.ObjectFieldSelector{
					FieldPath: "metadata.namespace",
				},
			},
		},
	}

	// Add API key references from secret
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

func (r *AragoraClusterReconciler) reconcileService(ctx context.Context, log logr.Logger, cluster *aragorav1alpha1.AragoraCluster) error {
	svc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      cluster.Name,
			Namespace: cluster.Namespace,
		},
	}

	op, err := controllerutil.CreateOrUpdate(ctx, r.Client, svc, func() error {
		labels := map[string]string{
			"app.kubernetes.io/name":     "aragora",
			"app.kubernetes.io/instance": cluster.Name,
		}

		svc.Spec = corev1.ServiceSpec{
			Selector: labels,
			Ports: []corev1.ServicePort{
				{
					Name:       "http",
					Port:       8080,
					TargetPort: intstr.FromInt(8080),
					Protocol:   corev1.ProtocolTCP,
				},
				{
					Name:       "metrics",
					Port:       9090,
					TargetPort: intstr.FromInt(9090),
					Protocol:   corev1.ProtocolTCP,
				},
			},
			Type: corev1.ServiceTypeClusterIP,
		}

		return controllerutil.SetControllerReference(cluster, svc, r.Scheme)
	})

	if err != nil {
		return err
	}

	log.Info("Service reconciled", "operation", op)
	return nil
}

func (r *AragoraClusterReconciler) reconcileHeadlessService(ctx context.Context, log logr.Logger, cluster *aragorav1alpha1.AragoraCluster) error {
	svc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:      cluster.Name + "-headless",
			Namespace: cluster.Namespace,
		},
	}

	op, err := controllerutil.CreateOrUpdate(ctx, r.Client, svc, func() error {
		labels := map[string]string{
			"app.kubernetes.io/name":     "aragora",
			"app.kubernetes.io/instance": cluster.Name,
		}

		svc.Spec = corev1.ServiceSpec{
			Selector:  labels,
			ClusterIP: "None",
			Ports: []corev1.ServicePort{
				{
					Name:       "http",
					Port:       8080,
					TargetPort: intstr.FromInt(8080),
					Protocol:   corev1.ProtocolTCP,
				},
			},
		}

		return controllerutil.SetControllerReference(cluster, svc, r.Scheme)
	})

	if err != nil {
		return err
	}

	log.Info("Headless Service reconciled", "operation", op)
	return nil
}

func (r *AragoraClusterReconciler) updateStatus(ctx context.Context, log logr.Logger, cluster *aragorav1alpha1.AragoraCluster) error {
	// Get the StatefulSet to check ready replicas
	sts := &appsv1.StatefulSet{}
	if err := r.Get(ctx, types.NamespacedName{Name: cluster.Name, Namespace: cluster.Namespace}, sts); err != nil {
		if !errors.IsNotFound(err) {
			return err
		}
	}

	// Update status
	cluster.Status.ReadyReplicas = sts.Status.ReadyReplicas
	cluster.Status.CurrentVersion = cluster.Spec.Version
	cluster.Status.Endpoint = fmt.Sprintf("%s.%s.svc.cluster.local:8080", cluster.Name, cluster.Namespace)
	cluster.Status.LastReconcileTime = &metav1.Time{Time: time.Now()}
	cluster.Status.ObservedGeneration = cluster.Generation

	// Determine phase
	if sts.Status.ReadyReplicas == cluster.Spec.Replicas {
		cluster.Status.Phase = aragorav1alpha1.ClusterPhaseRunning
		r.setCondition(cluster, "Ready", metav1.ConditionTrue, "ClusterReady", "All replicas are ready")
	} else if sts.Status.ReadyReplicas > 0 {
		cluster.Status.Phase = aragorav1alpha1.ClusterPhaseProvisioning
		r.setCondition(cluster, "Ready", metav1.ConditionFalse, "PartiallyReady",
			fmt.Sprintf("%d/%d replicas ready", sts.Status.ReadyReplicas, cluster.Spec.Replicas))
	} else {
		cluster.Status.Phase = aragorav1alpha1.ClusterPhaseProvisioning
		r.setCondition(cluster, "Ready", metav1.ConditionFalse, "NotReady", "No replicas ready")
	}

	// Fetch agent status from control plane API
	if r.APIEndpoint != "" {
		client := aragora.NewClient(r.APIEndpoint, r.APIToken)
		if agentStatus, err := client.GetAgentStatus(ctx); err == nil {
			cluster.Status.AgentStatus = agentStatus
		}
	}

	if err := r.Status().Update(ctx, cluster); err != nil {
		return err
	}

	// Update metrics
	r.MetricsCollector.RecordClusterStatus(cluster.Name, string(cluster.Status.Phase), int(cluster.Status.ReadyReplicas))

	return nil
}

func (r *AragoraClusterReconciler) setCondition(cluster *aragorav1alpha1.AragoraCluster, conditionType string, status metav1.ConditionStatus, reason, message string) {
	condition := metav1.Condition{
		Type:               conditionType,
		Status:             status,
		ObservedGeneration: cluster.Generation,
		LastTransitionTime: metav1.Now(),
		Reason:             reason,
		Message:            message,
	}

	// Update or add condition
	for i, existing := range cluster.Status.Conditions {
		if existing.Type == conditionType {
			if existing.Status != status {
				cluster.Status.Conditions[i] = condition
			}
			return
		}
	}
	cluster.Status.Conditions = append(cluster.Status.Conditions, condition)
}

func (r *AragoraClusterReconciler) reconcileDelete(ctx context.Context, log logr.Logger, cluster *aragorav1alpha1.AragoraCluster) (ctrl.Result, error) {
	log.Info("Reconciling cluster deletion")

	cluster.Status.Phase = aragorav1alpha1.ClusterPhaseTerminating
	if err := r.Status().Update(ctx, cluster); err != nil {
		return ctrl.Result{}, err
	}

	// Perform any cleanup tasks here
	// The StatefulSet, Services, and ConfigMap will be garbage collected due to owner references

	// Remove finalizer
	controllerutil.RemoveFinalizer(cluster, clusterFinalizer)
	if err := r.Update(ctx, cluster); err != nil {
		return ctrl.Result{}, err
	}

	r.Recorder.Event(cluster, corev1.EventTypeNormal, "Deleted", "Cluster deleted successfully")
	return ctrl.Result{}, nil
}

// SetupWithManager sets up the controller with the Manager
func (r *AragoraClusterReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&aragorav1alpha1.AragoraCluster{}).
		Owns(&appsv1.StatefulSet{}).
		Owns(&corev1.Service{}).
		Owns(&corev1.ConfigMap{}).
		Complete(r)
}

func boolPtr(b bool) *bool {
	return &b
}
