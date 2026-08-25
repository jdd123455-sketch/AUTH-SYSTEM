import os
import random
import sqlite3
import string
import time
import hashlib
import hmac
from datetime import datetime, timedelta
from functools import wraps

from authlib.integrations.flask_client import OAuth
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
    abort,
)
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Secret Keys & Environment Configurations
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "hsl_corp_ultra_secure_key_2026_x89")
APP_SALT = "HSL_SECURE_SALT_v2"

# Cookie Security Configuration
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False, # Production me True rakhein (HTTPS Required)
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4)
)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

PAID_USERS = ["js7876839939@gmail.com"]

oauth = OAuth(app)
google = oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    client_kwargs={"scope": "openid email profile"},
)

# ----------------- SECURITY & RATE LIMITING LAYER ----------------- #
REQUEST_HISTORY = {}

def rate_limit(max_requests=10, window_seconds=60):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            ip = request.remote_addr
            now = time.time()
            if ip not in REQUEST_HISTORY:
                REQUEST_HISTORY[ip] = []
            REQUEST_HISTORY[ip] = [t for t in REQUEST_HISTORY[ip] if now - t < window_seconds]
            if len(REQUEST_HISTORY[ip]) >= max_requests:
                return jsonify({
                    "status": "rate_limited",
                    "message": "Too many attempts. Request blocked due to security policies."
                }), 429
            REQUEST_HISTORY[ip].append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator

@app.after_request
def apply_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# ----------------- DATABASE SETUP ----------------- #
def init_db():
    con = sqlite3.connect("hsl.db")
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS apps (id INTEGER PRIMARY KEY, name TEXT,"
        " token TEXT UNIQUE, owner_email TEXT, created_at TEXT)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS keys (id INTEGER PRIMARY KEY, key_text TEXT"
        " UNIQUE, app_token TEXT, status TEXT, hwid TEXT, used_by TEXT,"
        " created_at TEXT)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT,"
        " hwid TEXT, app_token TEXT, key_text TEXT, first_seen TEXT)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS tool_users (id INTEGER PRIMARY KEY, username"
        " TEXT UNIQUE, password TEXT, app_token TEXT, status TEXT, hwid TEXT,"
        " created_at TEXT)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, app_token TEXT,"
        " username TEXT, action TEXT, ip TEXT, timestamp TEXT)"
    )
    con.commit()
    con.close()

init_db()

def db(query, params=(), fetch=False):
    con = sqlite3.connect("hsl.db")
    cur = con.cursor()
    cur.execute(query, params)
    data = cur.fetchall() if fetch else None
    con.commit()
    con.close()
    return data

