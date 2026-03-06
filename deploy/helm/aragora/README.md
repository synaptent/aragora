# Aragora Helm Chart

Helm chart for deploying Aragora to Kubernetes.

## Quick Start

```bash
# Development deployment (single replica, default settings)
helm install aragora ./deploy/helm/aragora

# Production deployment (HA, autoscaling, secure defaults)
helm install aragora ./deploy/helm/aragora -f deploy/helm/aragora/values-production.yaml
```

## Values Files

| File | Purpose | Use Case |
|------|---------|----------|
| `values.yaml` | Development defaults | Local testing, dev clusters |
| `values-production.yaml` | Production defaults | Production deployments |
| `values-staging.yaml` | Staging configuration | Pre-production testing |
| `values-supabase.yaml` | Supabase backend | When using Supabase |

## Development vs Production

The default `values.yaml` is configured for **development** with:
- Single replica
- No autoscaling
- `image.tag: "latest"`
- No PodDisruptionBudget

For **production**, always use `values-production.yaml` which provides:
- 3+ replicas for high availability
- Horizontal Pod Autoscaler enabled
- Pinned image version
- PodDisruptionBudget for safe updates
- Pod anti-affinity for node distribution
- Topology spread across availability zones

## Required Configuration

Before deploying to production, configure:

1. **Image Tag**: Set a specific version (not "latest")
   ```bash
   --set image.tag=v2.8.0
   ```

2. **API Keys**: Set your provider API keys
   ```bash
   --set config.anthropicApiKey=sk-ant-xxx
   --set config.openaiApiKey=sk-xxx
   ```

3. **Ingress**: Configure your domain
   ```yaml
   ingress:
     hosts:
       - host: aragora.yourdomain.com
   ```

4. **TLS**: Configure certificates
   ```yaml
   ingress:
     tls:
       - secretName: aragora-tls
         hosts:
           - aragora.yourdomain.com
   ```

## Secrets Management

Never commit API keys to version control. Options:

1. **External Secrets Operator**: Sync from AWS Secrets Manager, Vault, etc.
2. **Sealed Secrets**: Encrypted secrets committed to git
3. **Helm set flags**: Pass at deploy time (not in CI logs)

Example with external secrets:
```yaml
# external-secret.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: aragora-api-keys
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets
    kind: ClusterSecretStore
  target:
    name: aragora-api-keys
  data:
    - secretKey: ANTHROPIC_API_KEY
      remoteRef:
        key: aragora/api-keys
        property: anthropic
```

## Monitoring

Enable Prometheus ServiceMonitor:
```yaml
metrics:
  enabled: true
  serviceMonitor:
    enabled: true
```

Grafana dashboards are available in `deploy/grafana/`.

## Troubleshooting

```bash
# Check pod status
kubectl get pods -l app.kubernetes.io/name=aragora

# View logs
kubectl logs -l app.kubernetes.io/name=aragora --tail=100

# Check events
kubectl get events --sort-by='.lastTimestamp'

# Verify health endpoints
kubectl port-forward svc/aragora 8080:8080
curl http://localhost:8080/healthz
curl http://localhost:8080/readyz
```
