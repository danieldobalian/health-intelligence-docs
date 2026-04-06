# Synthetic Health Monitoring Datasets

Synthetic test data that mirrors the health monitor's data model (resources, policies, test results, resource snapshots). Useful for building and testing agents without hitting real GCP APIs.

## Datasets

### `scenario_fault_and_recovery.json`

A 1-hour window (`2026-04-06T14:00Z` to `15:00Z`) with a cascading fault injected at minute 35 that resolves by minute 55.

**Fault scenario:**

| Minute | Event |
|--------|-------|
| T+0 | All 6 resources healthy |
| T+35 | `sample-health-service` — latency spikes, error rate rises |
| T+37 | `sample-health-function` — downstream degradation (latency + errors) |
| T+38 | `sample-health-subscription` — message backlog grows |
| T+55 | Fault resolves, metrics begin recovering |
| T+58 | All resources return to healthy |

Unaffected resources throughout: `sample-health-instance`, `sample-health-bucket`, `health-engine-service`.

**Stats:** 6 resources, 6 policies, 13 enabled tests, 780 test results, 360 resource snapshots.

### Structure

```jsonc
{
  "metadata": { /* scenario description, time range, fault window */ },
  "resources": [ /* Resource objects matching deploy/resources/ schema */ ],
  "policies": [ /* Policy objects matching deploy/policies/ schema */ ],
  "test_results": [ /* TestResult objects — one per test per minute */ ],
  "resource_snapshots": [ /* Per-resource health state at each minute */ ]
}
```

Each `test_result` follows the `TestResult` model from `src/health_monitor/core/models.py` and includes `result` (status, value, thresholds), `execution` (timestamps, duration), and `explanation` (summary, severity, recommendation).

Each `resource_snapshot` tracks `health_state`, `previous_state`, `state_changed`, consecutive failure/success counts, and a `test_summary` breakdown.

## Regenerating

```bash
python3 datasets/synthetic/generate_scenario.py                # default output
python3 datasets/synthetic/generate_scenario.py -o custom.json  # custom path
```

The generator uses `random.seed(42)` for deterministic output.
