#!/usr/bin/env python3
"""Generate a synthetic health monitoring dataset with a fault-and-recovery scenario.

Produces a JSON file matching the health monitor data model (resources, policies,
test results) over a 1-hour window.  A simulated fault is injected at minute 35
and resolves at minute 55.

Scenario narrative:
  - sample-health-service starts returning errors and high latency at T+35
  - sample-health-function (downstream) degrades 2 minutes later at T+37
  - sample-health-subscription backs up 3 minutes later at T+38
  - Other resources (GCE instance, GCS bucket, health engine) remain healthy
  - All faults resolve by T+55

Usage:
    python generate_scenario.py                # writes scenario_fault_and_recovery.json
    python generate_scenario.py -o output.json  # custom output path
"""

from __future__ import annotations

import argparse
import json
import math
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_TIME = datetime(2026, 4, 6, 14, 0, 0, tzinfo=timezone.utc)
DURATION_MINUTES = 60
INTERVAL_SECONDS = 60  # one test execution per minute

FAULT_START_MIN = 35
FAULT_END_MIN = 55

PROJECT_ID = "moni-test-484500"
LOCATION = "us-central1"

# Seed for reproducibility
random.seed(42)

# ---------------------------------------------------------------------------
# Resource & policy definitions (mirrors deploy/ YAML, no sensitive data)
# ---------------------------------------------------------------------------

RESOURCES = [
    {
        "resource_id": "sample-health-service",
        "name": "Sample Health Service",
        "resource_type": "cloud_run_service",
        "gcp_resource_name": f"projects/{PROJECT_ID}/locations/{LOCATION}/services/sample-health-service",
        "project_id": PROJECT_ID,
        "location": LOCATION,
        "policy_ids": ["sample-cloudrun-policy"],
        "labels": {"environment": "demo", "team": "health-monitor"},
    },
    {
        "resource_id": "sample-health-instance",
        "name": "Sample Health Instance",
        "resource_type": "gce_instance",
        "gcp_resource_name": f"projects/{PROJECT_ID}/zones/{LOCATION}-a/instances/7760578158268484794",
        "project_id": PROJECT_ID,
        "location": f"{LOCATION}-a",
        "policy_ids": ["sample-gce-policy"],
        "labels": {"environment": "demo", "team": "health-monitor", "machine_type": "e2-micro"},
    },
    {
        "resource_id": "sample-health-bucket",
        "name": "Sample Health Bucket",
        "resource_type": "gcs_bucket",
        "gcp_resource_name": f"projects/{PROJECT_ID}/buckets/{PROJECT_ID}-health-test",
        "project_id": PROJECT_ID,
        "location": LOCATION,
        "policy_ids": ["sample-gcs-policy"],
        "labels": {"environment": "demo", "team": "health-monitor", "storage_class": "standard"},
    },
    {
        "resource_id": "sample-health-function",
        "name": "Sample Health Function",
        "resource_type": "cloud_run_service",
        "gcp_resource_name": f"projects/{PROJECT_ID}/locations/{LOCATION}/services/sample-health-function",
        "project_id": PROJECT_ID,
        "location": LOCATION,
        "policy_ids": ["sample-function-policy"],
        "labels": {"environment": "demo", "team": "health-monitor", "runtime": "python311"},
    },
    {
        "resource_id": "sample-health-subscription",
        "name": "Sample Health Subscription",
        "resource_type": "pubsub_subscription",
        "gcp_resource_name": f"projects/{PROJECT_ID}/subscriptions/health-test-sub",
        "project_id": PROJECT_ID,
        "location": LOCATION,
        "policy_ids": ["sample-pubsub-policy"],
        "labels": {"environment": "demo", "team": "health-monitor"},
    },
    {
        "resource_id": "health-engine-service",
        "name": "Health Engine Service",
        "resource_type": "cloud_run_service",
        "gcp_resource_name": f"projects/{PROJECT_ID}/locations/{LOCATION}/services/health-engine",
        "project_id": PROJECT_ID,
        "location": LOCATION,
        "policy_ids": ["self-monitoring-policy"],
        "labels": {"environment": "demo", "team": "health-monitor", "component": "health-engine"},
    },
]

