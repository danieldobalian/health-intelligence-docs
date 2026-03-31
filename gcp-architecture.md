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
|  | Metric sources:   |         | Docker images     |                      |
|  |  - Cloud Run      |         | health-engine:*   |                      |
|  |  - Cloud SQL      |         +-------------------+                      |
|  |  - Cloud Storage  |                                                    |
|  |  - Pub/Sub        |                                                    |
|  |  - Compute Engine |                                                    |
|  |  - Vertex AI      |                                                    |
|  |  - Cloud Functions|                                                    |
|  +-------------------+                                                    |
|                                                                           |
|  +-------------------+         +------------------------------------+     |
|  | Service Account   |         | Test Resources (terraform/         |     |
|  | health-engine-sa  |         |   test-resources/)                 |     |
|  |                   |         |                                    |     |
|  | Roles:            |         | - GCS bucket (free tier)           |     |
|  | - monitoring.viewer|         | - Pub/Sub topic + subscription    |     |
|  | - datastore.user  |         | - GCE e2-micro instance (free)    |     |
|  | - run.viewer      |         +------------------------------------+     |
|  | - run.invoker     |                                                    |
|  | - storage.objViewer|         +------------------------------------+    |
|  | - compute.viewer  |         | MCP Server (Cloud Run)              |    |
|  | - pubsub.viewer   |         | health-mcp-server                   |    |
|  +-------------------+         |                                      |    |
|                                | - FastMCP (8 LLM agent tools)       |    |
|                                | - Reads Firestore + Service Health  |    |
|                                | - STDIO + streamable-HTTP transport |    |
|                                +------------------------------------+     |
|                                                                           |
|                                +------------------------------------+     |
|                                | Traffic Simulator                   |    |
|                                | (Cloud Run Job + Cloud Scheduler)   |    |
|                                |                                      |    |
|                                | - Runs every 5 minutes              |    |
|                                | - Generates traffic to test resources|    |
|                                | - GCS, Pub/Sub, GCE, Cloud Run,    |    |
|                                |   Cloud Functions                    |    |
|                                +------------------------------------+     |
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

### Cloud Run -- MCP Server

A separate Cloud Run service hosts the MCP server for LLM agent integration.

| Setting | Value |
|---------|-------|
| Service name | `health-mcp-server` |
| Image source | Artifact Registry (`health-monitor/health-mcp:latest`) |
| Port | 8080 |
| Transport | `streamable-http` (deployed) / `stdio` (local) |
| Dockerfile | `deploy/mcp-server/Dockerfile` |
| Deploy script | `scripts/deploy_mcp.sh` |

The MCP server reads from Firestore (resource status, test results) and the GCP Service Health API (incident data). It exposes 8 tools that LLM agents can call to query health state, test history, and correlate GCP incidents with monitored resources.

**Local access via proxy:**
```bash
gcloud run services proxy health-mcp-server --region=us-central1 --port=3000
```

### Cloud Run Job -- Traffic Simulator

A Cloud Run Job generates periodic traffic to test resources so health tests have real metrics to evaluate.

| Setting | Value |
|---------|-------|
| Job name | `traffic-simulator` |
| Scheduler | Cloud Scheduler (every 5 minutes) |
| Terraform | `terraform/traffic-simulator/` |
| Script | `scripts/simulate_traffic.py` |

Targets: GCS (PUT/GET/DELETE), Pub/Sub (publish + pull), GCE (status check), Cloud Run (HTTP), Cloud Functions (HTTP).

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

**Supported metric sources by resource type**:

| Resource Type | Metric Prefix | Example Metrics |
|---|---|---|
| Cloud Run | `run.googleapis.com/` | `container/cpu/utilization`, `request_latencies`, `request_count` |
| Cloud Functions | `cloudfunctions.googleapis.com/` | `function/execution_times`, `function/user_memory_bytes` |
| Cloud SQL | `cloudsql.googleapis.com/` | `database/cpu/utilization`, `database/up`, `database/disk/utilization` |
| Cloud Storage | `storage.googleapis.com/` | `api/request_latencies`, `api/request_count` |
| Pub/Sub | `pubsub.googleapis.com/` | `subscription/oldest_unacked_message_age`, `subscription/num_undelivered_messages` |
| Compute Engine | `compute.googleapis.com/` | `instance/cpu/utilization`, `instance/uptime` |
| Compute Engine (Ops Agent) | `agent.googleapis.com/` | `disk/percent_used` |
| Vertex AI | `aiplatform.googleapis.com/` | `prediction/latencies`, `prediction/error_count` |

**Aggregation methods**: mean, max, min, sum, count, p05, p50, p95, p99

### Artifact Registry

Docker repository for container images.

| Setting | Value |
|---------|-------|
| Repository | `health-monitor` |
| Format | Docker |
| Image naming | `{region}-docker.pkg.dev/{project}/health-monitor/health-engine:{tag}` |
| MCP image | `{region}-docker.pkg.dev/{project}/health-monitor/health-mcp:{tag}` |

### APIs Enabled

Terraform enables these project APIs automatically:

**Core (terraform/main.tf)**:
- `run.googleapis.com`
- `firestore.googleapis.com`
- `monitoring.googleapis.com`
- `cloudbuild.googleapis.com`
- `artifactregistry.googleapis.com`

**Test resources (terraform/test-resources/main.tf)**:
- `storage.googleapis.com`
- `pubsub.googleapis.com`
- `compute.googleapis.com`

## IAM & Service Account

A dedicated service account (`health-engine-sa`) runs the Cloud Run service with least-privilege access:

```
health-engine-sa
    |
    +-- roles/monitoring.viewer       Read Cloud Monitoring metrics (all resource types)
    +-- roles/datastore.user          Read/write Firestore documents
    +-- roles/run.viewer              Read Cloud Run service metadata
    +-- roles/run.invoker             Invoke its own Cloud Run service (self-monitoring)
    +-- roles/storage.objectViewer    Read GCS bucket metadata and metrics
    +-- roles/compute.viewer          Read GCE instance metadata and metrics
    +-- roles/pubsub.viewer           Read Pub/Sub subscription metadata and metrics
```

**No write access** to Cloud Monitoring or monitored services -- the engine only observes, never modifies the services it monitors.

## Test Resources

The `terraform/test-resources/` module deploys lightweight GCP resources for testing health monitoring policies. All resources run within the GCP free tier ($0/mo):

| Resource | Name | Cost |
|---|---|---|
| GCS Bucket | `{project-id}-health-test` | Free (standard class, empty) |
| Pub/Sub Topic | `health-test-topic` | Free (< 10 GiB/mo) |
| Pub/Sub Subscription | `health-test-sub` | Free |
| GCE Instance | `health-test-instance` | Free (e2-micro in us-central1) |

**Note**: Vertex AI Endpoints are not deployed as test resources due to cost (~$60+/mo minimum). Vertex AI monitoring is supported via code and policy templates only.

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
    +-- terraform apply ------> Test Resources (GCS, Pub/Sub, GCE)
    |   (test-resources/)       |
    |                           |
    +-- deploy_mcp.sh -------> MCP Server (Cloud Run)
    |                           |
    +-- terraform apply ------> Traffic Simulator (Cloud Run Job + Scheduler)
    |   (traffic-simulator/)    |
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
# Deploy health engine
cd terraform
export TF_VAR_project_id="my-gcp-project"
terraform plan
terraform apply
terraform output
# --> service_url, service_account_email, artifact_registry_repository

# Deploy test resources (free tier)
cd terraform/test-resources
terraform apply
terraform output
# --> gcs_bucket_name, pubsub_subscription_name, gce_instance_name
```
