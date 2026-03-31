# Health Monitor - Team Overview

Semantic health monitoring for Google Cloud Platform resources. This system continuously evaluates configurable health policies against live Cloud Monitoring metrics and reports semantic health states: **healthy**, **warning**, **unhealthy**, or **unknown**.

## Supported Resource Types

| Resource | Monitor At | Golden Signal |
|---|---|---|
| Cloud Run | Service | 5xx rate + P95 latency |
| Cloud Functions | Function | Execution time + error rate |
| Cloud SQL | Instance | CPU, memory, disk, `database/up` |
| Cloud Storage | Bucket | 5xx error rate + API latency |
| Pub/Sub | Subscription | `oldest_unacked_message_age` |
| Compute Engine | Instance / MIG | CPU utilization + uptime |
| Vertex AI | Endpoint | Prediction latency + error count |

### Key Capabilities

- **On-demand test execution**: Run health tests immediately via `health test run --resource <id>`
- **MCP server**: 8 tools for LLM agents (Claude Code) -- health overview, incident correlation, test explanations
- **Traffic simulation**: Automated traffic generation to populate Cloud Monitoring metrics
- **GCP incident correlation**: Cross-reference GCP Service Health incidents with monitored resources

## Documentation

| Document | Description |
|----------|-------------|
| [System Overview](./system-overview.md) | High-level architecture, components, and data flow |
| [Investigation Architecture](./investigation-architecture.md) | How health checks are defined, executed, and evaluated |
| [Multi-Agent Architecture](./multi-agent-architecture.md) | How the Scheduler, Executor, and PolicyWatcher coordinate |
| [GCP Architecture](./gcp-architecture.md) | Cloud infrastructure, Terraform resources, and IAM |
| [CLI Experience](./cli-experience.md) | User-facing commands with example workflows |

## Quick Start

```bash
# Install the CLI
pip install -e .

# Check health of all resources
health status overview

# Get detailed status for a specific resource
health status resource my-service

# Run tests on demand
health test run --resource my-service

# Explain a test result
health test explain cpu-utilization --resource my-service

# Create a policy from a template
health policy create --file examples/policies/gcs-standard.yaml

# Register a resource to monitor
health resource create --file examples/sample-resource.yaml
```

## Key Concepts

- **Resource**: A GCP service being monitored (e.g., a Cloud Run service, GCS bucket, Pub/Sub subscription)
- **Policy**: A named collection of health tests that apply to a resource type
- **Test**: A single check (e.g., "CPU utilization < 90%") with thresholds and schedule
- **Health State**: The semantic result of evaluating all tests for a resource
