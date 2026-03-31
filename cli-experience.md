# CLI Experience

The Health Monitor CLI (`health`) is the primary user interface. It uses Click for command parsing and Rich for formatted terminal output.

## Installation

```bash
pip install -e .
```

This registers the `health` command via the `pyproject.toml` entry point.

## Command Structure

```
health [--project/-p PROJECT] [--format/-f table|json] [--verbose/-v]
  |
  +-- status
  |     +-- overview          Show all resources with health summary
  |     +-- resource <id>     Detailed status for one resource
  |
  +-- resource
  |     +-- list              List monitored resources (--type, --state filters)
  |     +-- get <id>          Show resource details
  |     +-- create --file     Create resource from YAML/JSON
  |     +-- update <id>       Update resource
  |     +-- delete <id>       Delete resource
  |     +-- assign-policy     Link a policy to a resource
  |
  +-- policy
  |     +-- list              List policies (--type, --enabled filters)
  |     +-- get <id>          Show policy details with tests
  |     +-- create --file     Create policy from YAML
  |     +-- update <id>       Update policy
  |     +-- delete <id>       Delete policy
  |     +-- validate --file   Validate policy without creating
  |     +-- export <id>       Export policy as YAML
  |
  +-- test
        +-- run               Run tests on demand (--resource, --test-id)
        +-- list              Show available test types
        +-- history           Show test execution history (--resource, --test-id)
        +-- explain <id>      Detailed explanation of a test result (--resource)
        +-- validate --file   Validate test configuration
```

## Example Workflows

### 1. Check the health of everything

```
$ health status overview

                    Health Monitor - Status Overview

  Summary: 5 Healthy | 1 Warning | 0 Unhealthy | 1 Unknown

  ┌──────────────────────┬─────────────────────┬───────────┬─────────────────────┬───────┐
  │ Resource ID          │ Type                │ Status    │ Last Check          │ Tests │
  ├──────────────────────┼─────────────────────┼───────────┼─────────────────────┼───────┤
  │ api-gateway          │ cloud_run_service   │ healthy   │ 2025-01-15 14:32:01 │ 4/4   │
  │ payment-service      │ cloud_run_service   │ warning   │ 2025-01-15 14:32:05 │ 2/4   │
  │ main-database        │ cloud_sql           │ healthy   │ 2025-01-15 14:31:58 │ 5/5   │
  │ event-queue          │ pubsub_subscription │ healthy   │ 2025-01-15 14:32:03 │ 3/3   │
  │ data-bucket          │ gcs_bucket          │ healthy   │ 2025-01-15 14:31:55 │ 2/2   │
  │ web-server           │ gce_instance        │ healthy   │ 2025-01-15 14:32:08 │ 3/3   │
  │ ml-endpoint          │ vertex_ai_endpoint  │ unknown   │ --                  │ 0/0   │
  └──────────────────────┴─────────────────────┴───────────┴─────────────────────┴───────┘
```

Status values are colorized: green for healthy, yellow for warning, red for unhealthy, dim for unknown.

### 2. Investigate a warning

```
$ health status resource payment-service

  Resource: payment-service
  Type:     cloud_run_service
  Status:   WARNING
  Last Check: 2025-01-15 14:32:05 PST

  Test Results:
  ┌────────────────┬──────────────────┬─────────┬────────┬──────────┬───────────┐
  │ Test ID        │ Name             │ Status  │ Value  │ Warning  │ Critical  │
  ├────────────────┼──────────────────┼─────────┼────────┼──────────┼───────────┤
  │ cpu-check      │ CPU Utilization  │ PASSING │ 0.45   │ 0.70     │ 0.90      │
  │ memory-check   │ Memory Usage     │ PASSING │ 0.62   │ 0.80     │ 0.95      │
  │ latency-p99    │ Latency (P99)    │ WARNING │ 1.23s  │ 1.00s    │ 5.00s     │
  │ error-rate     │ Error Rate       │ WARNING │ 1.8%   │ 1.0%     │ 5.0%      │
  └────────────────┴──────────────────┴─────────┴────────┴──────────┴───────────┘

  Explanation (latency-p99):
    P99 latency at 1.23s, above warning threshold of 1.0s
    Recommendation: Check for slow database queries or upstream dependencies
```

