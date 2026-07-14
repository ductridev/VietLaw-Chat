"""Static, dependency-free HTML report."""

from __future__ import annotations

import html
from pathlib import Path

from ..schemas.result import CheckStatus, RunResult

CSS = """
:root { color-scheme: light dark; --bg:#fff; --fg:#1b1b1f; --muted:#6b6b76; --line:#e3e3e8;
        --pass:#0a7d3c; --fail:#c02626; --warn:#b06a00; --card:#f7f7f9; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16161a; --fg:#e8e8ec; --muted:#9a9aa5; --line:#2c2c33; --card:#1e1e23; }
}
* { box-sizing: border-box; }
body { margin:0; padding:2rem 1.25rem; background:var(--bg); color:var(--fg);
       font:15px/1.55 ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif; }
main { max-width: 1080px; margin: 0 auto; }
h1 { font-size:1.55rem; margin:0 0 .35rem; }
h2 { font-size:1.15rem; margin:2.2rem 0 .75rem; padding-bottom:.35rem; border-bottom:1px solid var(--line); }
.sub { color:var(--muted); margin:0 0 1.5rem; font-size:.9rem; }
.verdict { display:inline-block; padding:.3rem .8rem; border-radius:999px; font-weight:650; letter-spacing:.02em; }
.verdict.pass { background:rgba(10,125,60,.14); color:var(--pass); }
.verdict.fail { background:rgba(192,38,38,.14); color:var(--fail); }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.75rem; margin:1.25rem 0; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:.85rem 1rem; }
.tile .k { color:var(--muted); font-size:.75rem; text-transform:uppercase; letter-spacing:.05em; }
.tile .v { font-size:1.5rem; font-weight:640; margin-top:.15rem; font-variant-numeric:tabular-nums; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:.88rem; }
th,td { text-align:left; padding:.5rem .65rem; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; font-size:.76rem; text-transform:uppercase; letter-spacing:.04em; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.pass { color:var(--pass); font-weight:600; }
.fail { color:var(--fail); font-weight:600; }
.info { color:var(--muted); }
.blocker { background:rgba(192,38,38,.09); }
code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.86em; }
details { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:.6rem .85rem; margin:.4rem 0; }
summary { cursor:pointer; font-weight:600; }
ul.checks { margin:.5rem 0 0; padding-left:1.1rem; color:var(--muted); font-size:.85rem; }
.note { background:rgba(176,106,0,.1); border-left:3px solid var(--warn); padding:.6rem .8rem; border-radius:4px; margin:.5rem 0; }
"""


def render(run: RunResult) -> str:
    e = html.escape
    ok = run.ok
    verdict_class = "pass" if ok else "fail"
    parts: list[str] = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>VietLaw-Chat eval — {e(run.suite)}</title>",
        f"<style>{CSS}</style></head><body><main>",
        f"<h1>VietLaw-Chat evaluation — <code>{e(run.suite)}</code></h1>",
        f"<p class='sub'>{e(run.target)} · run <code>{e(run.run_id)}</code> · seed {run.seed} · "
        f"git {e(run.git_commit or 'n/a')} · {e(run.started_at)}</p>",
        f"<span class='verdict {verdict_class}'>{'PASS' if ok else 'FAIL'}</span>",
        "<div class='grid'>",
        f"<div class='tile'><div class='k'>Cases</div><div class='v'>{run.total}</div></div>",
        f"<div class='tile'><div class='k'>Passed</div><div class='v pass'>{run.passed}</div></div>",
        f"<div class='tile'><div class='k'>Failed</div><div class='v {'fail' if run.failed else ''}'>{run.failed}</div></div>",
        f"<div class='tile'><div class='k'>Pass rate</div><div class='v'>{run.pass_rate:.0%}</div></div>",
        f"<div class='tile'><div class='k'>Blockers</div>"
        f"<div class='v {'fail' if run.blocker_failures else ''}'>{len(run.blocker_failures)}</div></div>",
    ]
    if run.latency:
        parts.append(
            f"<div class='tile'><div class='k'>p95 latency</div>"
            f"<div class='v'>{run.latency.get('p95_ms', 0):.0f}<span class='info' style='font-size:.9rem'>ms</span></div></div>"
        )
    parts.append("</div>")

    if run.blocker_failures:
        parts.append(
            "<div class='note'>Blocker failures are present. A blocker fails the suite regardless "
            "of the aggregate pass rate.</div>"
        )
    for note in run.notes:
        parts.append(f"<div class='note'>{e(note)}</div>")

    parts.append("<h2>Metrics vs thresholds</h2><div class='scroll'><table>")
    parts.append("<tr><th>Metric</th><th>Value</th><th>Threshold</th><th>Result</th><th>Sample</th></tr>")
    for metric in run.metrics:
        cls = "pass" if metric.passed else "fail" if metric.passed is False else "info"
        label = "PASS" if metric.passed else "FAIL" if metric.passed is False else "info"
        threshold = f"{metric.comparator} {metric.threshold}" if metric.threshold is not None else "—"
        parts.append(
            f"<tr><td><code>{e(metric.name)}</code></td><td class='num'>{metric.value:.3f}</td>"
            f"<td>{e(threshold)}</td><td class='{cls}'>{label}</td>"
            f"<td class='num'>{metric.numerator}/{metric.denominator}</td></tr>"
        )
    parts.append("</table></div>")

    failures = [c for c in run.cases if c.status != CheckStatus.PASS]
    parts.append(f"<h2>Failures ({len(failures)})</h2>")
    if not failures:
        parts.append("<p class='info'>No case failed.</p>")
    for case in sorted(failures, key=lambda c: (not c.blocker_failed, c.case_id)):
        flag = " · <span class='fail'>BLOCKER</span>" if case.blocker_failed else ""
        parts.append(
            f"<details{' class=blocker' if case.blocker_failed else ''}>"
            f"<summary><code>{e(case.case_id)}</code>{flag} — {e(case.title)}</summary>"
            f"<ul class='checks'>"
            + "".join(
                f"<li><code>{e(c.name)}</code> [{e(c.oracle)}]: {e(c.message)}</li>" for c in case.failed_checks
            )
            + "</ul></details>"
        )

    parts.append("<h2>Cases by suite</h2><div class='scroll'><table>")
    parts.append("<tr><th>Suite</th><th>Cases</th><th>Passed</th><th>Failed</th></tr>")
    by_suite: dict[str, list] = {}
    for case in run.cases:
        by_suite.setdefault(case.suite, []).append(case)
    for suite in sorted(by_suite):
        cases = by_suite[suite]
        passed = sum(1 for c in cases if c.status == CheckStatus.PASS)
        parts.append(
            f"<tr><td>{e(suite)}</td><td class='num'>{len(cases)}</td>"
            f"<td class='num pass'>{passed}</td>"
            f"<td class='num {'fail' if len(cases) - passed else ''}'>{len(cases) - passed}</td></tr>"
        )
    parts.append("</table></div></main></body></html>")
    return "".join(parts)


def write(run: RunResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.html").write_text(render(run), encoding="utf-8")
