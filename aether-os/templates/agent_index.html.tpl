<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{agent_name} - Agent UI</title>
<style>
:root {{ --bg:#0b1020; --card:#131a2f; --txt:#eaf0ff; --muted:#9fb0d8; --acc:#4f8cff; }}
body {{ margin:0; font-family:Segoe UI,Arial,sans-serif; background:radial-gradient(1200px 600px at 20% -10%, #1d2752 0%, var(--bg) 40%); color:var(--txt); }}
main {{ max-width:900px; margin:32px auto; padding:0 16px; }}
.panel {{ background:var(--card); border:1px solid #263157; border-radius:14px; padding:16px; }}
input,button {{ width:100%; box-sizing:border-box; border-radius:10px; border:1px solid #2a3b72; background:#0f1730; color:var(--txt); padding:10px; }}
button {{ margin-top:10px; background:linear-gradient(180deg,#5a95ff,#3d78ef); border:none; font-weight:600; cursor:pointer; }}
#out {{ margin-top:12px; white-space:pre-wrap; color:var(--muted); }}
</style>
</head>
<body>
<main>
  <h1>{agent_name}</h1>
  <p>{agent_role}</p>
  <div class="panel">
    <label for="task">Task</label>
    <input id="task" placeholder="Ask your agent..." />
    <button id="runBtn">Run</button>
    <div id="out"></div>
  </div>
</main>
<script>
const out = document.getElementById('out');
const task = document.getElementById('task');
document.getElementById('runBtn').addEventListener('click', async () => {{
  const t = task.value.trim();
  if (!t) return;
  out.textContent = 'Running...';
  try {{
    const res = await fetch('/run', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{task:t}}),
    }});
    const data = await res.json();
    out.textContent = data.result || data.detail || 'No response';
  }} catch (e) {{
    out.textContent = 'Request failed.';
  }}
}});
</script>
</body>
</html>