POLICIES = [
    {
        "policy_id": "sample-cloudrun-policy",
        "name": "Sample Cloud Run Health Policy",
        "description": "Health checks for sample-health-service",
        "resource_type": "cloud_run_service",
        "enabled": True,
        "version": 1,
        "tests": [
            {
                "test_id": "request-latency",
                "test_type": "metric_threshold",
                "name": "Request Latency P99",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 600},
                "config": {
                    "metric_type": "run.googleapis.com/request_latencies",
                    "aggregation": "percentile_99",
                    "threshold_operator": "greater_than",
                    "warning_threshold": 1000,
                    "critical_threshold": 5000,
                    "unit": "ms",
                },
            },
            {
                "test_id": "error-rate",
                "test_type": "error_rate",
                "name": "HTTP Error Rate",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 600},
                "config": {
                    "request_count_metric": "run.googleapis.com/request_count",
                    "error_filter": "response_code_class='4xx' OR response_code_class='5xx'",
                    "warning_threshold_percent": 1.0,
                    "critical_threshold_percent": 5.0,
                },
            },
        ],
        "labels": {"environment": "demo", "resource": "sample-health-service"},
    },
    {
        "policy_id": "sample-gce-policy",
        "name": "Sample GCE Health Policy",
        "description": "Health checks for sample-health-instance",
        "resource_type": "gce_instance",
        "enabled": True,
        "version": 1,
        "tests": [
            {
                "test_id": "cpu-utilization",
                "test_type": "metric_threshold",
                "name": "CPU Utilization",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 300},
                "config": {
                    "metric_type": "compute.googleapis.com/instance/cpu/utilization",
                    "aggregation": "mean",
                    "threshold_operator": "greater_than",
                    "warning_threshold": 0.8,
                    "critical_threshold": 0.95,
                    "unit": "ratio",
                },
            },
            {
                "test_id": "uptime-check",
                "test_type": "metric_threshold",
                "name": "Instance Uptime",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 300},
                "config": {
                    "metric_type": "compute.googleapis.com/instance/uptime",
                    "aggregation": "min",
                    "threshold_operator": "less_than",
                    "critical_threshold": 10,
                    "unit": "seconds",
                },
            },
        ],
        "labels": {"environment": "demo", "resource": "sample-health-instance"},
    },
    {
        "policy_id": "sample-gcs-policy",
        "name": "Sample GCS Health Policy",
        "description": "Health checks for sample-health-bucket",
        "resource_type": "gcs_bucket",
        "enabled": True,
        "version": 1,
        "tests": [
            {
                "test_id": "error-rate",
                "test_type": "error_rate",
                "name": "API Error Rate",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 600},
                "config": {
                    "request_count_metric": "storage.googleapis.com/api/request_count",
                    "error_filters": [
                        'metric.labels.response_code = "500"',
                        'metric.labels.response_code = "503"',
                    ],
                    "warning_threshold_percent": 0.1,
                    "critical_threshold_percent": 1.0,
                },
            },
        ],
        "labels": {"environment": "demo", "resource": "sample-health-bucket"},
    },
    {
        "policy_id": "sample-function-policy",
        "name": "Sample Function Health Policy",
        "description": "Health checks for sample-health-function",
        "resource_type": "cloud_run_service",
        "enabled": True,
        "version": 2,
        "tests": [
            {
                "test_id": "request-latency",
                "test_type": "metric_threshold",
                "name": "Request Latency P95",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 600},
                "config": {
                    "metric_type": "run.googleapis.com/request_latencies",
                    "aggregation": "percentile_95",
                    "threshold_operator": "greater_than",
                    "warning_threshold": 3000,
                    "critical_threshold": 10000,
                    "unit": "ms",
                },
            },
            {
                "test_id": "error-rate",
                "test_type": "error_rate",
                "name": "Function Error Rate",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 600},
                "config": {
                    "request_count_metric": "run.googleapis.com/request_count",
                    "error_filters": [
                        'metric.labels.response_code_class = "4xx"',
                        'metric.labels.response_code_class = "5xx"',
                    ],
                    "warning_threshold_percent": 1.0,
                    "critical_threshold_percent": 5.0,
                },
            },
        ],
        "labels": {"environment": "demo", "resource": "sample-health-function"},
    },
    {
        "policy_id": "sample-pubsub-policy",
        "name": "Sample Pub/Sub Health Policy",
        "description": "Health checks for sample-health-subscription",
        "resource_type": "pubsub_subscription",
        "enabled": True,
        "version": 1,
        "tests": [
            {
                "test_id": "oldest-unacked-age",
                "test_type": "metric_threshold",
                "name": "Oldest Unacked Message Age",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 300},
                "config": {
                    "metric_type": "pubsub.googleapis.com/subscription/oldest_unacked_message_age",
                    "aggregation": "max",
                    "threshold_operator": "greater_than",
                    "warning_threshold": 300,
                    "critical_threshold": 600,
                    "unit": "seconds",
                },
            },
            {
                "test_id": "undelivered-messages",
                "test_type": "metric_threshold",
                "name": "Undelivered Message Count",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 300},
                "config": {
                    "metric_type": "pubsub.googleapis.com/subscription/num_undelivered_messages",
                    "aggregation": "max",
                    "threshold_operator": "greater_than",
                    "warning_threshold": 10000,
                    "critical_threshold": 100000,
                    "unit": "messages",
                },
            },
        ],
        "labels": {"environment": "demo", "resource": "sample-health-subscription"},
    },
    {
        "policy_id": "self-monitoring-policy",
        "name": "Self-Monitoring Policy",
        "description": "Health checks for the health-engine service itself",
        "resource_type": "cloud_run_service",
        "enabled": True,
        "version": 1,
        "tests": [
            {
                "test_id": "cpu-utilization",
                "test_type": "metric_threshold",
                "name": "CPU Utilization",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 300},
                "config": {
                    "metric_type": "run.googleapis.com/container/cpu/utilizations",
                    "aggregation": "mean",
                    "threshold_operator": "greater_than",
                    "warning_threshold": 70,
                    "critical_threshold": 90,
                    "unit": "%",
                },
            },
            {
                "test_id": "memory-utilization",
                "test_type": "metric_threshold",
                "name": "Memory Utilization",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 300},
                "config": {
                    "metric_type": "run.googleapis.com/container/memory/utilizations",
                    "aggregation": "mean",
                    "threshold_operator": "greater_than",
                    "warning_threshold": 80,
                    "critical_threshold": 95,
                    "unit": "%",
                },
            },
            {
                "test_id": "request-latency-p99",
                "test_type": "metric_threshold",
                "name": "Request Latency P99",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 300},
                "config": {
                    "metric_type": "run.googleapis.com/request_latencies",
                    "aggregation": "percentile_99",
                    "threshold_operator": "greater_than",
                    "warning_threshold": 500,
                    "critical_threshold": 1000,
                    "unit": "ms",
                },
            },
            {
                "test_id": "error-rate",
                "test_type": "error_rate",
                "name": "Error Rate",
                "enabled": True,
                "schedule": {"interval_seconds": 60, "evaluation_window_seconds": 300},
                "config": {
                    "request_count_metric": "run.googleapis.com/request_count",
                    "error_filters": [
                        'metric.labels.response_code_class = "5xx"',
                    ],
                    "warning_threshold_percent": 1.0,
                    "critical_threshold_percent": 5.0,
                },
            },
        ],
        "labels": {"environment": "demo", "resource": "health-engine-service"},
    },
]

