#!/usr/bin/env python3
"""Simulation console: browse sessions, replay them animated, launch live runs.

Usage:  python console.py   (then open http://localhost:7007)

Left pane: sessions from Phoenix + a run form. Right pane: animated playback.
New runs stream live: the page polls Phoenix as the agent works.
"""

import csv
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

import agent_student
import make_replay

PORT = 7007
PHOENIX = os.environ.get("PHOENIX_URL", "http://localhost:6006")
GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:4000")
KEYS = {r["email"].split("@")[0]: r["key"]
        for r in csv.DictReader(open(os.path.join(os.path.dirname(__file__), "sim_keys.csv")))}
RUNNING = {}  # session -> {"student":..., "task":..., "done": bool}


def list_sessions():
    spans = make_replay.fetch_spans(PHOENIX)
    out = []
    for s in spans:
        if s["parentId"] is None and not s["name"].startswith(("Received", "self")):
            a = json.loads(s["attributes"])
            inp = a.get("input", {}).get("value") if isinstance(a.get("input"), dict) else None
            if inp:
                out.append({"name": s["name"],
                            "student": a.get("user", {}).get("id", "?"),
                            "result": (a.get("output", {}).get("value", "") or "")[:80],
                            "start": s["startTime"]})
    live = [{"name": k, "student": v["student"], "result": "⏳ running...", "start": "~now"}
            for k, v in RUNNING.items() if not v["done"]]
    return live + sorted(out, key=lambda x: x["start"], reverse=True)


def get_session(name):
    spans = make_replay.fetch_spans(PHOENIX)
    # finished session: named root exists
    try:
        data = make_replay.build_session(spans, name)
        data["done"] = True
        return data
    except SystemExit:
        pass
    # live session: find calls tagged with this session_id in requester metadata
    tids = {s["context"]["traceId"] for s in spans
            if s["name"] == "litellm_request" and name in s["attributes"]}
    calls = sorted((s for s in spans if s["context"]["traceId"] in tids
                    and s["name"] == "raw_gen_ai_request"), key=lambda s: s["startTime"])
    steps = []
    for c in calls:
        import ast
        at = json.loads(c["attributes"]).get("llm", {}).get("openai", {})
        msgs = ast.literal_eval(at.get("messages", "[]")) if at.get("messages") else []
        choices = ast.literal_eval(at.get("choices", "[]")) if at.get("choices") else []
        usage = ast.literal_eval(at.get("usage", "{}")) if at.get("usage") else {}
        steps.append({"incoming": msgs[-1]["content"] if msgs else "",
                      "reply": choices[0]["message"]["content"] if choices else "",
                      "messages": [{"role": m.get("role", "?"), "content": str(m.get("content", ""))} for m in msgs],
                      "tin": usage.get("prompt_tokens", 0), "tout": usage.get("completion_tokens", 0),
                      "latency": round(float(at.get("response_time", 0) or 0), 2),
                      "model": at.get("model", "")})
    info = RUNNING.get(name, {})
    return {"session": name, "student": info.get("student", "?"),
            "task": info.get("task", ""), "result": "", "steps": steps,
            "done": info.get("done", False) and True}


def budgets():
    """Fleet budget view: spend vs cap per key (instructor; needs master key)."""
    master = os.environ.get("LITELLM_MASTER_KEY")
    if not master:
        return []
    out, page = [], 1
    while True:
        r = requests.get(f"{GATEWAY}/key/list",
                         params={"return_full_object": "true", "page": page, "size": 100},
                         headers={"Authorization": f"Bearer {master}"}, timeout=15)
        r.raise_for_status()
        batch = r.json().get("keys", [])
        for k in batch:
            if k.get("max_budget"):
                out.append({"student": k.get("key_alias") or k["key_name"],
                            "spend": round(float(k.get("spend") or 0), 4),
                            "cap": k["max_budget"],
                            "blocked": bool(k.get("blocked"))})
        if len(batch) < 100:
            break
        page += 1
    return sorted(out, key=lambda r: -r["spend"] / r["cap"])


