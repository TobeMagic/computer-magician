from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.models.admin_session import AdminSession
from app.services.sessions import get_active_admin_session


router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin_web_session(
    request: Request,
    db: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> AdminSession:
    raw_token = request.cookies.get(settings.cookie_name)
    admin_session = get_active_admin_session(db, raw_token=raw_token, settings=settings)
    if admin_session is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Not authenticated",
            headers={"Location": _login_redirect_url(request)},
        )
    return admin_session


@router.get("/login", response_class=HTMLResponse)
def admin_login(next: str = "/admin") -> HTMLResponse:
    return HTMLResponse(_login_page(_safe_next_url(next)))


@router.get("", response_class=HTMLResponse)
def admin_home(_: AdminSession = Depends(require_admin_web_session)) -> HTMLResponse:
    return HTMLResponse(_page_shell("AImagician Control Ledger", _home_body()))


@router.get("/spa", response_class=HTMLResponse)
def admin_spa(_: AdminSession = Depends(require_admin_web_session)) -> HTMLResponse:
    return HTMLResponse(_page_shell("AImagician SPA Console", _spa_body()))


@router.get("/articles/{article_id}", response_class=HTMLResponse)
def admin_article_detail(article_id: str, _: AdminSession = Depends(require_admin_web_session)) -> HTMLResponse:
    return HTMLResponse(_page_shell("Article Ledger", _article_body(article_id)))


@router.get("/series/{series_id}", response_class=HTMLResponse)
def admin_series_detail(series_id: str, _: AdminSession = Depends(require_admin_web_session)) -> HTMLResponse:
    return HTMLResponse(_page_shell("Series Ledger", _series_body(series_id)))


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def admin_run_detail(run_id: str, _: AdminSession = Depends(require_admin_web_session)) -> HTMLResponse:
    return HTMLResponse(_page_shell("Run Observatory", _run_body(run_id)))


@router.get("/prompts", response_class=HTMLResponse)
def admin_prompts(_: AdminSession = Depends(require_admin_web_session)) -> HTMLResponse:
    return HTMLResponse(_page_shell("PromptOps Ledger", _prompts_body()))


@router.get("/prompts/{prompt_key:path}", response_class=HTMLResponse)
def admin_prompt_detail(prompt_key: str, _: AdminSession = Depends(require_admin_web_session)) -> HTMLResponse:
    return HTMLResponse(_page_shell("Prompt Definition", _prompt_body(prompt_key)))


@router.get("/prompt-snapshots", response_class=HTMLResponse)
def admin_prompt_snapshots(_: AdminSession = Depends(require_admin_web_session)) -> HTMLResponse:
    return HTMLResponse(_page_shell("Prompt Snapshot Ledger", _prompt_snapshots_body()))


@router.get("/platforms", response_class=HTMLResponse)
def admin_platforms(_: AdminSession = Depends(require_admin_web_session)) -> HTMLResponse:
    return HTMLResponse(_page_shell("Platform Operations", _platforms_body()))


@router.get("/notion-import", response_class=HTMLResponse)
def admin_notion_import(_: AdminSession = Depends(require_admin_web_session)) -> HTMLResponse:
    return HTMLResponse(_page_shell("Notion Import Control", _notion_import_body()))


@router.get("/platforms/{platform:path}", response_class=HTMLResponse)
def admin_platform_detail(platform: str, _: AdminSession = Depends(require_admin_web_session)) -> HTMLResponse:
    return HTMLResponse(_page_shell("Platform Session Console", _platform_body(platform)))


def _login_redirect_url(request: Request) -> str:
    next_url = request.url.path
    if request.url.query:
        next_url = f"{next_url}?{request.url.query}"
    return f"/admin/login?next={quote(next_url, safe='')}"


def _safe_next_url(next_url: str) -> str:
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        return "/admin"
    return next_url


def _login_page(next_url: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AImagician Login</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <!-- Apple-style glass console -->
  <style>
    :root {{
      --ink: #0f172a;
      --muted: #64748b;
      --paper: #f8fbff;
      --line: rgba(15, 23, 42, 0.10);
      --blue: #2563eb;
      --accent: #60a5fa;
      --shadow: 0 30px 90px rgba(37, 99, 235, 0.14);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 16% 8%, rgba(96, 165, 250, 0.22), transparent 30rem),
        radial-gradient(circle at 82% 12%, rgba(14, 165, 233, 0.14), transparent 28rem),
        linear-gradient(135deg, #ffffff 0%, var(--paper) 48%, #eef6ff 100%);
      padding: 24px;
    }}
    .card {{
      width: min(460px, 100%);
      border: 1px solid var(--line);
      border-radius: 34px;
      background: rgba(255, 255, 255, 0.78);
      box-shadow: var(--shadow);
      backdrop-filter: blur(24px) saturate(1.3);
      padding: 34px;
    }}
    .eyebrow {{ color: var(--blue); letter-spacing: .18em; text-transform: uppercase; font-size: 12px; font-weight: 800; }}
    h1 {{ margin: 10px 0 8px; font-size: clamp(38px, 9vw, 58px); line-height: .96; letter-spacing: -.055em; }}
    p {{ color: var(--muted); margin: 0 0 22px; }}
    label {{ display: grid; gap: 8px; margin: 16px 0; color: var(--muted); }}
    input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 13px 14px;
      background: rgba(255,255,255,.84);
      color: var(--ink);
      font: inherit;
    }}
    button {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 13px 16px;
      background: linear-gradient(135deg, #0f172a, #2563eb);
      color: #ffffff;
      cursor: pointer;
      font: inherit;
      margin-top: 10px;
    }}
    #error {{ min-height: 22px; margin-top: 14px; color: #a33a2b; }}
  </style>
</head>
<body>
  <main class="card">
    <div class="eyebrow">AImagician private console</div>
    <h1>Admin Login</h1>
    <p>登录后进入后台面板。Session cookie 由后端设置，CSRF token 仅保存到当前浏览器会话。</p>
    <form id="loginForm">
      <label>账号<input id="email" name="email" autocomplete="username" value="aimagician" required></label>
      <label>密码<input id="password" name="password" type="password" autocomplete="current-password" required autofocus></label>
      <button type="submit">进入后台</button>
      <div id="error"></div>
    </form>
  </main>
  <script>
    const nextUrl = {next_url!r};
    const csrfStorageKey = 'aimagician.csrfToken';
    document.querySelector('#loginForm').addEventListener('submit', async (event) => {{
      event.preventDefault();
      const error = document.querySelector('#error');
      error.textContent = '';
      const response = await fetch('/api/auth/login', {{
        method: 'POST',
        headers: {{'content-type': 'application/json'}},
        body: JSON.stringify({{
          email: document.querySelector('#email').value.trim(),
          password: document.querySelector('#password').value
        }})
      }});
      if (!response.ok) {{
        error.textContent = response.status === 401 ? '账号或密码不正确。' : await response.text();
        return;
      }}
      const payload = await response.json();
      sessionStorage.setItem(csrfStorageKey, payload.csrf_token);
      window.location.assign(nextUrl);
    }});
  </script>