# ---------------------------------------------------------------------------
# Metric simulation helpers
# ---------------------------------------------------------------------------


def _noise(base: float, pct: float = 0.10) -> float:
    """Add Gaussian noise to a base value (clamped >= 0)."""
    return max(0.0, base + random.gauss(0, base * pct))


def _ramp(minute: int, start: int, peak_offset: int, peak_val: float, base_val: float) -> float:
    """Smooth ramp from base_val to peak_val over peak_offset minutes after start."""
    if minute < start:
        return base_val
    elapsed = minute - start
    if elapsed >= peak_offset:
        return peak_val
    # Sine-based smooth ramp
    progress = elapsed / peak_offset
    return base_val + (peak_val - base_val) * (0.5 - 0.5 * math.cos(math.pi * progress))


def _ramp_down(minute: int, end: int, tail: int, peak_val: float, base_val: float) -> float:
    """Smooth ramp from peak_val back to base_val over tail minutes ending at end+tail."""
    if minute > end + tail:
        return base_val
    if minute <= end:
        return peak_val
    elapsed = minute - end
    progress = elapsed / tail
    return peak_val + (base_val - peak_val) * (0.5 - 0.5 * math.cos(math.pi * progress))


def fault_value(
    minute: int,
    base: float,
    peak: float,
    fault_start: int = FAULT_START_MIN,
    fault_end: int = FAULT_END_MIN,
    ramp_up_mins: int = 3,
    ramp_down_mins: int = 3,
    noise_pct: float = 0.08,
) -> float:
    """Generate a metric value that ramps up during fault and recovers after."""
    if minute < fault_start:
        return _noise(base, noise_pct)
    if minute < fault_start + ramp_up_mins:
        val = _ramp(minute, fault_start, ramp_up_mins, peak, base)
        return _noise(val, noise_pct)
    if minute <= fault_end:
        return _noise(peak, noise_pct)
    if minute <= fault_end + ramp_down_mins:
        val = _ramp_down(minute, fault_end, ramp_down_mins, peak, base)
        return _noise(val, noise_pct)
    return _noise(base, noise_pct)


