# System Overview

## What It Does

Health Monitor provides **semantic health monitoring** for Google Cloud services. Instead of raw metric dashboards, it translates Cloud Monitoring data into actionable health states -- answering "is this service healthy?" rather than "what is the CPU at?"

## Architecture at a Glance

```
                        +---------------------+
                        |     CLI (Click)      |
                        |   health status ...  |
                        +----------+----------+
                                   |
                                   v
+------------------------------+   |   +------------------------------+
|       Cloud Monitoring       |   |   |         Firestore            |
|       (Metrics Source)       |   |   |  (Policies, Resources,       |
|                              |   |   |   Results, History)          |
+-------------+----------------+   |   +-------------+----------------+
              |                    |                   |
              v                    v                   v
        +---------------------------------------------+
        |           Health Engine (FastAPI)            |
        |                                             |
        |  +----------+  +-----------+  +-----------+ |
        |  | Scheduler|  | Executor  |  | Policy    | |
        |  | (APSched)|  | (Runner)  |  | Watcher   | |
        |  +----------+  +-----------+  +-----------+ |
        |                                             |
        |  +------------------------------------------+|
        |  | Health Tests (Plugin Registry)            ||
        |  |  - MetricThresholdTest                    ||
        |  |  - ErrorRateTest                          ||
        |  +------------------------------------------+|
        +---------------------------------------------+
                        |
                        v
                  Cloud Run (Hosting)
```

## Component Breakdown

| Component | Role | Technology |
|-----------|------|------------|
| **CLI** | User interface for managing resources, policies, and viewing health | Click + Rich |
| **Health Engine** | Always-on backend that executes health checks on a schedule | FastAPI + Uvicorn |
| **Scheduler** | Manages periodic execution of health checks per resource | APScheduler |
| **Executor** | Runs tests against Cloud Monitoring data, writes results | Custom orchestrator |
| **Policy Watcher** | Listens for Firestore changes and dynamically updates schedules | Firestore snapshots |
| **Health Tests** | Pluggable test implementations (metric threshold, error rate) | Plugin registry pattern |
| **Firestore** | Stores policies, resources, test results, and health history | Google Firestore |
| **Cloud Monitoring** | Source of truth for GCP service metrics | Google Cloud Monitoring API |

## Data Flow

```
1. User creates Policy (YAML) --> stored in Firestore
2. User creates Resource --> linked to Policy(s), stored in Firestore
3. PolicyWatcher detects new resource --> tells Scheduler to schedule checks
4. Scheduler fires at interval --> calls Executor
5. Executor loads Policy tests --> queries Cloud Monitoring for metrics
6. Each test evaluates metric against thresholds --> produces TestResult
7. Executor aggregates results --> computes HealthState (healthy/warning/unhealthy)
8. Results + state written to Firestore
9. User runs `health status overview` --> reads from Firestore, displays table
```

## Data Model

```
Policy (1) ----< TestConfig (many)
   |
   | referenced by policy_ids
   v
Resource (1) ----> ResourceStatus
   |                  - health_state
   |                  - consecutive_failures/successes
   |
   +----> TestSummary
   |        - passing / warning / failing / unknown counts
   |
   +----< TestResult (many, per execution)
   |        - status, value, thresholds
   |        - explanation (summary, details, recommendation)
   |
   +----< HealthHistory (many, time-series snapshots)
            - health_state transitions over time
```

## Project Structure

```
health/
  src/health_monitor/
    cli/                  # Click CLI commands
      commands/
        status.py         # health status overview | resource <id>
        resource.py       # health resource list | get | create | delete
        policy.py         # health policy list | get | create | validate
        test.py           # health test list | history | validate
    core/
      config.py           # Pydantic settings (env vars)
      models.py           # All domain models (Policy, Resource, TestResult, ...)
      enums.py            # HealthState, TestStatus enums
    engine/
      app.py              # FastAPI app + lifespan (startup/shutdown)
      executor.py         # Orchestrates test execution per resource
      scheduler.py        # APScheduler-based periodic job manager
      policy_watcher.py   # Real-time Firestore listener
    health_tests/
      base.py             # Abstract HealthTest class
      registry.py         # Plugin discovery + registration
      metric_threshold.py # MetricThresholdTest implementation
      error_rate.py       # ErrorRateTest implementation
    monitoring/
      client.py           # Cloud Monitoring API wrapper
    storage/
      firestore_client.py # Firestore connection manager
      repositories/       # CRUD for policies, resources, results
  terraform/              # Infrastructure-as-code
  examples/               # Sample YAML configs
  docs/                   # Dev docs (deployment, testing)
```