</body>
</html>"""


def _page_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <!-- Apple-style glass console -->
  <style>
    :root {{
      --ink: #0f172a;
      --muted: #64748b;
      --paper: #f8fbff;
      --panel: rgba(255, 255, 255, 0.78);
      --line: rgba(15, 23, 42, 0.10);
      --green: #2563eb;
      --blue: #2563eb;
      --gold: #0ea5e9;
      --shadow: 0 28px 80px rgba(37, 99, 235, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(96, 165, 250, 0.22), transparent 32rem),
        radial-gradient(circle at 82% 12%, rgba(14, 165, 233, 0.14), transparent 28rem),
        linear-gradient(135deg, #ffffff 0%, var(--paper) 48%, #eef6ff 100%);
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image: linear-gradient(rgba(37, 99, 235, 0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(37, 99, 235, 0.04) 1px, transparent 1px);
      background-size: 28px 28px;
      mask-image: linear-gradient(to bottom, black, transparent 78%);
    }}
    .wrap {{ width: min(1180px, calc(100vw - 32px)); margin: 0 auto; padding: 34px 0 56px; }}
    header {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 20px;
      align-items: end;
      margin-bottom: 26px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 22px;
    }}
    .eyebrow {{ color: var(--green); letter-spacing: .22em; text-transform: uppercase; font-size: 12px; font-weight: 700; }}
    h1 {{ margin: 8px 0 0; font-size: clamp(34px, 5vw, 68px); line-height: .96; letter-spacing: -.045em; }}
    .status-pill {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,.52);
      padding: 12px 16px;
      border-radius: 999px;
      color: var(--muted);
      box-shadow: 0 8px 26px rgba(23,33,28,.06);
    }}
    .grid {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 18px; }}
    .panel {{
      grid-column: span 6;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 28px;
      padding: 22px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(24px) saturate(1.25);
      animation: rise .55s ease both;
    }}
    .panel.wide {{ grid-column: span 12; }}
    .panel.third {{ grid-column: span 4; }}
    h2 {{ margin: 0 0 14px; font-size: 22px; letter-spacing: -.02em; }}
    .metric {{ font-size: 42px; line-height: 1; font-weight: 800; color: var(--green); }}
    .muted {{ color: var(--muted); }}
    .list {{ display: grid; gap: 10px; }}
    .toolbar {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 12px 0; }}
    .split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .item {{
      display: grid;
      gap: 5px;
      padding: 13px 0;
      border-top: 1px solid var(--line);
    }}
    .item:first-child {{ border-top: 0; }}
    .kicker {{ font-size: 12px; color: var(--gold); letter-spacing: .12em; text-transform: uppercase; font-weight: 700; }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background: #18211d;
      color: #edf4f0;
      padding: 18px;
      border-radius: 18px;
      overflow: auto;
    }}
    textarea, input, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
      background: rgba(255,255,255,.72);
      color: var(--ink);
      font: inherit;
    }}
    textarea {{
      min-height: 420px;
      font-family: "JetBrains Mono", "SFMono-Regular", ui-monospace, monospace;
      font-size: 14px;
      line-height: 1.6;
    }}
    button {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 10px 14px;
      background: linear-gradient(135deg, #0f172a, #2563eb);
      color: #ffffff;
      cursor: pointer;
      margin: 6px 6px 0 0;
    }}
    button.secondary {{ background: rgba(255,255,255,.62); color: var(--ink); }}
    @keyframes rise {{ from {{ opacity: 0; transform: translateY(14px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    @media (max-width: 760px) {{
      header {{ grid-template-columns: 1fr; }}
      .panel, .panel.third {{ grid-column: span 12; }}
      .split {{ grid-template-columns: 1fr; }}
      .wrap {{ width: min(100vw - 20px, 1180px); padding-top: 18px; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <header>
      <div>
        <div class="eyebrow">AImagician private operations console</div>
        <h1>{title}</h1>
      </div>
      <div class="status-pill">DB-first · Notion mirror · Script-safe</div>
    </header>
    {body}
  </main>
  <script>
    window.AIMAGICIAN_CSRF_STORAGE_KEY = 'aimagician.csrfToken';
    window.getAImagicianCsrfToken = async function() {{
      let token = window.sessionStorage.getItem(window.AIMAGICIAN_CSRF_STORAGE_KEY);
      if (token) return token;
      token = window.prompt('CSRF token missing. Paste csrf_token from /api/auth/login response once.');
      if (!token) throw new Error('missing csrf');
      window.sessionStorage.setItem(window.AIMAGICIAN_CSRF_STORAGE_KEY, token);
      return token;
    }};
  </script>
</body>
</html>"""


