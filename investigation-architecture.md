# Investigation Architecture

This document explains how Health Monitor defines, executes, and evaluates health checks.

## Core Concepts

A **health investigation** is the process of determining whether a GCP resource is healthy. It works through three layers:

```
+-------------------+     +-------------------+     +-------------------+
|     Policy        |     |     Test          |     |     Result        |
|                   |     |                   |     |                   |
| "What to check"   | --> | "How to check"    | --> | "What happened"   |
|                   |     |                   |     |                   |
| - resource_type   |     | - metric query    |     | - PASSING         |
| - list of tests   |     | - thresholds      |     | - WARNING         |
| - enabled flag    |     | - aggregation     |     | - FAILING         |
|                   |     | - eval window     |     | - ERROR           |
+-------------------+     +-------------------+     +-------------------+
```

## Policy Definition

A **Policy** defines which tests to run for a type of resource. Policies are written in YAML and stored in Firestore.

```yaml
policy_id: cloud-run-standard
name: Standard Cloud Run Health Policy
resource_type: cloud_run_service
enabled: true
tests:
  - test_id: cpu-check
    test_type: metric_threshold
    name: CPU Utilization
    schedule:
      interval_seconds: 60
      evaluation_window_seconds: 300
    config:
      metric_type: run.googleapis.com/container/cpu/utilization
      threshold_operator: greater_than
      warning_threshold: 0.7
      critical_threshold: 0.9

  - test_id: error-rate
    test_type: error_rate
    name: Request Error Rate
    config:
      request_count_metric: run.googleapis.com/request_count
      critical_threshold_percent: 5.0
      warning_threshold_percent: 1.0
```

A single resource can have **multiple policies** assigned via `policy_ids`. All tests from all assigned policies are evaluated.

### Standard Policy Templates

Standard policies are provided for all 7 supported resource types in `examples/policies/`:

| Policy | Resource Type | Tests |
|---|---|---|
| `cloud-sql-standard.yaml` | `cloud_sql` | CPU, memory, disk, connections, replication lag |
| `cloud-function-standard.yaml` | `cloud_function` | Execution latency P99, memory, active instances, error rate |
| `gcs-standard.yaml` | `gcs_bucket` | API request latency P95, error rate |
| `pubsub-standard.yaml` | `pubsub_subscription` | Oldest unacked age, undelivered count, push error rate |
| `gce-standard.yaml` | `gce_instance` | CPU utilization, uptime, disk utilization |
| `vertex-ai-endpoint-standard.yaml` | `vertex_ai_endpoint` | Prediction latency P95, error count, request volume |

## Test Plugin System

Tests are implemented as plugins using a registry pattern:

```
                    HealthTest (Abstract Base)
                    |
                    |-- execute(resource, config) -> TestResult
                    |-- validate_config(config)
                    |
          +---------+---------+
          |                   |
   MetricThresholdTest   ErrorRateTest
   - Queries a single    - Calculates error
     metric and compares   rate as % of total
     against thresholds    requests
   - Supports all 7      - Supports: Cloud
     resource types        Run, Cloud Functions,
                           GCS, Pub/Sub,
                           Vertex AI
```

### MetricThresholdTest

The most common test type. Fetches a single metric from Cloud Monitoring and compares it against warning and critical thresholds.

**Supported aggregations**: mean, max, min, sum, count, p50, p95, p99

**Supported resource types**: All 7 (cloud_run_service, cloud_function, cloud_sql, gcs_bucket, pubsub_subscription, gce_instance, vertex_ai_endpoint)

**Evaluation logic**:
```
metric_value = query_cloud_monitoring(metric_type, aggregation, eval_window)

if threshold_operator == "greater_than":
    if value > critical_threshold  --> FAILING
    if value > warning_threshold   --> WARNING
    else                           --> PASSING

if threshold_operator == "less_than":
    if value < critical_threshold  --> FAILING
    if value < warning_threshold   --> WARNING
    else                           --> PASSING
```

