"""Inert self-contained HTML. Raw native reports remain separate attachments."""
import html
import json
from urllib.parse import urlsplit


def safe_url(value):
    if not isinstance(value, str) or any(ord(c) < 33 for c in value) or '\\' in value:
        return None
    try:
        url = urlsplit(value)
        if url.scheme == 'https' and url.hostname and not url.username and not url.password:
            return value
        if not url.scheme and not url.netloc and value.startswith('#'):
            return value
    except ValueError:
        pass
    return None


def e(value):
    return html.escape(str(value), quote=True)


def detail(value):
    return '<pre>' + e(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)) + '</pre>'


def disclosure(title, value):
    return '<details><summary>' + e(title) + '</summary>' + detail(value) + '</details>'


def finding_rows(findings):
    return ''.join('<tr><th scope="row">' + e(f['id']) + '<br>' + e(f['dimension']) +
                   '</th><td>' + e(f['state']) + '</td><td>' + e(f['reason']) +
                   '<br><small>Owner: ' + e(f['owner']) + '. Next: ' + e(f['next_action']) +
                   '</small><details><summary>Evidence and consequence</summary>' + detail(f) + '</details></td></tr>'
                   for f in findings)


def finding_table(findings):
    return ('<div class="scroll"><table><thead><tr><th>Dimension</th><th>State</th><th>Decision and next action</th></tr></thead><tbody>' +
            finding_rows(findings) + '</tbody></table></div>')