def _home_body() -> str:
    return """
<section class="grid">
  <article class="panel third"><h2>Articles</h2><div class="metric" id="articleCount">-</div><p class="muted">recent canonical records</p></article>
  <article class="panel third"><h2>Pending Queue</h2><div class="metric" id="entryCount">-</div><p class="muted">series entries awaiting work</p></article>
  <article class="panel third"><h2>Notion Backlog</h2><div class="metric" id="outboxCount">-</div><p class="muted">lazy mirror tasks</p></article>
  <article class="panel third"><h2>Published</h2><div class="metric" id="publishedCount">-</div><p class="muted">public publications</p></article>
  <article class="panel third"><h2>Queued Jobs</h2><div class="metric" id="queuedJobCount">-</div><p class="muted">worker backlog</p></article>
  <article class="panel third"><h2>Severe Events</h2><div class="metric" id="severeEventCount">-</div><p class="muted">warnings/errors/critical</p></article>
  <article class="panel"><h2>Recent Articles</h2><div id="articles" class="list"></div></article>
  <article class="panel"><h2>Series Queue</h2><div id="entries" class="list"></div></article>
  <article class="panel"><h2>Platform Coverage</h2><div id="coverage" class="list"></div></article>
  <article class="panel"><h2>Platform Health</h2><div id="platformHealth" class="list"></div><p><a href="/admin/platforms">Open Platform Operations</a></p></article>
  <article class="panel"><h2>PromptOps</h2><p class="muted">Inspect prompt definitions, draft versions, activation diffs, and rendered snapshots.</p><p><a href="/admin/prompts">Open PromptOps Ledger</a> · <a href="/admin/prompt-snapshots">Prompt Snapshots</a></p></article>
  <article class="panel"><h2>Notion Import</h2><p class="muted">Full historical import ledger, outbox drain, and Postgres source-of-truth cutover status.</p><p><a href="/admin/notion-import">Open Notion Import Control</a></p></article>
  <article class="panel"><h2>Full SPA</h2><p class="muted">Single-page Apple/Tailwind console for dashboard, articles, runs, platforms, PromptOps, and Notion import.</p><p><a href="/admin/spa">Open SPA Console</a></p></article>
  <article class="panel"><h2>Material Hub</h2><p class="muted">Reaction placeholders resolve through the local manifest.</p><p>assets/reaction-library</p></article>
  <article class="panel"><h2>Warnings</h2><div id="events" class="list"></div></article>
  <article class="panel"><h2>Active Runs</h2><div id="runs" class="list"></div></article>
  <article class="panel"><h2>Failed Jobs</h2><div id="jobs" class="list"></div></article>
  <article class="panel wide"><h2>Runtime Timeline</h2><div id="runtimeEvents" class="list"></div></article>
</section>
<script>
async function loadSummary() {
  const [response, analyticsResponse] = await Promise.all([
    fetch('/api/dashboard/summary'),
    fetch('/api/dashboard/analytics')
  ]);
  const data = await response.json();
  const analytics = await analyticsResponse.json();
  document.querySelector('#articleCount').textContent = data.recent_articles.length;
  document.querySelector('#entryCount').textContent = data.pending_series_entries.length;
  document.querySelector('#outboxCount').textContent = data.notion_outbox_backlog.reduce((sum, item) => sum + item.count, 0);
  document.querySelector('#publishedCount').textContent = analytics.published_public_count;
  document.querySelector('#queuedJobCount').textContent = analytics.queued_job_count;
  document.querySelector('#severeEventCount').textContent = analytics.severe_event_counts.reduce((sum, item) => sum + item.count, 0);
  renderList('#articles', data.recent_articles, item => `<div class="kicker">${item.status}</div><a href="/admin/articles/${item.id}">${item.confirmed_title || item.seed_title || item.id}</a><div class="muted">${item.summary || 'No summary yet'}</div>`);
  renderList('#entries', data.pending_series_entries, item => `<div class="kicker">${item.status} · ${item.outline_code || item.entry_key}</div><div>${item.final_title || item.draft_title || item.entry_key}</div><div class="muted">${item.topic_summary || 'No topic summary yet'}</div>`);
  renderList('#coverage', data.platform_coverage, item => `<div class="kicker">${item.platform}</div><div>${item.status}: ${item.count}</div>`);
  renderList('#platformHealth', data.platform_health, item => `<div class="kicker">${item.platform} · ${item.status}</div><div>${item.readiness}</div><div class="muted">${JSON.stringify(item.blockers_json || {})}</div>`);
  renderList('#events', data.recent_severe_events, item => `<div class="kicker">${item.level}</div><div>${item.event_type}</div><div class="muted">${item.message}</div>`);
  renderList('#runs', data.active_runs, item => `<div class="kicker">${item.status} · ${item.run_type}</div><a href="/admin/runs/${item.id}">${item.current_stage || item.id}</a><div class="muted">${item.next_action || 'No next action'}</div>`);
  renderList('#jobs', data.failed_jobs, item => `<div class="kicker">${item.status} · ${item.job_type}</div><div>${item.failure_code || 'failure'}</div><div class="muted">${item.failure_message || 'No message'}</div>`);
  renderList('#runtimeEvents', data.recent_runtime_events, item => `<div class="kicker">${item.level} · ${item.event_type}</div><div>${item.message}</div><div class="muted">${item.created_at}</div>`);
}
function renderList(selector, items, render) {
  document.querySelector(selector).innerHTML = items.length ? items.map(item => `<div class="item">${render(item)}</div>`).join('') : '<p class="muted">No records yet.</p>';
}
loadSummary();
</script>"""


def _spa_body() -> str:
    return """
<section class="grid">
  <article class="panel wide">
    <h2>Operations SPA</h2>
    <div class="toolbar">
      <button onclick="routeTo('dashboard')">Dashboard</button>
      <button onclick="routeTo('articles')">Articles</button>
      <button onclick="routeTo('runs')">Runs</button>
      <button onclick="routeTo('platforms')">Platforms</button>
      <button onclick="routeTo('prompts')">PromptOps</button>
      <button onclick="routeTo('logs')">Logs</button>
      <button onclick="routeTo('notion')">Notion Import</button>
    </div>
    <p class="muted">This is a single-page API-first shell. It does not use server-side page transitions after initial load.</p>
  </article>
  <article class="panel wide"><div id="spaRoot" class="list">Loading...</div></article>
</section>
<script>
const routes = {
  dashboard: async () => {
    const [summary, analytics] = await Promise.all([
      fetch('/api/dashboard/summary').then(r => r.json()),
      fetch('/api/dashboard/analytics').then(r => r.json())
    ]);
    return `<div class="split">
      ${metric('Articles', summary.recent_articles.length)}
      ${metric('Published', analytics.published_public_count)}
      ${metric('Queued Jobs', analytics.queued_job_count)}
      ${metric('Notion Outbox', summary.notion_outbox_backlog.reduce((sum, item) => sum + item.count, 0))}
    </div><h2>Recent Articles</h2>${cards(summary.recent_articles, item => `${escapeHtml(item.confirmed_title || item.seed_title || item.id)}<div class="muted">${escapeHtml(item.status)}</div>`)}`;
  },
  articles: async () => {
    const articles = await fetch('/api/articles?limit=30').then(r => r.json());
    return `<h2>Articles</h2>${cards(articles, item => `<a href="/admin/articles/${item.id}">${escapeHtml(item.confirmed_title || item.seed_title || item.id)}</a><div class="muted">${escapeHtml(item.status)} · ${escapeHtml(item.summary || '')}</div>`)}`;
  },
  runs: async () => {
    const summary = await fetch('/api/dashboard/summary').then(r => r.json());
    return `<h2>Active Runs</h2>${cards(summary.active_runs, item => `<a href="/admin/runs/${item.id}">${escapeHtml(item.current_stage || item.id)}</a><div class="muted">${escapeHtml(item.status)} · ${escapeHtml(item.next_action || '')}</div>`)}`;
  },
  platforms: async () => {
    const platforms = await fetch('/api/platforms').then(r => r.json());
    return `<h2>Platforms</h2>${cards(platforms, item => `<a href="/admin/platforms/${encodeURIComponent(item.platform)}">${escapeHtml(item.platform)}</a><div class="muted">${escapeHtml(item.status)} · ${escapeHtml(item.readiness)}</div>`)}`;
  },
  prompts: async () => {
    const prompts = await fetch('/api/prompts').then(r => r.json());
    return `<h2>PromptOps</h2><div class="toolbar"><button class="secondary" onclick="importSourcePromptsFromSpa()">import source-file prompts</button><a href="/admin/prompt-snapshots">Prompt snapshots</a></div><div id="spaPromptImportStatus" class="muted"></div>${cards(prompts, item => `<a href="/admin/prompts/${encodeURIComponent(item.prompt_key)}">${escapeHtml(item.prompt_key)}</a><div class="muted">${escapeHtml(item.domain)} · active=${item.is_active}</div>`)}`;
  },
  logs: async () => {
    const summary = await fetch('/api/dashboard/summary').then(r => r.json());
    return `<h2>Logs</h2><p class="muted">只读 runtime event stream，用于追踪每篇文章的 run、平台 URL、blocker、warning 和修复证据。</p>${cards(summary.recent_runtime_events || [], item => `<div class="kicker">${escapeHtml(item.level)} · ${escapeHtml(item.event_type)}</div><div>${escapeHtml(item.message)}</div><div class="muted">${escapeHtml(item.created_at)} · run=${escapeHtml(item.run_id || 'none')}</div>`)}`;
  },
  notion: async () => {
    const summary = await fetch('/api/notion-import/summary').then(r => r.json());
    return `<h2>Notion Import</h2><pre>${escapeHtml(JSON.stringify(summary.source_of_truth, null, 2))}</pre>${cards(summary.configured_databases || [], item => `${escapeHtml(item.key)}<div class="muted">${escapeHtml(item.role)} · ${item.configured ? 'configured' : 'missing'}</div>`)}`;
  }
};
function routeTo(name) {
  window.location.hash = name;
  renderRoute();
}
async function renderRoute() {
  const name = (window.location.hash || '#dashboard').slice(1);
  const root = document.querySelector('#spaRoot');
  root.innerHTML = '<p class="muted">Loading...</p>';
  try {
    root.innerHTML = await (routes[name] || routes.dashboard)();
  } catch (error) {
    root.innerHTML = `<pre>${escapeHtml(String(error))}</pre>`;
  }
}
function metric(label, value) {
  return `<div class="panel"><div class="kicker">${escapeHtml(label)}</div><div class="metric">${escapeHtml(String(value))}</div></div>`;
}
function cards(items, render) {
  return items && items.length ? items.map(item => `<div class="item">${render(item)}</div>`).join('') : '<p class="muted">No records yet.</p>';
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
async function importSourcePromptsFromSpa() {
  const csrf = await window.getAImagicianCsrfToken();
  const response = await fetch('/api/prompts/import-source-files', {
    method: 'POST',
    headers: {'content-type':'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify({})
  });
  const payload = response.ok ? await response.json() : {error: await response.text()};
  document.querySelector('#spaPromptImportStatus').innerHTML = `<pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
  if (response.ok) await routeTo('prompts');
}
window.addEventListener('hashchange', renderRoute);
renderRoute();
</script>"""