### ErrorRateTest

Calculates error rate as a percentage of total requests using request count metrics with error filters.

**Supported resource types**: cloud_run_service, cloud_function, gcs_bucket, pubsub_subscription, vertex_ai_endpoint

```
total_requests = query(request_count_metric, window)
error_requests = query(request_count_metric, window, error_filters)

error_rate = (error_requests / total_requests) * 100

if error_rate > critical_threshold  --> FAILING
if error_rate > warning_threshold   --> WARNING
else                                --> PASSING
```

## Test Execution Flow

```
Scheduler triggers check for resource-123
            |
            v
  +------- Executor.execute_for_resource("resource-123") -------+
  |                                                              |
  |  1. Load Resource from Firestore                             |
  |  2. For each policy_id on the resource:                      |
  |     a. Load Policy from Firestore                            |
  |     b. For each enabled test in policy.tests:                |
  |        i.  Look up test class from TestRegistry              |
  |        ii. Call test.execute(resource, config)               |
  |            - Query Cloud Monitoring API                      |
  |            - Evaluate value against thresholds               |
  |            - Generate explanation if unhealthy               |
  |        iii. Store TestResult in Firestore                    |
  |  3. Aggregate all results:                                   |
  |     - Count passing / warning / failing / unknown            |
  |     - Update TestSummary on resource                         |
  |  4. Determine HealthState:                                   |
  |     - ANY failing  --> UNHEALTHY                             |
  |     - ANY warning  --> WARNING                               |
  |     - ALL passing  --> HEALTHY                               |
  |     - Otherwise    --> UNKNOWN                               |
  |  5. Update ResourceStatus in Firestore                       |
  |  6. Write HealthHistory snapshot                             |
  |                                                              |
  +--------------------------------------------------------------+
```

## Health State Determination

The final health state for a resource follows a **worst-case escalation** model:

```
  All tests pass?
       |
       +-- Yes --> HEALTHY (green)
       |
       +-- No
            |
            Any tests failing?
                 |
                 +-- Yes --> UNHEALTHY (red)
                 |
                 +-- No
                      |
                      Any tests warning?
                           |
                           +-- Yes --> WARNING (yellow)
                           |
                           +-- No --> UNKNOWN (grey)
```

## Test Result Model

Each test execution produces a `TestResult` containing:

```
TestResult
  +-- test_result_id      Unique ID
  +-- resource_id         Which resource was checked
  +-- policy_id           Which policy defined this test
  +-- test_id             Which test within the policy
  +-- result
  |     +-- status         PASSING | WARNING | FAILING | ERROR | SKIPPED
  |     +-- value          The actual metric value (e.g., 0.73)
  |     +-- threshold_*    Warning and critical thresholds
  |     +-- unit           Metric unit
  +-- execution
  |     +-- started_at     When the test started
  |     +-- completed_at   When it finished
  |     +-- duration_ms    How long it took
  |     +-- eval_window    Time range of metrics evaluated
  +-- explanation          (if unhealthy)
        +-- summary        "CPU utilization at 93%, above critical threshold of 90%"
        +-- details        Extended context
        +-- severity       info | warning | critical
        +-- recommendation "Consider scaling up or optimizing CPU-intensive operations"
```

## Adding a New Test Type

The plugin registry makes it straightforward to add new test types:

```python
from health_monitor.health_tests.base import HealthTest
from health_monitor.health_tests.registry import register_test

@register_test("latency_percentile")
class LatencyPercentileTest(HealthTest):
    display_name = "Latency Percentile"
    description = "Check request latency at a given percentile"
    supported_resource_types = ["cloud_run_service", "gcs_bucket", "vertex_ai_endpoint"]

    async def execute(self, resource, config):
        # Query metric, evaluate, return TestResult
        ...

    def validate_config(self, config):
        # Validate required fields
        ...
```

The test is automatically discovered on engine startup via `TestRegistry.discover_plugins()`.
