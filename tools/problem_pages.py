"""Plain static HTML/Markdown/JSON entrypoints for measured robotics cases."""
import html
import json
from pathlib import Path

if __package__:
    from .generate_problem_cases import verified_cases
else:
    from generate_problem_cases import verified_cases


def publish(root: Path, output: Path, base: str, commit: str):
    entries = verified_cases(root)
    if not entries: return []
    destination = output / 'problems'; destination.mkdir(parents=True, exist_ok=True)
    links = []
    def page(title, text, canonical, related=''):
        esc = html.escape
        return f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{esc(title)} | Robot Skill Hub</title><link rel="canonical" href="{esc(canonical)}"><meta name="description" content="{esc(title)}: pinned robotics input, source and bounded reproduction evidence."></head><body><h1>{esc(title)}</h1>{related}<pre>{esc(text)}</pre><p><a href="{base}/agent.json">Agent contract</a> | <a href="{base}/problems/">All cases</a></p></body></html>\n'
    receipt = json.loads((root / 'evidence/integration/agent-discovery-v1/problem-cases.json').read_text())
    reports = {r['id']: r for r in receipt['cases']}
    for case in entries:
        directory = destination / case['id']; directory.mkdir(parents=True, exist_ok=True)
        text = (root / 'docs/problems' / (case['id'] + '.md')).read_text(encoding='utf-8')
        canonical = base + '/problems/' + case['id'] + '/'
        related = f'<p><a href="index.md">Markdown</a> | <a href="index.json">JSON with evidence</a> | <a href="{base}/skills/{case["skill_id"]}/">Recipe contract</a></p>'
        (directory / 'index.html').write_text(page(case['title'], text, canonical, related), encoding='utf-8')
        (directory / 'index.md').write_text(text, encoding='utf-8')
        (directory / 'index.json').write_text(json.dumps({'hub_commit': commit, 'case': case, 'evidence': reports[case['id']], 'observed_at': receipt['observed_at'], 'maintainer_authored': True}, indent=2) + '\n', encoding='utf-8')
        links.append(canonical)
    index = (root / 'docs/problems.md').read_text(encoding='utf-8')
    listing = '<ul>' + ''.join(f'<li><a href="{c["id"]}/">{html.escape(c["title"])}</a></li>' for c in entries) + '</ul>'
    (destination / 'index.html').write_text(page('Robotics problem reproductions', 'Ten authored CPU input/contract checks. Not autonomous agent discovery or hardware verification.', base + '/problems/', listing), encoding='utf-8')
    (destination / 'index.md').write_text(index, encoding='utf-8')
    (destination / 'index.json').write_text(json.dumps({'hub_commit': commit, 'cases': [{'id': c['id'], 'title': c['title'], 'url': base + '/problems/' + c['id'] + '/index.json'} for c in entries]}, indent=2) + '\n')
    return [base + '/problems/'] + links