def _notion_import_body() -> str:
    return """
<section class="grid">
  <article class="panel wide"><h2>Source Of Truth</h2><pre id="sot">Loading...</pre><div class="toolbar"><button onclick="loadImport()">refresh</button><button onclick="createDryRun()">create dry-run import</button><button class="secondary" onclick="retryOutbox()">retry failed outbox</button><button class="secondary" onclick="drainOutbox()">drain pending outbox</button></div><div id="notionStatus" class="muted"></div></article>
  <article class="panel"><h2>Configured Databases</h2><div id="databases" class="list"></div></article>
  <article class="panel"><h2>Import Runs</h2><div id="runs" class="list"></div></article>
  <article class="panel wide"><h2>Import Items</h2><div id="items" class="list"></div></article>
</section>
<script>
async function loadImport() {
  const [summary, runs, items, outbox] = await Promise.all([
    fetch('/api/notion-import/summary').then(r => r.json()),
    fetch('/api/notion-import/runs?limit=20').then(r => r.json()),
    fetch('/api/notion-import/items?limit=30').then(r => r.json()),
    fetch('/api/notion-sync/outbox/summary').then(r => r.json())
  ]);
  document.querySelector('#sot').textContent = JSON.stringify({source_of_truth: summary.source_of_truth, outbox}, null, 2);
  renderList('#databases', summary.configured_databases || [], item => `<div class="kicker">${item.role} · ${item.configured ? 'configured' : 'missing'}</div><div>${item.key}</div><div class="muted">${item.env_key}</div>`);
  renderList('#runs', runs, item => `<div class="kicker">${item.status} · ${item.import_scope}</div><div>${item.id}</div><div class="muted">${JSON.stringify(item.statistics_json || {})}</div>`);
  renderList('#items', items, item => `<div class="kicker">${item.status} · ${item.source_database_key}</div><div>${item.notion_page_id}</div><div class="muted">${item.target_entity_type || 'raw'} · ${item.error_message || item.imported_at || ''}</div>`);
}
async function createDryRun() {
  const csrf = await window.getAImagicianCsrfToken();
  const response = await fetch('/api/notion-import/runs', {
    method: 'POST',
    headers: {'content-type':'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify({dry_run: true, metadata_json: {requested_from: 'admin_ui'}})
  });
  document.querySelector('#notionStatus').textContent = response.ok ? 'dry-run import created' : await response.text();
  await loadImport();
}
async function retryOutbox() {
  const csrf = await window.getAImagicianCsrfToken();
  const response = await fetch('/api/notion-sync/outbox/retry-all', {
    method: 'POST',
    headers: {'content-type':'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify({statuses:['failed','dead_letter','retry_scheduled'], limit: 1000})
  });
  document.querySelector('#notionStatus').textContent = response.ok ? 'outbox retry queued' : await response.text();
  await loadImport();
}
async function drainOutbox() {
  const csrf = await window.getAImagicianCsrfToken();
  const response = await fetch('/api/notion-sync/outbox/drain', {
    method: 'POST',
    headers: {'content-type':'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify({statuses:['pending','failed','retry_scheduled','claimed'], final_status:'archived_noop', reason:'admin-ui drain'})
  });
  document.querySelector('#notionStatus').textContent = response.ok ? 'outbox drained' : await response.text();
  await loadImport();
}
function renderList(selector, items, render) {
  document.querySelector(selector).innerHTML = items.length ? items.map(item => `<div class="item">${render(item)}</div>`).join('') : '<p class="muted">No records yet.</p>';
}
loadImport();
</script>"""


