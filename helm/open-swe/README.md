# Open SWE Helm Chart

A Kubernetes Helm chart for deploying Open SWE (powered by Aegra) to production.

**Note:** This deployment is **completely free** — Aegra eliminates the LangSmith dependency, so you only pay for compute (Kubernetes), database (PostgreSQL), and cache (Redis).

## Prerequisites

- Kubernetes 1.20+
- Helm 3.0+
- PostgreSQL 14+ (managed service recommended)
- Redis 6.0+ (managed service recommended, or deployed separately)

## Installation

### 1. Add and update Helm repository

```bash
helm repo add open-swe https://your-registry.example.com/helm
helm repo update
```

### 2. Create namespace

```bash
kubectl create namespace open-swe
```

### 3. Create secrets for sensitive values

```bash
# Generate a token encryption key
TOKEN_ENCRYPTION_KEY=$(openssl rand -base64 32)

# Create secret with API keys and tokens
kubectl create secret generic open-swe-secrets \
  --from-literal=github-app-private-key="$(cat /path/to/private-key.pem)" \
  --from-literal=token-encryption-key="$TOKEN_ENCRYPTION_KEY" \
  -n open-swe
```

### 4. Create values file

Create `values-prod.yaml`:

```yaml
replicaCount: 2

image:
  repository: your-registry/open-swe
  tag: v1.0.0

ingress:
  enabled: true
  hosts:
    - host: open-swe.example.com
      paths:
        - path: /

# PostgreSQL connection
postgres:
  host: your-rds-instance.rds.amazonaws.com
  port: 5432
  database: openswe
  username: openswe
  password: "" # Set via --set or external secret

# Redis connection
redis:
  host: your-elasticache.cache.amazonaws.com
  port: 6379
  brokerEnabled: "true"
  password: "" # Set via --set or external secret

# Scaling
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5

# Resources
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: 2
    memory: 2Gi

# Environment variables
env:
  LANGSMITH_API_KEY_PROD: "your-api-key"
  ANTHROPIC_API_KEY: "your-api-key"
  GITHUB_APP_ID: "your-app-id"
  GITHUB_APP_INSTALLATION_ID: "your-installation-id"
  GITHUB_WEBHOOK_SECRET: "your-webhook-secret"
  # ... other env vars
```

### 5. Deploy

```bash
helm install open-swe ./open-swe \
  --namespace open-swe \
  --values values-prod.yaml \
  --set postgres.password=your-postgres-password \
  --set redis.password=your-redis-password
```

Or with separate secret:

```bash
helm install open-swe ./open-swe \
  --namespace open-swe \
  --values values-prod.yaml \
  --set postgres.existingSecret=postgres-secret \
  --set postgres.existingSecretPasswordKey=password \
  --set redis.existingSecret=redis-secret \
  --set redis.existingSecretPasswordKey=password
```

## Upgrading

```bash
helm upgrade open-swe ./open-swe \
  --namespace open-swe \
  --values values-prod.yaml
```

## Uninstalling

```bash
helm uninstall open-swe -n open-swe
```

## Configuration

See `values.yaml` for all available options. Key configurations:

### Database

Two ways to configure PostgreSQL connection:

**Option 1: Connection string (recommended)**
```yaml
postgres:
  # DATABASE_URL will be built as:
  # postgresql://username:password@host:port/database
  host: your-host
  port: 5432
  database: openswe
  username: openswe
  password: your-password
```

**Option 2: External secret**
```yaml
postgres:
  existingSecret: my-postgres-secret
  existingSecretPasswordKey: password
```

### Redis

Optional for single-instance deployments (runs async jobs in-process). Required for multi-instance deployments.

```yaml
redis:
  enabled: true
  host: your-redis-host
  port: 6379
  brokerEnabled: "true"
  password: your-password
```

### Ingress

```yaml
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: open-swe.example.com
      paths:
        - path: /
  tls:
    - secretName: open-swe-tls
      hosts:
        - open-swe.example.com
```

### Autoscaling

```yaml
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 80
  targetMemoryUtilizationPercentage: 80
```

## Health Checks

The chart includes liveness and readiness probes that use Aegra's health check endpoints:

- `/ready` - Readiness probe (ready to accept traffic)
- `/live` - Liveness probe (process is alive)
- `/health` - Overall health status

## Environment Variables

All environment variables from `values.yaml` are available as ConfigMap. Sensitive values (API keys, tokens, secrets) should use `values.secrets` or be passed separately.

## Troubleshooting

### Pod won't start

Check logs:
```bash
kubectl logs -f deployment/open-swe -n open-swe
```

### Database connection errors

Verify DATABASE_URL:
```bash
kubectl get secret open-swe -n open-swe -o jsonpath='{.data.database-url}' | base64 -d
```

### Liveness probe failures

Check /live endpoint:
```bash
kubectl port-forward svc/open-swe 2026:80 -n open-swe
curl http://localhost:2026/live
```

## License

Same as Open SWE project
