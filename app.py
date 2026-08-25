import os
import random
import sqlite3
import string
import time
import hashlib
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
)
from werkzeug.middleware.proxy_fix import ProxyFix

# ==========================================
# APP INITIALIZATION & SECURITY CONFIG
# ==========================================

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY", 
    "hsl_corp_ultra_brutal_key_2026_x89_production"
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4)
)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

PAID_USERS = [
    "js7876839939@gmail.com"
]

oauth = OAuth(app)
google = oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    client_kwargs={
        "scope": "openid email profile"
    },
)

# ==========================================
# RATE LIMITING & SECURITY MIDDLEWARE
# ==========================================

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
                return jsonify({"status": "rate_limited", "message": "Access Denied: Rate Limit Triggered."}), 429
            REQUEST_HISTORY[ip].append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator

@app.after_request
def apply_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# ==========================================
# DATABASE ENGINE & SCHEMAS
# ==========================================

def init_db():
    con = sqlite3.connect("hsl.db")
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS apps (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT, 
            token TEXT UNIQUE, 
            owner_email TEXT, 
            version TEXT DEFAULT '2.4.0',
            status TEXT DEFAULT 'ONLINE',
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            key_text TEXT UNIQUE, 
            app_token TEXT, 
            status TEXT, 
            hwid TEXT, 
            used_by TEXT, 
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tool_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            username TEXT UNIQUE, 
            password TEXT, 
            app_token TEXT, 
            status TEXT, 
            hwid TEXT, 
            last_login TEXT,
            created_at TEXT
        )
    """)
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

# ==========================================
# BRUTAL CYBERPUNK STYLES & CURSOR
# ==========================================

COMMON_HEAD = """
<script src="https://cdn.tailwindcss.com"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap');
  
  body { 
    background: #020408; 
    cursor: none; 
    font-family: 'JetBrains Mono', monospace; 
  }
  
  #c { 
    position: fixed; 
    inset: 0; 
    z-index: 0; 
    pointer-events: none; 
  }
  
  .glass-brutal { 
    background: rgba(3, 7, 18, 0.85); 
    border: 1px solid rgba(239, 68, 68, 0.25); 
    box-shadow: 0 0 25px rgba(239, 68, 68, 0.08), inset 0 0 15px rgba(239, 68, 68, 0.03); 
    backdrop-filter: blur(16px); 
  }
  
  .glass-card { 
    background: rgba(5, 10, 25, 0.75); 
    border: 1px solid rgba(239, 68, 68, 0.2); 
    backdrop-filter: blur(12px); 
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1); 
  }
  
  .glass-card:hover { 
    border-color: rgba(239, 68, 68, 0.7); 
    transform: translateY(-3px); 
    box-shadow: 0 10px 30px -5px rgba(239, 68, 68, 0.3); 
  }
  
  #cursor-dot { 
    position: fixed; 
    width: 8px; 
    height: 8px; 
    background: #ef4444; 
    border-radius: 50%; 
    pointer-events: none; 
    z-index: 9999; 
    transform: translate(-50%, -50%); 
    box-shadow: 0 0 15px #ef4444, 0 0 30px #ef4444; 
  }
  
  #cursor-crosshair { 
    position: fixed; 
    width: 36px; 
    height: 36px; 
    border: 1px solid rgba(239, 68, 68, 0.8); 
    pointer-events: none; 
    z-index: 9998; 
    transform: translate(-50%, -50%); 
  }
  
  #cursor-crosshair::before { 
    content: ''; 
    position: absolute; 
    top: 50%; 
    left: -8px; 
    width: 50px; 
    height: 1px; 
    background: rgba(239, 68, 68, 0.9); 
    transform: translateY(-50%); 
  }
  
  #cursor-crosshair::after { 
    content: ''; 
    position: absolute; 
    left: 50%; 
    top: -8px; 
    height: 50px; 
    width: 1px; 
    background: rgba(239, 68, 68, 0.9); 
    transform: translateX(-50%); 
  }
