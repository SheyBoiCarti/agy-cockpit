"""Standalone CLI hook. Stdlib only: the CLI runs a copy before using a tool."""
import json
import os
from pathlib import Path
import sys
import time
import uuid


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else 'tool'
    try:
        directory = os.environ.get('AGY_COCKPIT_GATE_DIR')
        if not directory:
            raise RuntimeError('No active Cockpit permission bridge')
        root = Path(directory)
        payload = json.load(sys.stdin)
        key = uuid.uuid4().hex
        request = root / f'{key}.request.json'
        temporary = root / f'{key}.tmp'
        response = root / f'{key}.response.json'
        temporary.write_text(json.dumps({'phase': phase, 'data': payload}), encoding='utf-8')
        temporary.replace(request)
        deadline = time.monotonic() + 305
        while time.monotonic() < deadline:
            if response.exists():
                result = json.loads(response.read_text(encoding='utf-8'))
                if phase == 'tool' and result.get('decision') not in ('allow', 'deny'):
                    raise RuntimeError('Invalid permission response')
                print(json.dumps(result), flush=True)
                return
            if not root.exists():
                raise RuntimeError('Permission bridge closed')
            time.sleep(.05)
        raise RuntimeError('Permission decision timed out')
    except Exception:
        # Never let a broken/missing bridge grant permission.
        print(json.dumps({'decision': 'deny', 'reason': 'Cockpit permission bridge unavailable; tool blocked.'}), flush=True)
        if phase != 'tool':
            raise SystemExit(1)


if __name__ == '__main__':
    main()