def stable_value(base: float, noise_pct: float = 0.10) -> float:
    """Generate a stable metric value with noise (no fault impact)."""
    return _noise(base, noise_pct)


# ---------------------------------------------------------------------------
# Status determination
# ---------------------------------------------------------------------------


def determine_status(
    value: float,
    config: dict,
) -> str:
    """Determine test status from value and thresholds."""
    operator = config.get("threshold_operator", "greater_than")
    critical = config.get("critical_threshold") or config.get("critical_threshold_percent")
    warning = config.get("warning_threshold") or config.get("warning_threshold_percent")

    if operator in ("greater_than", "greater_than_or_equal"):
        if critical is not None and value >= critical:
            return "failing"
        if warning is not None and value >= warning:
            return "warning"
        return "passing"
    elif operator in ("less_than", "less_than_or_equal"):
        if critical is not None and value <= critical:
            return "failing"
        if warning is not None and value <= warning:
            return "warning"
        return "passing"
    return "passing"


def make_explanation(status: str, test_name: str, value: float, unit: str | None, config: dict) -> dict:
    """Generate a human-readable explanation for a test result."""
    unit_str = f" {unit}" if unit else ""
    val_display = f"{value:.2f}{unit_str}"
    critical = config.get("critical_threshold") or config.get("critical_threshold_percent")
    warning = config.get("warning_threshold") or config.get("warning_threshold_percent")

    if status == "passing":
        return {
            "summary": f"{test_name} is within normal range at {val_display}",
            "severity": "info",
        }
    elif status == "warning":
        return {
            "summary": f"{test_name} elevated at {val_display} (warning threshold: {warning}{unit_str})",
            "severity": "warning",
            "recommendation": f"Monitor {test_name.lower()} — approaching critical threshold",
            "context": {"value": round(value, 4), "warning_threshold": warning},
        }
    else:  # failing
        return {
            "summary": f"{test_name} critical at {val_display} (threshold: {critical}{unit_str})",
            "details": f"Measured {val_display} exceeds critical threshold of {critical}{unit_str}",
            "severity": "critical",
            "recommendation": f"Investigate {test_name.lower()} immediately",
            "context": {"value": round(value, 4), "critical_threshold": critical},
        }


# ---------------------------------------------------------------------------
# Value generators per (resource_id, test_id)
# ---------------------------------------------------------------------------

# Each generator returns (value, unit_for_display) for a given minute
VALUE_GENERATORS: dict[tuple[str, str], callable] = {
    # --- sample-health-service: FAULTED ---
    ("sample-health-service", "request-latency"): lambda m: (
        fault_value(m, base=280, peak=7200, ramp_up_mins=3, ramp_down_mins=4),
        "ms",
    ),
    ("sample-health-service", "error-rate"): lambda m: (
        fault_value(m, base=0.3, peak=18.0, ramp_up_mins=2, ramp_down_mins=3),
        "%",
    ),
    # --- sample-health-instance: STABLE ---
    ("sample-health-instance", "cpu-utilization"): lambda m: (stable_value(0.22), "ratio"),
    ("sample-health-instance", "uptime-check"): lambda m: (stable_value(60.0, 0.02), "seconds"),
    # --- sample-health-bucket: STABLE ---
    ("sample-health-bucket", "error-rate"): lambda m: (stable_value(0.03, 0.30), "%"),
    # --- sample-health-function: FAULTED (delayed 2 min) ---
    ("sample-health-function", "request-latency"): lambda m: (
        fault_value(
            m, base=720, peak=13500,
            fault_start=FAULT_START_MIN + 2, fault_end=FAULT_END_MIN,
            ramp_up_mins=4, ramp_down_mins=3,
        ),
        "ms",
    ),
    ("sample-health-function", "error-rate"): lambda m: (
        fault_value(
            m, base=0.5, peak=11.0,
            fault_start=FAULT_START_MIN + 2, fault_end=FAULT_END_MIN,
            ramp_up_mins=3, ramp_down_mins=3,
        ),
        "%",
    ),
    # --- sample-health-subscription: FAULTED (delayed 3 min) ---
    ("sample-health-subscription", "oldest-unacked-age"): lambda m: (
        fault_value(
            m, base=12, peak=950,
            fault_start=FAULT_START_MIN + 3, fault_end=FAULT_END_MIN,
            ramp_up_mins=5, ramp_down_mins=4,
        ),
        "seconds",
    ),
    ("sample-health-subscription", "undelivered-messages"): lambda m: (
        fault_value(
            m, base=120, peak=22000,
            fault_start=FAULT_START_MIN + 3, fault_end=FAULT_END_MIN,
            ramp_up_mins=5, ramp_down_mins=5,
        ),
        "messages",
    ),
    # --- health-engine-service: STABLE (self-monitoring) ---
    ("health-engine-service", "cpu-utilization"): lambda m: (stable_value(18.0), "%"),
    ("health-engine-service", "memory-utilization"): lambda m: (stable_value(47.0, 0.05), "%"),
    ("health-engine-service", "request-latency-p99"): lambda m: (stable_value(95.0, 0.15), "ms"),
    ("health-engine-service", "error-rate"): lambda m: (stable_value(0.05, 0.50), "%"),
}


