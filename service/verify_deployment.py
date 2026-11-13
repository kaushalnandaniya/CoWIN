#!/usr/bin/env python3
"""Read-only service contract check. Does not provision, stop or start instances."""
import argparse
from datetime import datetime, timezone
import json
import time
from urllib.request import urlopen
from urllib.parse import urlparse


def check(url, samples=20, interval=0.2):
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username:
        raise ValueError('expected HTTP(S) URL without embedded credentials')
    if samples < 1 or interval < 0:
        raise ValueError('samples must be positive; interval must be non-negative')
    zones, instances = set(), set()
    with urlopen(url.rstrip('/') + '/health', timeout=3) as response:
        health = json.load(response)
        if response.status != 200 or health.get('status') != 'healthy':
            raise ValueError('health contract failed')
    for _ in range(samples):
        with urlopen(url.rstrip('/') + '/api/v1/centers?district=Ahmedabad', timeout=3) as response:
            data = json.load(response)
            zone = response.headers.get('X-Served-By-Zone')
            instance = response.headers.get('X-Instance-Id')
            if response.status != 200 or not isinstance(data.get('centers'), list) or not zone or not instance:
                raise ValueError('lookup contract/identity headers failed')
            zones.add(zone)
            instances.add(instance)
        time.sleep(interval)
    return {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'target_url': url,
            'zones': sorted(zones), 'instances': sorted(instances), 'samples': samples,
            'two_zones_observed': len(zones) >= 2,
            'note': 'Client observation only. Confirm target health and AZ placement in AWS separately.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True)
    p.add_argument('--samples', type=int, default=20)
    args = p.parse_args()
    try:
        result = check(args.url, args.samples)
    except Exception as exc:
        p.exit(2, f'Verification failed: {exc}\n')
    print(json.dumps(result, indent=2))
    return 0 if result['two_zones_observed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
