"""A dependency-free local web UI (Python standard library only).

    python -m careem_ai_reviewer serve --mock
    -> http://127.0.0.1:8000

The page is static; all state lives in the browser and every run is a POST to
`/api/run`, which returns both the structured report and the rendered Markdown so the
UI can show a readable view, the raw Markdown, and the JSON side by side.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .analyzers import analyze_source
from .config import Settings
from .llm import LLMError
from .pipeline import run_pair, run_review, run_snippet
from .reporters import render_pair_markdown, render_review_markdown, render_snippet_markdown

MAX_BODY_BYTES = 2_000_000


def _samples_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "samples"


def load_samples() -> dict:
    directory = _samples_dir()
    if not directory.is_dir():
        return {}
    return {
        path.name: path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix in {".go", ".py", ".js", ".ts"}
    }


def _run(payload: dict, settings: Settings) -> dict:
    if not isinstance(payload, dict):
        raise LLMError("Request body must be a JSON object.")

    mode = payload.get("mode", "review")
    if mode not in ("review", "pair", "snippet"):
        raise LLMError(f"Unknown mode {mode!r}; expected review, pair or snippet.")

    code = payload.get("code", "")
    if not isinstance(code, str):
        raise LLMError("`code` must be a JSON string.")
    filename = payload.get("filename") or "input.go"
    if not isinstance(filename, str):
        raise LLMError("`filename` must be a JSON string.")
    if not code.strip():
        raise LLMError("Paste some code first.")

    run_settings = Settings(
        model=settings.model,
        provider=settings.provider,
        max_tokens=settings.max_tokens,
        effort=payload.get("effort") or settings.effort,
        mock=bool(payload.get("mock", settings.mock)),
    )

    if mode == "snippet":
        result, analysis = run_snippet(code, run_settings, filename)
        return {
            "mode": mode,
            "report": result.data,
            "markdown": render_snippet_markdown(result, [analysis]),
            "provider": result.provider,
            "model": result.model,
            "elapsed_s": result.elapsed_s,
            "notes": result.notes,
            "static_findings": [f.to_dict() for f in analysis.findings],
            "gate": None,
        }

    analysis = analyze_source(filename, code, run_settings.thresholds)

    if mode == "pair":
        result = run_pair([analysis], run_settings, task=payload.get("task", ""))
        markdown = render_pair_markdown(result, [analysis])
        gate = None
    else:
        result, decision = run_review(
            [analysis], run_settings, context=payload.get("context", "")
        )
        markdown = render_review_markdown(result, [analysis], decision)
        gate = {"passed": decision.passed, "reasons": decision.reasons,
                "counts": decision.counts}

    return {
        "mode": mode,
        "report": result.data,
        "markdown": markdown,
        "provider": result.provider,
        "model": result.model,
        "elapsed_s": result.elapsed_s,
        "notes": result.notes,
        "static_findings": [f.to_dict() for f in analysis.findings],
        "gate": gate,
    }


class _Handler(BaseHTTPRequestHandler):
    settings = Settings(mock=True)
    server_version = "careem-ai-reviewer"

    def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
        print(f"  {self.address_string()} {fmt % args}")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802 - stdlib signature
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/samples":
            self._send_json(200, {"samples": load_samples()})
        elif self.path == "/api/health":
            self._send_json(200, {"ok": True, "has_api_key": Settings.has_api_key()})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802 - stdlib signature
        if self.path != "/api/run":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                raise LLMError("Request body missing or too large.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            self._send_json(200, _run(payload, self.settings))
        except LLMError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - surface anything to the browser
            self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})


def serve(host: str = "127.0.0.1", port: int = 8000, settings: Settings | None = None) -> None:
    _Handler.settings = settings or Settings(mock=True)
    mode = "MOCK (offline)" if _Handler.settings.mock else f"live ({_Handler.settings.model})"
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"careem-ai-reviewer web UI: http://{host}:{port}   [default mode: {mode}]")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Careem AI Code Review Toolkit</title>
<style>
  :root {
    --bg: #0f1412; --panel: #161d1a; --line: #24302b; --ink: #e8f0ec;
    --muted: #8ba396; --accent: #3fd07a; --accent-dim: #1f6b41;
    --blocker: #ff6b6b; --major: #ffa94d; --minor: #74c0fc; --nit: #8ba396;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 14px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
  header { padding: 18px 24px; border-bottom: 1px solid var(--line);
           display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
  header h1 { font-size: 17px; margin: 0; letter-spacing: .2px; }
  header .sub { color: var(--muted); font-size: 13px; }
  main { display: grid; grid-template-columns: minmax(340px, 42%) 1fr; gap: 0;
         height: calc(100vh - 61px); }
  .pane { overflow: auto; padding: 18px 22px; }
  .pane + .pane { border-left: 1px solid var(--line); }
  label { display: block; font-size: 12px; color: var(--muted);
          text-transform: uppercase; letter-spacing: .6px; margin: 14px 0 6px; }
  textarea, input, select {
    width: 100%; background: var(--panel); color: var(--ink);
    border: 1px solid var(--line); border-radius: 8px; padding: 9px 11px;
    font-family: ui-monospace, "Cascadia Code", Consolas, monospace; font-size: 13px;
  }
  textarea { min-height: 320px; resize: vertical; line-height: 1.5; }
  .row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .row > * { flex: 1; }
  .tabs { display: flex; gap: 6px; margin-bottom: 4px; }
  .tab { flex: 1; text-align: center; padding: 9px 8px; border-radius: 8px;
         border: 1px solid var(--line); background: var(--panel); color: var(--muted);
         cursor: pointer; font-size: 13px; user-select: none; }
  .tab.on { background: var(--accent-dim); color: #fff; border-color: var(--accent); }
  button.go { flex: none; width: 100%; margin-top: 16px; padding: 12px;
              background: var(--accent); color: #06130c; border: 0; border-radius: 8px;
              font-weight: 700; font-size: 14px; cursor: pointer; }
  button.go:disabled { opacity: .55; cursor: progress; }
  .chip { display: inline-block; padding: 2px 9px; border-radius: 999px;
          font-size: 11px; font-weight: 700; letter-spacing: .5px; }
  .chip.blocker { background: rgba(255,107,107,.16); color: var(--blocker); }
  .chip.major   { background: rgba(255,169,77,.16);  color: var(--major); }
  .chip.minor   { background: rgba(116,192,252,.16); color: var(--minor); }
  .chip.nit     { background: rgba(139,163,150,.16); color: var(--nit); }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
          padding: 14px 16px; margin-bottom: 12px; }
  .card h3 { margin: 0 0 6px; font-size: 14px; }
  .card .loc { color: var(--muted); font-size: 12px;
               font-family: ui-monospace, Consolas, monospace; }
  .card .fix { margin-top: 8px; padding-left: 10px; border-left: 2px solid var(--accent-dim); }
  .verdict { display: inline-block; padding: 6px 14px; border-radius: 8px;
             font-weight: 700; letter-spacing: .4px; }
  .verdict.approve { background: rgba(63,208,122,.15); color: var(--accent); }
  .verdict.comment { background: rgba(116,192,252,.15); color: var(--minor); }
  .verdict.request_changes { background: rgba(255,107,107,.15); color: var(--blocker); }
  .scores { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
  .score { background: var(--panel); border: 1px solid var(--line);
           border-left: 3px solid var(--accent); border-radius: 8px; padding: 8px 12px; }
  .score b { display: block; font-size: 18px; }
  .score span { color: var(--muted); font-size: 11px; text-transform: uppercase; }
  pre { background: #0b100e; border: 1px solid var(--line); border-radius: 8px;
        padding: 12px; overflow: auto; font-size: 12.5px; white-space: pre-wrap;
        word-break: break-word; }
  .meta { color: var(--muted); font-size: 12px; margin-bottom: 10px;
          font-family: ui-monospace, Consolas, monospace; }
  .note { background: rgba(255,169,77,.08); border: 1px solid rgba(255,169,77,.3);
          color: #ffd8a8; border-radius: 8px; padding: 9px 12px; margin-bottom: 12px;
          font-size: 12.5px; }
  .err { background: rgba(255,107,107,.1); border: 1px solid rgba(255,107,107,.35);
         color: #ffc9c9; border-radius: 8px; padding: 12px; white-space: pre-wrap; }
  ul { margin: 6px 0 0; padding-left: 20px; }
  .muted { color: var(--muted); }
  .hide { display: none; }
</style>
</head>
<body>
<header>
  <h1>Careem AI Code Review Toolkit</h1>
  <span class="sub">Smart Code Reviewer &middot; AI Pair Engineer &middot; Code Review Assistant</span>
</header>

<main>
  <section class="pane">
    <div class="tabs">
      <div class="tab on" data-mode="review">1. Review</div>
      <div class="tab" data-mode="pair">2. Pair</div>
      <div class="tab" data-mode="snippet">3. Snippet 3+1</div>
    </div>

    <label>Sample</label>
    <select id="sample"><option value="">-- load a sample --</option></select>

    <label>Code</label>
    <textarea id="code" spellcheck="false" placeholder="Paste code here..."></textarea>

    <div class="row">
      <div>
        <label>Filename (language detection)</label>
        <input id="filename" value="eta_service.go">
      </div>
      <div>
        <label>Effort</label>
        <select id="effort">
          <option>low</option><option selected>medium</option>
          <option>high</option><option>xhigh</option><option>max</option>
        </select>
      </div>
    </div>

    <label id="extraLabel">Context: what is this change meant to do?</label>
    <input id="extra" placeholder="optional">

    <label><input type="checkbox" id="mock" checked style="width:auto"> Offline mock mode (no API key)</label>

    <button class="go" id="run">Run</button>
  </section>

  <section class="pane">
    <div class="tabs">
      <div class="tab on" data-view="report">Report</div>
      <div class="tab" data-view="markdown">Markdown</div>
      <div class="tab" data-view="json">JSON</div>
    </div>
    <div id="report"></div>
    <pre id="markdown" class="hide"></pre>
    <pre id="json" class="hide"></pre>
  </section>
</main>

<script>
const $ = (id) => document.getElementById(id);
let mode = "review";
let last = null;

document.querySelectorAll('.tab[data-mode]').forEach(tab => {
  tab.onclick = () => {
    document.querySelectorAll('.tab[data-mode]').forEach(t => t.classList.remove('on'));
    tab.classList.add('on');
    mode = tab.dataset.mode;
    $('extraLabel').textContent = mode === 'pair'
      ? 'Task: what are you building right now?'
      : (mode === 'snippet' ? 'Not used for snippet mode' : 'Context: what is this change meant to do?');
    $('extra').disabled = mode === 'snippet';
  };
});

document.querySelectorAll('.tab[data-view]').forEach(tab => {
  tab.onclick = () => {
    document.querySelectorAll('.tab[data-view]').forEach(t => t.classList.remove('on'));
    tab.classList.add('on');
    ['report','markdown','json'].forEach(v =>
      $(v).classList.toggle('hide', v !== tab.dataset.view));
  };
});

fetch('/api/samples').then(r => r.json()).then(d => {
  const sel = $('sample');
  Object.keys(d.samples).forEach(name => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name; sel.appendChild(opt);
  });
  sel.onchange = () => {
    if (!sel.value) return;
    $('code').value = d.samples[sel.value];
    $('filename').value = sel.value;
  };
  const first = Object.keys(d.samples)[0];
  if (first) { $('code').value = d.samples[first]; $('filename').value = first; sel.value = first; }
});

$('run').onclick = async () => {
  const btn = $('run');
  btn.disabled = true; btn.textContent = 'Running...';
  $('report').innerHTML = '<p class="muted">Working...</p>';
  try {
    const body = {
      mode, code: $('code').value, filename: $('filename').value,
      effort: $('effort').value, mock: $('mock').checked,
      context: mode === 'review' ? $('extra').value : '',
      task: mode === 'pair' ? $('extra').value : ''
    };
    const res = await fetch('/api/run', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    last = data;
    $('markdown').textContent = data.markdown;
    $('json').textContent = JSON.stringify(data.report, null, 2);
    render(data);
  } catch (e) {
    $('report').innerHTML = '<div class="err">' + esc(e.message) + '</div>';
  } finally {
    btn.disabled = false; btn.textContent = 'Run';
  }
};

const esc = (s) => String(s ?? '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function meta(d) {
  let html = '<div class="meta">provider: ' + esc(d.provider) + ' &middot; model: '
    + esc(d.model) + ' &middot; ' + d.elapsed_s + 's</div>';
  (d.notes || []).forEach(n => html += '<div class="note">' + esc(n) + '</div>');
  return html;
}

function list(items) {
  if (!items || !items.length) return '<p class="muted">None.</p>';
  return '<ul>' + items.map(i => '<li>' + esc(i) + '</li>').join('') + '</ul>';
}

function render(d) {
  const r = d.report;
  let html = meta(d);

  if (d.mode === 'review') {
    html += '<p><span class="verdict ' + esc(r.verdict) + '">'
         + esc((r.verdict || '').replace('_', ' ').toUpperCase()) + '</span></p>';
    html += '<p>' + esc(r.summary) + '</p>';
    html += '<div class="scores">' + Object.entries(r.scores || {}).map(([k, v]) =>
      '<div class="score"><b>' + v + ' / 5</b><span>' + esc(k.replace(/_/g, ' ')) + '</span></div>'
    ).join('') + '</div>';
    if (d.gate) {
      html += '<div class="' + (d.gate.passed ? 'note' : 'err') + '">CI gate: '
        + (d.gate.passed ? 'PASS' : 'FAIL - ' + esc(d.gate.reasons.join(' '))) + '</div>';
    }
    html += '<h2>Findings (' + (r.findings || []).length + ')</h2>';
    (r.findings || []).forEach(f => {
      html += '<div class="card"><h3><span class="chip ' + esc(f.severity) + '">'
        + esc(f.severity.toUpperCase()) + '</span> ' + esc(f.rule) + '</h3>'
        + '<div class="loc">' + esc(f.file) + ':' + f.line
        + (f.symbol ? ' &middot; ' + esc(f.symbol) : '') + '</div>'
        + '<p>' + esc(f.message) + '</p>'
        + '<div class="fix"><b>Fix:</b> ' + esc(f.suggestion) + '</div></div>';
    });
    html += '<h2>What the author got right</h2>' + list(r.positive_notes);
    html += '<h2>Still needs a human</h2>' + list(r.review_checklist);
  }

  if (d.mode === 'pair') {
    html += '<h2>1. Design review</h2><p>' + esc((r.design_review || {}).summary) + '</p>';
    ((r.design_review || {}).flaws || []).forEach(f => {
      html += '<div class="card"><h3><span class="chip ' + esc(f.severity) + '">'
        + esc((f.severity || '').toUpperCase()) + '</span> ' + esc(f.title) + '</h3>'
        + '<div class="loc">' + esc(f.where) + '</div><p>' + esc(f.why_it_matters) + '</p>'
        + '<div class="fix"><b>Change:</b> ' + esc(f.recommended_change) + '</div></div>';
    });
    html += '<h2>2. Tests I would write</h2>';
    (r.proposed_tests || []).forEach(t => {
      html += '<div class="card"><h3>' + esc(t.name) + ' <span class="loc">('
        + esc(t.kind) + ')</span></h3><p>' + esc(t.catches) + '</p><pre>'
        + esc(t.code) + '</pre></div>';
    });
    html += '<h2>3. Refactors</h2>';
    (r.refactors || []).forEach(x => {
      html += '<div class="card"><h3>' + esc(x.title) + ' <span class="loc">risk: '
        + esc(x.risk) + '</span></h3><p>' + esc(x.rationale) + '</p>'
        + (x.unified_diff ? '<pre>' + esc(x.unified_diff) + '</pre>' : '') + '</div>';
    });
    html += '<h2>Keep doing</h2>' + list(r.keep_doing);
    html += '<h2>Open questions</h2>' + list(r.open_questions);
  }

  if (d.mode === 'snippet') {
    html += '<p class="muted">language: ' + esc(r.language) + '</p>';
    html += '<h2>Three improvements</h2>';
    (r.improvements || []).forEach((i, n) => {
      html += '<div class="card"><h3>' + (n + 1) + '. ' + esc(i.title) + '</h3>'
        + '<p>' + esc(i.why) + '</p>'
        + '<div class="loc">before</div><pre>' + esc(i.before) + '</pre>'
        + '<div class="loc">after</div><pre>' + esc(i.after) + '</pre></div>';
    });
    html += '<h2>One positive note</h2><div class="card">' + esc(r.positive_note) + '</div>';
    html += '<p><b>Verdict:</b> ' + esc(r.verdict) + '</p>';
  }

  $('report').innerHTML = html;
}
</script>
</body>
</html>
"""
