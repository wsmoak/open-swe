# Open SWE K8s Deployment Checklist

Use this checklist before deploying Open SWE to Kubernetes.

## Pre-Deployment

- [ ] **Cluster ready**
  - [ ] Kubernetes 1.20+ running
  - [ ] kubectl configured and authenticated
  - [ ] Helm 3.0+ installed

- [ ] **External dependencies provisioned**
  - [ ] PostgreSQL 14+ database created (AWS RDS, Google Cloud SQL, etc.)
  - [ ] Redis 6.0+ instance created (AWS ElastiCache, etc.)
  - [ ] Test database connections

- [ ] **Docker image built and pushed**
  - [ ] `docker build -t your-registry/open-swe:v1.0.0 .`
  - [ ] `docker push your-registry/open-swe:v1.0.0`
  - [ ] Image pulls successfully: `docker pull your-registry/open-swe:v1.0.0`

- [ ] **API keys and tokens collected**
  - [ ] GitHub App ID and Installation ID
  - [ ] GitHub App private key
  - [ ] GitHub webhook secret
  - [ ] Anthropic API key
  - [ ] Slack bot token (if using Slack)
  - [ ] Linear API key (if using Linear)
  - [ ] Token encryption key: `openssl rand -base64 32`
  - [X] No LangSmith API key needed

## Kubernetes Setup

- [ ] **Namespace created**
  ```bash
  kubectl create namespace open-swe
  ```

- [ ] **Secrets configured**
  ```bash
  kubectl create secret generic open-swe-secrets \
    --from-literal=github-app-private-key="$(cat ~/private-key.pem)" \
    --from-literal=token-encryption-key="$(openssl rand -base64 32)" \
    -n open-swe
  ```

- [ ] **values.yaml prepared**
  - [ ] Copy `examples/values-prod.yaml` to your environment
  - [ ] Update `image.repository` to your registry
  - [ ] Update `image.tag` to your version
  - [ ] Update `postgres.host`, `postgres.port`, `postgres.database`
  - [ ] Update `redis.host`, `redis.port`
  - [ ] Update `ingress.hosts[0].host` to your domain
  - [ ] Update all `env.*` variables with actual values
  - [ ] Review resource limits and autoscaling settings

## Helm Deployment

- [ ] **Dry run test**
  ```bash
  helm install open-swe ./open-swe \
    -n open-swe \
    -f values-prod.yaml \
    --set postgres.password=*** \
    --set redis.password=*** \
    --dry-run --debug
  ```

- [ ] **Dry run output reviewed**
  - [ ] All secrets are properly formatted
  - [ ] Environment variables are correct
  - [ ] Database URL is complete
  - [ ] Redis URL is complete
  - [ ] Ingress hosts are correct

- [ ] **Install release**
  ```bash
  helm install open-swe ./open-swe \
    -n open-swe \
    -f values-prod.yaml \
    --set postgres.password=*** \
    --set redis.password=***
  ```

## Post-Deployment Verification

- [ ] **Check pod status**
  ```bash
  kubectl get pods -n open-swe
  # All pods should be Running
  ```

- [ ] **Check pod logs**
  ```bash
  kubectl logs -f deployment/open-swe -n open-swe
  # Should see: "Uvicorn running on..."
  ```

- [ ] **Wait for readiness**
  ```bash
  kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=open-swe -n open-swe --timeout=300s
  ```

- [ ] **Check service**
  ```bash
  kubectl get svc -n open-swe
  # open-swe service should exist
  ```

- [ ] **Test health endpoints**
  ```bash
  kubectl port-forward svc/open-swe 2026:80 -n open-swe &
  curl http://localhost:2026/health
  curl http://localhost:2026/ready
  curl http://localhost:2026/live
  kill %1
  ```

- [ ] **Check ingress**
  ```bash
  kubectl get ingress -n open-swe
  kubectl describe ingress open-swe -n open-swe
  # Should show endpoints mapped to service
  ```

- [ ] **Test ingress URL**
  ```bash
  # Once DNS is updated, test:
  curl -I https://open-swe.example.com/health
  ```

## Configuration Verification

- [ ] **Environment variables loaded**
  ```bash
  kubectl get configmap open-swe -n open-swe -o yaml
  # Review all env values
  ```

- [ ] **Secrets mounted**
  ```bash
  kubectl get secret open-swe -n open-swe -o yaml
  # Review database-url and redis-url (base64 encoded)
  ```

- [ ] **Database connection works**
  ```bash
  kubectl exec -it deployment/open-swe -n open-swe -- \
    psql $DATABASE_URL -c "SELECT version();"
  ```

- [ ] **Redis connection works**
  ```bash
  kubectl exec -it deployment/open-swe -n open-swe -- \
    redis-cli -u $REDIS_URL ping
  # Should return: PONG
  ```

## Webhook Configuration

- [ ] **GitHub App webhook URL updated**
  - [ ] URL: `https://open-swe.example.com/webhooks/github`
  - [ ] Test in GitHub App settings

- [ ] **Slack app webhook URL updated** (if applicable)
  - [ ] URL: `https://open-swe.example.com/webhooks/slack`
  - [ ] Test by mentioning bot in Slack

- [ ] **Linear webhook URL updated** (if applicable)
  - [ ] URL: `https://open-swe.example.com/webhooks/linear`
  - [ ] Test by commenting on Linear issue

## Monitoring Setup

- [ ] **Liveness/readiness probes working**
  ```bash
  kubectl get events -n open-swe
  # Should not see repeated probe failures
  ```

- [ ] **Autoscaling configured**
  ```bash
  kubectl get hpa -n open-swe
  kubectl describe hpa open-swe -n open-swe
  ```

- [ ] **Resource usage monitored**
  ```bash
  kubectl top pods -n open-swe
  kubectl top nodes
  ```

## Backup & Recovery

- [ ] **Database backups configured**
  - [ ] AWS RDS: Automated backups enabled
  - [ ] Retention period set (recommend 7+ days)

- [ ] **Redis persistence enabled**
  - [ ] AWS ElastiCache: Automatic failover enabled
  - [ ] Snapshots configured (recommend daily)

- [ ] **Helm release backed up**
  ```bash
  helm get values open-swe -n open-swe > backup-values.yaml
  ```

## Production Readiness

- [ ] **TLS certificate issued**
  - [ ] cert-manager installed (if using)
  - [ ] Certificate shows in ingress

- [ ] **Rate limiting enabled** (ingress annotations)
  - [ ] nginx.ingress.kubernetes.io/rate-limit configured

- [ ] **Network policies considered**
  - [ ] Database accessible only from app pods
  - [ ] Redis accessible only from app pods

- [ ] **Pod security policies reviewed**
  - [ ] runAsNonRoot: true
  - [ ] readOnlyRootFilesystem: true
  - [ ] allowPrivilegeEscalation: false

- [ ] **Resource quotas set** (recommended)
  ```bash
  kubectl create quota -n open-swe --hard=pods=50,cpu=20,memory=50Gi
  ```

## Rollback Plan

- [ ] **Previous version tagged and available**
  ```bash
  docker tag your-registry/open-swe:v1.0.0 your-registry/open-swe:v0.9.9
  docker push your-registry/open-swe:v0.9.9
  ```

- [ ] **Helm rollback procedure documented**
  ```bash
  helm rollback open-swe 1 -n open-swe
  ```

- [ ] **Database migration rollback plan exists**
  - [ ] Migrations are backward compatible or
  - [ ] Rollback script prepared