def _platforms_body() -> str:
    return """
<section class="grid">
  <article class="panel wide"><h2>Platform Readiness</h2><p class="muted">Use this before publish. A platform with validation pending or blockers should not be selected by OpenClaw until a check-session job updates readiness.</p><div id="platforms" class="list"></div></article>
</section>
<script>
async function loadPlatforms() {
  const platforms = await fetch('/api/platforms').then(r => r.json());
  renderList('#platforms', platforms, item => `<div class="kicker">${item.platform} · ${item.status}</div><a href="/admin/platforms/${encodeURIComponent(item.platform)}">${item.readiness}</a><div class="muted">credential=${item.credential_id || 'none'} · blockers=${JSON.stringify(item.blockers_json || {})}</div>`);
}
function renderList(selector, items, render) {
  document.querySelector(selector).innerHTML = items.length ? items.map(item => `<div class="item">${render(item)}</div>`).join('') : '<p class="muted">No records yet.</p>';
}
loadPlatforms();
</script>"""


def _platform_body(platform: str) -> str:
    return f"""
<section class="grid">
  <article class="panel wide"><h2>Platform Health</h2><pre id="health">Loading...</pre><div class="toolbar"><button onclick="checkSession()">enqueue check-session</button><a href="/admin/platforms">back to platform list</a></div><div id="platformStatus" class="muted"></div></article>
  <article class="panel"><h2>GUI Runner Login</h2><p class="muted">统一触发平台登录态修复：先 bootstrap 打开远端浏览器，再按需请求/提交验证码，最后 check-session。</p><input id="loginPhone" placeholder="手机号，仅提交到后端加密材料"><input id="loginCode" placeholder="验证码，仅提交到后端加密材料"><div class="toolbar"><button onclick="bootstrapLogin()">bootstrap</button><button class="secondary" onclick="requestCode()">request code</button><button onclick="submitCode()">submit code</button></div><div id="loginStatus" class="muted"></div></article>
  <article class="panel"><h2>Credential Metadata</h2><div id="credentials" class="list"></div></article>
  <article class="panel"><h2>Credential Upload Command</h2><p class="muted">This command is for the GUI/remote machine. The upload token is never shown or stored in plaintext by the console.</p><pre id="uploadCommand"></pre></article>
</section>
<script>
const platform = {platform!r};
async function loadPlatform() {{
  const [health, credentials] = await Promise.all([
    fetch(`/api/platforms/${{encodeURIComponent(platform)}}/health`).then(r => r.json()),
    fetch(`/api/platforms/${{encodeURIComponent(platform)}}/credentials`).then(r => r.json())
  ]);
  document.querySelector('#health').textContent = JSON.stringify(health, null, 2);
  renderList('#credentials', credentials, item => `<div class="kicker">${{item.credential_kind}} · ${{item.validation_status}}</div><div>fingerprint=${{item.fingerprint}}</div><div class="muted">${{item.source_machine || 'unknown machine'}} · expires=${{item.expires_at || 'unknown'}}</div>`);
  document.querySelector('#uploadCommand').textContent = [
    `curl -X POST "$AIMAGICIAN_API_BASE_URL/api/credentials/${{encodeURIComponent(platform)}}/upload" \\\\`,
    `  -H "X-AImagician-Upload-Token: $AIMAGICIAN_CREDENTIAL_UPLOAD_TOKEN" \\\\`,
    `  -H "Content-Type: application/json" \\\\`,
    `  --data '{{"credential_kind":"browser_session","material":{{"cookies":[],"localStorage":{{}}}},"source_machine":"gui-runner"}}'`,
    '',
    `After upload: POST /api/platforms/${{encodeURIComponent(platform)}}/check-session`
  ].join('\\n');
}}
function renderList(selector, items, render) {{
  document.querySelector(selector).innerHTML = items.length ? items.map(item => `<div class="item">${{render(item)}}</div>`).join('') : '<p class="muted">No credential metadata yet.</p>';
}}
async function csrfPrompt() {{
  if (window.getAImagicianCsrfToken) return window.getAImagicianCsrfToken();
  const token = window.prompt('CSRF token missing.');
  if (!token) throw new Error('missing csrf');
  return token;
}}
async function checkSession() {{
  const token = await csrfPrompt();
  const response = await fetch(`/api/platforms/${{encodeURIComponent(platform)}}/check-session`, {{
    method: 'POST',
    headers: {{'content-type': 'application/json', 'X-CSRF-Token': token}},
    body: JSON.stringify({{idempotency_key: `platform-health:${{platform}}:${{new Date().toISOString().slice(0,10)}}`, input_json: {{source: 'admin_console'}}, timeout_seconds: 300}})
  }});
  if (!response.ok) return alert(await response.text());
  const result = await response.json();
  document.querySelector('#platformStatus').textContent = `check-session queued: job=${{result.job.id}}`;
  await loadPlatform();
}}
async function bootstrapLogin() {{
  const token = await csrfPrompt();
  const response = await fetch(`/api/platforms/${{encodeURIComponent(platform)}}/login/bootstrap`, {{
    method: 'POST',
    headers: {{'content-type': 'application/json', 'X-CSRF-Token': token}},
    body: JSON.stringify({{login_method: 'browser_sms', idempotency_key: `platform-login-bootstrap:${{platform}}:${{Date.now()}}`, input_json: {{source: 'admin_console', mode: 'visible_browser'}}, timeout_seconds: 1800}})
  }});
  if (!response.ok) return alert(await response.text());
  const result = await response.json();
  document.querySelector('#loginStatus').textContent = `bootstrap queued: job=${{result.job.id}}`;
  await loadPlatform();
}}
async function requestCode() {{
  const phone = document.querySelector('#loginPhone').value.trim();
  if (!phone) return alert('phone is required');
  const token = await csrfPrompt();
  const response = await fetch(`/api/platforms/${{encodeURIComponent(platform)}}/login/request-code`, {{
    method: 'POST',
    headers: {{'content-type': 'application/json', 'X-CSRF-Token': token}},
    body: JSON.stringify({{phone, idempotency_key: `platform-login-request-code:${{platform}}:${{Date.now()}}`, input_json: {{source: 'admin_console', mode: 'sms'}}, timeout_seconds: 600}})
  }});
  if (!response.ok) return alert(await response.text());
  const result = await response.json();
  document.querySelector('#loginStatus').textContent = `request-code queued: job=${{result.job.id}}`;
  await loadPlatform();
}}
async function submitCode() {{
  const code = document.querySelector('#loginCode').value.trim();
  if (!code) return alert('code is required');
  const token = await csrfPrompt();
  const response = await fetch(`/api/platforms/${{encodeURIComponent(platform)}}/login/submit-code`, {{
    method: 'POST',
    headers: {{'content-type': 'application/json', 'X-CSRF-Token': token}},
    body: JSON.stringify({{code, idempotency_key: `platform-login-submit-code:${{platform}}:${{Date.now()}}`, input_json: {{source: 'admin_console', mode: 'sms'}}, timeout_seconds: 600}})
  }});
  if (!response.ok) return alert(await response.text());
  const result = await response.json();
  document.querySelector('#loginStatus').textContent = `submit-code queued: job=${{result.job.id}}; run check-session after runner confirms.`;
  await loadPlatform();
}}
loadPlatform();
</script>"""


