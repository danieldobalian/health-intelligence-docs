# Multi-Agent Architecture

The Health Engine uses three coordinating agents (components) that work together to continuously monitor resources. Each has a distinct responsibility, and they communicate through well-defined interfaces.

## The Three Agents

```
+------------------------------------------------------------------+
|                      Health Engine (FastAPI)                      |
|                                                                  |
|  +-----------------+    +----------------+    +----------------+ |
|  |  PolicyWatcher  |    |   Scheduler    |    |   Executor     | |
|  |                 |    |                |    |                | |
|  | "What changed?" |    | "When to run?" |    | "Run the test" | |
|  |                 |--->|                |--->|                | |
|  | Listens to      |    | Manages timed  |    | Queries Cloud  | |
|  | Firestore for   |    | jobs for each  |    | Monitoring,    | |
|  | policy/resource  |    | resource       |    | evaluates      | |
|  | changes         |    |                |    | results, writes| |
|  |                 |    |                |    | to Firestore   | |
|  +-----------------+    +----------------+    +----------------+ |
|         |                      |                      |          |
|         v                      v                      v          |
|     Firestore             APScheduler          Cloud Monitoring  |
|   (on_snapshot)          (AsyncIO jobs)          (API queries)   |
+------------------------------------------------------------------+
```

## Agent Details

### 1. PolicyWatcher -- The Listener

**Role**: Detects changes to policies and resources in real-time and keeps the scheduler in sync.

**How it works**:
- Uses Firestore `on_snapshot()` to set up real-time listeners on the `policies` and `resources` collections
- When a document is added, modified, or removed, it fires a callback
- On resource ADDED/MODIFIED: tells the Scheduler to schedule (or reschedule) checks
- On resource REMOVED: tells the Scheduler to unschedule checks
- On policy MODIFIED: reschedules all resources using that policy (to pick up new test configs or intervals)

```
Firestore (resources collection)
    |
    | on_snapshot callback
    v
PolicyWatcher
    |
    +-- ADDED:    scheduler.schedule_resource(resource_id, interval)
    +-- MODIFIED: scheduler.unschedule(id) + scheduler.schedule(id, new_interval)
    +-- REMOVED:  scheduler.unschedule_resource(resource_id)
```

**Startup behavior**: On start, the PolicyWatcher loads all existing resources and schedules them, establishing the initial set of monitoring jobs.

### 2. Scheduler -- The Timer

**Role**: Manages when health checks fire. Ensures each resource is checked at its configured interval without overlapping executions.

**How it works**:
- Built on `APScheduler.AsyncIOScheduler`
- Creates interval-based jobs: "run check for resource X every N seconds"
- Prevents concurrent checks for the same resource (job coalescing)
- Supports immediate trigger for on-demand checks

```
Scheduler
    |
    +-- schedule_resource(resource_id, interval_seconds)
    |     --> Creates APScheduler interval job
    |
    +-- unschedule_resource(resource_id)
    |     --> Removes the job
    |
    +-- trigger_immediate(resource_id)
    |     --> Fires the job now (bypasses interval)
    |
    +-- get_scheduled_resources()
          --> Lists all active resource jobs
```

**Default interval**: 60 seconds (configurable per test via `schedule.interval_seconds`).

### 3. Executor -- The Worker

**Role**: Actually runs health tests and records results. This is where metric queries happen.

**How it works**:
- Receives a resource_id from the Scheduler
- Loads the resource and its linked policies from Firestore
- For each test in each policy, instantiates the test plugin and calls `execute()`
- Each test queries the Cloud Monitoring API, evaluates the result, and returns a `TestResult`
- Executor aggregates all results into a health state and writes everything back to Firestore

```
Executor.execute_for_resource(resource_id)
    |
    +-- Load Resource from Firestore
    +-- For each policy_id:
    |     +-- Load Policy
    |     +-- For each test:
    |           +-- TestRegistry.get(test_type)
    |           +-- test.execute(resource, config)
    |           |     +-- MonitoringClient.query_metric(...)
    |           |     +-- Evaluate against thresholds
    |           |     +-- Return TestResult
    |           +-- Store TestResult in Firestore
    +-- Aggregate: count passing/warning/failing
    +-- Compute HealthState
    +-- Update Resource status in Firestore
    +-- Write HealthHistory snapshot
```

## Agent Interaction Sequence

Here is the full lifecycle of a new resource being added and monitored:

```
 User (CLI)          Firestore         PolicyWatcher       Scheduler          Executor         Cloud Monitoring
    |                    |                   |                  |                  |                   |
    |-- create resource->|                   |                  |                  |                   |
    |                    |-- on_snapshot ---->|                  |                  |                   |
    |                    |                   |-- schedule ------>|                  |                   |
    |                    |                   |                  |                  |                   |
    |                    |                   |            [60s interval]            |                   |
    |                    |                   |                  |                  |                   |
    |                    |                   |                  |-- execute ------->|                   |
    |                    |                   |                  |                  |-- query metrics -->|
    |                    |                   |                  |                  |<-- metric data ----|
    |                    |                   |                  |                  |                   |
    |                    |                   |                  |                  |-- evaluate tests   |
    |                    |                   |                  |                  |                   |
    |                    |<-------------- write results --------|                  |                   |
    |                    |<-------------- update status --------|                  |                   |
    |                    |                   |                  |                  |                   |
    |-- status overview->|                   |                  |                  |                   |
    |<-- health table ---|                   |                  |                  |                   |
```

## Self-Monitoring (Bootstrap Problem)

The engine monitors itself, which creates a chicken-and-egg problem: the engine needs to be running to monitor itself. This is solved at startup:

```
Engine Startup
    |
    +-- Check: does "self-monitoring-policy" exist in Firestore?
    |     +-- No  --> Create default policy (CPU, Memory, Latency P99, Error Rate)
    |     +-- Yes --> Skip
    |
    +-- Check: does "health-engine-service" resource exist?
          +-- No  --> Register engine as monitored resource
          +-- Yes --> Skip
```

The self-monitoring policy includes four tests:
- **CPU Utilization**: warning > 70%, critical > 90%
- **Memory Utilization**: warning > 70%, critical > 90%
- **Request Latency (P99)**: warning > 1s, critical > 5s
- **Error Rate**: warning > 1%, critical > 5%

## Concurrency Model

- The engine runs as a single async Python process (asyncio)
- APScheduler uses the AsyncIO scheduler -- jobs are async coroutines
- Firestore listeners run on background threads (managed by the Firestore SDK)
- `MAX_CONCURRENT_CHECKS` (default: 10) limits parallel test executions
- Same-resource checks are coalesced to prevent overlap

## Lifecycle Management

The FastAPI lifespan context manager ensures clean startup and shutdown:

```
STARTUP                              SHUTDOWN
  |                                     |
  +-- Init Firestore client             +-- Stop PolicyWatcher
  +-- Init Monitoring client            +-- Stop Scheduler
  +-- Discover test plugins             +-- Close Firestore connection
  +-- Create Executor
  +-- Create Scheduler
  +-- Create PolicyWatcher
  +-- Start Scheduler
  +-- Start PolicyWatcher
  +-- Bootstrap self-monitoring
```
