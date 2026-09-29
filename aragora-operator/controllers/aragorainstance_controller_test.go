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
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	ctrl "sigs.k8s.io/controller-runtime"

	aragorav1alpha1 "github.com/synaptent/aragora-operator/api/v1alpha1"
)

func TestAragoraInstanceReconcilerSetsStatus(t *testing.T) {
	cfg, c := requireEnvtest(t)
	defer stopControlPlaneOnPanic()

	namespace := newNamespace(t, c)
	mgr := newManager(t, cfg, namespace, ctrl.Options{})
	setupInstanceReconciler(t, mgr)
	startManager(t, mgr)

	orphan := newTestInstance(namespace, "orphan", "no-such-cluster")
	create(t, c, orphan)
	waitForCondition(t, c, orphan, "ClusterRef", metav1.ConditionFalse, "ClusterNotFound")

	cluster := newTestCluster(namespace, "aragora")
	create(t, c, cluster)
	instance := newTestInstance(namespace, "worker", cluster.Name)
	create(t, c, instance)

	// No kubelet runs under envtest, so the Deployment never has ready replicas.
	waitForCondition(t, c, instance, "Ready", metav1.ConditionFalse, "NotReady")
	if instance.Status.Phase != aragorav1alpha1.InstancePhaseStarting {
		t.Errorf("phase = %q, want %q", instance.Status.Phase, aragorav1alpha1.InstancePhaseStarting)
	}
	if instance.Status.ObservedGeneration != instance.Generation {
		t.Errorf("observedGeneration = %d, want %d", instance.Status.ObservedGeneration, instance.Generation)
	}
	if instance.Status.DesiredReplicas != instance.Spec.Scaling.MinReplicas {
		t.Errorf("desiredReplicas = %d, want %d", instance.Status.DesiredReplicas, instance.Spec.Scaling.MinReplicas)
	}

	deploy := &appsv1.Deployment{}
	assertControlledBy(t, c, instance, instance.Name, deploy)
	if got := deploy.Spec.Replicas; got == nil || *got != instance.Spec.Scaling.MinReplicas {
		t.Errorf("Deployment replicas = %v, want %d", got, instance.Spec.Scaling.MinReplicas)
	}
}

// newTestInstance sets Scaling because the reconciler reads
// Spec.Scaling.MinReplicas without a nil check, and it inherits the test
// cluster's explicit CPU request because the reconciler's default request is
// 250 whole CPUs, above the 500m limit, which the API server rejects.
func newTestInstance(namespace, name, clusterRef string) *aragorav1alpha1.AragoraInstance {
	return &aragorav1alpha1.AragoraInstance{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
		Spec: aragorav1alpha1.AragoraInstanceSpec{
			ClusterRef: clusterRef,
			Role:       aragorav1alpha1.InstanceRoleWorker,
			Scaling: &aragorav1alpha1.ScalingConfig{
				MinReplicas: 2,
				MaxReplicas: 4,
			},
		},
	}
}