</style>
"""

CURSOR_SCRIPT = """
<div id="cursor-dot"></div>
<div id="cursor-crosshair"></div>
<script>
  const dot = document.getElementById('cursor-dot');
  const cross = document.getElementById('cursor-crosshair');
  let mx = window.innerWidth / 2, my = window.innerHeight / 2, cx = mx, cy = my;

  window.addEventListener('mousemove', (e) => {
    mx = e.clientX;
    my = e.clientY;
    dot.style.left = mx + 'px';
    dot.style.top = my + 'px';

    for(let i = 0; i < 2; i++) {
      particlesArray.push({ 
        x: mx, y: my, 
        r: Math.random() * 2.2 + 0.8, 
        vx: (Math.random() - 0.5) * 6.0,
        vy: (Math.random() - 0.5) * 6.0, 
        opacity: 1,
        color: Math.random() > 0.5 ? '#ef4444' : '#f97316'
      });
    }
    if(particlesArray.length > 300) particlesArray.splice(0, 2);
  });

  function renderCursor() {
    cx += (mx - cx) * 0.25;
    cy += (my - cy) * 0.25;
    cross.style.left = cx + 'px';
    cross.style.top = cy + 'px';
    requestAnimationFrame(renderCursor);
  }
  renderCursor();

  const canvasElement = document.getElementById('c');
  const ctx = canvasElement.getContext('2d');
  
  function resizeCanvas() { 
    canvasElement.width = window.innerWidth; 
    canvasElement.height = window.innerHeight; 
  }
  resizeCanvas(); 
  window.onresize = resizeCanvas;
  
  let particlesArray = [];
  for(let i = 0; i < 100; i++) {
    particlesArray.push({ 
      x: Math.random() * canvasElement.width, 
      y: Math.random() * canvasElement.height, 
      r: Math.random() * 1.5 + 0.4, 
      vx: (Math.random() - 0.5) * 0.4,
      vy: Math.random() * 1.0 + 0.2, 
      opacity: Math.random() * 0.6 + 0.2,
      color: '#ef4444'
    });
  }

  function animateParticles() {
    ctx.clearRect(0, 0, canvasElement.width, canvasElement.height);
    particlesArray.forEach((p) => {
      p.x += p.vx;
      p.y += p.vy;
      if(p.opacity > 0.02) p.opacity -= 0.006; else p.opacity = 0;
      if(p.y > canvasElement.height || p.x < 0 || p.x > canvasElement.width || p.opacity <= 0) { 
        p.y = 0; p.x = Math.random() * canvasElement.width; p.opacity = 0.8; 
      }
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(239, 68, 68, ${p.opacity})`;
      ctx.shadowBlur = 12;
      ctx.shadowColor = '#ef4444';
      ctx.fill();
    });
    requestAnimationFrame(animateParticles);
  }
  animateParticles();
</script>
"""

# ==========================================
# UI TEMPLATES
# ==========================================

LANDING = """<!DOCTYPE html>
<html>
<head>""" + COMMON_HEAD + """</head>
<body class="text-white overflow-x-hidden relative min-h-screen flex flex-col justify-between">
<canvas id="c"></canvas>
<nav class="relative z-10 flex justify-between items-center px-10 py-5 bg-black/60 border-b border-red-500/20">
  <div class="flex items-center gap-3">
    <div class="w-10 h-10 bg-gradient-to-br from-red-600 to-orange-600 rounded-lg flex items-center justify-center shadow-[0_0_20px_#ef4444] font-black text-lg">⚠️</div>
    <div>
      <p class="font-extrabold text-sm tracking-widest text-red-500">HSL CORP</p>
      <p class="text-[9px] text-zinc-400 tracking-wider">BRUTAL SECURITY INFRASTRUCTURE</p>
    </div>
  </div>
  <div class="flex gap-4">
    <a href="/login" class="bg-zinc-900 border border-zinc-700 px-6 py-2.5 rounded-lg text-xs font-bold hover:border-red-500 transition">ACCESS GATE</a>
    <a href="/dashboard" class="bg-gradient-to-r from-red-600 to-orange-600 px-6 py-2.5 rounded-lg text-xs font-black shadow-[0_0_20px_rgba(239,68,68,0.5)] transition">CONSOLE</a>
  </div>
</nav>
<div class="relative z-10 flex flex-col items-center text-center pt-24 px-4">
  <div class="border border-red-500/40 bg-red-500/10 px-4 py-1.5 rounded-full text-xs text-red-400 font-bold mb-6 shadow-[0_0_20px_rgba(239,68,68,0.3)]">
    🔥 MAXIMUM PROTECTION & HARDWARE LOCKING
  </div>
  <h1 class="text-6xl md:text-8xl font-black bg-gradient-to-r from-red-500 via-orange-500 to-yellow-500 bg-clip-text text-transparent drop-shadow-[0_0_40px_rgba(239,68,68,0.5)]">HSL AUTH ENGINE</h1>
  <p class="text-zinc-400 mt-6 font-semibold text-sm max-w-xl">Unbreakable anti-crack, hardware fingerprinting, and dynamic batch license management.</p>
  <a href="/login" class="mt-10 bg-gradient-to-r from-red-600 to-orange-600 px-10 py-4 rounded-xl text-xs font-black shadow-[0_0_30px_rgba(239,68,68,0.6)] hover:scale-105 transition">INITIALIZE SYSTEM</a>
</div>
<footer class="relative z-10 text-center py-6 border-t border-red-500/10 text-[10px] text-zinc-600">&copy; 2026 HSL CORP. ALL RIGHTS RESERVED.</footer>
""" + CURSOR_SCRIPT + """</body></html>"""

LOGIN = """<!DOCTYPE html>
<html>
<head>""" + COMMON_HEAD + """</head>
<body class="flex items-center justify-center h-screen overflow-hidden relative">
<canvas id="c"></canvas>
<div class="relative z-10 w-[420px] glass-brutal rounded-2xl p-9 text-center shadow-[0_0_80px_rgba(239,68,68,0.3)]">
  <div class="w-16 h-16 bg-gradient-to-br from-red-600 to-orange-600 rounded-xl mx-auto flex items-center justify-center shadow-[0_0_30px_#ef4444] text-2xl font-black">🔒</div>
  <h1 class="font-black text-2xl mt-5 text-white tracking-widest">SECURE LOGIN</h1>
  <p class="text-[11px] text-zinc-400 mt-1">Authenticate via OAuth 2.0 Credentials</p>
  <a href="/auth/google" class="mt-8 w-full bg-white hover:bg-zinc-200 text-black rounded-xl py-3.5 flex justify-center items-center gap-3 font-extrabold text-xs shadow-[0_0_20px_rgba(255,255,255,0.3)] transition">
    <img src="https://www.svgrepo.com/show/475656/google-color.svg" width=18> LOGIN WITH GOOGLE
  </a>
</div>
""" + CURSOR_SCRIPT + """</body></html>"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
""" + COMMON_HEAD + """
<style>
  .side-active { 
    background: rgba(239,68,68,0.2) !important; 
    border: 1px solid rgba(239,68,68,0.6) !important; 
    color: #ef4444 !important; 
    font-weight: 800; 
  }
</style>
</head>
<body class="flex h-screen text-white overflow-hidden relative">
<canvas id="c"></canvas>

<div class="w-[270px] bg-black/90 border-r border-red-500/20 flex flex-col relative z-10">
  <div class="p-5 flex items-center gap-3 border-b border-red-500/20">
    <div class="w-9 h-9 bg-gradient-to-br from-red-600 to-orange-600 rounded-lg flex items-center justify-center shadow-[0_0_15px_#ef4444] font-black">⚡</div>
    <div>
      <p class="font-black text-xs tracking-widest text-red-500">HSL CORP</p>
      <p class="text-[8px] text-zinc-400">DEVELOPER CONSOLE</p>
    </div>
  </div>
  
  <div class="p-3 space-y-1.5 text-xs" id="sidebar">
    <button onclick="showTab('overview')" id="btn-overview" class="side-active w-full text-left rounded-lg px-4 py-3 transition">🏠 DASHBOARD OVERVIEW</button>
    <button onclick="showTab('applications')" id="btn-applications" class="w-full text-left text-zinc-400 hover:text-white px-4 py-3 rounded-lg transition">📦 APPLICATIONS & VERSIONS</button>
    <button onclick="showTab('tool_users')" id="btn-tool_users" class="w-full text-left text-zinc-400 hover:text-white px-4 py-3 rounded-lg transition">👤 CLIENT USERS ({{tool_user_count}}/{{limit_text}})</button>
    <button onclick="showTab('keys')" id="btn-keys" class="w-full text-left text-zinc-400 hover:text-white px-4 py-3 rounded-lg transition">🔑 LICENSE KEY MANAGER</button>
    <button onclick="showTab('integrate')" id="btn-integrate" class="w-full text-left text-zinc-400 hover:text-white px-4 py-3 rounded-lg transition">🔌 ANTI-CRACK PAYLOAD</button>
    <button onclick="showTab('billing')" id="btn-billing" class="w-full text-left text-zinc-400 hover:text-white px-4 py-3 rounded-lg transition">💎 PLANS & BILLING</button>
  </div>
  
  <div class="mt-auto p-4 border-t border-red-500/20 flex items-center gap-3 bg-black/50">
    <img src="https://ui-avatars.com/api/?name={{name}}&background=ef4444&color=fff" class="w-8 h-8 rounded-lg border border-red-500/50">
    <div class="overflow-hidden">
      <p class="text-[10px] font-bold truncate text-zinc-200">{{email}}</p>
      <p class="text-[9px] {{plan_color}} font-black">{{plan_text}}</p>
    </div>
    <a href="/logout" class="ml-auto text-[10px] text-red-400 hover:text-red-300 font-bold">OUT</a>
  </div>
</div>

<div class="flex-1 overflow-y-auto relative z-10">
  <div class="h-14 bg-black/70 border-b border-red-500/20 flex items-center justify-between px-8">
    <p class="text-[11px] font-extrabold tracking-widest text-red-400">HSL SYSTEM STATUS: <span class="text-green-400">ONLINE (SECURE)</span></p>
    <button onclick="showTab('billing')" class="text-[11px] bg-gradient-to-r from-red-600 to-orange-600 hover:opacity-90 text-white px-5 py-2 rounded-lg font-black shadow-[0_0_15px_rgba(239,68,68,0.4)] transition">UPGRADE UNLIMITED</button>
  </div>
  
  <div class="p-8">
    <!-- OVERVIEW TAB -->
    <div id="tab-overview">
      <h1 class="text-2xl font-black text-white tracking-wide">SYSTEM METRICS & OVERVIEW</h1>
      
      <div class="grid grid-cols-4 gap-4 mt-6">
        <div class="glass-card rounded-xl p-5">
          <p class="text-[9px] font-extrabold text-red-400">TOTAL APPS</p>
          <p class="text-3xl font-black mt-2 text-white">{{app_count}}</p>
        </div>
        <div class="glass-card rounded-xl p-5">
          <p class="text-[9px] font-extrabold text-orange-400">ACTIVE USERS</p>
          <p class="text-3xl font-black mt-2 text-white">{{tool_user_count}}</p>
        </div>
        <div class="glass-card rounded-xl p-5">
          <p class="text-[9px] font-extrabold text-emerald-400">TOTAL KEYS</p>
          <p class="text-3xl font-black mt-2 text-white">{{key_count}}</p>
        </div>
        <div class="glass-card rounded-xl p-5">
          <p class="text-[9px] font-extrabold text-yellow-400">PLAN USAGE</p>
          <p class="text-3xl font-black mt-2 text-white">{{tool_user_count}} / {{limit_text}}</p>
        </div>
      </div>

      <div class="mt-6 grid grid-cols-[1.4fr_1fr] gap-6">
        <div class="glass-card rounded-xl p-6">
          <p class="text-[10px] font-extrabold text-red-400 tracking-wider">ACTIVE APPLICATION</p>
          <select id="appSelect" onchange="selectApp(this.value)" class="bg-black/90 border border-red-500/30 rounded-lg px-3 py-3 text-xs mt-3 w-full font-bold focus:outline-none focus:border-red-500">{{app_options}}</select>
          
          <p class="text-[10px] font-extrabold text-zinc-400 tracking-wider mt-5">MASTER APPLICATION TOKEN</p>
          <div class="mt-2 flex justify-between items-center bg-black/90 rounded-lg px-3 py-2.5 border border-red-500/20">
            <p id="tokenDisplay" class="text-xs font-mono text-red-300 truncate">{{active_token}}</p>
            <button onclick="copyToken()" class="text-[10px] bg-gradient-to-r from-red-600 to-orange-600 px-3 py-1.5 rounded font-black hover:scale-105 transition">COPY</button>
          </div>
        </div>
        
        <div class="glass-card rounded-xl p-6 flex flex-col justify-between">
          <div>
            <p class="text-xs font-black text-white">⚡ QUICK ACTIONS</p>
            <p class="text-[10px] text-zinc-400 mt-1">Direct terminal execution commands.</p>
          </div>
          <div class="space-y-2.5 mt-4">
            <button onclick="showTab('applications')" class="w-full bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 py-2.5 rounded-lg text-xs font-bold transition">Manage Apps & Versions</button>
            <button onclick="showTab('keys')" class="w-full bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 py-2.5 rounded-lg text-xs font-bold transition">Batch Key Generator</button>
          </div>
        </div>
      </div>
      
      <div class="mt-6 glass-card rounded-xl p-7">
        <p class="text-sm font-black text-white">+ REGISTER SECURE CLIENT USER</p>
        <div class="flex gap-4 mt-4">
          <input id="newUsername" placeholder="Username" class="flex-1 bg-black/90 border border-red-500/30 rounded-lg px-4 py-3 text-xs focus:outline-none focus:border-red-500">
          <input id="newPassword" placeholder="Password" class="flex-1 bg-black/90 border border-red-500/30 rounded-lg px-4 py-3 text-xs focus:outline-none focus:border-red-500">
        </div>
        <button onclick="createUser()" class="mt-4 w-full bg-gradient-to-r from-red-600 to-orange-600 py-3 rounded-lg text-xs font-black shadow-[0_0_20px_rgba(239,68,68,0.4)] transition">DEPLOY USER</button>
      </div>
    </div>

    <!-- APPLICATIONS TAB -->
    <div id="tab-applications" class="hidden">
      <h1 class="text-2xl font-black text-white">APPLICATIONS & VERSION CONTROL</h1>
      <div class="glass-card mt-6 rounded-xl p-7">
        <div class="space-y-3 mb-6">{{app_list_html}}</div>
        <div class="border-t border-red-500/20 pt-5">
          <p class="text-sm font-black text-white">+ INITIALIZE NEW APPLICATION</p>
          <input id="newAppName" placeholder="App Name (e.g. HSL Loader / Cheat)" class="mt-3 w-full bg-black/90 border border-red-500/30 rounded-lg px-4 py-3 text-xs focus:outline-none focus:border-red-500">
          <button onclick="createApp()" class="mt-4 w-full bg-gradient-to-r from-red-600 to-orange-600 py-3 rounded-lg text-xs font-black shadow-[0_0_20px_rgba(239,68,68,0.4)] transition">CREATE APP</button>
        </div>
      </div>
    </div>

    <!-- USERS TAB -->
    <div id="tab-tool_users" class="hidden">
      <h1 class="text-2xl font-black text-white">CLIENT USERS MANAGER ({{tool_user_count}}/{{limit_text}})</h1>
      <div class="glass-card mt-6 rounded-xl p-6">
        <div class="space-y-3 text-xs font-mono">{{tool_users_list_html}}</div>
      </div>
    </div>

    <!-- KEYS TAB -->
    <div id="tab-keys" class="hidden">
      <h1 class="text-2xl font-black text-white">BATCH LICENSE KEY GENERATOR</h1>
      <div class="glass-card mt-6 rounded-xl p-6">
        <div class="bg-black/80 border border-red-500/20 p-5 rounded-lg mb-6">
          <p class="text-xs font-black text-red-400 mb-3">🔑 GENERATE BATCH KEYS (HSL-XXXX-XXXX-XXXX)</p>
          <div class="flex gap-4">
            <input id="keyCount" type="number" value="10" min="1" max="50" class="w-28 bg-black/90 border border-red-500/30 rounded-lg px-3 py-2.5 text-xs text-center font-bold">
            <button onclick="generateKeys()" class="bg-gradient-to-r from-red-600 to-orange-600 px-6 py-2.5 rounded-lg text-xs font-black transition">GENERATE KEYS</button>
          </div>
        </div>
        <div class="space-y-2 text-xs font-mono max-h-[380px] overflow-y-auto">{{keys_list_html}}</div>
      </div>
    </div>

    <!-- INTEGRATION TAB -->
    <div id="tab-integrate" class="hidden">
      <h1 class="text-2xl font-black text-white">ANTI-CRACK PAYLOAD INTEGRATION</h1>
      <div class="glass-card mt-6 rounded-xl p-7">
        <p class="text-xs font-black text-red-400">Python Secure Auth Client Script (Anti-HTTP Debugger & HWID Binding)</p>
        <pre class="mt-4 bg-black/95 border border-red-500/30 rounded-xl p-5 text-xs font-mono overflow-x-auto text-green-400 leading-relaxed">
import requests
import subprocess
import hashlib

APP_TOKEN = "{{active_token}}"
API_ENDPOINT = "https://YOUR-DOMAIN.com/api/auth_login"

def get_hwid():
    try:
        return subprocess.check_output('wmic baseboard get serialnumber', shell=True).decode().split('\\n')[1].strip()
    except:
        return "UNKNOWN_HWID"

def authenticate(username, password):
    hwid = get_hwid()
    signature = hashlib.sha256(f"{username}:{hwid}:{APP_TOKEN}".encode()).hexdigest()
    
    payload = {"username": username, "password": password, "hwid": hwid, "token": APP_TOKEN, "sig": signature}
    response = requests.post(API_ENDPOINT, json=payload)
    return response.json()
</pre>
      </div>
    </div>

    <!-- BILLING TAB -->
    <div id="tab-billing" class="hidden">
      <h1 class="text-2xl font-black text-white">PLANS & UPGRADE TIERS</h1>
      <div class="grid grid-cols-2 gap-6 mt-6">
        <div class="glass-card rounded-xl p-7">
          <p class="font-bold text-xs text-zinc-400">FREE PLAN</p>
          <p class="text-4xl font-black mt-2 text-white">₹0</p>
          <p class="text-xs text-zinc-400 mt-4 leading-relaxed">✓ Max 10 Users & Keys<br>✓ Max 2 Applications<br>✓ Standard HWID Lock</p>
          <p class="mt-6 text-[10px] bg-zinc-900 border border-zinc-700 rounded px-4 py-2 inline-block font-bold">STATUS: {{plan_text}}</p>
        </div>
        <div class="glass-card rounded-xl p-7 border-red-500/50 bg-red-500/10">
          <p class="font-bold text-xs text-red-400">PRO UNLIMITED</p>
          <p class="text-4xl font-black mt-2 text-white">₹499</p>
          <p class="text-xs text-zinc-200 mt-4 leading-relaxed">✓ Unlimited Client Users<br>✓ Unlimited Applications<br>✓ Unlimited Batch Keys<br>✓ Advanced Anti-Crack Protection</p>
          <a href="https://wa.me/919999999999" target="_blank" class="mt-6 block text-center bg-gradient-to-r from-red-600 to-orange-600 py-3 rounded-xl text-xs font-black shadow-[0_0_25px_rgba(239,68,68,0.5)] transition">UPGRADE NOW ON WHATSAPP</a>
        </div>
      </div>
    </div>
  </div>
</div>
""" + CURSOR_SCRIPT + """
<script>
function showTab(name) {
    document.querySelectorAll('[id^="tab-"]').forEach(d => d.classList.add('hidden'));
    document.getElementById('tab-' + name).classList.remove('hidden');
    document.querySelectorAll('#sidebar button').forEach(b => {
        b.classList.remove('side-active');
        b.classList.add('text-zinc-400');
    });
    let btn = document.getElementById('btn-' + name);
    if(btn) { btn.classList.add('side-active'); btn.classList.remove('text-zinc-400'); }
}

async function createApp() {
    let name = document.getElementById('newAppName').value.trim();
    if(!name) { alert('Enter App Name!'); return; }
    let res = await fetch('/api/create_app', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name}) });
    let data = await res.json();
    if(data.error) alert(data.error); else { alert('App Initialized!'); location.reload(); }
}

async function deleteApp(token) {
    if(!confirm('Terminate Application?')) return;
    let res = await fetch('/api/delete_app', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({token}) });
    let data = await res.json(); alert(data.message); location.reload();
}

async function generateKeys() {
    let token = document.getElementById('tokenDisplay').innerText;
    let count = document.getElementById('keyCount').value;
    if(!token.startsWith('HSL_')) { alert('Select a valid App Token first!'); return; }
    let res = await fetch('/api/generate_keys', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({app_token: token, count}) });
    let data = await res.json(); alert(data.message); location.reload();
}

function copyToken() {
    let t = document.getElementById('tokenDisplay').innerText;
    navigator.clipboard.writeText(t);
    alert('Copied to Clipboard: ' + t);
}

function selectApp(token) { document.getElementById('tokenDisplay').innerText = token; }

async function createUser() {
    let username = document.getElementById('newUsername').value.trim();
    let password = document.getElementById('newPassword').value.trim();
    let app_token = document.getElementById('tokenDisplay').innerText;
    if(!username || !password) { alert('Fill all credentials!'); return; }
    let res = await fetch('/api/create_user', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username, password, app_token}) });
    let data = await res.json(); alert(data.message); location.reload();
}

async function deleteUser(username) {
    if(!confirm('Delete user ' + username + '?')) return;
    let res = await fetch('/api/delete_user', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username}) });
    let data = await res.json(); alert(data.message); location.reload();
}

async function resetHwid(username) {
    let res = await fetch('/api/reset_hwid', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username}) });
    let data = await res.json(); alert(data.message); location.reload();
}

async function toggleBan(username) {
    let res = await fetch('/api/toggle_ban', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username}) });
    let data = await res.json(); alert(data.message); location.reload();
}

async function editUser(oldU, oldP) {
    let newU = prompt("New Username:", oldU); if(newU === null) return;
    let newP = prompt("New Password:", oldP); if(newP === null) return;
    let res = await fetch('/api/edit_user', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({old_username: oldU, new_username: newU.trim(), new_password: newP.trim()}) });
    let data = await res.json(); alert(data.message); location.reload();
}
</script>
</body>
</html>
"""

# ==========================================
# ROUTES & APIs
# ==========================================

@app.route("/")
def home(): return render_template_string(LANDING)

@app.route("/login")
def login(): return render_template_string(LOGIN)

@app.route("/auth/google")
@rate_limit(max_requests=5, window_seconds=60)
def auth_google():
    return google.authorize_redirect(request.url_root.rstrip("/") + "/auth/callback")

@app.route("/auth/callback")
def callback():
    try:
        token = google.authorize_access_token()
        user = token.get("userinfo") or google.get("https://openidconnect.googleapis.com/v1/userinfo").json()
        session["user"] = user
        return redirect("/dashboard")
    except:
        return redirect("/login")

@app.route("/dashboard")
def dash():
    if "user" not in session: return redirect("/login")
    email = session["user"]["email"]
    is_paid = email in PAID_USERS
    limit_text = "UNLIMITED" if is_paid else "10"
    plan_text = "PRO UNLIMITED" if is_paid else "FREE TIER"
    plan_color = "text-emerald-400" if is_paid else "text-yellow-400"
    
    apps = db("SELECT * FROM apps WHERE owner_email=?", (email,), True)
    app_count = len(apps) if apps else 0
    
    if not apps:
        app_options = "<option>No Apps Available</option>"
        active_token = "Initialize app to generate token"
        app_list_html = "<p class='text-zinc-500 text-xs'>No applications deployed.</p>"
    else:
        app_options = "".join([f"<option value='{a[2]}'>{a[1]}</option>" for a in apps])
        active_token = apps[0][2]
        app_list_html = "".join([
            f"""<div class='bg-black/90 border border-red-500/20 rounded-lg px-4 py-3 flex justify-between items-center mb-2'>
                <div>
                    <span class='font-bold text-white'>{a[1]}</span><br>
                    <span class='text-[10px] text-zinc-500 font-mono'>Token: {a[2]}</span>
                </div>
                <button onclick="deleteApp('{a[2]}')" class='bg-red-950 border border-red-500/40 px-3 py-1.5 rounded text-[10px] hover:bg-red-900 transition text-red-300 font-bold'>TERMINATE</button>
            </div>""" for a in apps
        ])
        
    keys = db("SELECT * FROM keys WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True) if apps else []
    key_count = len(keys) if keys else 0
    keys_list_html = "".join([
        f"<div class='flex justify-between bg-black/90 border border-red-500/20 rounded-lg px-4 py-2.5'><span>{k[1]}</span><span class='{'text-emerald-400' if k[3] == 'unused' else 'text-red-400'}'>● {k[3].upper()}</span></div>"
        for k in keys
    ]) if keys else "<p class='text-center text-zinc-600 text-xs mt-10'>No license keys generated.</p>"

    tool_users = db("SELECT * FROM tool_users WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True) if apps else []
    tool_user_count = len(tool_users)
    
    tool_users_list_html = ""
    for u in tool_users:
        hwid_short = (u[5][:14] + "...") if u[5] else "UNBOUND"
        status_color = "text-emerald-400" if u[4] == "active" else "text-red-400"
        ban_text = "BAN" if u[4] == "active" else "UNBAN"
        tool_users_list_html += f"""
        <div class='flex justify-between items-center bg-black/90 border border-red-500/20 rounded-lg px-4 py-3 mb-2'>
            <div>
                <span class='text-white font-bold'>{u[1]}</span><span class='text-zinc-600'> / {u[2]}</span><br>
                <span class='text-[9px] text-zinc-500'>HWID: {hwid_short} | STATUS: <span class='{status_color}'>{u[4].upper()}</span></span>
            </div>
            <div class='flex gap-1.5 flex-wrap justify-end max-w-[60%]'>
                <button onclick="editUser('{u[1]}','{u[2]}')" class='bg-blue-950 border border-blue-500/40 px-2.5 py-1 rounded text-[9px] hover:bg-blue-900 transition font-bold'>EDIT</button>
                <button onclick="toggleBan('{u[1]}')" class='bg-yellow-950 border border-yellow-500/40 px-2.5 py-1 rounded text-[9px] hover:bg-yellow-900 transition font-bold'>{ban_text}</button>
                <button onclick="resetHwid('{u[1]}')" class='bg-zinc-900 border border-zinc-700 px-2.5 py-1 rounded text-[9px] hover:bg-zinc-800 transition font-bold'>RESET HWID</button>
                <button onclick="deleteUser('{u[1]}')" class='bg-red-950 border border-red-500/40 px-2.5 py-1 rounded text-[9px] hover:bg-red-900 transition font-bold'>DELETE</button>
            </div>
        </div>
        """
    if not tool_users_list_html: tool_users_list_html = "<p class='text-center text-zinc-600 text-xs mt-10'>No client users registered.</p>"

    html = (DASHBOARD_HTML.replace("{{name}}", session["user"].get("name", "User"))
        .replace("{{email}}", email)
        .replace("{{app_count}}", str(app_count))
        .replace("{{key_count}}", str(key_count))
        .replace("{{app_options}}", app_options)
        .replace("{{active_token}}", active_token)
        .replace("{{app_list_html}}", app_list_html)
        .replace("{{keys_list_html}}", keys_list_html)
        .replace("{{tool_user_count}}", str(tool_user_count))
        .replace("{{limit_text}}", limit_text)
        .replace("{{plan_text}}", plan_text)
        .replace("{{plan_color}}", plan_color)
        .replace("{{tool_users_list_html}}", tool_users_list_html))
    return render_template_string(html)

@app.route("/api/create_app", methods=["POST"])
def api_create_app():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    email = session["user"]["email"]
    apps = db("SELECT COUNT(*) FROM apps WHERE owner_email=?", (email,), True)
    if email not in PAID_USERS and apps[0][0] >= 2:
        return jsonify({"error": "Free Plan limit reached (Max 2 apps)."}), 400
    name = request.json.get("name", "").strip()
    if not name: return jsonify({"error": "Invalid App Name"})
    token = f"HSL_{''.join(random.choices(string.ascii_uppercase + string.digits, k=24))}"
    db("INSERT INTO apps (name, token, owner_email, created_at) VALUES (?,?,?,?)", (name, token, email, datetime.now().isoformat()))
    return jsonify({"token": token})

@app.route("/api/delete_app", methods=["POST"])
def api_delete_app():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    token = request.json.get("token")
    db("DELETE FROM apps WHERE token=? AND owner_email=?", (token, session["user"]["email"]))
    db("DELETE FROM tool_users WHERE app_token=?", (token,))
    db("DELETE FROM keys WHERE app_token=?", (token,))
    return jsonify({"message": "Application terminated."})

@app.route("/api/generate_keys", methods=["POST"])
def api_generate_keys():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    email = session["user"]["email"]
    data = request.json or {}
    token, count = data.get("app_token"), int(data.get("count", 10))
    app_check = db("SELECT * FROM apps WHERE token=? AND owner_email=?", (token, email), True)
    if not app_check: return jsonify({"message": "Invalid App Token!"})
    
    generated = 0
    for _ in range(count):
        k_text = "HSL-" + "-".join("".join(random.choices(string.ascii_uppercase + string.digits, k=4)) for _ in range(3))
        try:
            db("INSERT INTO keys (key_text, app_token, status, created_at) VALUES (?,?,?,?)", (k_text, token, "unused", datetime.now().isoformat()))
            generated += 1
        except: pass
    return jsonify({"message": f"Successfully generated {generated} license keys!"})

@app.route("/api/create_user", methods=["POST"])
def api_create_user():
    data = request.json or {}
    app_token, username, password = data.get("app_token"), data.get("username", "").strip(), data.get("password", "").strip()
    if not username or not password or not app_token: return jsonify({"message": "Missing fields!"})
    try:
        db("INSERT INTO tool_users (username, password, app_token, status, created_at) VALUES (?,?,?,?,?)", (username, password, app_token, "active", datetime.now().isoformat()))
        return jsonify({"message": f"Client User Created: {username}"})
    except: return jsonify({"message": "Username already exists!"})

@app.route("/api/delete_user", methods=["POST"])
def api_delete_user():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    db("DELETE FROM tool_users WHERE username=?", (request.json.get("username"),))
    return jsonify({"message": "User deleted successfully"})

@app.route("/api/reset_hwid", methods=["POST"])
def api_reset_hwid():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    username = request.json.get("username")
    db("UPDATE tool_users SET hwid=NULL, status='active' WHERE username=?", (username,))
    return jsonify({"message": f"HWID fingerprint reset for {username}"})

@app.route("/api/toggle_ban", methods=["POST"])
def api_toggle_ban():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    username = request.json.get("username")
    res = db("SELECT status FROM tool_users WHERE username=?", (username,), True)
    if not res: return jsonify({"message": "User not found"})
    new_status = "banned" if res[0][0] == "active" else "active"
    db("UPDATE tool_users SET status=? WHERE username=?", (new_status, username))
    return jsonify({"message": f"User status toggled to {new_status.upper()}"})

@app.route("/api/edit_user", methods=["POST"])
def api_edit_user():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    old_u, new_u, new_p = request.json.get("old_username"), request.json.get("new_username"), request.json.get("new_password")
    try:
        db("UPDATE tool_users SET username=?, password=? WHERE username=?", (new_u, new_p, old_u))
        return jsonify({"message": f"Credentials updated for {old_u}"})
    except: return jsonify({"message": "Update failed."})

# External Client Authentication API Endpoint (Used by Anti-Crack Payload)
@app.route("/api/auth_login", methods=["POST"])
def api_auth_login():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")
    hwid = data.get("hwid")
    token = data.get("token")
    
    if not all([username, password, hwid, token]):
        return jsonify({"status": "failed", "message": "Missing authentication parameters."}), 400
        
    user = db("SELECT * FROM tool_users WHERE username=? AND password=? AND app_token=?", (username, password, token), True)
    if not user:
        return jsonify({"status": "failed", "message": "Invalid username or password."}), 401
        
    u_data = user[0]
    # u_data indices: 0:id, 1:username, 2:password, 3:app_token, 4:status, 5:hwid, 6:last_login, 7:created_at
    if u_data[4] == "banned":
        return jsonify({"status": "failed", "message": "Access Denied: User is banned."}), 403
        
    stored_hwid = u_data[5]
    if stored_hwid is None:
        db("UPDATE tool_users SET hwid=?, last_login=? WHERE username=?", (hwid, datetime.now().isoformat(), username))
    elif stored_hwid != hwid:
        return jsonify({"status": "failed", "message": "HWID Mismatch: License locked to another machine."}), 403
    else:
        db("UPDATE tool_users SET last_login=? WHERE username=?", (datetime.now().isoformat(), username))
        
    return jsonify({"status": "success", "message": "Authenticated successfully."})

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)