### 3. Create a new policy

```
$ cat my-policy.yaml
policy_id: strict-cloud-run
name: Strict Cloud Run Monitoring
resource_type: cloud_run_service
tests:
  - test_id: cpu-check
    test_type: metric_threshold
    name: CPU Utilization
    config:
      metric_type: run.googleapis.com/container/cpu/utilization
      threshold_operator: greater_than
      warning_threshold: 0.5
      critical_threshold: 0.8
  - test_id: error-rate
    test_type: error_rate
    name: Error Rate
    config:
      request_count_metric: run.googleapis.com/request_count
      critical_threshold_percent: 2.0
      warning_threshold_percent: 0.5

$ health policy create --file my-policy.yaml
Policy 'strict-cloud-run' created successfully.

$ health policy list
  ┌─────────────────────┬──────────────────────────────┬──────────────────┬───────┬─────────┐
  │ Policy ID           │ Name                         │ Resource Type    │ Tests │ Enabled │
  ├─────────────────────┼──────────────────────────────┼──────────────────┼───────┼─────────┤
  │ self-monitoring      │ Self Monitoring Policy       │ cloud_run_service│ 4     │ Yes     │
  │ strict-cloud-run     │ Strict Cloud Run Monitoring  │ cloud_run_service│ 2     │ Yes     │
  └─────────────────────┴──────────────────────────────┴──────────────────┴───────┴─────────┘
```

### 4. Register a resource

```
$ cat my-resource.yaml
resource_id: payment-service
name: Payment Service
resource_type: cloud_run_service
gcp_resource_name: projects/my-project/locations/us-central1/services/payment-service
project_id: my-project
location: us-central1
policy_ids:
  - strict-cloud-run

$ health resource create --file my-resource.yaml
Resource 'payment-service' created successfully.
Assigned policies: strict-cloud-run
```

Once created, the PolicyWatcher automatically detects the new resource and the Scheduler begins monitoring it within seconds.

### 5. View test execution history

```
$ health test history --resource payment-service --limit 5

  Test History: payment-service
  ┌─────────────────────┬────────────────┬─────────┬────────┬──────────┐
  │ Timestamp           │ Test ID        │ Status  │ Value  │ Duration │
  ├─────────────────────┼────────────────┼─────────┼────────┼──────────┤
  │ 2025-01-15 14:32:05 │ cpu-check      │ PASSING │ 0.45   │ 230ms    │
  │ 2025-01-15 14:32:05 │ error-rate     │ WARNING │ 1.8%   │ 310ms    │
  │ 2025-01-15 14:31:05 │ cpu-check      │ PASSING │ 0.42   │ 215ms    │
  │ 2025-01-15 14:31:05 │ error-rate     │ PASSING │ 0.7%   │ 298ms    │
  │ 2025-01-15 14:30:05 │ cpu-check      │ PASSING │ 0.38   │ 220ms    │
  └─────────────────────┴────────────────┴─────────┴────────┴──────────┘
```

### 6. Validate before creating

```
$ health policy validate --file my-policy.yaml
Policy validation passed.
  - 2 tests configured
  - Resource type: cloud_run_service
  - All metric types valid

$ health test validate --file test-config.yaml
Test validation passed.
  - Type: metric_threshold
  - Metric: run.googleapis.com/container/cpu/utilization
  - Thresholds: warning=0.5, critical=0.8
```

### 7. Export and share a policy

```
$ health policy export self-monitoring --output exported-policy.yaml
Policy 'self-monitoring' exported to exported-policy.yaml
```

### 8. JSON output for scripting

```
$ health status overview --format json
{
  "summary": {
    "healthy": 3,
    "warning": 1,
    "unhealthy": 0,
    "unknown": 1
  },
  "resources": [
    {
      "resource_id": "api-gateway",
      "resource_type": "cloud_run_service",
      "health_state": "healthy",
      "last_check_time": "2025-01-15T14:32:01Z",
      "test_summary": {
        "total_tests": 4,
        "passing_tests": 4,
        "warning_tests": 0,
        "failing_tests": 0
      }
    }
  ]
}
```

