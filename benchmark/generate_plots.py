#!/usr/bin/env python3
"""Render portable SVG evidence from one run's CSV and JSON; no fixed event times."""
import argparse
import csv
import html
import json
from pathlib import Path


def render(run_dir):
    run_dir = Path(run_dir)
    summary = json.loads((run_dir / 'benchmark_results.json').read_text())
    with (run_dir / 'benchmark_requests.csv').open() as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError('no request samples to plot')
    width, height, left, right = 1100, 650, 80, 1040
    x_max = max(float(r['elapsed_s']) for r in rows) or 1
    y_max = max(float(r['latency_ms']) for r in rows) * 1.15 or 1
    x = lambda v: left + float(v) / x_max * (right - left)
    y = lambda v: 400 - float(v) / y_max * 260
    esc = lambda v: html.escape(str(v), quote=True)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#ffffff"/>',
             '<style>text{font-family:Arial,sans-serif;fill:#172b4d;font-size:14px}.muted{fill:#52647a;font-size:12px}</style>',
             '<text x="80" y="32" font-size="23">CoWIN latency and routing evidence</text>']
    meta = summary['benchmark_metadata']
    parts += [f'<text x="80" y="60">Environment: {esc(meta.get("environment", "unlabelled legacy run"))} | {esc(meta.get("started_at_utc", meta.get("date", "")))}</text>',
              '<text x="80" y="84" class="muted">Client samples only. Simulator results are not AWS results; event markers are observations, not health-check proof.</text>']
    for i in range(6):
        yy = 400 - i * 52
        parts += [f'<line x1="80" y1="{yy}" x2="1040" y2="{yy}" stroke="#e1e7ef"/>',
                  f'<text x="8" y="{yy+5}" class="muted">{y_max*i/5:.2f} ms</text>']
        xx = x(x_max * i / 5)
        parts.append(f'<text x="{xx-12:.1f}" y="425" class="muted">{x_max*i/5:.1f}s</text>')
    points = ' '.join(f'{x(r["elapsed_s"]):.2f},{y(r["latency_ms"]):.2f}' for r in rows)
    parts.append(f'<polyline points="{points}" fill="none" stroke="#2368c4" stroke-width="1.5"/>')
    zones = sorted({r['zone'] for r in rows})
    colors = ['#2368c4', '#16805d', '#8054af', '#967326']
    for row in rows:
        xx = x(row['elapsed_s'])
        good = row['success'] == 'True'
        color = colors[zones.index(row['zone']) % len(colors)] if good else '#bf243a'
        parts.append(f'<circle cx="{xx:.2f}" cy="{y(row["latency_ms"]):.2f}" r="2" fill="{color}"/>')
        lane = 460 + 22 * zones.index(row['zone'])
        parts.append(f'<circle cx="{xx:.2f}" cy="{lane}" r="2.5" fill="{color}"/>')
    for i, zone in enumerate(zones):
        parts.append(f'<text x="8" y="{464+22*i}" class="muted">{esc(zone)}</text>')
    for i, event in enumerate(summary.get('events', [])):
        xx = x(event['elapsed_s'])
        parts.append(f'<line x1="{xx:.2f}" y1="135" x2="{xx:.2f}" y2="400" stroke="#ba4b16" stroke-dasharray="4 4"/>')
        # Labels use a separate legend so nearby events cannot overlap the plot.
        parts.append(f'<text x="{xx:.2f}" y="125" class="muted">{i+1}</text>')
        col, line = i % 2, i // 2
        parts.append(f'<text x="{80+col*480}" y="{550+line*19}" class="muted">{i+1}. {esc(event["event"])} at {event["elapsed_s"]:.3f}s</text>')
    parts += ['<text x="80" y="630" class="muted">Blue/green/purple: zone samples. Red: failed lookup. Raw timestamps and status codes remain in the CSV.</text>', '</svg>']
    path = run_dir / 'latency_timeline.svg'
    path.write_text('\n'.join(parts) + '\n')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', default=str(Path(__file__).parent))
    args = parser.parse_args()
    print(render(args.run_dir))


if __name__ == '__main__':
    main()
