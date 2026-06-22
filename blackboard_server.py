#!/usr/bin/env python3
import argparse
import datetime as dt
import html
import json
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from learning_os import BASE, BLACKBOARD_PATH, load_config, load_state, save_state, generate_today, parse_date_arg, set_task_state


PORT = 8765
PYTHON = "/Users/zxydediannao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"


def today_text():
    return dt.date.today().isoformat()


def esc(value):
    return html.escape(str(value or ""))


def play_sound(name="Glass"):
    subprocess.Popen(["afplay", f"/System/Library/Sounds/{name}.aiff"])


def open_target(target):
    if target:
        subprocess.Popen(["open", target])


def task_rows(date_text):
    state = load_state()
    tasks = [t for t in state["tasks"].values() if t.get("date") == date_text]
    order = {"AP_Calculus_BC": 0, "AP_CSA": 1, "GLOBAL": 2}
    return sorted(tasks, key=lambda t: (order.get(t.get("course"), 9), t.get("id", "")))


def render_task(task):
    resources = task.get("resources", [])
    indexed_primary = next((
        r for r in resources
        if str(r.get("label", "")).startswith("resource_index_")
        and r.get("target")
    ), None)
    primary = next((
        r for r in resources
        if str(r.get("label", "")).startswith("task_excerpt")
        and not (task.get("course") == "AP_CSA" and r.get("label") == "task_excerpt_java_illuminated")
    ), None)
    launch_url = next((x.get("target") for x in task.get("launch", []) if x.get("type") == "url"), None)
    state_class = esc(task.get("state", ""))
    parts = [
        f'<section class="task {state_class.replace(" ", "-")}">',
        '<div class="task-head">',
        f'<div><div class="state">{esc(task.get("state"))}</div><h2>{esc(task.get("title"))}</h2></div>',
        f'<div class="time">{esc(task.get("target_min"))} min</div>',
        '</div>',
        f'<p class="goal">{esc(task.get("observable_goal"))}</p>',
        '<div class="actions">',
        f'<form method="post" action="/api/start"><input type="hidden" name="task" value="{esc(task["id"])}"><button>Start Workflow</button></form>',
        f'<form method="post" action="/api/state"><input type="hidden" name="task" value="{esc(task["id"])}"><input type="hidden" name="state" value="Completed"><button class="ok">Mark Completed</button></form>',
        f'<form method="post" action="/api/state"><input type="hidden" name="task" value="{esc(task["id"])}"><input type="hidden" name="state" value="Partially Completed"><button class="partial">Partial</button></form>',
        f'<form method="post" action="/api/state"><input type="hidden" name="task" value="{esc(task["id"])}"><input type="hidden" name="state" value="Blocked"><button class="block">Blocked</button></form>',
        '</div>',
        '<div class="links">',
    ]
    if launch_url:
        parts.append(f'<a href="/api/open?target={urllib.parse.quote(launch_url)}">Khan</a>')
    if indexed_primary:
        parts.append(f'<a href="/api/open?target={urllib.parse.quote(indexed_primary["target"])}">Indexed Resource</a>')
    if primary:
        parts.append(f'<a href="/api/open?target={urllib.parse.quote(primary["target"])}">Task PDF</a>')
    parts.append('</div>')
    parts.append('<details><summary>Resources</summary><ul>')
    for r in resources:
        label = esc(r.get("label"))
        target = esc(r.get("target"))
        index_name = esc(r.get("index_filename"))
        page_range = r.get("page_range")
        suffix = f' <span class="pages">p{page_range[0]}-{page_range[1]}</span>' if page_range else ''
        if r.get("target"):
            parts.append(f'<li><a href="/api/open?target={urllib.parse.quote(r.get("target", ""))}">{label}</a>{suffix}<br><code>{target}</code></li>')
        else:
            parts.append(f'<li>{label} <strong>MISSING</strong>{suffix}<br><code>{index_name}</code></li>')
    parts.append('</ul></details>')
    parts.append('</section>')
    return "\n".join(parts)


