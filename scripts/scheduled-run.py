#!/usr/bin/env python3
"""Launch the daily runner after a bounded, independently drawn random delay."""
import argparse
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-dir',type=Path,default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--max-delay-seconds',type=int,default=1200)
    args = parser.parse_args()
    if args.max_delay_seconds < 0:
        parser.error('max delay must be nonnegative')
    logdir = args.project_dir/'data'/'logs'
    logdir.mkdir(parents=True,exist_ok=True)
    delay = secrets.randbelow(args.max_delay_seconds+1)
    def log(message):
        with (logdir/'schedule.log').open('a') as output:
            output.write(f'[{datetime.now(timezone.utc).isoformat()}] {message}\n')
    log(f'scheduled delay_seconds={delay}')
    time.sleep(delay)
    log('daily runner starting')
    result = subprocess.run(['sh',str(args.project_dir/'scripts'/'daily-run.sh')],cwd=args.project_dir)
    log(f'daily runner finished status={result.returncode}')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
