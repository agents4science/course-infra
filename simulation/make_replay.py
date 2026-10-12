#!/usr/bin/env python3
"""Export a session from Phoenix as a self-contained animated replay HTML.

Usage:
    python make_replay.py <session-name-or-prefix> [--phoenix URL] [--out FILE]

Finds the named session root span, collects its LLM calls, and writes
replay_<session>.html — open in any browser, no server needed.
"""

import argparse
import ast
import html
import json
import os
import re

import requests

Q = '{"query":"query { projects { edges { node { spans(first: 1000) { edges { node { name parentId startTime attributes context { traceId } } } } } } } }"}'


def fetch_spans(phoenix: str):
    r = requests.post(f"{phoenix}/graphql", data=Q,
                      headers={"Content-Type": "application/json"}, timeout=30)
    r.raise_for_status()
    return [e["node"] for e in
            r.json()["data"]["projects"]["edges"][0]["node"]["spans"]["edges"]]


def build_session(spans, session_prefix):
    roots = [s for s in spans if s["parentId"] is None
             and s["name"].startswith(session_prefix)]
    if not roots:
        raise SystemExit(f"no session root matching '{session_prefix}'")
    root = sorted(roots, key=lambda s: s["startTime"])[-1]  # latest match
    a = json.loads(root["attributes"])
    trace_id = root["context"]["traceId"]

    calls = sorted((s for s in spans
                    if s["context"]["traceId"] == trace_id
                    and s["name"] == "raw_gen_ai_request"),
                   key=lambda s: s["startTime"])
    steps = []
    for c in calls:
        at = json.loads(c["attributes"]).get("llm", {}).get("openai", {})
        msgs = ast.literal_eval(at.get("messages", "[]")) if at.get("messages") else []
        choices = ast.literal_eval(at.get("choices", "[]")) if at.get("choices") else []
        usage = ast.literal_eval(at.get("usage", "{}")) if at.get("usage") else {}
        incoming = msgs[-1]["content"] if msgs else ""
        reply = choices[0]["message"]["content"] if choices else ""
        steps.append({
            "incoming": incoming, "reply": reply,
            "messages": [{"role": m.get("role", "?"),
                          "content": str(m.get("content", ""))} for m in msgs],
            "tin": usage.get("prompt_tokens", 0),
            "tout": usage.get("completion_tokens", 0),
            "latency": round(float(at.get("response_time", 0) or 0), 2),
            "model": at.get("model", ""),
        })
    def dig(d, *keys, default=""):
        for k in keys:
            d = d.get(k, {}) if isinstance(d, dict) else {}
        return d if isinstance(d, str) else default

    return {
        "session": root["name"],
        "student": dig(a, "user", "id", default="?"),
        "task": dig(a, "input", "value"),
        "result": dig(a, "output", "value"),
        "steps": steps,
    }


TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<title>replay: __SESSION__</title><style>
body{font-family:Georgia,serif;background:#f6f8fa;color:#1F3B5C;max-width:860px;margin:2rem auto;padding:0 1rem}
h1{font-size:1.2rem} .meta{color:#6B7280;font-size:.9rem;margin-bottom:.4rem}
#task{background:#EEF2F6;border-left:4px solid #1F3B5C;padding:.7rem 1rem;border-radius:6px;margin:1rem 0}
.step{opacity:0;transition:opacity .5s;margin:1rem 0}
.step.on{opacity:1}
.reply{background:#fff;border:1px solid #4A7BA6;border-radius:8px;padding:.8rem 1rem;white-space:pre-wrap;font-size:.95rem}
.obs{background:#1F3B5C;color:#dfe8f2;border-radius:8px;padding:.6rem 1rem;white-space:pre-wrap;font-family:Menlo,monospace;font-size:.83rem;margin-top:.5rem}
.obs.err{background:#D1495B}
.lat{color:#6B7280;font-size:.78rem;margin:.2rem 0}
#bar{position:sticky;top:0;background:#f6f8fa;padding:.6rem 0;border-bottom:1px solid #d7dee6;display:flex;gap:1.2rem;align-items:center}
#meters{margin-left:auto;font-family:Menlo,monospace;font-size:.85rem}
button,select{font:inherit;padding:.25rem .8rem}
#verdict{display:none;background:#EEF2F6;border:2px solid #1F3B5C;border-radius:8px;padding:.8rem 1rem;margin:1.2rem 0;font-weight:bold}
.cursor::after{content:"▋";animation:blink 1s infinite}@keyframes blink{50%{opacity:0}}
details{margin-top:.45rem;font-size:.82rem}summary{cursor:pointer;color:#4A7BA6;font-family:Menlo,monospace}
.msg{border-left:3px solid #d7dee6;margin:.4rem 0;padding:.3rem .6rem;white-space:pre-wrap;font-family:Menlo,monospace;font-size:.78rem;background:#fff}
.msg .role{font-weight:bold;color:#4A7BA6;display:block;margin-bottom:.15rem;text-transform:uppercase;font-size:.7rem}
.msg.system{border-color:#E8A33D}.msg.assistant{border-color:#1F3B5C}.msg.user{border-color:#4A7BA6}
</style></head><body>
<div id="bar"><button id="play">▶ Play</button>
<select id="speed"><option value="1">1×</option><option value="4" selected>4×</option><option value="16">16×</option></select>
<span id="meters">step <span id="mstep">0</span>/__NSTEPS__ · <span id="mtok">0</span> tok · $<span id="mcost">0.000000</span></span></div>
<h1>__SESSION__</h1>
<div class="meta">student: __STUDENT__ · model: __MODEL__</div>
<div id="task"><b>TASK:</b> __TASK__</div>
<div id="steps"></div><div id="verdict"></div>
<script>
const S=__DATA__;
const IN_RATE=0.25e-6, OUT_RATE=1.00e-6;
let playing=false,i=0,tok=0,cost=0;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function typewrite(el,text,cps){el.classList.add('cursor');
 for(let j=0;j<text.length;j+=3){el.textContent=text.slice(0,j+3);window.scrollTo(0,document.body.scrollHeight);await sleep(1000*3/cps);if(!playing)await waitPlay();}
 el.textContent=text;el.classList.remove('cursor');}
function waitPlay(){return new Promise(r=>{const t=setInterval(()=>{if(playing){clearInterval(t);r()}},100)})}
async function run(){
 const sp=()=>+document.getElementById('speed').value;
 for(;i<S.steps.length;i++){
  if(!playing)await waitPlay();
  const st=S.steps[i];
  const d=document.createElement('div');d.className='step';
  const lat=document.createElement('div');lat.className='lat';
  lat.textContent=`model call ${i+1} — ${st.latency}s, ${st.tin}+${st.tout} tokens`;
  const rp=document.createElement('div');rp.className='reply';
  d.append(lat,rp);document.getElementById('steps').append(d);
  requestAnimationFrame(()=>d.classList.add('on'));
  await sleep(Math.min(st.latency*1000,3000)/sp());
  await typewrite(rp,st.reply,60*sp());
  const det=document.createElement('details');
  const sum=document.createElement('summary');
  sum.textContent=`full LLM call — ${st.messages.length} messages sent, ${st.tin} tokens in`;
  det.append(sum);
  st.messages.forEach(m=>{const b=document.createElement('div');b.className='msg '+m.role;
   const r=document.createElement('span');r.className='role';r.textContent=m.role;
   b.append(r,document.createTextNode(m.content));det.append(b);});
  const rb=document.createElement('div');rb.className='msg assistant';
  const rl=document.createElement('span');rl.className='role';rl.textContent='assistant (response)';
  rb.append(rl,document.createTextNode(st.reply));det.append(rb);
  d.append(det);
  tok+=st.tin+st.tout;cost+=st.tin*IN_RATE+st.tout*OUT_RATE;
  document.getElementById('mstep').textContent=i+1;
  document.getElementById('mtok').textContent=tok;
  document.getElementById('mcost').textContent=cost.toFixed(6);
  if(i+1<S.steps.length){const nxt=S.steps[i+1].incoming;
   if(nxt.startsWith('OBSERVATION')){const ob=document.createElement('div');
    ob.className='obs'+(nxt.includes('ERROR')?' err':'');ob.textContent=nxt;
    d.append(ob);await sleep(800/sp());}}
 }
 const v=document.getElementById('verdict');v.style.display='block';
 v.textContent='SESSION END — '+S.result;window.scrollTo(0,document.body.scrollHeight);
}
document.getElementById('play').onclick=e=>{playing=!playing;
 e.target.textContent=playing?'⏸ Pause':'▶ Play';
 if(playing&&i===0&&!document.querySelector('.step'))run();};
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--phoenix", default=os.environ.get("PHOENIX_URL", "http://localhost:6006"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    data = build_session(fetch_spans(args.phoenix), args.session)
    out = args.out or f"replay_{re.sub(r'[^A-Za-z0-9_-]', '_', data['session'])}.html"
    page = (TEMPLATE
            .replace("__DATA__", json.dumps(data))
            .replace("__SESSION__", html.escape(data["session"]))
            .replace("__STUDENT__", html.escape(data["student"]))
            .replace("__MODEL__", html.escape(data["steps"][0]["model"] if data["steps"] else "?"))
            .replace("__TASK__", html.escape(data["task"]))
            .replace("__NSTEPS__", str(len(data["steps"]))))
    open(out, "w").write(page)
    print(f"wrote {out}  ({len(data['steps'])} steps)")


if __name__ == "__main__":
    main()