def key_usage(key):
    """Self-service usage: a key querying its own info (no master key involved)."""
    r = requests.get(f"{GATEWAY}/key/info",
                     headers={"Authorization": f"Bearer {key}"}, timeout=10)
    if r.status_code != 200:
        return {"error": "key not recognized"}
    i = r.json()["info"]
    return {"student": i.get("key_alias") or "?",
            "spend": round(float(i.get("spend") or 0), 4),
            "cap": i.get("max_budget")}


def launch(student, task, model):
    stamp = time.strftime("%m%d-%H%M%S")
    session = f"console-{student.removeprefix('sim-')}-{stamp}"
    RUNNING[session] = {"student": student, "task": task, "done": False}

    def work():
        try:
            agent_student.run_agent(task, KEYS[student], model, GATEWAY,
                                    session_id=session, student=student)
        finally:
            RUNNING[session]["done"] = True
    threading.Thread(target=work, daemon=True).start()
    return session


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/sessions":
            self._json(list_sessions())
        elif self.path.startswith("/api/session/"):
            self._json(get_session(self.path.split("/api/session/", 1)[1]))
        elif self.path == "/api/students":
            self._json(sorted(KEYS))
        elif self.path == "/api/budgets":
            self._json(budgets())
        elif self.path == "/usage":
            body = USAGE_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/run":
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            session = launch(req["student"], req["task"], req.get("model", "argonne-coder"))
            self._json({"session": session})
        elif self.path == "/api/usage":
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            self._json(key_usage(req.get("key", "")))
        else:
            self._json({"error": "not found"}, 404)


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>sim console</title><style>
body{font-family:Georgia,serif;background:#f6f8fa;color:#1F3B5C;margin:0;display:flex;height:100vh}
#left{width:340px;min-width:340px;border-right:1px solid #d7dee6;padding:1rem;overflow-y:auto;background:#EEF2F6}
#right{flex:1;padding:1rem 2rem;overflow-y:auto}
h2{font-size:1rem;margin:.6rem 0}
.sess{background:#fff;border:1px solid #c6d2de;border-radius:6px;padding:.5rem .7rem;margin:.4rem 0;cursor:pointer;font-size:.85rem}
.sess:hover{border-color:#1F3B5C}.sess .nm{font-family:Menlo,monospace;font-size:.78rem;font-weight:bold}
.sess .rs{color:#6B7280;font-size:.75rem}
textarea,select,button,input{font:inherit;width:100%;margin:.2rem 0;box-sizing:border-box}
textarea{height:5.5rem;font-size:.85rem}
button{background:#1F3B5C;color:#fff;border:none;border-radius:5px;padding:.45rem;cursor:pointer}
button:hover{background:#4A7BA6}
#task{background:#EEF2F6;border-left:4px solid #1F3B5C;padding:.6rem 1rem;border-radius:6px;margin:.8rem 0;font-size:.9rem}
.step{opacity:0;transition:opacity .4s;margin:.9rem 0}.step.on{opacity:1}
.reply{background:#fff;border:1px solid #4A7BA6;border-radius:8px;padding:.7rem 1rem;white-space:pre-wrap;font-size:.92rem}
.obs{background:#1F3B5C;color:#dfe8f2;border-radius:8px;padding:.5rem 1rem;white-space:pre-wrap;font-family:Menlo,monospace;font-size:.8rem;margin-top:.45rem}
.obs.err{background:#D1495B}
.lat{color:#6B7280;font-size:.75rem;margin:.15rem 0}
#meters{font-family:Menlo,monospace;font-size:.85rem;color:#1F3B5C;position:sticky;top:0;background:#f6f8fa;padding:.4rem 0;border-bottom:1px solid #d7dee6}
#verdict{display:none;background:#EEF2F6;border:2px solid #1F3B5C;border-radius:8px;padding:.7rem 1rem;margin:1rem 0;font-weight:bold}
.cursor::after{content:"▋";animation:bl 1s infinite}@keyframes bl{50%{opacity:0}}
details{margin-top:.4rem;font-size:.8rem}summary{cursor:pointer;color:#4A7BA6;font-family:Menlo,monospace}
.msg{border-left:3px solid #d7dee6;margin:.35rem 0;padding:.25rem .55rem;white-space:pre-wrap;font-family:Menlo,monospace;font-size:.75rem;background:#fff}
.msg .role{font-weight:bold;color:#4A7BA6;display:block;text-transform:uppercase;font-size:.68rem}
.msg.system{border-color:#E8A33D}.msg.assistant{border-color:#1F3B5C}
#livebadge{display:none;color:#D1495B;font-weight:bold}
</style></head><body>
<div id="left">
  <h2>Run an agent</h2>
  <select id="student"></select>
  <select id="model"><option>argonne-coder</option><option>sim-mock</option></select>
  <textarea id="taskin">Compute Avogadro's number divided by the number of GPUs on Sophia, then give the base-10 logarithm of the result to 3 decimal places. Use lookup() for both constants.</textarea>
  <button id="runbtn">▶ Run live</button>
  <h2>Sessions <button id="rf" style="width:auto;padding:.1rem .5rem;font-size:.75rem">↻</button></h2>
  <div id="list"></div>
  <h2>Budgets</h2>
  <div id="budgets" style="font-size:.75rem;font-family:Menlo,monospace"></div>
</div>
<div id="right">
  <div id="meters">step <span id="mstep">0</span> · <span id="mtok">0</span> tok · $<span id="mcost">0.000000</span> <span id="livebadge">● LIVE</span></div>
  <h2 id="title">← pick a session or run one</h2>
  <div id="task"></div><div id="steps"></div><div id="verdict"></div>
</div>
<script>
const IN_RATE=0.25e-6,OUT_RATE=1.00e-6;
let rendered=0,tok=0,cost=0,current=null,pollTimer=null,busy=false;
const $=id=>document.getElementById(id);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function typewrite(el,t){el.classList.add('cursor');
 for(let j=0;j<t.length;j+=4){el.textContent=t.slice(0,j+4);await sleep(12);}
 el.textContent=t;el.classList.remove('cursor');}
function reset(name,task){rendered=0;tok=0;cost=0;current=name;
 $('steps').innerHTML='';$('verdict').style.display='none';
 $('title').textContent=name;$('task').innerHTML='<b>TASK:</b> '+(task||'');
 $('mstep').textContent=0;$('mtok').textContent=0;$('mcost').textContent='0.000000';}
async function render(data){
 if(busy)return;busy=true;
 if(data.task&&!$('task').textContent.slice(6))$('task').innerHTML='<b>TASK:</b> '+data.task;
 for(;rendered<data.steps.length;rendered++){
  const st=data.steps[rendered];
  const d=document.createElement('div');d.className='step';
  const lat=document.createElement('div');lat.className='lat';
  lat.textContent=`call ${rendered+1} — ${st.latency}s, ${st.tin}+${st.tout} tok (${st.model})`;
  const rp=document.createElement('div');rp.className='reply';
  d.append(lat,rp);
  if(st.incoming&&st.incoming.startsWith('OBSERVATION')){
   const ob=document.createElement('div');ob.className='obs'+(st.incoming.includes('ERROR')?' err':'');
   ob.textContent=st.incoming;$('steps').append(ob);}
  $('steps').append(d);requestAnimationFrame(()=>d.classList.add('on'));
  await typewrite(rp,st.reply);
  const det=document.createElement('details');
  det.innerHTML='<summary>full LLM call — '+st.messages.length+' messages, '+st.tin+' tok in</summary>';
  st.messages.concat([{role:'assistant (response)',content:st.reply}]).forEach(m=>{
   const b=document.createElement('div');b.className='msg '+m.role.split(' ')[0];
   b.innerHTML='<span class="role"></span>';b.querySelector('.role').textContent=m.role;
   b.append(document.createTextNode(m.content));det.append(b);});
  d.append(det);
  tok+=st.tin+st.tout;cost+=st.tin*IN_RATE+st.tout*OUT_RATE;
  $('mstep').textContent=rendered+1;$('mtok').textContent=tok;$('mcost').textContent=cost.toFixed(6);
  window.scrollTo(0,document.body.scrollHeight);}
 if(data.done){clearInterval(pollTimer);pollTimer=null;$('livebadge').style.display='none';
  if(data.result){const v=$('verdict');v.style.display='block';v.textContent='SESSION END — '+data.result;}}
 busy=false;}
async function play(name,task,live){reset(name,task);
 if(pollTimer)clearInterval(pollTimer);
 $('livebadge').style.display=live?'inline':'none';
 const tick=async()=>{const r=await fetch('/api/session/'+encodeURIComponent(name));render(await r.json());};
 await tick();pollTimer=setInterval(tick,2500);}
async function loadSessions(){const r=await fetch('/api/sessions');const ss=await r.json();
 $('list').innerHTML='';ss.forEach(s=>{const d=document.createElement('div');d.className='sess';
  d.innerHTML='<div class="nm"></div><div class="rs"></div>';
  d.querySelector('.nm').textContent=s.name;
  d.querySelector('.rs').textContent=s.student+' · '+s.result;
  d.onclick=()=>play(s.name,null,s.result.startsWith('⏳'));$('list').append(d);});}
$('rf').onclick=loadSessions;
$('runbtn').onclick=async()=>{const body={student:$('student').value,model:$('model').value,task:$('taskin').value};
 const r=await fetch('/api/run',{method:'POST',body:JSON.stringify(body)});
 const {session}=await r.json();await loadSessions();play(session,body.task,true);};
async function loadBudgets(){const r=await fetch('/api/budgets');const bs=await r.json();
 $('budgets').innerHTML='';bs.forEach(b=>{
  const pct=Math.min(100,100*b.spend/b.cap);
  const tier=pct>=95?'#D1495B':pct>=80?'#E8A33D':'#4A7BA6';
  const d=document.createElement('div');d.style.margin='.3rem 0';
  d.innerHTML='<div></div><div style="background:#d7dee6;border-radius:3px;height:6px">'+
   '<div style="height:6px;border-radius:3px;width:'+Math.max(pct,1)+'%;background:'+tier+'"></div></div>';
  d.firstChild.textContent=b.student.split('@')[0]+'  $'+b.spend.toFixed(2)+' / $'+b.cap+(b.blocked?'  BLOCKED':'');
  $('budgets').append(d);});}
fetch('/api/students').then(r=>r.json()).then(ss=>{ss.forEach(s=>{const o=document.createElement('option');o.textContent=s;$('student').append(o);});});
loadSessions();loadBudgets();setInterval(loadBudgets,30000);
</script></body></html>"""

USAGE_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>my usage</title><style>
body{font-family:Georgia,serif;background:#f6f8fa;color:#1F3B5C;max-width:28rem;margin:4rem auto;padding:0 1rem}
input,button{font:inherit;width:100%;box-sizing:border-box;margin:.3rem 0;padding:.5rem}
button{background:#1F3B5C;color:#fff;border:none;border-radius:5px;cursor:pointer}
#out{margin-top:1.5rem;font-size:1.05rem}
#bar{background:#d7dee6;border-radius:4px;height:14px;margin:.6rem 0}
#fill{height:14px;border-radius:4px;background:#4A7BA6;width:0}
</style></head><body>
<h1 style="font-size:1.3rem">CMSC 35370 — my usage</h1>
<p>Paste your gateway key. It is checked against the gateway directly and shows only your own account.</p>
<input id="key" type="password" placeholder="sk-...">
<button onclick="go()">Show my usage</button>
<div id="out"></div><div id="bar" style="display:none"><div id="fill"></div></div>
<script>
async function go(){
 const r=await fetch('/api/usage',{method:'POST',body:JSON.stringify({key:document.getElementById('key').value.trim()})});
 const d=await r.json();const out=document.getElementById('out');
 if(d.error){out.textContent=d.error;return;}
 const pct=d.cap?Math.min(100,100*d.spend/d.cap):0;
 out.innerHTML='';const b=document.createElement('b');b.textContent=d.student;
 out.append(b,document.createTextNode(' — $'+d.spend.toFixed(2)+' of $'+d.cap+' ('+pct.toFixed(1)+'%)'));
 document.getElementById('bar').style.display='block';
 const f=document.getElementById('fill');f.style.width=Math.max(pct,1)+'%';
 f.style.background=pct>=95?'#D1495B':pct>=80?'#E8A33D':'#4A7BA6';}
</script></body></html>"""


if __name__ == "__main__":
    print(f"sim console: http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
