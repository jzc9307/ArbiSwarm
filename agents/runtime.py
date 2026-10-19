"""Request-local execution evidence; never stores prompts, photos or credentials."""
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import uuid

_current = ContextVar('arbi_agent_run', default=None)
_lock = threading.RLock()
_history = deque(maxlen=100)
_active = {}


class RequestBudgetExceeded(RuntimeError):
    code = 429


@dataclass
class AgentRun:
    kind: str
    budget: int
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    attempts: int = 0
    events: list = field(default_factory=list)

    def record(self, agent, status, **details):
        with _lock:
            # All details originate from server code, not model/provider messages.
            if len(self.events) < 250:
                self.events.append({'agent': agent, 'status': status, 'at': datetime.now(timezone.utc).isoformat(), **details})

    def reserve(self):
        with _lock:
            if self.attempts >= self.budget:
                raise RequestBudgetExceeded('This operation reached its local Gemini request budget.')
            self.attempts += 1

    def snapshot(self):
        with _lock:
            events = [dict(item) for item in self.events]
        provider = [item for item in events if item['status'] == 'provider_response']
        metadata = [item['usage'] for item in provider if item.get('usage')]
        names = ('prompt_token_count', 'candidates_token_count', 'thoughts_token_count', 'total_token_count')
        usage = {name: sum(item['usage'][name] for item in provider)
                 if all(name in item.get('usage', {}) for item in provider) else None for name in names} if metadata else None
        ai = [item for item in events if item['status'] in {'ai_completed', 'cache_reused'}]
        return {
            'run_id': self.run_id, 'kind': self.kind, 'started_at': self.started_at,
            'request_budget': self.budget, 'provider_attempts': self.attempts,
            'successful_provider_responses': len(provider),
            'ai_completed': any(item['status'] == 'ai_completed' for item in ai),
            'cached_ai_reused': any(item['status'] == 'cache_reused' for item in ai),
            'token_usage': usage,
            'usage_complete': bool(usage) and all(value is not None for value in usage.values()),
            'events': events,
            'stages': stage_statuses(events),
        }


def stage_statuses(events):
    """Accepted work per role, not a global 'one agent ran' success flag."""
    stages = {}
    for role in ('manager', 'analyst', 'vision', 'reviewer', 'chat'):
        rows = [row for row in events if row['agent'] == role]
        if not rows:
            continue
        accepted = [i for i, row in enumerate(rows) if row['status'] in {'ai_completed', 'cache_reused'}]
        failures = [i for i, row in enumerate(rows) if row['status'] in {'request_failed', 'local_fallback'}]
        last_failure = rows[failures[-1]] if failures else {}
        error = last_failure.get('error')
        if error is None and failures:
            error = {'state': last_failure.get('reason', 'unavailable'),
                     'message': 'This stage did not complete a validated AI review.'}
        partial = any(row.get('outside_shortlist', 0) or row.get('rejected_or_missing', 0) for row in rows)
        unresolved = bool(failures and (not accepted or failures[-1] > accepted[-1]))
        state = ('partial' if unresolved or partial else 'completed') if accepted else ('failed' if failures else 'skipped')
        stages[role] = {
            'state': state,
            'ai_completed': any(row['status'] == 'ai_completed' for row in rows),
            'cached_ai_reused': any(row['status'] == 'cache_reused' for row in rows),
            'provider_attempts': sum(row['status'] == 'request_started' for row in rows),
            'successful_provider_responses': sum(row['status'] == 'provider_response' for row in rows),
            'error': error if unresolved else None,
        }
    return stages


def evidence_status(report, role='analyst'):
    stage = report.get('stages', {}).get(role, {})
    accepted = stage.get('ai_completed') or stage.get('cached_ai_reused')
    if accepted:
        partial = stage.get('state') == 'partial'
        return {'state': 'partial' if partial else 'connected', 'role': role,
                'message': 'AI review is partial. Unreviewed or failed offers remain on hold.' if partial else 'AI evidence review completed or validated cached findings reused.',
                'error': stage.get('error')}
    if stage.get('error'):
        return {**stage['error'], 'role': role,
                'message': 'Marketplace results may be available, but AI evidence review did not complete. ' + stage['error']['message']}
    return {'state': 'skipped', 'role': role,
            'message': 'No new AI evidence review: local/demo mode, no eligible candidates, or no usable photos. No AI buy recommendation is claimed.'}


def record(agent, status, **details):
    run = _current.get()
    if run:
        run.record(agent, status, **details)


def reserve_attempt():
    run = _current.get()
    if run:
        run.reserve()


@contextmanager
def operation(kind, budget=3):
    existing = _current.get()
    if existing:
        yield existing
        return
    run = AgentRun(kind, max(0, budget))
    token = _current.set(run)
    with _lock:
        _active[run.run_id] = run
    try:
        yield run
    except Exception:
        run.record('controller', 'failed')
        raise
    finally:
        with _lock:
            _active.pop(run.run_id, None)
            _history.appendleft(run.snapshot())
        _current.reset(token)


def runs():
    with _lock:
        return {'active': [run.snapshot() for run in _active.values()], 'recent': list(_history)[:20]}


def mode(report):
    return 'gemini' if report['ai_completed'] or report['cached_ai_reused'] else 'deterministic'