def log_event(app_token, username, action):
    ip = request.remote_addr
    db("INSERT INTO logs (app_token, username, action, ip, timestamp) VALUES (?,?,?,?,?)",
       (app_token, username, action, ip, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

# ----------------- TEMPLATES & STYLES ----------------- #
COMMON_HEAD = """
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body { background: #030712; cursor: none; font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif; }
  #c { position: fixed; inset: 0; z-index: 0; pointer-events: none; }
  .glass { backdrop-filter: blur(25px); background: rgba(10, 15, 30, 0.75); border: 1px solid rgba(56, 189, 248, 0.15); }
  .glass-card { background: rgba(15, 23, 42, 0.65); border: 1px solid rgba(56, 189, 248, 0.12); backdrop-filter: blur(16px); transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); }
  .glass-card:hover { border-color: rgba(56, 189, 248, 0.4); transform: translateY(-2px); box-shadow: 0 10px 30px -10px rgba(56,189,248,0.2); }
  
  /* STYLISH CROSSHAIR + ORBIT CURSOR ANIMATION */
  #cursor-dot { position: fixed; width: 6px; height: 6px; background: #38bdf8; border-radius: 50%; pointer-events: none; z-index: 9999; transform: translate(-50%, -50%); box-shadow: 0 0 12px #38bdf8, 0 0 24px #38bdf8; }
  #cursor-crosshair { position: fixed; width: 26px; height: 26px; border: 1px solid rgba(56, 189, 248, 0.4); border-radius: 50%; pointer-events: none; z-index: 9998; transform: translate(-50%, -50%); transition: width 0.2s, height 0.2s, border-color 0.2s; }
  #cursor-crosshair::before, #cursor-crosshair::after { content: ''; position: absolute; background: rgba(56, 189, 248, 0.8); }
  #cursor-crosshair::before { top: 50%; left: -5px; width: 36px; height: 1px; transform: translateY(-50%); }
  #cursor-crosshair::after { left: 50%; top: -5px; height: 36px; width: 1px; transform: translateX(-50%); }
  
  #cursor-orbit { position: fixed; width: 48px; height: 48px; border: 1px dashed rgba(99, 102, 241, 0.6); border-radius: 50%; pointer-events: none; z-index: 9997; transform: translate(-50%, -50%); animation: spinOrbit 8s linear infinite; }
  @keyframes spinOrbit { 0% { transform: translate(-50%, -50%) rotate(0deg); } 100% { transform: translate(-50%, -50%) rotate(360deg); } }
</style>
"""

CURSOR_SCRIPT = """
<div id="cursor-dot"></div>
<div id="cursor-crosshair"></div>
<div id="cursor-orbit"></div>
<script>
  const dot = document.getElementById('cursor-dot');
  const cross = document.getElementById('cursor-crosshair');
  const orbit = document.getElementById('cursor-orbit');
  let mx = 0, my = 0, cx = 0, cy = 0;

  window.addEventListener('mousemove', (e) => {
    mx = e.clientX;
    my = e.clientY;
    dot.style.left = mx + 'px';
    dot.style.top = my + 'px';
  });

  function renderCursor() {
    cx += (mx - cx) * 0.2;
    cy += (my - cy) * 0.2;
    cross.style.left = cx + 'px';
    cross.style.top = cy + 'px';
    orbit.style.left = cx + 'px';
    orbit.style.top = cy + 'px';
    requestAnimationFrame(renderCursor);
  }
  renderCursor();

  const c = document.getElementById('c'), x = c.getContext('2d');
  function R(){ c.width = innerWidth; c.height = innerHeight; }
  R(); onresize = R;
  let p = [];
  for(let i=0; i<90; i++) p.push({ x: Math.random()*c.width, y: Math.random()*c.height, r: Math.random()*1.5+0.5, vy: Math.random()*0.5+0.2, opacity: Math.random()*0.6+0.2 });

  function A(){
    x.clearRect(0, 0, c.width, c.height);
    p.forEach(o => {
      o.y -= o.vy;
      if(o.y < 0){ o.y = c.height; o.x = Math.random()*c.width; }
      x.beginPath();
      x.arc(o.x, o.y, o.r, 0, 6.28);
      x.fillStyle = `rgba(56, 189, 248, ${o.opacity})`;
      x.shadowBlur = 10;
      x.shadowColor = '#38bdf8';
      x.fill();
    });
    requestAnimationFrame(A);
  }
  A();
</script>
"""

LANDING = """<!DOCTYPE html><html><head>""" + COMMON_HEAD + """</head><body class="text-white overflow-x-hidden relative"><canvas id="c"></canvas>
<nav class="relative z-10 flex justify-between items-center px-8 py-4 bg-black/50 backdrop-blur-md border-b border-sky-500/10">
  <div class="flex items-center gap-3">
    <div class="w-9 h-9 bg-gradient-to-r from-sky-400 to-indigo-600 rounded-xl flex items-center justify-center shadow-[0_0_15px_#38bdf8]">🛡️</div>
    <div><p class="font-black text-sm tracking-wider">HSL CORP</p><p class="text-[9px] text-sky-400 font-bold tracking-widest">KEYAUTH STYLE AUTHENTICATION SYSTEM</p></div>
  </div>
  <div class="flex gap-3">
    <a href="/login" class="bg-zinc-900/80 hover:bg-zinc-800 border border-zinc-700 px-5 py-2 rounded-full text-xs font-semibold transition">Sign In</a>
    <a href="/login" class="bg-gradient-to-r from-sky-400 to-indigo-600 hover:opacity-90 px-5 py-2 rounded-full text-xs font-bold shadow-[0_0_20px_rgba(56,189,248,0.5)] transition">Dashboard</a>
  </div>
</nav>

<div class="relative z-10 flex flex-col items-center text-center pt-24 px-4">
  <div class="inline-block border border-sky-500/30 bg-sky-500/10 px-4 py-1.5 rounded-full text-xs text-sky-300 font-semibold mb-6 shadow-[0_0_15px_rgba(56,189,248,0.2)]">⚡ Next-Gen Secure Software Panel</div>
  <h1 class="text-6xl md:text-7xl font-black bg-gradient-to-r from-sky-300 via-cyan-400 to-indigo-500 bg-clip-text text-transparent drop-shadow-[0_0_35px_rgba(56,189,248,0.4)] max-w-4xl leading-tight">HSL CORP AUTH</h1>
  <p class="text-zinc-400 mt-5 font-medium text-base max-w-xl">Ultimate Hardware-Locked Licensing & Application Protection Infrastructure.</p>
  <a href="/login" class="bg-gradient-to-r from-sky-400 to-indigo-600 hover:scale-105 px-8 py-3.5 rounded-2xl text-sm font-bold shadow-[0_0_30px_rgba(56,189,248,0.6)] mt-8 transition duration-300">🚀 Get Started</a>
</div>
""" + CURSOR_SCRIPT + """
</body></html>"""

LOGIN = """<!DOCTYPE html><html><head>""" + COMMON_HEAD + """</head><body class="flex items-center justify-center h-screen overflow-hidden relative"><canvas id="c"></canvas>
<div class="relative z-10 w-[420px] glass rounded-[28px] p-9 text-center shadow-[0_0_60px_rgba(56,189,248,0.2)]">
  <div class="w-16 h-16 bg-gradient-to-r from-sky-400 to-indigo-600 rounded-2xl mx-auto flex items-center justify-center shadow-[0_0_25px_#38bdf8]">🛡️</div>
  <h1 class="font-black text-2xl mt-5 text-white bg-gradient-to-r from-sky-300 to-indigo-400 bg-clip-text text-transparent">HSL CORP AUTH</h1>
  <p class="text-xs text-zinc-400 mt-1">Secure OAuth Sign-In Portal</p>
  <a href="/auth/google" class="mt-8 w-full bg-white hover:bg-zinc-100 text-black rounded-xl py-3.5 flex justify-center items-center gap-3 font-bold text-sm shadow-lg hover:scale-[1.02] transition">
    <img src="https://www.svgrepo.com/show/475656/google-color.svg" width=20> Continue with Google
  </a>
</div>
""" + CURSOR_SCRIPT + """
</body></html>"""

DASHBOARD_HTML = """<!DOCTYPE html><html><head>""" + COMMON_HEAD + """
<style>
  .side-active{ background: rgba(56,189,248,0.15); border: 1px solid rgba(56,189,248,0.4); color: #38bdf8 !important; font-weight: bold; }
</style>
</head>
<body class="flex h-screen text-white overflow-hidden relative"><canvas id="c"></canvas>

<div class="w-[260px] bg-black/80 backdrop-blur-xl border-r border-white/10 flex flex-col relative z-10">
  <div class="p-5 flex items-center gap-3 border-b border-white/10">
    <div class="w-9 h-9 bg-gradient-to-r from-sky-400 to-indigo-600 rounded-xl flex items-center justify-center shadow-[0_0_12px_#38bdf8]">🛡️</div>
    <div><p class="font-black text-sm tracking-wide">HSL CORP</p><p class="text-[9px] text-sky-400 font-bold">KeyAuth Console</p></div>
  </div>
  
  <div class="p-3 space-y-1 text-xs" id="sidebar">
    <button onclick="showTab('overview')" id="btn-overview" class="side-active w-full text-left rounded-xl px-4 py-2.5 transition">🏠 Overview</button>
    <button onclick="showTab('applications')" id="btn-applications" class="w-full text-left text-zinc-400 hover:text-white px-4 py-2.5 transition">📦 Applications</button>
    <button onclick="showTab('tool_users')" id="btn-tool_users" class="w-full text-left text-zinc-400 hover:text-white px-4 py-2.5 transition">👤 Users ({{tool_user_count}}/{{limit_text}})</button>
    <button onclick="showTab('keys')" id="btn-keys" class="w-full text-left text-zinc-400 hover:text-white px-4 py-2.5 transition">🔑 License Keys</button>
    <button onclick="showTab('logs')" id="btn-logs" class="w-full text-left text-zinc-400 hover:text-white px-4 py-2.5 transition">📜 Session Audit Logs</button>
    <button onclick="showTab('integrate')" id="btn-integrate" class="w-full text-left text-zinc-400 hover:text-white px-4 py-2.5 transition">🔌 Integration Code</button>
    <button onclick="showTab('billing')" id="btn-billing" class="w-full text-left text-zinc-400 hover:text-white px-4 py-2.5 transition">💎 Billing / Upgrade</button>
  </div>
  
  <div class="mt-auto p-4 border-t border-white/10 flex items-center gap-3 bg-black/40">
    <img src="https://ui-avatars.com/api/?name={{name}}&background=38bdf8&color=fff" class="w-8 h-8 rounded-full border border-sky-400/40">
    <div><p class="text-[11px] font-bold truncate w-[110px]">{{email}}</p><p class="text-[9px] {{plan_color}} font-bold">{{plan_text}}</p></div>
    <a href="/logout" class="ml-auto text-[11px] text-red-400 hover:text-red-300 font-semibold">Logout</a>
  </div>
</div>

<div class="flex-1 overflow-y-auto relative z-10">
  <div class="h-14 bg-black/50 backdrop-blur-md border-b border-white/10 flex items-center justify-between px-8">
    <div class="flex items-center gap-4 text-xs font-semibold text-sky-300">
      <span class="flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> KeyAuth Status: Operational</span>
      <span class="text-zinc-600">|</span>
      <span>API Ping: <span class="text-emerald-400">18ms</span></span>
    </div>
    <button onclick="showTab('billing')" class="text-xs bg-gradient-to-r from-sky-400 to-indigo-600 hover:opacity-90 text-white px-5 py-2 rounded-full font-bold shadow-[0_0_15px_rgba(56,189,248,0.4)] transition">Upgrade to Unlimited</button>
  </div>
  
  <div class="p-8">
    <div id="tab-overview">
      <h1 class="text-2xl font-black">Dashboard Analytics</h1>
      <div class="mt-6 grid grid-cols-4 gap-4">
        <div class="glass-card rounded-2xl p-5"><p class="text-[10px] font-bold text-sky-400 tracking-wider">TOTAL USERS</p><p class="text-2xl font-black mt-2">{{tool_user_count}}</p></div>
        <div class="glass-card rounded-2xl p-5"><p class="text-[10px] font-bold text-emerald-400 tracking-wider">HWID BOUND</p><p class="text-2xl font-black mt-2">{{hwid_bound_count}}</p></div>
        <div class="glass-card rounded-2xl p-5"><p class="text-[10px] font-bold text-rose-400 tracking-wider">BANNED USERS</p><p class="text-2xl font-black mt-2">{{banned_count}}</p></div>
        <div class="glass-card rounded-2xl p-5"><p class="text-[10px] font-bold text-indigo-400 tracking-wider">TOTAL KEYS</p><p class="text-2xl font-black mt-2">{{keys_count}}</p></div>
      </div>

      <div class="mt-6 grid grid-cols-[1.3fr_1fr_0.7fr] gap-4">
        <div class="glass-card rounded-2xl p-5"><p class="text-[10px] font-bold text-sky-400 tracking-wider">ACTIVE APPLICATION</p><select id="appSelect" onchange="selectApp(this.value)" class="bg-black/80 border border-white/20 rounded-xl px-3 py-2.5 text-xs mt-3 w-full font-semibold focus:outline-none focus:border-sky-400">{{app_options}}</select></div>
        <div class="glass-card rounded-2xl p-5"><p class="text-[10px] font-bold text-zinc-400 tracking-wider">MASTER APP TOKEN</p><div class="mt-3 flex justify-between items-center bg-black/80 rounded-xl px-3 py-2 border border-white/10"><p id="tokenDisplay" class="text-xs font-mono text-zinc-300 truncate">{{active_token}}</p><button onclick="copyToken()" class="text-[10px] bg-gradient-to-r from-sky-400 to-indigo-600 px-3 py-1.5 rounded-lg font-bold hover:scale-105 transition">Copy</button></div></div>
        <div class="glass-card rounded-2xl p-5"><p class="text-[10px] font-bold text-zinc-400 tracking-wider">PLAN LIMIT</p><p class="text-xs font-bold mt-3">{{tool_user_count}} / {{limit_text}} Used</p><div class="w-full bg-zinc-800 h-2 mt-3 rounded-full overflow-hidden"><div class="bg-gradient-to-r from-sky-400 to-indigo-600 h-2 rounded-full" style="width:{{percent}}%"></div></div></div>
      </div>
      
      <div class="mt-6 glass-card rounded-2xl p-7">
        <p class="text-base font-bold text-white">+ Create New Secure User</p>
        <div class="flex gap-3 mt-4">
          <input id="newUsername" placeholder="Username" class="flex-1 bg-black/80 border border-white/15 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-sky-400">
          <input id="newPassword" placeholder="Password" class="flex-1 bg-black/80 border border-white/15 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-sky-400">
        </div>
        <button onclick="createUser()" class="mt-4 w-full bg-gradient-to-r from-sky-400 to-indigo-600 hover:opacity-90 py-3 rounded-xl text-sm font-bold shadow-[0_0_20px_rgba(56,189,248,0.4)] transition">Create User</button>
      </div>
    </div>

    <div id="tab-applications" class="hidden"><h1 class="text-2xl font-black">Applications</h1><div class="glass-card mt-6 rounded-2xl p-7"><div class="space-y-3 mb-6">{{app_list_html}}</div><div class="border-t border-white/10 pt-5"><p class="text-base font-bold">+ Create New App</p><input id="newAppName" placeholder="App Name" class="mt-3 w-full bg-black/80 border border-white/15 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-sky-400"><button onclick="createApp()" class="mt-4 w-full bg-gradient-to-r from-sky-400 to-indigo-600 py-3 rounded-xl text-sm font-bold shadow-[0_0_20px_rgba(56,189,248,0.4)] transition">Create Application</button></div></div></div>

    <div id="tab-tool_users" class="hidden"><h1 class="text-2xl font-black">Registered Users ({{tool_user_count}}/{{limit_text}})</h1><div class="glass-card mt-6 rounded-2xl p-6"><div class="space-y-3 text-xs font-mono">{{tool_users_list_html}}</div></div></div>

    <div id="tab-keys" class="hidden"><h1 class="text-2xl font-black">License Keys</h1><div class="glass-card mt-6 rounded-2xl p-6"><div class="space-y-3 text-xs font-mono">{{keys_list_html}}</div></div></div>

    <div id="tab-logs" class="hidden"><h1 class="text-2xl font-black">KeyAuth Session Audit Trail</h1><div class="glass-card mt-6 rounded-2xl p-6"><div class="space-y-3 text-xs font-mono">{{logs_list_html}}</div></div></div>

    <div id="tab-integrate" class="hidden"><h1 class="text-2xl font-black">Secure Client Integration</h1><div class="glass-card mt-6 rounded-2xl p-7">
      <p class="text-xs font-bold text-sky-300">KeyAuth Encrypted Payload Verification Script (Anti-Fiddler Engine)</p>
      <pre class="mt-4 bg-black/90 border border-white/10 rounded-xl p-5 text-xs font-mono overflow-x-auto text-emerald-400 leading-relaxed">
import requests, subprocess, hashlib

MY_APP_TOKEN = "{{active_token}}"
AUTH_URL = "https://YOUR-DOMAIN.com/api/auth_login"

def get_hwid():
    try:
        r = subprocess.check_output('wmic baseboard get serialnumber', shell=True).decode().split('\\n')[1].strip()
        return r
    except:
        return "UNKNOWN_HWID"

def secure_login(username, password):
    hwid = get_hwid()
    raw_sig = f"{username}:{hwid}:{MY_APP_TOKEN}"
    sig = hashlib.sha256(raw_sig.encode()).hexdigest()
    
    payload = {
        "username": username,
        "password": password,
        "hwid": hwid,
        "token": MY_APP_TOKEN,
        "sig": sig
    }
    
    try:
        res = requests.post(AUTH_URL, json=payload, timeout=10)
        return res.json()
    except Exception as e:
        return {"status": "error", "message": "Connection Tampered"}
</pre>
    </div></div>

    <div id="tab-billing" class="hidden"><h1 class="text-2xl font-black">Billing / Plans</h1>
      <div class="grid grid-cols-2 gap-6 mt-6">
        <div class="glass-card rounded-2xl p-7"><p class="font-bold text-sm text-zinc-300">FREE PLAN</p><p class="text-4xl font-black mt-2">₹0</p><p class="text-xs text-zinc-400 mt-3 leading-relaxed">✓ 10 Users / Keys Only<br>✓ 1 Application<br>✓ HWID Lock</p><p class="mt-6 text-xs bg-zinc-800/80 rounded-full px-4 py-1.5 inline-block font-semibold">Current: {{plan_text}}</p></div>
        <div class="glass-card rounded-2xl p-7 border-sky-400/50 bg-sky-500/10"><p class="font-bold text-sm text-sky-400">PRO UNLIMITED</p><p class="text-4xl font-black mt-2">₹499</p><p class="text-xs text-zinc-200 mt-3 leading-relaxed">✓ Unlimited Users<br>✓ Unlimited Apps<br>✓ Unlimited Keys<br>✓ Anti-Crack Engine</p><a href="https://wa.me/919999999999" target="_blank" class="mt-6 block text-center bg-gradient-to-r from-sky-400 to-indigo-600 py-3 rounded-xl text-sm font-bold shadow-[0_0_25px_rgba(56,189,248,0.5)] transition">Buy on WhatsApp</a></div>
      </div>
    </div>
  </div>
</div>
""" + CURSOR_SCRIPT + """
<script>
function showTab(name){
    document.querySelectorAll('[id^="tab-"]').forEach(d=>d.classList.add('hidden'));
    document.getElementById('tab-'+name).classList.remove('hidden');
    document.querySelectorAll('#sidebar button').forEach(b=>{b.classList.remove('side-active');b.classList.add('text-zinc-400')});
    let btn=document.getElementById('btn-'+name);
    if(btn){btn.classList.add('side-active');btn.classList.remove('text-zinc-400')}
}

async function createApp(){
    let name=document.getElementById('newAppName').value.trim();
    if(!name){alert('Enter Name!');return;}
    let res=await fetch('/api/create_app',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})});
    let data=await res.json();
    if(data.error){alert(data.error);} 
    else{alert('App Created! Token: '+data.token);location.reload();}
}

function copyToken(){
    let t=document.getElementById('tokenDisplay').innerText;
    navigator.clipboard.writeText(t);
    alert('Copied: '+t);
}

function selectApp(token){
    document.getElementById('tokenDisplay').innerText=token;
}

async function createUser(){
    let u=document.getElementById('newUsername').value.trim();
    let p=document.getElementById('newPassword').value.trim();
    let token=document.getElementById('tokenDisplay').innerText;
    if(!u||!p){alert('Fill fields!');return;}
    let res=await fetch('/api/create_user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p,app_token:token})});
    let data=await res.json();
    alert(data.message);
    location.reload();
}

async function deleteUser(username){
    if(!confirm('Delete '+username+'?'))return;
    let res=await fetch('/api/delete_user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:username})});
    let data=await res.json();
    alert(data.message);
    location.reload();
}

async function resetHwid(username){
    let res=await fetch('/api/reset_hwid',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:username})});
    let data=await res.json();
    alert(data.message);
    location.reload();
}

async function toggleBan(username){
    let res=await fetch('/api/toggle_ban',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:username})});
    let data=await res.json();
    alert(data.message);
    location.reload();
}

async function editUser(oldU, oldP){
    let newU = prompt("New Username:", oldU); if(newU===null) return;
    let newP = prompt("New Password:", oldP); if(newP===null) return;
    let res=await fetch('/api/edit_user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old_username:oldU, new_username:newU.trim(), new_password:newP.trim()})});
    let data=await res.json();
    alert(data.message);
    location.reload();
}
</script>
</body></html>
"""

# ----------------- ROUTES & API ENDPOINTS ----------------- #

@app.route("/")
def home():
    return render_template_string(LANDING)

@app.route("/login")
def login():
    return render_template_string(LOGIN)

@app.route("/auth/google")
@rate_limit(max_requests=5, window_seconds=60)
def auth_google():
    redirect_uri = request.url_root.rstrip("/") + "/auth/callback"
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/callback")
def callback():
    try:
        token = google.authorize_access_token()
        user = token.get("userinfo") or google.get(
            "https://openidconnect.googleapis.com/v1/userinfo"
        ).json()
        session["user"] = user
        return redirect("/dashboard")
    except Exception:
        return redirect("/login")

@app.route("/dashboard")
def dash():
    if "user" not in session:
        return redirect("/login")
    email = session["user"]["email"]
    is_paid = email in PAID_USERS
    limit_text = "Unlimited" if is_paid else "10"
    plan_text = "PRO UNLIMITED" if is_paid else "FREE"
    plan_color = "text-emerald-400" if is_paid else "text-amber-400"
    
    apps = db("SELECT * FROM apps WHERE owner_email=?", (email,), True)
    if not apps:
        app_options = "<option>No Apps Created</option>"
        active_token = "Create an app to get Token"
        app_list_html = "<p class='text-zinc-500 text-sm'>No apps yet - Create one below</p>"
    else:
        app_options = "".join([f"<option value='{a[2]}'>{a[1]}</option>" for a in apps])
        active_token = apps[0][2]
        app_list_html = "".join([
            f"<div class='bg-black/80 border border-white/10 rounded-xl px-4 py-3 flex justify-between items-center'><span>{a[1]}</span><span class='text-xs text-zinc-500 font-mono'>{a[2][:20]}...</span></div>"
            for a in apps
        ])
        
    keys = db("SELECT * FROM keys WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True) if apps else []
    keys_count = len(keys)
    keys_list_html = "".join([
        f"<div class='flex justify-between bg-black/80 border border-white/10 rounded-xl px-4 py-3'><span>{k[1]}</span><span class='{'text-emerald-400' if k[3] == 'unused' else 'text-rose-400'}'>● {k[3]}</span></div>"
        for k in keys
    ]) if keys else "<p class='text-center text-zinc-600 text-xs mt-10'>No keys</p>"

    tool_users = db("SELECT * FROM tool_users WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True) if apps else []
    tool_user_count = len(tool_users)
    hwid_bound_count = sum(1 for u in tool_users if u[5])
    banned_count = sum(1 for u in tool_users if u[4] == "banned")
    percent = 10 if tool_user_count == 0 else min(int(tool_user_count / (999999 if is_paid else 10) * 100), 100)
    
    tool_users_list_html = ""
    for u in tool_users:
        hwid_short = (u[5][:15] + "...") if u[5] else "Not Bound"
        status_color = "text-emerald-400" if u[4] == "active" else "text-rose-400"
        ban_text = "Ban" if u[4] == "active" else "Unban"
        tool_users_list_html += f"""
        <div class='flex justify-between items-center bg-black/80 border border-white/10 rounded-xl px-4 py-3 mb-2'>
            <div>
                <span class='text-white font-bold'>{u[1]}</span><span class='text-zinc-500'> / {u[2]}</span><br>
                <span class='text-[10px] text-zinc-500'>HWID: {hwid_short} | Status: <span class='{status_color}'>{u[4].upper()}</span></span>
            </div>
            <div class='flex gap-2 flex-wrap justify-end max-w-[60%]'>
                <button onclick="editUser('{u[1]}','{u[2]}')" class='bg-blue-900/50 border border-blue-500/30 px-3 py-1 rounded-lg text-[10px] hover:bg-blue-800 transition'>Edit</button>
                <button onclick="toggleBan('{u[1]}')" class='bg-amber-900/50 border border-amber-500/30 px-3 py-1 rounded-lg text-[10px] hover:bg-amber-800 transition'>{ban_text}</button>
                <button onclick="resetHwid('{u[1]}')" class='bg-zinc-800 border border-white/10 px-3 py-1 rounded-lg text-[10px] hover:bg-zinc-700 transition'>Reset HWID</button>
                <button onclick="deleteUser('{u[1]}')" class='bg-rose-900/50 border border-rose-500/30 px-3 py-1 rounded-lg text-[10px] hover:bg-rose-800 transition'>Delete</button>
            </div>
        </div>
        """
    if not tool_users_list_html:
        tool_users_list_html = "<p class='text-center text-zinc-600 text-xs mt-10'>No registered users.</p>"

    logs = db("SELECT * FROM logs WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?) ORDER BY id DESC LIMIT 20", (email,), True) if apps else []
    logs_list_html = "".join([
        f"<div class='flex justify-between bg-black/80 border border-white/10 rounded-xl px-4 py-2.5 text-[11px]'><span class='text-sky-300 font-bold'>[{l[5]}]</span><span>{l[2]} ({l[3]})</span><span class='text-zinc-500'>IP: {l[4]}</span></div>"
        for l in logs
    ]) if logs else "<p class='text-center text-zinc-600 text-xs mt-10'>No authentication audit logs found.</p>"

    html = (
        DASHBOARD_HTML.replace("{{name}}", session["user"].get("name", "User"))
        .replace("{{email}}", email)
        .replace("{{app_options}}", app_options)
        .replace("{{active_token}}", active_token)
        .replace("{{app_list_html}}", app_list_html)
        .replace("{{keys_list_html}}", keys_list_html)
        .replace("{{keys_count}}", str(keys_count))
        .replace("{{tool_user_count}}", str(tool_user_count))
        .replace("{{hwid_bound_count}}", str(hwid_bound_count))
        .replace("{{banned_count}}", str(banned_count))
        .replace("{{limit_text}}", limit_text)
        .replace("{{plan_text}}", plan_text)
        .replace("{{plan_color}}", plan_color)
        .replace("{{percent}}", str(percent))
        .replace("{{tool_users_list_html}}", tool_users_list_html)
        .replace("{{logs_list_html}}", logs_list_html)
    )
    return render_template_string(html)

def check_limit(email):
    if email in PAID_USERS:
        return False
    tool_users = db("SELECT COUNT(*) FROM tool_users WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True)
    keys = db("SELECT COUNT(*) FROM keys WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True)
    total = (tool_users[0][0] if tool_users else 0) + (keys[0][0] if keys else 0)
    return total >= 10

@app.route("/api/create_app", methods=["POST"])
def api_create_app():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    email = session["user"]["email"]
    apps = db("SELECT COUNT(*) FROM apps WHERE owner_email=?", (email,), True)
    if email not in PAID_USERS and apps[0][0] >= 1:
        return jsonify({"error": "Free Plan limit reached."})
    name = request.json.get("name", "").strip()
    if not name:
        return jsonify({"error": "Invalid app name"})
    token = "HSL_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=24))
    db("INSERT INTO apps (name, token, owner_email, created_at) VALUES (?,?,?,?)", (name, token, email, datetime.now().isoformat()))
    return jsonify({"token": token})

@app.route("/api/create_user", methods=["POST"])
def api_create_user():
    data = request.json or {}
    app_token = data.get("app_token")
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password or not app_token:
        return jsonify({"message": "Missing required fields!"})

    app_data = db("SELECT owner_email FROM apps WHERE token=?", (app_token,), True)
    if not app_data:
        return jsonify({"message": "Invalid App Token!"})

    email = app_data[0][0]
    if check_limit(email):
        return jsonify({"message": "Plan limit reached!"})

    try:
        db("INSERT INTO tool_users (username, password, app_token, status, created_at) VALUES (?,?,?,?,?)",
           (username, password, app_token, "active", datetime.now().isoformat()))
        log_event(app_token, username, "USER_CREATED")
        return jsonify({"message": f"User Created: {username}"}), 200
    except Exception:
        return jsonify({"message": "Username already exists!"})

@app.route("/api/delete_user", methods=["POST"])
def api_delete_user():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    username = request.json.get("username")
    db("DELETE FROM tool_users WHERE username=?", (username,))
    return jsonify({"message": "Deleted"})

@app.route("/api/reset_hwid", methods=["POST"])
def api_reset_hwid():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    username = request.json.get("username")
    db("UPDATE tool_users SET hwid=NULL, status='active' WHERE username=?", (username,))
    return jsonify({"message": f"HWID Reset for {username}"})

@app.route("/api/toggle_ban", methods=["POST"])
def api_toggle_ban():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    username = request.json.get("username")
    res = db("SELECT status FROM tool_users WHERE username=?", (username,), True)
    if not res: return jsonify({"message": "User not found"})
    new_status = "banned" if res[0][0] == "active" else "active"
    db("UPDATE tool_users SET status=? WHERE username=?", (new_status, username))
    return jsonify({"message": f"{username} status updated to {new_status.upper()}"})

@app.route("/api/edit_user", methods=["POST"])
def api_edit_user():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    old_u = request.json.get("old_username")
    new_u = request.json.get("new_username") or old_u
    new_p = request.json.get("new_password")
    try:
        db("UPDATE tool_users SET username=?, password=? WHERE username=?", (new_u, new_p, old_u))
        return jsonify({"message": f"Updated {old_u}"})
    except Exception:
        return jsonify({"message": "Update failed."})

# ----------------- ANTI-CRACK API ENDPOINTS ----------------- #

@app.route("/api/auth_login", methods=["POST"])
@rate_limit(max_requests=10, window_seconds=60)
def api_auth_login():
    data = request.json or {}
    
    username = data.get("username")
    password = data.get("password")
    hwid = data.get("hwid")
    token = data.get("token")
    client_sig = data.get("sig")
    
    if not username or not password or not token or not hwid:
        return jsonify({"status": "invalid", "message": "Malformed request parameters"}), 400

    expected_sig = hashlib.sha256(f"{username}:{hwid}:{token}".encode()).hexdigest()
    if client_sig and client_sig != expected_sig:
        log_event(token, username or "UNKNOWN", "TAMPER_ATTEMPT")
        return jsonify({"status": "tampered", "message": "Request payload tampered!"}), 403

    res = db("SELECT * FROM tool_users WHERE username=? AND password=? AND app_token=?", (username, password, token), True)
    if not res:
        log_event(token, username, "FAILED_LOGIN")
        return jsonify({"status": "invalid", "message": "Incorrect credentials"})
        
    user_row = res[0]
    if user_row[4] == "banned":
        log_event(token, username, "BANNED_ATTEMPT")
        return jsonify({"status": "banned", "message": "Account suspended"})
        
    if not user_row[5]:
        db("UPDATE tool_users SET hwid=?, status='active' WHERE username=?", (hwid, username))
        log_event(token, username, "HWID_BOUND")
        return jsonify({"status": "valid", "message": "HWID Bound Successfully"})
    else:
        if user_row[5] == hwid:
            log_event(token, username, "SUCCESSFUL_AUTH")
            return jsonify({"status": "valid", "message": "Authentication Success"})
        else:
            log_event(token, username, "HWID_MISMATCH")
            return jsonify({"status": "hwid_mismatch", "message": "Hardware mismatch detected"})

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(port=5000, debug=False)