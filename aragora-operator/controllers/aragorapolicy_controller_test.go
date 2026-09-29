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
	"slices"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	ctrl "sigs.k8s.io/controller-runtime"

	aragorav1alpha1 "github.com/synaptent/aragora-operator/api/v1alpha1"
)

func TestAragoraPolicyReconcilerAppliesPolicy(t *testing.T) {
	cfg, c := requireEnvtest(t)
	defer stopControlPlaneOnPanic()

	namespace := newNamespace(t, c)
	api := newFakeControlPlane(t)
	mgr := newManager(t, cfg, namespace, ctrl.Options{})
	setupPolicyReconciler(t, mgr, api.URL)
	startManager(t, mgr)

	orphan := newTestPolicy(namespace, "orphan", "no-such-cluster")
	create(t, c, orphan)
	waitForCondition(t, c, orphan, "ClusterRef", metav1.ConditionFalse, "ClusterNotFound")
	if orphan.Status.Phase != aragorav1alpha1.PolicyPhaseError {
		t.Errorf("phase of a policy without its cluster = %q, want %q",
			orphan.Status.Phase, aragorav1alpha1.PolicyPhaseError)
	}

	cluster := newTestCluster(namespace, "aragora")
	create(t, c, cluster)
	policy := newTestPolicy(namespace, "cost-guard", cluster.Name)
	create(t, c, policy)

	waitForCondition(t, c, policy, "Applied", metav1.ConditionTrue, "PolicyApplied")
	if policy.Status.Phase != aragorav1alpha1.PolicyPhaseActive || !policy.Status.Applied {
		t.Errorf("phase/applied = %q/%v, want %q/true",
			policy.Status.Phase, policy.Status.Applied, aragorav1alpha1.PolicyPhaseActive)
	}
	if !slices.Equal(policy.Status.AffectedWorkspaces, []string{fakeWorkspace}) {
		t.Errorf("affectedWorkspaces = %v, want [%s] from the fake control plane",
			policy.Status.AffectedWorkspaces, fakeWorkspace)
	}
	policyPath := policiesPath + string(policy.UID)
	if !api.received("PUT " + policyPath) {
		t.Errorf("the reconciler never called PUT %s on the fake control plane", policyPath)
	}

	if err := c.Delete(context.Background(), policy); err != nil {
		t.Fatalf("delete AragoraPolicy: %v", err)
	}
	eventuallyDeleted(t, c, policy)
	if !api.received("DELETE " + policyPath) {
		t.Errorf("deleting the policy never called DELETE %s on the fake control plane", policyPath)
	}
}

// newTestPolicy relies on the CRD default for spec.enabled: the field is
// `omitempty`, so false is never sent and the API server defaults it to true.
func newTestPolicy(namespace, name, clusterRef string) *aragorav1alpha1.AragoraPolicy {
	perMinute := 30
	return &aragorav1alpha1.AragoraPolicy{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
		Spec: aragorav1alpha1.AragoraPolicySpec{
			ClusterRef: clusterRef,
			Priority:   100,
			Enabled:    true,
			RateLimits: &aragorav1alpha1.RateLimitsPolicy{DebatesPerMinute: &perMinute},
			Selector:   &aragorav1alpha1.PolicySelector{Workspaces: []string{fakeWorkspace}},
		},
	}
}
