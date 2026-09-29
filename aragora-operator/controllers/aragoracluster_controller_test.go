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
	"errors"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"

	aragorav1alpha1 "github.com/synaptent/aragora-operator/api/v1alpha1"
)

// envtest runs no kubelet or StatefulSet controller, so no replica ever
// becomes ready and the Ready condition can only be False/NotReady.
func TestAragoraClusterReconcilerSetsReadyCondition(t *testing.T) {
	cfg, c := requireEnvtest(t)
	defer stopControlPlaneOnPanic()

	namespace := newNamespace(t, c)
	api := newFakeControlPlane(t)
	mgr := newManager(t, cfg, namespace, ctrl.Options{})
	setupClusterReconciler(t, mgr, api.URL)
	startManager(t, mgr)

	cluster := newTestCluster(namespace, "aragora")
	create(t, c, cluster)
	key := client.ObjectKeyFromObject(cluster)

	eventually(t, "AragoraCluster has a Ready condition", func(ctx context.Context) error {
		if err := c.Get(ctx, key, cluster); err != nil {
			return err
		}
		if meta.FindStatusCondition(cluster.Status.Conditions, "Ready") == nil {
			return errors.New("no Ready condition yet")
		}
		return nil
	})
	ready := meta.FindStatusCondition(cluster.Status.Conditions, "Ready")
	t.Logf("Ready condition: status=%s reason=%s message=%q", ready.Status, ready.Reason, ready.Message)
	if ready.Status != metav1.ConditionFalse || ready.Reason != "NotReady" {
		t.Errorf("Ready condition = %s/%s, want False/NotReady", ready.Status, ready.Reason)
	}
	if cluster.Status.Phase != aragorav1alpha1.ClusterPhaseProvisioning {
		t.Errorf("phase = %q, want %q", cluster.Status.Phase, aragorav1alpha1.ClusterPhaseProvisioning)
	}
	if !cluster.Status.AgentStatus[fakeAgent].Available {
		t.Errorf("agentStatus = %v, want %q available as reported by the fake control plane",
			cluster.Status.AgentStatus, fakeAgent)
	}
	if !api.received("GET " + agentsPath) {
		t.Errorf("the reconciler never called GET %s on the fake control plane", agentsPath)
	}

	assertControlledBy(t, c, cluster, cluster.Name, &appsv1.StatefulSet{})
	assertControlledBy(t, c, cluster, cluster.Name+"-config", &corev1.ConfigMap{})
	assertControlledBy(t, c, cluster, cluster.Name, &corev1.Service{})
	assertControlledBy(t, c, cluster, cluster.Name+"-headless", &corev1.Service{})

	if err := c.Delete(context.Background(), cluster); err != nil {
		t.Fatalf("delete AragoraCluster: %v", err)
	}
	eventuallyDeleted(t, c, cluster)
}