def render(audit):
    identity = audit['input'].get('identity', {})
    refs = []
    for r in audit['input'].get('references', []):
        url = safe_url(r.get('url'))
        label = e(r['id']) + ': ' + e(r['source'])
        if url:
            label = '<a rel="noreferrer noopener" href="' + e(url) + '">' + label + '</a>'
        elif r.get('url'):
            label += ' (unsafe link omitted)'
        refs.append('<li>' + label + disclosure('Date, identity and availability', r) + '</li>')
    recommendations = ''.join('<article><h3>' + e(r['id']) + ': ' + e(r['action'] or 'needs evidence') +
                              '</h3><p>' + e(r.get('rationale') or r['unresolved_claim']) +
                              '</p><p>Retained: ' + e(r['protection_retained']) +
                              '. Lost: ' + e(r['protection_lost']) + '</p>' + disclosure('Protection, cost and evidence', r) + '</article>'
                              for r in audit['analysis']['recommendations'])
    scope = audit['scope']
    organization = scope.get('kind') == 'organization'
    if organization:
        findings_section = '<h2>Repository findings</h2>'
        for repository in scope.get('results', []):
            findings_section += '<h3>' + e(repository['repository']) + '</h3>'
            if 'analysis' in repository:
                findings_section += finding_table(repository['analysis']['findings'])
                findings_section += disclosure('Repository timing, ranked recommendations, protection and limitations', repository['analysis'])
            else:
                findings_section += '<p>Test-value assessment incomplete: ' + e(repository['reason']) + '</p>'
    else:
        findings_section = '<h2>Twelve findings</h2>' + finding_table(audit['analysis']['findings'])
    limits = scope.get('limits', {})
    scope_summary = ('<p>' + e(scope.get('kind', 'unknown')) + ' scope. Classification: ' +
                     e(scope.get('classification', scope.get('visibility', 'unknown'))) +
                     '. Audit ceiling: ' + e(limits.get('seconds', 'unknown')) + ' seconds, ' +
                     e(limits.get('repos', 'unknown')) + ' repositories.</p>')
    if organization:
        scope_summary += ('<p>Inventory denominator: ' + e(scope['denominator_state']) +
                          '. Fleet-wide coverage established: ' + e(scope['fleet_wide']) + '.</p>')
    limitations = '<ul>' + ''.join('<li>' + e(v) + '</li>' for v in audit['analysis']['limitations']) + '</ul>'
    timing = audit['analysis']['timing']
    p95 = timing.get('available_p95')
    timing_summary = ('<p>T_available &le; 600s. Capacity-adjusted p95: ' +
                      (e(p95['seconds']) + 's, rank ' + e(p95['rank']) + ' of ' + e(p95['n']) +
                       (' (small sample).' if p95['small_sample_warning'] else '.') if p95 else 'unknown.') +
                      ' Modelled breaches: ' + e(len(timing['breaches'])) +
                      '. Observed elapsed breaches: ' + e(len(timing['observed_breaches'])) +
                      '. Estimates and observed latency stay separate.</p>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'">
<title>tests-omg advisory report</title><style>
:root{color-scheme:light dark;--paper:#eef0e8;--ink:#1f2a24;--rule:#c6cdbf;--link:#2f6b4f}
@media(prefers-color-scheme:dark){:root{--paper:#15201b;--ink:#e6eae0;--rule:#2f3e37;--link:#7bc49a}}
*{box-sizing:border-box}body{background:var(--paper);color:var(--ink);font:17px/1.55 system-ui,sans-serif;margin:auto;padding:1.2rem;max-width:76rem}
h1,h2,h3{font-family:Georgia,serif;line-height:1.2}h2{border-top:1px solid var(--rule);padding-top:1rem}a{color:var(--link)}
table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:.7rem;border-bottom:1px solid var(--rule)}th{min-width:9rem}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem}small{font-size:.9rem}article{border-bottom:1px solid var(--rule)}
.scroll{overflow:auto}p,li,td{overflow-wrap:anywhere}summary{cursor:pointer}details{margin:.5rem 0}
@media(max-width:40rem){body{padding:.8rem;font-size:16px}th{min-width:6rem}td,th{padding:.4rem}table{font-size:.9rem}}
</style><main><h1>Test protection and cost</h1><p>Advisory evidence. No certification or merge authorization.</p>''' + (
        '<p>Repository: ' + e(audit['repository']) + '<br>Head: ' + e(audit['snapshot']['head_sha']) +
        '<br>Actual tested SHA: ' + e(identity.get('tested_sha') or 'unknown') +
        '<br>Comparison base: ' + e(identity.get('comparison_base') or 'unknown') +
        '<br>Run: ' + e(audit['run_id']) + ' · Generated: ' + e(audit['generated_at']) +
        '<br>Audit completion: ' + e(audit['completion']) + ' · Declared validation: ' +
        e(audit['analysis']['validation_verdict']) + '</p>' +
        disclosure('Run, tested ref, environment and tool identity', identity) + '<h2>Scope and limits</h2>' +
        scope_summary + limitations + disclosure('Scope, inventory and audit counters', audit['scope']) +
        '<h2>Residual risks</h2>' + (detail(audit['risks']) if audit.get('risks') else
                                   '<p>Residual exposure remains unverified; see the findings and unexamined scope.</p>') +
        findings_section +
        ('' if organization else '<h2>Ranked recommendations</h2>' + (recommendations or '<p>No supported action yet. Inspect test value before deciding what to retain or remove.</p>')) +
        ('' if organization else '<h2>Ten-minute validation path</h2>' + timing_summary + disclosure('Dependency paths, phases, capacity and every breach', timing) +
        '<h2>Attempts and completeness</h2><p>' + e(audit['analysis']['count_units']) + '</p>' +
        '<p>Collected ' + e(len(audit['analysis']['collected_checks'])) + ', completed ' + e(len(audit['analysis']['completed_checks'])) +
        ', missing ' + e(len(audit['analysis']['missing_checks'])) + ' declared check-shards.</p>' +
        disclosure('Counts, missing checks and all attempts', {k: audit['analysis'][k] for k in ('counts', 'expected_checks', 'collected_checks', 'completed_checks', 'missing_checks', 'intermittent', 'per_test_attempts')}) +
        disclosure('Original check attempts and diagnostics, including ordinary failures', audit['input'].get('checks', [])) +
        '<h2>Coverage, history and sampling</h2>' + disclosure('Denominators, history access and selected samples', {k: audit['analysis'][k] for k in ('coverage', 'history', 'sample')})) +
        '<h2>Predecessor comparison</h2>' + disclosure('Compatibility and prior observations', audit.get('comparison', {'state': 'unknown'})) +
        '<h2>Evidence and reproduction</h2><ul>' + ''.join(refs) + '</ul>' +
        disclosure('Exact reproduction commands and execution limits', audit['input'].get('execution', [])) +
        '<h2>Snapshot and provenance</h2>' + disclosure('Source inventory and binding', audit['snapshot']) +
        '<p>Generator ' + e(audit['generator_version']) + ', benchmark ' + e(audit['benchmark_version']) +
        '. Input digest: ' + e(audit['input_sha256']) +
        '. Local private report. Authenticated download, PR summary and hosted browsing require separate authorization and remain unverified.</p></main></html>')
