# GCP Architecture

All infrastructure is defined in Terraform (`terraform/`) and deploys to a single GCP project.

## Infrastructure Diagram

```
+------------------------------- GCP Project -------------------------------+
|                                                                           |
|  +-------------------+         +-------------------+                      |
|  |   Cloud Run       |         |   Firestore       |                      |
|  |   (health-engine) |<------->|   (Native mode)   |                      |
|  |                   |         |                   |                      |
|  |  FastAPI app      |         |  Collections:     |                      |
|  |  Min: 1 instance  |         |  - policies       |                      |
|  |  Max: 3 instances |         |  - resources      |                      |
|  |  1 CPU / 512Mi    |         |  - test_results   |                      |
|  |  Port 8080        |         |  - health_history |                      |
|  +--------+----------+         +-------------------+                      |
|           |                                                               |
|           |  reads metrics                                                |
|           v                                                               |
|  +-------------------+         +-------------------+                      |
|  | Cloud Monitoring  |         | Artifact Registry |                      |
|  | (metrics API)     |         | (health-monitor)  |                      |
|  |                   |         |                   |                      |
|  | Cloud Run metrics |         | Docker images     |                      |
|  | Custom metrics    |         | health-engine:*   |                      |
|  +-------------------+         +-------------------+                      |
|                                                                           |
|  +-------------------+                                                    |
|  | Service Account   |                                                    |
|  | health-engine-sa  |                                                    |
|  |                   |                                                    |
|  | Roles:            |                                                    |
|  | - monitoring.viewer|                                                   |
|  | - datastore.user  |                                                    |
|  | - run.viewer      |                                                    |
|  | - run.invoker     |                                                    |
|  +-------------------+                                                    |
+---------------------------------------------------------------------------+
```

## GCP Services Used

### Cloud Run

The Health Engine runs as an always-on Cloud Run service.

| Setting | Value |
|---------|-------|
| Service name | `health-engine` (configurable) |
| Image source | Artifact Registry (`health-monitor/health-engine:latest`) |
| Port | 8080 |
| CPU | 1 |
| Memory | 512Mi |
| Min instances | 1 (always warm) |
| Max instances | 3 |
| Probes | Startup + Liveness at `/health` |

**Why min=1?** The engine must be always-on to maintain its APScheduler jobs and Firestore snapshot listeners. Cold starts would lose all scheduled monitoring state.

### Firestore (Native Mode)

Persistent storage for all domain data. Uses the default database.

| Collection | Purpose | Key Fields |
|------------|---------|------------|
| `policies` | Health check definitions | policy_id, tests[], resource_type |
| `resources` | Monitored GCP services | resource_id, policy_ids[], current_status |
| `test_results` | Individual test execution results | test_result_id, status, value, explanation |
| `health_history` | Time-series health state snapshots | health_state, previous_state, timestamp |

Firestore also provides **real-time listeners** (`on_snapshot`) used by the PolicyWatcher to detect changes without polling.

### Cloud Monitoring

Read-only access to GCP metrics. The engine queries metrics for the resources it monitors.

**Supported metric sources**:
- `run.googleapis.com/container/cpu/utilization` -- Cloud Run CPU
- `run.googleapis.com/container/memory/utilization` -- Cloud Run memory
- `run.googleapis.com/request_latencies` -- Request latency
- `run.googleapis.com/request_count` -- Request volume and error rates
- Firestore, Cloud Functions, and Cloud SQL metrics also supported

**Aggregation methods**: mean, max, min, sum, count, p50, p95, p99

### Artifact Registry

Docker repository for container images.

| Setting | Value |
|---------|-------|
| Repository | `health-monitor` |
| Format | Docker |
| Image naming | `{region}-docker.pkg.dev/{project}/health-monitor/health-engine:{tag}` |

### APIs Enabled

Terraform enables these project APIs automatically:

- `run.googleapis.com`
- `firestore.googleapis.com`
- `monitoring.googleapis.com`
- `cloudbuild.googleapis.com`
- `artifactregistry.googleapis.com`

## IAM & Service Account

A dedicated service account (`health-engine-sa`) runs the Cloud Run service with least-privilege access:

```
health-engine-sa
    |
    +-- roles/monitoring.viewer    Read Cloud Monitoring metrics
    +-- roles/datastore.user       Read/write Firestore documents
    +-- roles/run.viewer           Read Cloud Run service metadata
    +-- roles/run.invoker          Invoke its own Cloud Run service (self-monitoring)
```

**No write access** to Cloud Monitoring or Cloud Run -- the engine only observes, never modifies the services it monitors.

## Environment Variables

The Cloud Run service receives these environment variables (set in Terraform):

| Variable | Source | Purpose |
|----------|--------|---------|
| `HEALTH_PROJECT_ID` | `var.project_id` | GCP project to monitor |
| `HEALTH_SERVICE_NAME` | `var.service_name` | This service's name |
| `HEALTH_LOCATION` | `var.region` | GCP region |

Additional runtime configuration (set via env vars, not in Terraform):

| Variable | Default | Purpose |
|----------|---------|---------|
| `HEALTH_PORT` | 8080 | HTTP port |
| `HEALTH_DEBUG` | false | Debug mode |
| `HEALTH_DEFAULT_CHECK_INTERVAL_SECONDS` | 60 | Default check frequency |
| `HEALTH_MAX_CONCURRENT_CHECKS` | 10 | Max parallel test executions |
| `HEALTH_FIRESTORE_DATABASE` | (default) | Firestore database name |
| `HEALTH_CONSECUTIVE_FAILURES_FOR_UNHEALTHY` | 3 | Failures before unhealthy |
| `HEALTH_CONSECUTIVE_SUCCESSES_FOR_HEALTHY` | 2 | Successes before healthy |
| `HEALTH_HISTORY_RETENTION_DAYS` | 30 | How long to keep history |

## Container Build

The Dockerfile uses a Python 3.11 slim base image:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
CMD ["python", "-m", "uvicorn", "health_monitor.engine.app:app",
     "--host", "0.0.0.0", "--port", "8080"]
```

## Deployment Flow

```
Developer                      GCP
    |                           |
    +-- docker build & push --> Artifact Registry
    |                           |
    +-- terraform apply ------> Cloud Run (pulls image)
    |                           |    |
    |                           |    +--> Creates service account
    |                           |    +--> Creates Firestore DB
    |                           |    +--> Enables APIs
    |                           |    +--> Starts Cloud Run service
    |                           |
    +-- health policy create -> Firestore
    +-- health resource create> Firestore
    |                           |
    |                     PolicyWatcher detects changes
    |                     Scheduler starts monitoring
    |                           |
    +-- health status --------> Reads from Firestore
```

## Terraform Usage

```bash
cd terraform

# Set your project
export TF_VAR_project_id="my-gcp-project"

# Review the plan
terraform plan

# Apply infrastructure
terraform apply

# See outputs
terraform output
# --> service_url, service_account_email, artifact_registry_repository
```