def _prompts_body() -> str:
    return """
<section class="grid">
  <article class="panel wide"><h2>Prompt Definitions</h2><div class="toolbar"><input id="domainFilter" placeholder="domain filter, e.g. article"><button onclick="loadPrompts()">filter</button><button class="secondary" onclick="importSourceFiles()">import source-file prompts</button><a href="/admin/prompt-snapshots">view snapshots</a></div><div id="promptImportStatus" class="muted"></div><div id="prompts" class="list"></div></article>
</section>
<script>
async function loadPrompts() {
  const domain = document.querySelector('#domainFilter').value.trim();
  const url = domain ? `/api/prompts?domain=${encodeURIComponent(domain)}` : '/api/prompts';
  const prompts = await fetch(url).then(r => r.json());
  renderList('#prompts', prompts, item => `<div class="kicker">${item.domain} · ${item.is_active ? 'active' : 'inactive'}</div><a href="/admin/prompts/${encodeURIComponent(item.prompt_key)}">${item.prompt_key}</a><div>${item.label}</div><div class="muted">${item.purpose || 'No purpose'} · active_version=${item.active_version_id || 'none'}</div>`);
}
function renderList(selector, items, render) {
  document.querySelector(selector).innerHTML = items.length ? items.map(item => `<div class="item">${render(item)}</div>`).join('') : '<p class="muted">No records yet.</p>';
}
async function importSourceFiles() {
  const csrf = await window.getAImagicianCsrfToken();
  const response = await fetch('/api/prompts/import-source-files', {
    method: 'POST',
    headers: {'content-type':'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify({})
  });
  const text = response.ok ? JSON.stringify(await response.json(), null, 2) : await response.text();
  document.querySelector('#promptImportStatus').innerHTML = `<pre>${text}</pre>`;
  await loadPrompts();
}
loadPrompts();
</script>"""


def _prompt_body(prompt_key: str) -> str:
    return f"""
<section class="grid">
  <article class="panel wide"><h2>Prompt Definition</h2><pre id="definition">Loading...</pre></article>
  <article class="panel wide"><h2>Draft Version Editor</h2><textarea id="templateText" placeholder="Prompt template text"></textarea><input id="changeReason" placeholder="change reason"><div class="toolbar"><button onclick="createDraft()">create draft version</button><button class="secondary" onclick="loadActiveTemplate()">reload active template</button><a href="/admin/prompts">back to prompt list</a></div><div id="promptStatus" class="muted"></div></article>
  <article class="panel"><h2>Versions</h2><div id="versions" class="list"></div></article>
  <article class="panel"><h2>Snapshots</h2><div id="snapshots" class="list"></div></article>
  <article class="panel wide"><h2>Version Diff</h2><div class="split"><pre id="leftTemplate">Pick a version.</pre><pre id="rightTemplate">Pick a version.</pre></div><pre id="diffStatus">No diff loaded.</pre></article>
</section>
<script>
const promptKey = {prompt_key!r};
let definition = null;
let versions = [];
async function loadPrompt() {{
  const [definitionPayload, versionPayload, snapshotPayload] = await Promise.all([
    fetch(`/api/prompts/${{encodeURIComponent(promptKey)}}`).then(r => r.json()),
    fetch(`/api/prompts/${{encodeURIComponent(promptKey)}}/versions`).then(r => r.json()),
    fetch(`/api/prompt-snapshots?prompt_key=${{encodeURIComponent(promptKey)}}&limit=25`).then(r => r.json())
  ]);
  definition = definitionPayload;
  versions = versionPayload;
  document.querySelector('#definition').textContent = JSON.stringify(definition, null, 2);
  renderList('#versions', versions, item => `<div class="kicker">v${{item.version}} · ${{item.status}}</div><div>${{item.change_reason || 'No change reason'}}</div><div class="muted">${{item.created_at}}</div><button class="secondary" onclick="loadTemplate('${{item.id}}')">load</button><button class="secondary" onclick="diffActive('${{item.id}}')">diff active</button><button onclick="activateVersion('${{item.id}}')">activate</button>`);
  renderList('#snapshots', snapshotPayload, item => `<div class="kicker">${{item.parse_status}} · ${{item.stage || 'no stage'}}</div><div>${{item.model || 'no model'}} · ${{item.total_tokens || 0}} tokens</div><div class="muted">${{item.parse_error || item.created_at}}</div>`);
  await loadActiveTemplate();
}}
function renderList(selector, items, render) {{
  document.querySelector(selector).innerHTML = items.length ? items.map(item => `<div class="item">${{render(item)}}</div>`).join('') : '<p class="muted">No records yet.</p>';
}}
async function csrfPrompt() {{
  if (window.getAImagicianCsrfToken) return window.getAImagicianCsrfToken();
  const token = window.prompt('CSRF token missing.');
  if (!token) throw new Error('missing csrf');
  return token;
}}
async function loadActiveTemplate() {{
  const active = versions.find(item => item.id === definition.active_version_id) || versions[0];
  if (!active) {{
    document.querySelector('#templateText').value = '';
    document.querySelector('#promptStatus').textContent = 'No versions yet.';
    return;
  }}
  document.querySelector('#templateText').value = active.template_text || '';
  document.querySelector('#promptStatus').textContent = `Loaded v${{active.version}} (${{active.status}})`;
}}
async function loadTemplate(versionId) {{
  const version = await fetch(`/api/prompt-versions/${{versionId}}`).then(r => r.json());
  document.querySelector('#templateText').value = version.template_text || '';
  document.querySelector('#promptStatus').textContent = `Loaded v${{version.version}}`;
}}
async function createDraft() {{
  const token = await csrfPrompt();
  const response = await fetch(`/api/prompts/${{encodeURIComponent(promptKey)}}/versions`, {{
    method: 'POST',
    headers: {{'content-type': 'application/json', 'X-CSRF-Token': token}},
    body: JSON.stringify({{template_text: document.querySelector('#templateText').value, change_reason: document.querySelector('#changeReason').value || 'manual promptops draft'}})
  }});
  if (!response.ok) return alert(await response.text());
  const draft = await response.json();
  document.querySelector('#promptStatus').textContent = `Draft v${{draft.version}} created.`;
  await loadPrompt();
}}
async function activateVersion(versionId) {{
  const reason = window.prompt('Activation reason');
  if (!reason) return;
  const token = await csrfPrompt();
  const response = await fetch(`/api/prompt-versions/${{versionId}}/activate`, {{
    method: 'POST',
    headers: {{'content-type': 'application/json', 'X-CSRF-Token': token}},
    body: JSON.stringify({{change_reason: reason}})
  }});
  if (!response.ok) return alert(await response.text());
  document.querySelector('#promptStatus').textContent = 'Version activated.';
  await loadPrompt();
}}
async function diffActive(versionId) {{
  if (!definition.active_version_id) {{
    document.querySelector('#diffStatus').textContent = 'No active version to diff.';
    return;
  }}
  const diff = await fetch(`/api/prompt-versions/${{definition.active_version_id}}/diff/${{versionId}}`).then(r => r.json());
  document.querySelector('#leftTemplate').textContent = diff.left_template_text || '';
  document.querySelector('#rightTemplate').textContent = diff.right_template_text || '';
  document.querySelector('#diffStatus').textContent = diff.changed ? 'Templates differ.' : 'No template changes.';
}}
loadPrompt();
</script>"""