### 9. Run tests on demand

```
$ health test run --resource sample-health-service

  Running tests for sample-health-service...

  Test Results for sample-health-service
  ╭────────────────────┬──────────────────┬─────────┬────────┬──────────┬───────────┬──────────╮
  │ Test ID            │ Type             │ Status  │ Value  │ Warning  │ Critical  │ Duration │
  ├────────────────────┼──────────────────┼─────────┼────────┼──────────┼───────────┼──────────┤
  │ cpu-utilization    │ metric_threshold │ PASSING │ 0.12   │ 0.70     │ 0.90      │ 245ms    │
  │ memory-utilization │ metric_threshold │ PASSING │ 0.45   │ 0.70     │ 0.90      │ 230ms    │
  │ request-latency    │ metric_threshold │ PASSING │ 0.08s  │ 1.00s    │ 5.00s     │ 215ms    │
  │ error-rate         │ error_rate       │ PASSING │ 0.0%   │ 1.0%     │ 5.0%      │ 310ms    │
  ╰────────────────────┴──────────────────┴─────────┴────────┴──────────┴───────────┴──────────╯

  4/4 tests passing

$ health test run --resource sample-health-function --test-id memory-usage

  Running tests for sample-health-function...

  Test Results for sample-health-function
  ╭──────────────┬──────────────────┬─────────┬────────┬──────────┬───────────┬──────────╮
  │ Test ID      │ Type             │ Status  │ Value  │ Warning  │ Critical  │ Duration │
  ├──────────────┼──────────────────┼─────────┼────────┼──────────┼───────────┼──────────┤
  │ memory-usage │ metric_threshold │ WARNING │ 180MB  │ 150MB    │ 230MB     │ 220ms    │
  ╰──────────────┴──────────────────┴─────────┴────────┴──────────┴───────────┴──────────╯

  0/1 tests passing
```

Run all tests or a specific test for any monitored resource without waiting for the scheduler.

### 10. Explain a test result

```
$ health test explain memory-utilization --resource health-engine-service

  ╭── Test Result ──────────────────────────────────────╮
  │ Result ID: metric-threshold-abc123                  │
  │ Test: memory-utilization (metric_threshold)         │
  │ Resource: health-engine-service                     │
  │ Status: WARNING                                     │
  │ Value: 0.75                                         │
  │ Warning Threshold: 0.70                             │
  │ Critical Threshold: 0.90                            │
  │ Unit: ratio                                         │
  ╰─────────────────────────────────────────────────────╯

  ╭── Execution ────────────────────────────────────────╮
  │ Started: 2025-01-15 14:32:05 PST                    │
  │ Completed: 2025-01-15 14:32:05 PST                  │
  │ Duration: 230ms                                     │
  │ Window Start: 2025-01-15 14:27:05 PST               │
  │ Window End: 2025-01-15 14:32:05 PST                 │
  ╰─────────────────────────────────────────────────────╯

  ╭── Explanation ──────────────────────────────────────╮
  │ Summary: Memory utilization at 75%, above warning   │
  │   threshold of 70%                                  │
  │                                                     │
  │ Severity: warning                                   │
  │                                                     │
  │ Recommendation:                                     │
  │   Consider increasing memory allocation or          │
  │   investigating memory leaks                        │
  ╰─────────────────────────────────────────────────────╯
```

Shows the full result including metric value, thresholds, execution timing, and an explanation with recommendations if the test is not passing.

## Output Formatting

| Mode | Flag | Use Case |
|------|------|----------|
| Table (default) | `--format table` | Human-readable with colors and borders |
| JSON | `--format json` | Scripting, piping to `jq`, automation |
| Verbose | `--verbose` | Debugging -- shows stack traces and extra context |

## Common Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--project` | `-p` | Override GCP project (defaults to `GOOGLE_CLOUD_PROJECT` env var) |
| `--format` | `-f` | Output format: `table` or `json` |
| `--verbose` | `-v` | Enable verbose/debug output |
| `--yes` | `-y` | Skip confirmation prompts (for delete operations) |
| `--file` | | Path to YAML/JSON config file (for create/update) |
