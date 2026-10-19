"""Safe setup check; --live explicitly spends at most one Gemini request.

Run from any folder: python /path/to/ArbiSwarm/scripts/check_gemini.py --live
Never prints credentials, listing/user content, or raw provider exceptions.
"""
import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from agents import _llm, runtime
from agents.batch_analyst import Findings, PROMPT


def timeout_seconds(value):
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Timeout must be an integer from 10 to 60 seconds.') from exc
    if not 10 <= seconds <= 60:
        raise argparse.ArgumentTypeError('Timeout must be from 10 to 60 seconds.')
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Send one small analyst-schema test to Gemini. Uses quota.')
    parser.add_argument('--timeout-seconds', type=timeout_seconds, help='Request deadline, 10–60 seconds; defaults to AI_ANALYSIS_TIMEOUT_MS.')
    args = parser.parse_args()
    timeout_ms = args.timeout_seconds * 1000 if args.timeout_seconds is not None else config.AI_ANALYSIS_TIMEOUT_MS
    output = {'configuration': _llm.runtime_status(), 'live_request_sent': False, 'deadline_seconds': timeout_ms / 1000}
    if not args.live:
        output['note'] = 'Configuration only, not proof of connectivity. Use --live to explicitly test the analyst schema.'
        print(json.dumps(output, indent=2))
        return 0
    if not _llm.is_enabled():
        output['error'] = _llm.ai_status()
        print(json.dumps(output, indent=2))
        return 1
    title = 'LEGO Star Wars 75192 UCS Millennium Falcon'
    sample = {'offer_id': 'diagnostic:1', 'marketplace': 'carousell', 'title': title,
              'description': 'Synthetic diagnostic only: complete used set. Authenticity not established.', 'condition': 'Used'}
    payload = {'query': 'LEGO 75192', 'match_mode': 'exact', 'listings': [sample]}
    # One wire attempt total: no fallback-key/model probe or hidden retry storm.
    started = time.monotonic()
    with patch.object(config, 'GEMINI_MAX_ATTEMPTS', 1), runtime.operation('gemini_diagnostic', 1) as run:
        try:
            answer = _llm.call_json(PROMPT, json.dumps(payload), Findings,
                                    role='analyst', max_output_tokens=2048, timeout_ms=timeout_ms)
            if len(answer.findings) != 1 or answer.findings[0].offer_id != sample['offer_id']:
                raise _llm.InvalidAIResponse()
            finding = answer.findings[0]
            if not finding.evidence or any(not quote.text.strip() or quote.text.casefold() not in sample[quote.field].casefold() for quote in finding.evidence):
                raise _llm.InvalidAIResponse()
            runtime.record('analyst', 'ai_completed', count=1)
            output['verified'] = True
        except Exception as exc:
            output['verified'] = False
            output['error'] = _llm.failure_status(exc)
        report = run.snapshot()
        output.update(live_request_sent=report['provider_attempts'] > 0, agent_run=report)
    # This is an after-run snapshot, not the old pre-request zero counters.
    output.update(configuration=_llm.runtime_status(), elapsed_seconds=round(time.monotonic() - started, 2))
    print(json.dumps(output, indent=2))
    return 0 if output.get('verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
