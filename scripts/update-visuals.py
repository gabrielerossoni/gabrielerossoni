"""Render README images from real public contribution data, without publishing."""
import argparse
import itertools
import json
import os
from pathlib import Path
import random
import re
import subprocess
import tempfile
import urllib.request
from datetime import date

from PIL import Image
from gh_space_shooter.game import Animator, ColumnStrategy
from gh_space_shooter.output import resolve_output_provider

ROOT = Path(__file__).resolve().parent.parent


def activity_chart(days, width):
    total = sum(day['count'] for day in days)
    active = sum(day['count'] > 0 for day in days)
    maximum = max(day['count'] for day in days) or 1
    x0, x1, y0, y1 = 35, width - 30, 80, 198
    points = [(x0 + index * (x1 - x0) / (len(days) - 1),
               y1 - day['count'] * (y1 - y0) / maximum) for index, day in enumerate(days)]
    line = ' '.join(f'{x:.1f},{y:.1f}' for x, y in points)
    area = f'{x0},{y1} {line} {x1},{y1}'
    labels = ''.join(f'<text x="{points[index][0]:.1f}" y="225" text-anchor="middle">{date.fromisoformat(day["date"]).strftime("%m/%y")}</text>'
                     for index, day in enumerate(days) if day['date'].endswith('-01') and date.fromisoformat(day['date']).month % (3 if width < 600 else 2) == 0)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="250" viewBox="0 0 {width} 250" role="img" aria-labelledby="title desc">
<title id="title">Daily public contributions</title><desc id="desc">{total} contributions across {active} active days, from {days[0]['date']} to {days[-1]['date']}.</desc>
<rect x="1" y="1" width="{width-2}" height="248" rx="12" fill="#0d1117" stroke="#30363d"/>
<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" fill="#e6edf3">
<text x="24" y="31" font-size="16" font-weight="600">Public contributions · past 12 months</text>
<text x="24" y="56" font-size="14" fill="#8b949e">{total} contributions · {active} active days</text>
<polygon points="{area}" fill="#1f6feb" opacity=".18"/><polyline points="{line}" fill="none" stroke="#58a6ff" stroke-width="1.8" stroke-linejoin="round"/>
<path d="M{x0} {y1}H{x1}" stroke="#30363d"/>
<g font-size="12" fill="#8b949e">{labels}</g>
</g></svg>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='Use a saved public API response for local preview')
    args = parser.parse_args()
    if args.input:
        raw = json.loads(args.input.read_text(encoding='utf-8-sig'))
    else:
        request = urllib.request.Request(
            'https://github-contributions-api.jogruber.de/v4/gabrielerossoni?y=last',
            headers={'User-Agent': 'gabrielerossoni-profile-visuals'},
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = json.load(response)
    days = raw['contributions']
    if not 364 <= len(days) <= 371:
        raise ValueError('Expected a complete public contribution year')
    previous = None
    for day in days:
        current = date.fromisoformat(day['date'])
        if previous is not None and (current - previous).days != 1:
            raise ValueError('Contribution dates must be consecutive')
        if type(day['count']) is not int or day['count'] < 0 or type(day['level']) is not int or day['level'] not in range(5):
            raise ValueError('Invalid public contribution count or intensity')
        previous = current
    total = sum(day['count'] for day in days)
    if total != raw['total']['lastYear']:
        raise ValueError('Contribution counts do not match the public total')
    weeks = []
    for day in days:
        weekday = (date.fromisoformat(day['date']).weekday() + 1) % 7
        if not weeks or weekday == 0:
            weeks.append({'days': []})
        weeks[-1]['days'].append(day)
    data = {'username': 'gabrielerossoni', 'total_contributions': total, 'weeks': weeks}
    calendar = {'weeks': [{'contributionDays': [
        {'date': day['date'], 'contributionCount': day['count']} for day in days
    ]}]}
    assets = ROOT / 'assets'
    assets.mkdir(exist_ok=True)
    # Render to temporary files first, so a failure keeps the previous images.
    with tempfile.TemporaryDirectory(prefix='.render-', dir=assets) as temporary:
        temp = Path(temporary)
        assert temp.resolve().is_relative_to(assets.resolve())
        (temp / 'calendar.json').write_text(json.dumps(calendar), encoding='utf-8')
        for filename, width in [('activity.svg', 960), ('activity-mobile.svg', 420)]:
            (temp / filename).write_text(activity_chart(days, width), encoding='utf-8')
        subprocess.run(['node', str(ROOT / 'scripts/generate-city.cjs'),
                        str(temp / 'calendar.json'), str(temp / 'contribution-city.svg')], check=True)
        random.seed(42)
        animator = Animator(data, ColumnStrategy(), fps=25)
        frames = list(itertools.islice(animator.generate_frames(), 420))
        if len(frames) < 2:
            raise ValueError('Space Shooter did not produce an animation')
        frames[0].save(temp / 'space-shooter-static.png')
        provider = resolve_output_provider(str(temp / 'space-shooter.gif'))
        provider.write(provider.encode(iter(frames), 80))
        with Image.open(temp / 'space-shooter.gif') as image:
            if image.n_frames < 2:
                raise ValueError('Generated GIF is not animated')
        (temp / 'visuals.json').write_text(json.dumps({
            'username': 'gabrielerossoni', 'period_start': days[0]['date'],
            'period_end': days[-1]['date'], 'contributions': total,
            'last_seven_days': [{'date': day['date'], 'count': day['count']} for day in days[-7:]],
            'source': 'https://github-contributions-api.jogruber.de/v4/gabrielerossoni?y=last',
        }, indent=2), encoding='utf-8')
        for name in ['contribution-city.svg', 'space-shooter.gif', 'space-shooter-static.png', 'visuals.json', 'activity.svg', 'activity-mobile.svg']:
            os.replace(temp / name, assets / name)
    readme = ROOT / 'README.md'
    text = readme.read_text(encoding='utf-8')
    text = re.sub(r'(?<=<!-- contribution-date -->).*?(?=<!-- /contribution-date -->)', days[-1]['date'], text)
    readme.write_text(text, encoding='utf-8')
    print(f'Generated real contribution visuals: {total} contributions, through {days[-1]["date"]}')


if __name__ == '__main__':
    main()