def _prompt_snapshots_body() -> str:
    return """
<section class="grid">
  <article class="panel wide"><h2>Rendered Prompt Snapshots</h2><div class="toolbar"><input id="promptKey" placeholder="prompt_key"><select id="parseStatus"><option value="">any parse status</option><option value="parsed">parsed</option><option value="parse_failed">parse_failed</option><option value="schema_failed">schema_failed</option><option value="not_required">not_required</option></select><button onclick="loadSnapshots()">filter</button><a href="/admin/prompts">prompt definitions</a></div><div id="snapshots" class="list"></div></article>
</section>
<script>
async function loadSnapshots() {
  const params = new URLSearchParams({limit: '100'});
  const promptKey = document.querySelector('#promptKey').value.trim();
  const parseStatus = document.querySelector('#parseStatus').value;
  if (promptKey) params.set('prompt_key', promptKey);
  if (parseStatus) params.set('parse_status', parseStatus);
  const snapshots = await fetch(`/api/prompt-snapshots?${params.toString()}`).then(r => r.json());
  renderList('#snapshots', snapshots, item => `<div class="kicker">${item.prompt_key} · ${item.parse_status}</div><div>${item.stage || 'no stage'} · ${item.model || 'no model'} · ${item.total_tokens || 0} tokens</div><div class="muted">${item.parse_error || item.created_at}</div><pre>${JSON.stringify({run_id: item.run_id, article_id: item.article_id, prompt_hash: item.prompt_hash, output_hash: item.output_hash}, null, 2)}</pre>`);
}
function renderList(selector, items, render) {
  document.querySelector(selector).innerHTML = items.length ? items.map(item => `<div class="item">${render(item)}</div>`).join('') : '<p class="muted">No records yet.</p>';
}
loadSnapshots();
</script>"""


def _article_body(article_id: str) -> str:
    return f"""
<section class="grid">
  <article class="panel wide"><h2>Article</h2><pre id="article">Loading...</pre></article>
  <article class="panel wide"><h2>Markdown Editor</h2><textarea id="editor" placeholder="Loading current Markdown version..."></textarea><button onclick="saveVersion()">save new version</button><button class="secondary" onclick="enqueueReview('review_article')">review dry-run</button><button class="secondary" onclick="enqueueReview('formatter_dry_run')">formatter dry-run</button><div id="editorStatus" class="muted"></div></article>
  <article class="panel"><h2>Publications</h2><div id="publications" class="list"></div></article>
  <article class="panel"><h2>Assets</h2><div id="assets" class="list"></div></article>
  <article class="panel wide"><h2>Versions</h2><div id="versions" class="list"></div></article>
  <article class="panel wide"><h2>Version Diff</h2><pre id="versionDiff">Select two versions from the version list.</pre></article>
</section>
<script>
const articleId = {article_id!r};
let currentVersionId = null;
async function loadArticle() {{
  const [article, publications, assets, versions] = await Promise.all([
    fetch(`/api/articles/${{articleId}}`).then(r => r.json()),
    fetch(`/api/articles/${{articleId}}/publications`).then(r => r.json()),
    fetch(`/api/articles/${{articleId}}/assets`).then(r => r.json()),
    fetch(`/api/articles/${{articleId}}/versions`).then(r => r.json())
  ]);
  document.querySelector('#article').textContent = JSON.stringify(article, null, 2);
  currentVersionId = article.current_version_id || (versions[0] && versions[0].id);
  if (currentVersionId) {{
    const version = await fetch(`/api/articles/${{articleId}}/versions/${{currentVersionId}}`).then(r => r.json());
    document.querySelector('#editor').value = version.body_markdown || version.body_html || '';
  }} else {{
    document.querySelector('#editor').value = '';
  }}
  renderList('#publications', publications, item => `<div class="kicker">${{item.platform}} · guard=${{item.duplicate_guard_state || 'unknown'}}</div><div>${{item.status}}</div><div class="muted">${{item.public_url || item.candidate_public_url || item.draft_id || 'No URL yet'}}</div><div class="muted">${{item.failure_code || ''}} ${{item.failure_message || ''}}</div><button onclick="publishPlatform('${{item.platform}}', false)">enqueue publish</button><button class="secondary" onclick="publishPlatform('${{item.platform}}', true)">force republish</button><button onclick="refreshUrl('${{item.platform}}')">check URL</button>`);
  renderList('#assets', assets, item => `<div class="kicker">${{item.asset_type}}</div><div>${{item.role || 'asset'}}</div><div class="muted">${{item.hosted_url || item.local_path || 'No pointer'}}</div>`);
  renderList('#versions', versions, item => `<div class="kicker">v${{item.version_number}} · ${{item.version_kind}}${{item.is_current ? ' · current' : ''}}</div><div>${{item.word_count || 0}} words</div><button class="secondary" onclick="loadVersion('${{item.id}}')">load</button><button class="secondary" onclick="diffAgainstCurrent('${{item.id}}')">diff current</button>`);
}}
function renderList(selector, items, render) {{
  document.querySelector(selector).innerHTML = items.length ? items.map(item => `<div class="item">${{render(item)}}</div>`).join('') : '<p class="muted">No records yet.</p>';
}}
async function csrfPrompt() {{
  if (window.getAImagicianCsrfToken) return window.getAImagicianCsrfToken();
  const token = window.prompt('CSRF token missing.');
  if (!token) throw new Error('missing csrf');
  return token;
}}
async function loadVersion(versionId) {{
  const version = await fetch(`/api/articles/${{articleId}}/versions/${{versionId}}`).then(r => r.json());
  currentVersionId = version.id;
  document.querySelector('#editor').value = version.body_markdown || version.body_html || '';
  document.querySelector('#editorStatus').textContent = `Loaded v${{version.version_number}}`;
}}
async function saveVersion() {{
  const token = await csrfPrompt();
  const response = await fetch(`/api/articles/${{articleId}}/versions`, {{
    method: 'POST',
    headers: {{'content-type': 'application/json', 'X-CSRF-Token': token}},
    body: JSON.stringify({{version_kind: 'manual_edit', body_markdown: document.querySelector('#editor').value, set_current: true}})
  }});
  if (!response.ok) return alert(await response.text());
  const version = await response.json();
  currentVersionId = version.id;
  document.querySelector('#editorStatus').textContent = `Saved v${{version.version_number}}`;
  await loadArticle();
}}
async function diffAgainstCurrent(versionId) {{
  if (!currentVersionId || currentVersionId === versionId) {{
    document.querySelector('#versionDiff').textContent = 'Pick a different version to diff.';
    return;
  }}
  const diff = await fetch(`/api/articles/${{articleId}}/versions/diff?left_version_id=${{encodeURIComponent(versionId)}}&right_version_id=${{encodeURIComponent(currentVersionId)}}`).then(r => r.json());
  document.querySelector('#versionDiff').textContent = diff.diff_markdown || '(no diff)';
}}
async function enqueueReview(jobKind) {{
  const token = await csrfPrompt();
  const response = await fetch(`/api/articles/${{articleId}}/review-jobs`, {{
    method: 'POST',
    headers: {{'content-type': 'application/json', 'X-CSRF-Token': token}},
    body: JSON.stringify({{job_kind: jobKind, version_id: currentVersionId, dry_run: true}})
  }});
  if (!response.ok) return alert(await response.text());
  const job = await response.json();
  document.querySelector('#editorStatus').textContent = `${{jobKind}} queued: ${{job.id}}`;
}}
async function publishPlatform(platform, force) {{
  const token = await csrfPrompt();
  const body = {{}};
  if (force) {{
    const reason = window.prompt('Force republish reason');
    if (!reason) return;
    body.force_republish = true;
    body.force_republish_reason = reason;
  }}
  const response = await fetch(`/api/articles/${{articleId}}/publications/${{encodeURIComponent(platform)}}/publish`, {{
    method: 'POST',
    headers: {{'content-type': 'application/json', 'X-CSRF-Token': token}},
    body: JSON.stringify(body)
  }});
  if (!response.ok) alert(await response.text());
  await loadArticle();
}}
async function refreshUrl(platform) {{
  const token = await csrfPrompt();
  const url = window.prompt('Public URL to verify');
  const response = await fetch(`/api/articles/${{articleId}}/publications/${{encodeURIComponent(platform)}}/refresh-url`, {{
    method: 'POST',
    headers: {{'content-type': 'application/json', 'X-CSRF-Token': token}},
    body: JSON.stringify({{url}})
  }});
  if (!response.ok) alert(await response.text());
  await loadArticle();
}}
loadArticle();
</script>"""


