"""
Interprets AROL's official closure-status codes (as supplied in the
project file "Status-code-to-meaning_mapping" / config/status_codes.json).

The mapping is embedded as a constant here (not read from disk at call
time) so that classify()/describe() work as simple, dependency-free
per-value functions usable inside pandas .apply() calls without threading
Settings through every analytics function. config/status_codes.json is
kept alongside it as the human-readable, authoritative reference - if
AROL ever revises the mapping, update BOTH: the JSON (documentation/
source of truth for reviewers) and STATUS_TABLE below (what the code
actually runs on).

Categories:
  success   status 0  - "Closure OK". The only status that counts as a
                        genuine successful capping event.
  no_load   status 2  - "No Load". The head cycled with no bottle
                        present - normal operation, not a fault. Torque
                        is expected to read ~0 for these.
  reject    reject_signal == "YES" - a genuine quality reject (failed to
                        reach torque/turns/timing thresholds, tracking
                        error, etc). These are the "real" failures.
  fault     reject_signal == "NO" and code not in {0, 2} - the machine
                        detected an abnormal condition (No Closure, No
                        InTorque, No CapTurns, Following Error, Bad
                        Closure) that did NOT trigger AROL's own reject
                        signal. Reported separately from "reject" since
                        lumping them together would misrepresent AROL's
                        own quality-reject rate.
  unknown   any code not present in the table below (defensive fallback,
                        logged once so it's noticed, never crashes).
"""
from __future__ import annotations

import logging
from typing import Dict, List, TypedDict

logger = logging.getLogger(__name__)

CATEGORY_SUCCESS = "success"
CATEGORY_NO_LOAD = "no_load"
CATEGORY_REJECT = "reject"
CATEGORY_FAULT = "fault"
CATEGORY_UNKNOWN = "unknown"


class _StatusEntry(TypedDict):
    reject_signal: bool
    description: str


# Kept in sync with config/status_codes.json - see module docstring.
STATUS_TABLE: Dict[int, _StatusEntry] = {
    0: {"reject_signal": False, "description": "Closure OK"},
    2: {"reject_signal": False, "description": "No Load"},
    3: {"reject_signal": True, "description": "Failing to reach the first torque threshold (SlowTorque)"},
    4: {"reject_signal": False, "description": "No Closure"},
    5: {"reject_signal": True, "description": "Failing to reach the final torque (ClosureTorque)"},
    8: {"reject_signal": False, "description": "No InTorque"},
    9: {"reject_signal": True, "description": "Closure Head raises before the TimeInTorque time was elapsed"},
    16: {"reject_signal": False, "description": "No CapTurns"},
    17: {"reject_signal": True, "description": "The cap is closed but with less degrees than CapTurns"},
    32: {"reject_signal": False, "description": "Following Error"},
    33: {"reject_signal": True, "description": "Tracking error between the real position and the controlled position of the head"},
    64: {"reject_signal": False, "description": "Bad Closure"},
    65: {"reject_signal": True, "description": "ClosureTorque reached but cap is still rotating when head raises"},
}

_warned_unknown_codes: set = set()


def classify(code) -> str:
    """Returns one of: success, no_load, reject, fault, unknown."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return CATEGORY_UNKNOWN

    if code == 0:
        return CATEGORY_SUCCESS
    if code == 2:
        return CATEGORY_NO_LOAD

    entry = STATUS_TABLE.get(code)
    if entry is None:
        if code not in _warned_unknown_codes:
            logger.warning("Unrecognized status code %s - treating as 'unknown'", code)
            _warned_unknown_codes.add(code)
        return CATEGORY_UNKNOWN

    return CATEGORY_REJECT if entry["reject_signal"] else CATEGORY_FAULT


def describe(code) -> str:
    """Human-readable description of a status code, for reports and
    fault_code_breakdown. Falls back gracefully for undocumented codes."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return f"Unrecognized status value ({code!r})"

    entry = STATUS_TABLE.get(code)
    if entry is None:
        return f"Unrecognized status code ({code})"
    return entry["description"]


def is_reject_signal(code) -> bool:
    """Raw AROL reject_signal for a code (False for unknown codes)."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return False
    entry = STATUS_TABLE.get(code)
    return bool(entry and entry["reject_signal"])


def full_table() -> List[dict]:
    """The complete status-code reference, for documentation/reporting
    (e.g. an agent tool that lists 'what do all the status codes mean')."""
    return [
        {
            "code": code,
            "category": classify(code),
            "reject_signal": entry["reject_signal"],
            "description": entry["description"],
        }
        for code, entry in sorted(STATUS_TABLE.items())
    ]