# ---------------------------------------------------------------------------
# Test result generation
# ---------------------------------------------------------------------------


def generate_test_results() -> list[dict]:
    """Generate all test results for the 1-hour window."""
    results = []

    # Build lookup: policy_id -> policy
    policy_map = {p["policy_id"]: p for p in POLICIES}

    for resource in RESOURCES:
        resource_id = resource["resource_id"]
        for policy_id in resource["policy_ids"]:
            policy = policy_map[policy_id]
            for test_cfg in policy["tests"]:
                if not test_cfg["enabled"]:
                    continue

                test_id = test_cfg["test_id"]
                test_type = test_cfg["test_type"]
                config = test_cfg["config"]
                schedule = test_cfg["schedule"]

                gen_key = (resource_id, test_id)
                if gen_key not in VALUE_GENERATORS:
                    continue

                gen_fn = VALUE_GENERATORS[gen_key]

                for minute in range(DURATION_MINUTES):
                    ts = BASE_TIME + timedelta(minutes=minute)
                    value, unit = gen_fn(minute)
                    value = round(value, 4)

                    status = determine_status(value, config)

                    # Build thresholds for result data
                    warning_thresh = config.get("warning_threshold") or config.get("warning_threshold_percent")
                    critical_thresh = config.get("critical_threshold") or config.get("critical_threshold_percent")

                    result_unit = config.get("unit", unit)

                    explanation = make_explanation(
                        status, test_cfg["name"], value, result_unit, config,
                    )

                    eval_window_secs = schedule["evaluation_window_seconds"]
                    exec_duration_ms = random.randint(80, 350)

                    started_at = ts
                    completed_at = ts + timedelta(milliseconds=exec_duration_ms)

                    result = {
                        "test_result_id": f"{resource_id}_{test_id}_{minute:03d}",
                        "resource_id": resource_id,
                        "policy_id": policy_id,
                        "test_id": test_id,
                        "test_type": test_type,
                        "result": {
                            "status": status,
                            "value": value,
                            "threshold_warning": warning_thresh,
                            "threshold_critical": critical_thresh,
                            "unit": result_unit,
                        },
                        "execution": {
                            "started_at": started_at.isoformat(),
                            "completed_at": completed_at.isoformat(),
                            "duration_ms": exec_duration_ms,
                            "evaluation_window_start": (ts - timedelta(seconds=eval_window_secs)).isoformat(),
                            "evaluation_window_end": ts.isoformat(),
                        },
                        "explanation": explanation,
                        "created_at": completed_at.isoformat(),
                    }

                    results.append(result)

    return results


# ---------------------------------------------------------------------------
# Resource status snapshots (final state at each minute)
# ---------------------------------------------------------------------------