def _series_body(series_id: str) -> str:
    return f"""
<section class="grid">
  <article class="panel"><h2>Series</h2><pre id="series">Loading...</pre></article>
  <article class="panel"><h2>Next Entry</h2><pre id="nextEntry">Loading...</pre></article>
  <article class="panel wide"><h2>Ordered Entries</h2><div id="entries" class="list"></div></article>
</section>
<script>
const seriesId = {series_id!r};
async function loadSeries() {{
  const [series, entries, nextEntry] = await Promise.all([
    fetch(`/api/series/${{seriesId}}`).then(r => r.json()),
    fetch(`/api/series/${{seriesId}}/entries`).then(r => r.json()),
    fetch(`/api/series/${{seriesId}}/next-entry`).then(r => r.json())
  ]);
  document.querySelector('#series').textContent = JSON.stringify(series, null, 2);
  document.querySelector('#nextEntry').textContent = JSON.stringify(nextEntry.entry, null, 2);
  renderList('#entries', entries, item => `<div class="kicker">${{item.status}} · order ${{item.order_index}}</div><div>${{item.final_title || item.draft_title || item.entry_key}}</div><div class="muted">${{item.topic_summary || 'No topic summary yet'}}</div>`);
}}
function renderList(selector, items, render) {{
  document.querySelector(selector).innerHTML = items.length ? items.map(item => `<div class="item">${{render(item)}}</div>`).join('') : '<p class="muted">No records yet.</p>';
}}
loadSeries();
</script>"""


def _run_body(run_id: str) -> str:
    return f"""
<section class="grid">
  <article class="panel wide"><h2>Run Observability</h2><pre id="observability">Loading...</pre></article>
  <article class="panel"><h2>Jobs</h2><div id="jobs" class="list"></div></article>
  <article class="panel"><h2>Artifacts</h2><div id="artifacts" class="list"></div></article>
  <article class="panel"><h2>Notion Outbox</h2><div id="outbox" class="list"></div></article>
  <article class="panel"><h2>Prompt Chain</h2><div id="prompts" class="list"></div></article>
  <article class="panel wide"><h2>Recent Events</h2><div id="events" class="list"></div></article>
</section>
<script>
const runId = {run_id!r};
async function loadRun() {{
  const [observability, promptChain] = await Promise.all([
    fetch(`/api/agents/article-flows/${{runId}}/observability`).then(r => r.json()),
    fetch(`/api/agents/article-flows/${{runId}}/prompt-chain`).then(r => r.ok ? r.json() : {{snapshots: []}})
  ]);
  document.querySelector('#observability').textContent = JSON.stringify({{
    lookup: observability.lookup,
    next_action: observability.next_action,
    event_summary: observability.event_summary,
    artifact_summary: observability.artifact_summary
  }}, null, 2);
  renderList('#jobs', observability.jobs || [], item => `<div class="kicker">${{item.status}} · ${{item.job_type}}</div><div>${{item.failure_code || item.waiting_for || item.id}}</div><div class="muted">${{item.failure_message || item.created_at}}</div>`);
  renderList('#artifacts', observability.artifacts || [], item => `<div class="kicker">${{item.asset_type}} · ${{item.role || 'asset'}}</div><div>${{item.hosted_url || item.local_path || item.source_url || item.id}}</div>`);
  renderList('#outbox', observability.notion_outbox || [], item => `<div class="kicker">${{item.status}} · ${{item.operation}}</div><div>${{item.notion_target_kind}}</div><div class="muted">${{item.last_error_message || item.updated_at}}</div>`);
  renderList('#prompts', promptChain.snapshots || [], item => `<div class="kicker">${{item.prompt_key}} · ${{item.parse_status}}</div><div>${{item.model || 'no model'}}</div><div class="muted">${{item.stage || item.created_at}}</div>`);
  renderList('#events', observability.recent_events || [], item => `<div class="kicker">${{item.level}} · ${{item.event_type}}</div><div>${{item.message}}</div><div class="muted">${{item.created_at}}</div>`);
}}
function renderList(selector, items, render) {{
  document.querySelector(selector).innerHTML = items.length ? items.map(item => `<div class="item">${{render(item)}}</div>`).join('') : '<p class="muted">No records yet.</p>';
}}
loadRun();
</script>"""
