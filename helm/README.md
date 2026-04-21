# Open SWE Helm Charts

Kubernetes Helm charts for deploying Open SWE powered by Aegra.

**Cost Structure:**
- **Aegra runtime** — Free & open source
- **PostgreSQL** — Your managed database (AWS RDS, Google Cloud SQL, etc.)
- **Redis** — Your cache layer (AWS ElastiCache, etc.)
- **Kubernetes** — Your compute costs (EKS, GKE, AKS, etc.)

No LangSmith subscription required.

## Quick Start

### 1. Build and push your Docker image

```bash
docker build -t your-registry/open-swe:v1.0.0 .
docker push your-registry/open-swe:v1.0.0
```

### 2. Deploy to Kubernetes

```bash
# Development
helm install open-swe ./open-swe \
  --namespace open-swe \
  --create-namespace \
  -f open-swe/examples/values-dev.yaml

# Production
helm install open-swe ./open-swe \
  --namespace open-swe \
  --create-namespace \
  -f open-swe/examples/values-prod.yaml \
  --set postgres.password=your-postgres-password \
  --set redis.password=your-redis-password
```

### 3. Verify deployment

```bash
kubectl get pods -n open-swe
kubectl logs -f deployment/open-swe -n open-swe
```

## Charts

- **open-swe** - Main application server running Aegra

## Prerequisites

- **Kubernetes 1.20+**
- **PostgreSQL 14+** - Managed service (AWS RDS, Google Cloud SQL, etc.) or self-hosted
- **Redis 6.0+** - Managed service (AWS ElastiCache, etc.) or self-hosted
- **Image Registry** - Docker Hub, ECR, GCR, or private registry

## Environment Setup

### Create namespace and secrets

```bash
kubectl create namespace open-swe

# Create secret with sensitive values
kubectl create secret generic open-swe-secrets \
  --from-literal=github-app-private-key="$(cat ~/private-key.pem)" \
  --from-literal=token-encryption-key="$(openssl rand -base64 32)" \
  -n open-swe
```

### Set up external databases (AWS example)

```bash
# RDS PostgreSQL
aws rds create-db-instance \
  --db-instance-identifier open-swe-db \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --master-username openswe \
  --master-user-password "your-password" \
  --allocated-storage 20

# ElastiCache Redis
aws elasticache create-cache-cluster \
  --cache-cluster-id open-swe-cache \
  --cache-node-type cache.t3.micro \
  --engine redis \
  --num-cache-nodes 1
```

## Deployment Strategies

### Dev Environment (single instance)

```bash
helm install open-swe ./open-swe \
  -f open-swe/examples/values-dev.yaml \
  --set postgres.password=dev-password
```

**Features:**
- Single replica
- In-process job queue (no Redis needed)
- LoadBalancer service
- Minimal resources

### Production Environment (highly available)

```bash
helm install open-swe ./open-swe \
  -f open-swe/examples/values-prod.yaml \
  --set postgres.password=your-password \
  --set redis.password=your-password
```

**Features:**
- 2+ replicas with autoscaling (up to 10)
- Redis-backed distributed job queue
- Ingress with TLS
- Pod anti-affinity
- Resource limits and requests
- Health checks and probes

## Upgrading

```bash
helm upgrade open-swe ./open-swe \
  --namespace open-swe \
  -f open-swe/examples/values-prod.yaml
```

## Uninstalling

```bash
helm uninstall open-swe -n open-swe
kubectl delete namespace open-swe
```

## Configuration Reference

See `open-swe/values.yaml` for all available options.

### Key configurations

- **Image** - `image.repository` and `image.tag`
- **Database** - `postgres.host`, `postgres.port`, `postgres.password`
- **Redis** - `redis.host`, `redis.port`, `redis.brokerEnabled`
- **Ingress** - `ingress.hosts` and `ingress.tls`
- **Scaling** - `autoscaling.minReplicas`, `maxReplicas`
- **Resources** - `resources.requests` and `resources.limits`
- **Environment** - `env.*` for all API keys and config

## Health & Monitoring

### Health endpoints

- `GET /health` - Overall status
- `GET /ready` - Readiness for traffic
- `GET /live` - Process liveness
- `GET /info` - Server info

### Check pod health

```bash
kubectl get pods -n open-swe -o wide
kubectl describe pod <pod-name> -n open-swe
kubectl logs <pod-name> -n open-swe
```

### Port forward for debugging

```bash
kubectl port-forward svc/open-swe 2026:80 -n open-swe
curl http://localhost:2026/health
```

## Troubleshooting

### Common issues

**Pods not starting:**
```bash
kubectl describe pod <pod-name> -n open-swe
kubectl logs <pod-name> -n open-swe
```

**Database connection error:**
- Verify `DATABASE_URL` environment variable
- Check PostgreSQL is accessible from the cluster
- Verify network policies/security groups

**Redis connection error:**
- Check `REDIS_URL` environment variable
- Verify Redis is accessible from the cluster
- Check Redis password if required

**Liveness probe failing:**
```bash
kubectl port-forward svc/open-swe 2026:80 -n open-swe
curl http://localhost:2026/live
```

## Support

See `open-swe/README.md` for detailed documentation.

For issues with Aegra deployment, check the [Aegra documentation](https://docs.aegra.ai).
