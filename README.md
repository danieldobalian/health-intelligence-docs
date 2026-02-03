# Health Monitor - Team Overview

Semantic health monitoring for Google Cloud Run services. This system continuously evaluates configurable health policies against live Cloud Monitoring metrics and reports semantic health states: **healthy**, **warning**, **unhealthy**, or **unknown**.

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

# Create a policy from YAML
health policy create --file examples/sample-policy.yaml

# Register a resource to monitor
health resource create --file examples/sample-resource.yaml
```

## Key Concepts

- **Resource**: A GCP service being monitored (e.g., a Cloud Run service)
- **Policy**: A named collection of health tests that apply to a resource type
- **Test**: A single check (e.g., "CPU utilization < 90%") with thresholds and schedule
- **Health State**: The semantic result of evaluating all tests for a resource
