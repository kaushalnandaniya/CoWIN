#!/usr/bin/env python3
"""Record an operator event after a successful stop/start command, not before it."""
import argparse
import json
from pathlib import Path
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--event', choices=['failure', 'recovery'], required=True)
    p.add_argument('--note', default='operator command accepted; confirm actual state separately')
    args = p.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        f.write(json.dumps({'event': args.event, 'timestamp': time.time(), 'note': args.note}) + '\n')


if __name__ == '__main__':
    main()