def render_page(date_text):
    tasks = task_rows(date_text)
    body = "\n".join(render_task(t) for t in tasks) if tasks else '<p class="empty">No tasks for this date.</p>'
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AP Learning OS Blackboard</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #202124; background: #f7f7f5; }}
header {{ position: sticky; top: 0; background: rgba(255,255,255,.94); border-bottom: 1px solid #ddd; padding: 14px 22px; display:flex; align-items:center; justify-content:space-between; gap:16px; }}
h1 {{ font-size: 20px; margin: 0; }}
main {{ max-width: 1080px; margin: 18px auto 60px; padding: 0 18px; }}
.task {{ background: #fff; border: 1px solid #dedede; border-radius: 8px; padding: 16px; margin: 12px 0; }}
.task-head {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }}
h2 {{ font-size: 18px; margin: 4px 0 0; }}
.state {{ font-size: 12px; color:#666; text-transform: uppercase; letter-spacing:.04em; }}
.time {{ font-weight: 700; white-space: nowrap; }}
.goal {{ color:#444; margin: 10px 0 14px; }}
.actions, .links {{ display:flex; flex-wrap:wrap; gap:8px; margin: 8px 0; }}
button, .links a, header a {{ border:1px solid #bbb; background:#fafafa; color:#202124; border-radius:6px; padding:8px 10px; font-size:14px; text-decoration:none; cursor:pointer; }}
button.ok {{ background:#e7f4ea; border-color:#9cc9a5; }}
button.partial {{ background:#fff7df; border-color:#e1be62; }}
button.block {{ background:#fdeaea; border-color:#df9d9d; }}
.Completed {{ border-left: 5px solid #2e7d32; }}
.Partially-Completed {{ border-left: 5px solid #b7791f; }}
.Blocked, .Failed {{ border-left: 5px solid #b3261e; }}
.Running, .Needs-Review, .Candidate-Complete {{ border-left: 5px solid #1a73e8; }}
details {{ margin-top: 10px; }}
li {{ margin: 8px 0; }}
code {{ font-size: 12px; color:#666; word-break: break-all; }}
.pages {{ color:#666; font-size:12px; }}
input[type=date] {{ padding:7px; border:1px solid #bbb; border-radius:6px; }}
</style>
</head>
<body>
<header>
  <h1>AP Learning OS Blackboard</h1>
  <form method="get" action="/">
    <input type="date" name="date" value="{esc(date_text)}">
    <button>Load</button>
    <a href="/api/generate?date={esc(date_text)}">Regenerate</a>
    <a href="/api/open?target={urllib.parse.quote(str(BASE / "sessions"))}">Evidence</a>
    <a href="/api/open?target={urllib.parse.quote(str(BLACKBOARD_PATH))}">Markdown</a>
  </form>
</header>
<main>{body}</main>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def redirect(self, path="/"):
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def send_html(self, text):
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/":
            date_text = query.get("date", [today_text()])[0]
            generate_today(load_config(), load_state(), parse_date_arg(date_text))
            self.send_html(render_page(date_text))
        elif parsed.path == "/api/generate":
            date_text = query.get("date", [today_text()])[0]
            generate_today(load_config(), load_state(), parse_date_arg(date_text))
            play_sound("Pop")
            self.redirect(f"/?date={urllib.parse.quote(date_text)}")
        elif parsed.path == "/api/open":
            target = query.get("target", [""])[0]
            open_target(target)
            self.redirect(self.headers.get("Referer", "/"))
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length).decode("utf-8")
        form = urllib.parse.parse_qs(data)
        if self.path == "/api/state":
            task_id = form.get("task", [""])[0]
            new_state = form.get("state", [""])[0]
            state = load_state()
            if task_id in state["tasks"]:
                set_task_state(state, task_id, new_state)
                save_state(state)
                play_sound("Glass" if new_state == "Completed" else "Pop")
            self.redirect(self.headers.get("Referer", "/"))
        elif self.path == "/api/start":
            task_id = form.get("task", [""])[0]
            cmd = f'{PYTHON} "{BASE / "learning_os.py"}" start --task "{task_id}"'
            subprocess.Popen([
                "osascript", "-e",
                f'tell application "Terminal" to do script {json.dumps(cmd)}'
            ])
            play_sound("Pop")
            self.redirect(self.headers.get("Referer", "/"))
        else:
            self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description="AP Learning OS local blackboard server")
    parser.add_argument("--no-open", action="store_true", help="start server without opening the browser")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"AP Learning OS blackboard: http://127.0.0.1:{PORT}")
    if not args.no_open:
        subprocess.Popen(["open", f"http://127.0.0.1:{PORT}"])
    server.serve_forever()


if __name__ == "__main__":
    main()