def compute_resource_snapshots(test_results: list[dict]) -> list[dict]:
    """Compute per-resource status snapshots at each minute boundary.

    Returns a list of resource status records showing how each resource's
    overall health evolves over the 1-hour window.
    """
    # Group results by (resource_id, minute)
    from collections import defaultdict

    by_resource_minute: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in test_results:
        rid = r["resource_id"]
        # Extract minute from the result id suffix
        minute = int(r["test_result_id"].rsplit("_", 1)[-1])
        by_resource_minute[rid][minute].append(r)

    resource_map = {r["resource_id"]: r for r in RESOURCES}
    snapshots = []

    for resource_id in sorted(by_resource_minute.keys()):
        prev_state = "unknown"
        consec_fail = 0
        consec_pass = 0
        last_state_change = BASE_TIME.isoformat()

        for minute in range(DURATION_MINUTES):
            ts = BASE_TIME + timedelta(minutes=minute)
            results_at_minute = by_resource_minute[resource_id].get(minute, [])

            statuses = [r["result"]["status"] for r in results_at_minute]

            if any(s in ("failing", "error") for s in statuses):
                state = "unhealthy"
            elif any(s == "warning" for s in statuses):
                state = "warning"
            elif any(s == "passing" for s in statuses):
                state = "healthy"
            else:
                state = "unknown"

            state_changed = state != prev_state
            if state_changed:
                last_state_change = ts.isoformat()
                consec_fail = 0
                consec_pass = 0

            if state in ("unhealthy",):
                consec_fail += 1
                consec_pass = 0
            elif state in ("healthy",):
                consec_pass += 1
                consec_fail = 0
            elif state == "warning":
                consec_fail = 0
                consec_pass = 0

            passing = sum(1 for s in statuses if s == "passing")
            warning = sum(1 for s in statuses if s == "warning")
            failing = sum(1 for s in statuses if s in ("failing", "error"))

            snapshots.append({
                "resource_id": resource_id,
                "timestamp": ts.isoformat(),
                "minute": minute,
                "health_state": state,
                "previous_state": prev_state,
                "state_changed": state_changed,
                "consecutive_failures": consec_fail,
                "consecutive_successes": consec_pass,
                "last_state_change": last_state_change,
                "test_summary": {
                    "total_tests": len(statuses),
                    "passing_tests": passing,
                    "warning_tests": warning,
                    "failing_tests": failing,
                    "unknown_tests": 0,
                },
            })
            prev_state = state

    return snapshots


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def build_dataset() -> dict:
    """Build the complete synthetic dataset."""
    test_results = generate_test_results()
    resource_snapshots = compute_resource_snapshots(test_results)

    return {
        "metadata": {
            "description": (
                "Synthetic health monitoring dataset: 1-hour window with a fault at T+35 "
                "that cascades across services and resolves at T+55."
            ),
            "scenario": "fault_and_recovery",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "time_range": {
                "start": BASE_TIME.isoformat(),
                "end": (BASE_TIME + timedelta(minutes=DURATION_MINUTES)).isoformat(),
            },
            "fault_window": {
                "start_minute": FAULT_START_MIN,
                "end_minute": FAULT_END_MIN,
                "description": (
                    "sample-health-service degrades at T+35; cascades to "
                    "sample-health-function (+2 min) and sample-health-subscription (+3 min). "
                    "All recover by T+55."
                ),
            },
            "total_test_results": len(test_results),
            "resources_count": len(RESOURCES),
            "policies_count": len(POLICIES),
        },
        "resources": RESOURCES,
        "policies": POLICIES,
        "test_results": test_results,
        "resource_snapshots": resource_snapshots,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic health monitoring dataset")
    parser.add_argument(
        "-o", "--output",
        default=str(Path(__file__).parent / "scenario_fault_and_recovery.json"),
        help="Output JSON file path",
    )
    args = parser.parse_args()

    dataset = build_dataset()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(dataset, indent=2) + "\n")

    # Print summary
    print(f"Generated dataset: {output_path}")
    print(f"  Time range: {dataset['metadata']['time_range']['start']} -> {dataset['metadata']['time_range']['end']}")
    print(f"  Resources: {dataset['metadata']['resources_count']}")
    print(f"  Policies: {dataset['metadata']['policies_count']}")
    print(f"  Test results: {dataset['metadata']['total_test_results']}")
    print(f"  Resource snapshots: {len(dataset['resource_snapshots'])}")
    print(f"  Fault window: minutes {FAULT_START_MIN}-{FAULT_END_MIN}")

    # Print state transitions
    print("\nState transitions:")
    seen = set()
    for snap in dataset["resource_snapshots"]:
        if snap["state_changed"]:
            key = (snap["resource_id"], snap["minute"], snap["health_state"])
            if key not in seen:
                seen.add(key)
                print(
                    f"  T+{snap['minute']:02d} {snap['resource_id']}: "
                    f"{snap['previous_state']} -> {snap['health_state']}"
                )


if __name__ == "__main__":
    main()
