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
    "hsl_corp_brutal_secure_key_2026_production"
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
                
            REQUEST_HISTORY[ip] = [
                t for t in REQUEST_HISTORY[ip] 
                if now - t < window_seconds
            ]
            
            if len(REQUEST_HISTORY[ip]) >= max_requests:
                return jsonify({
                    "status": "rate_limited",
                    "message": "Too many attempts. Request blocked by brutal firewall."
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
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            email TEXT, 
            hwid TEXT, 
            app_token TEXT, 
            key_text TEXT, 
            first_seen TEXT
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
# BRUTAL CYBERPUNK STYLES & CUSTOM CURSOR
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
  
  .glass { 
    backdrop-filter: blur(25px); 
    background: rgba(5, 8, 18, 0.85); 
    border: 1px solid rgba(0, 255, 204, 0.25); 
    box-shadow: 0 0 30px rgba(0, 0, 0, 0.8);
  }
  
  .glass-card { 
    background: rgba(8, 12, 24, 0.75); 
    border: 1px solid rgba(0, 255, 204, 0.18); 
    backdrop-filter: blur(15px); 
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1); 
  }
  
  .glass-card:hover { 
    border-color: rgba(0, 255, 204, 0.6); 
    transform: translateY(-3px); 
    box-shadow: 0 10px 30px -5px rgba(0,255,204,0.3); 
  }
  
  #cursor-dot { 
    position: fixed; 
    width: 6px; 
    height: 6px; 
    background: #00ffcc; 
    border-radius: 50%; 
    pointer-events: none; 
    z-index: 9999; 
    transform: translate(-50%, -50%); 
    box-shadow: 0 0 12px #00ffcc, 0 0 24px #00ffcc; 
  }
  
  #cursor-crosshair { 
    position: fixed; 
    width: 32px; 
    height: 32px; 
    border: 1.5px solid rgba(0, 255, 204, 0.7); 
    border-radius: 50%; 
    pointer-events: none; 
    z-index: 9998; 
    transform: translate(-50%, -50%); 
  }
  
  #cursor-crosshair::before { 
    content: ''; 
    position: absolute; 
    top: 50%; 
    left: -6px; 
    width: 42px; 
    height: 1.5px; 
    background: rgba(0, 255, 204, 0.8); 
    transform: translateY(-50%); 
  }
  
  #cursor-crosshair::after { 
    content: ''; 
    position: absolute; 
    left: 50%; 
    top: -6px; 
    height: 42px; 
    width: 1.5px; 
    background: rgba(0, 255, 204, 0.8); 
    transform: translateX(-50%); 
  }
  
  #cursor-orbit { 
    position: fixed; 
    width: 52px; 
    height: 52px; 
    border: 1px dashed rgba(255, 0, 85, 0.6); 
    border-radius: 50%; 
    pointer-events: none; 
    z-index: 9997; 
    transform: translate(-50%, -50%); 
    animation: spinOrbit 4s linear infinite; 
  }
  
  @keyframes spinOrbit { 
    0% { transform: translate(-50%, -50%) rotate(0deg); } 
    100% { transform: translate(-50%, -50%) rotate(360deg); } 
  }
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
    cx += (mx - cx) * 0.22;
    cy += (my - cy) * 0.22;
    cross.style.left = cx + 'px';
    cross.style.top = cy + 'px';
    orbit.style.left = cx + 'px';
    orbit.style.top = cy + 'px';
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
  for(let i = 0; i < 110; i++) {
    particlesArray.push({ 
      x: Math.random() * canvasElement.width, 
      y: Math.random() * canvasElement.height, 
      r: Math.random() * 1.8 + 0.6, 
      vy: Math.random() * 0.8 + 0.3, 
      opacity: Math.random() * 0.8 + 0.2 
    });
  }
  
  window.addEventListener('mousemove', (e) => {
    if(Math.random() > 0.3) {
      particlesArray.push({ 
        x: e.clientX, 
        y: e.clientY, 
        r: Math.random() * 2.2 + 1, 
        vy: -(Math.random() * 1.5 + 0.5), 
        opacity: 1 
      });
      if(particlesArray.length > 140) {
        particlesArray.shift();
      }
    }
  });

  function animateParticles() {
    ctx.clearRect(0, 0, canvasElement.width, canvasElement.height);
    particlesArray.forEach(p => {
      p.y -= p.vy;
      if(p.opacity > 0.3) {
        p.opacity -= 0.004;
      }
      if(p.y < 0) { 
        p.y = canvasElement.height; 
        p.x = Math.random() * canvasElement.width; 
        p.opacity = Math.random() * 0.8 + 0.2; 
      }
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0, 255, 204, ${p.opacity})`;
      ctx.shadowBlur = 12;
      ctx.shadowColor = '#00ffcc';
      ctx.fill();
    });
    requestAnimationFrame(animateParticles);
  }
  animateParticles();
</script>
"""

# ==========================================
# UI TEMPLATES (LANDING, LOGIN & DASHBOARD)
# ==========================================

LANDING = """<!DOCTYPE html>
<html>
<head>
""" + COMMON_HEAD + """
</head>
<body class="text-white overflow-x-hidden relative min-h-screen flex flex-col justify-between">
<canvas id="c"></canvas>

<nav class="relative z-10 flex justify-between items-center px-10 py-5 bg-black/60 backdrop-blur-xl border-b border-[#00ffcc]/20">
  <div class="flex items-center gap-3">
    <div class="w-10 h-10 bg-gradient-to-r from-[#00ffcc] to-[#ff0055] rounded-xl flex items-center justify-center shadow-[0_0_20px_#00ffcc]">⚡</div>
    <div>
      <p class="font-extrabold text-sm tracking-widest text-[#00ffcc]">HSL CORP</p>
      <p class="text-[9px] text-zinc-400 font-bold tracking-widest">BRUTAL LICENSE INFRASTRUCTURE</p>
    </div>
  </div>
  <div class="flex gap-4">
    <a href="/login" class="bg-zinc-900/90 hover:bg-zinc-800 border border-zinc-700 px-6 py-2.5 rounded-full text-xs font-bold transition">Sign In</a>
    <a href="/dashboard" class="bg-gradient-to-r from-[#00ffcc] to-[#ff0055] hover:opacity-90 px-6 py-2.5 rounded-full text-xs font-black shadow-[0_0_25px_rgba(0,255,204,0.6)] text-black transition">Dashboard</a>
  </div>
</nav>

<div class="relative z-10 flex flex-col items-center text-center pt-24 px-4">
  <div class="inline-flex items-center gap-2 border border-[#00ffcc]/40 bg-[#00ffcc]/10 px-5 py-2 rounded-full text-xs text-[#00ffcc] font-bold mb-8 shadow-[0_0_20px_rgba(0,255,204,0.3)]">
    <span>🔥</span> HARDWARE-LOCKED ELITE PROTECTION SYSTEM
  </div>
  <h1 class="text-6xl md:text-8xl font-black bg-gradient-to-r from-[#00ffcc] via-white to-[#ff0055] bg-clip-text text-transparent drop-shadow-[0_0_40px_rgba(0,255,204,0.5)] max-w-5xl leading-none">HSL CORP AUTH</h1>
  <p class="text-zinc-400 mt-6 font-semibold text-lg max-w-2xl">Unbreakable Anti-Crack, HWID Binding & Instant License Control Panel.</p>
  <a href="/login" class="bg-gradient-to-r from-[#00ffcc] to-[#ff0055] hover:scale-105 px-10 py-4 rounded-2xl text-sm font-black text-black shadow-[0_0_35px_rgba(0,255,204,0.7)] mt-10 transition duration-300 flex items-center gap-2">🚀 INITIALIZE SYSTEM</a>
</div>

<div class="relative z-10 w-full max-w-6xl mx-auto px-6 py-20">
  <div class="grid md:grid-cols-3 gap-8">
    <div class="glass-card rounded-2xl p-7">
      <div class="w-12 h-12 rounded-xl bg-[#00ffcc]/15 border border-[#00ffcc]/40 flex items-center justify-center text-2xl mb-4">🛡️</div>
      <h3 class="font-bold text-lg text-[#00ffcc]">Motherboard HWID Lock</h3>
      <p class="text-xs text-zinc-400 mt-2 leading-relaxed">Instantly locks activations to hardware signatures, completely blocking leaks, reverse engineering, and multi-user sharing.</p>
    </div>
    <div class="glass-card rounded-2xl p-7">
      <div class="w-12 h-12 rounded-xl bg-[#ff0055]/15 border border-[#ff0055]/40 flex items-center justify-center text-2xl mb-4">⚡</div>
      <h3 class="font-bold text-lg text-[#ff0055]">Anti-Debugger Payload</h3>
      <p class="text-xs text-zinc-400 mt-2 leading-relaxed">Dynamic SHA-256 request signing foils Fiddler, Wireshark, and HTTP Debugger interception out of the box.</p>
    </div>
    <div class="glass-card rounded-2xl p-7">
      <div class="w-12 h-12 rounded-xl bg-[#00ffcc]/15 border border-[#00ffcc]/40 flex items-center justify-center text-2xl mb-4">👑</div>
      <h3 class="font-bold text-lg text-[#00ffcc]">Brutal Admin Console</h3>
      <p class="text-xs text-zinc-400 mt-2 leading-relaxed">Manage users, issue instant permanent bans, execute HWID resets, and monitor active connections in real-time.</p>
    </div>
  </div>
</div>

<footer class="relative z-10 text-center py-6 border-t border-white/5 text-xs text-zinc-600">
  &copy; 2026 HSL CORP. ALL RIGHTS RESERVED.
</footer>
""" + CURSOR_SCRIPT + """
</body>
</html>"""

LOGIN = """<!DOCTYPE html>
<html>
<head>
""" + COMMON_HEAD + """
</head>
<body class="flex items-center justify-center h-screen overflow-hidden relative">
<canvas id="c"></canvas>
<div class="relative z-10 w-[440px] glass rounded-[32px] p-10 text-center shadow-[0_0_80px_rgba(0,255,204,0.3)]">
  <div class="w-16 h-16 bg-gradient-to-r from-[#00ffcc] to-[#ff0055] rounded-2xl mx-auto flex items-center justify-center shadow-[0_0_30px_#00ffcc] text-black font-black text-2xl">⚡</div>
  <h1 class="font-black text-3xl mt-6 text-white bg-gradient-to-r from-[#00ffcc] to-[#ff0055] bg-clip-text text-transparent">HSL CORP</h1>
  <p class="text-xs text-zinc-400 mt-2 tracking-wider">AUTHENTICATE VIA SECURE GATEWAY</p>
  <a href="/auth/google" class="mt-9 w-full bg-white hover:bg-zinc-100 text-black rounded-xl py-4 flex justify-center items-center gap-3 font-extrabold text-sm shadow-xl hover:scale-[1.02] transition">
    <img src="https://www.svgrepo.com/show/475656/google-color.svg" width=22> Sign In with Google
  </a>
</div>
""" + CURSOR_SCRIPT + """
</body>
</html>"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
""" + COMMON_HEAD + """
<style>
  .side-active { 
    background: rgba(0,255,204,0.2); 
    border: 1px solid rgba(0,255,204,0.5); 
    color: #00ffcc !important; 
    font-weight: 800; 
    box-shadow: 0 0 15px rgba(0,255,204,0.2);
  }
</style>
</head>
<body class="flex h-screen text-white overflow-hidden relative">
<canvas id="c"></canvas>

<div class="w-[280px] bg-black/90 backdrop-blur-2xl border-r border-[#00ffcc]/20 flex flex-col relative z-10">
  <div class="p-6 flex items-center gap-3 border-b border-[#00ffcc]/20">
    <div class="w-10 h-10 bg-gradient-to-r from-[#00ffcc] to-[#ff0055] rounded-xl flex items-center justify-center shadow-[0_0_15px_#00ffcc] text-black font-black">⚡</div>
    <div>
      <p class="font-black text-sm tracking-wider text-[#00ffcc]">HSL CORP</p>
      <p class="text-[9px] text-zinc-400 font-bold tracking-widest">BRUTAL CONSOLE</p>
    </div>
  </div>
  
  <div class="p-4 space-y-1.5 text-xs" id="sidebar">
    <button onclick="showTab('overview')" id="btn-overview" class="side-active w-full text-left rounded-xl px-4 py-3 transition">🏠 Overview</button>
    <button onclick="showTab('applications')" id="btn-applications" class="w-full text-left text-zinc-400 hover:text-white px-4 py-3 transition">📦 Applications</button>
    <button onclick="showTab('tool_users')" id="btn-tool_users" class="w-full text-left text-zinc-400 hover:text-white px-4 py-3 transition">👤 Users ({{tool_user_count}}/{{limit_text}})</button>
    <button onclick="showTab('keys')" id="btn-keys" class="w-full text-left text-zinc-400 hover:text-white px-4 py-3 transition">🔑 License Keys</button>
    <button onclick="showTab('integrate')" id="btn-integrate" class="w-full text-left text-zinc-400 hover:text-white px-4 py-3 transition">🔌 Anti-Crack Integration</button>
    <button onclick="showTab('billing')" id="btn-billing" class="w-full text-left text-zinc-400 hover:text-white px-4 py-3 transition">💎 Billing / Upgrade</button>
  </div>
  
  <div class="mt-auto p-4 border-t border-[#00ffcc]/20 flex items-center gap-3 bg-black/60">
    <img src="https://ui-avatars.com/api/?name={{name}}&background=00ffcc&color=000" class="w-9 h-9 rounded-full border border-[#00ffcc]/60">
    <div class="overflow-hidden">
      <p class="text-[11px] font-bold truncate w-[110px]">{{email}}</p>
      <p class="text-[9px] {{plan_color}} font-black tracking-wider">{{plan_text}}</p>
    </div>
    <a href="/logout" class="ml-auto text-[11px] text-red-400 hover:text-red-300 font-bold">Logout</a>
  </div>
</div>

<div class="flex-1 overflow-y-auto relative z-10">
  <div class="h-16 bg-black/60 backdrop-blur-md border-b border-[#00ffcc]/20 flex items-center justify-between px-8">
    <p class="text-xs font-black tracking-widest text-[#00ffcc]">SYSTEM STATUS: ACTIVE // PLAN: {{plan_text}}</p>
    <button onclick="showTab('billing')" class="text-xs bg-gradient-to-r from-[#00ffcc] to-[#ff0055] hover:opacity-90 text-black px-6 py-2.5 rounded-full font-black shadow-[0_0_20px_rgba(0,255,204,0.5)] transition">UPGRADE TO UNLIMITED</button>
  </div>
  
  <div class="p-10">
    <div id="tab-overview">
      <h1 class="text-3xl font-black tracking-wide text-white">Dashboard Overview</h1>
      <div class="mt-8 grid grid-cols-[1.4fr_1fr_0.8fr] gap-6">
        <div class="glass-card rounded-2xl p-6">
          <p class="text-[10px] font-black text-[#00ffcc] tracking-widest">ACTIVE TARGET APPLICATION</p>
          <select id="appSelect" onchange="selectApp(this.value)" class="bg-black/90 border border-[#00ffcc]/30 rounded-xl px-4 py-3 text-xs mt-3 w-full font-bold focus:outline-none focus:border-[#00ffcc] text-white">{{app_options|safe}}</select>
        </div>
        <div class="glass-card rounded-2xl p-6">
          <p class="text-[10px] font-black text-zinc-400 tracking-widest">MASTER APP TOKEN</p>
          <div class="mt-3 flex justify-between items-center bg-black/90 rounded-xl px-4 py-2.5 border border-white/15">
            <p id="tokenDisplay" class="text-xs font-mono text-zinc-300 truncate">{{active_token}}</p>
            <button onclick="copyToken()" class="text-[10px] bg-gradient-to-r from-[#00ffcc] to-[#ff0055] px-3.5 py-1.5 rounded-lg font-black text-black hover:scale-105 transition">COPY</button>
          </div>
        </div>
        <div class="glass-card rounded-2xl p-6">
          <p class="text-[10px] font-black text-zinc-400 tracking-widest">PLAN CAPACITY</p>
          <p class="text-xs font-black mt-3 text-white">{{tool_user_count}} / {{limit_text}} USERS</p>
          <div class="w-full bg-zinc-900 h-2.5 mt-3 rounded-full overflow-hidden border border-white/10">
            <div class="bg-gradient-to-r from-[#00ffcc] to-[#ff0055] h-2.5 rounded-full shadow-[0_0_10px_#00ffcc]" style="width:{{percent}}%"></div>
          </div>
        </div>
      </div>
      
      <div class="mt-8 glass-card rounded-2xl p-8 border-[#00ffcc]/30">
        <p class="text-lg font-black text-white flex items-center gap-2"><span>⚡</span> Create New Secure User</p>
        <div class="flex gap-4 mt-5">
          <input id="newUsername" placeholder="Enter Username" class="flex-1 bg-black/90 border border-white/20 rounded-xl px-5 py-3.5 text-sm font-bold focus:outline-none focus:border-[#00ffcc] text-white placeholder-zinc-600">
          <input id="newPassword" placeholder="Enter Password" class="flex-1 bg-black/90 border border-white/20 rounded-xl px-5 py-3.5 text-sm font-bold focus:outline-none focus:border-[#00ffcc] text-white placeholder-zinc-600">
        </div>
        <button onclick="createUser()" class="mt-6 w-full bg-gradient-to-r from-[#00ffcc] to-[#ff0055] hover:opacity-90 py-3.5 rounded-xl text-sm font-black text-black shadow-[0_0_25px_rgba(0,255,204,0.5)] transition">⚡ DEPLOY NEW USER</button>
      </div>
    </div>

    <div id="tab-applications" class="hidden">
      <h1 class="text-3xl font-black tracking-wide text-white">Applications Management</h1>
      <div class="glass-card mt-8 rounded-2xl p-8">
        <div class="space-y-4 mb-8">{{app_list_html|safe}}</div>
        <div class="border-t border-white/10 pt-6">
          <p class="text-base font-black text-white">+ Create New Application</p>
          <input id="newAppName" placeholder="Application Name" class="mt-4 w-full bg-black/90 border border-white/20 rounded-xl px-5 py-3.5 text-sm font-bold focus:outline-none focus:border-[#00ffcc] text-white placeholder-zinc-600">
          <button onclick="createApp()" class="mt-5 w-full bg-gradient-to-r from-[#00ffcc] to-[#ff0055] py-3.5 rounded-xl text-sm font-black text-black shadow-[0_0_25px_rgba(0,255,204,0.5)] transition">CREATE APPLICATION</button>
        </div>
      </div>
    </div>

    <div id="tab-tool_users" class="hidden">
      <h1 class="text-3xl font-black tracking-wide text-white">Registered Users ({{tool_user_count}}/{{limit_text}})</h1>
      <div class="glass-card mt-8 rounded-2xl p-6">
        <div class="space-y-3 text-xs font-mono">{{tool_users_list_html|safe}}</div>
      </div>
    </div>

    <div id="tab-keys" class="hidden">
      <h1 class="text-3xl font-black tracking-wide text-white">License Keys</h1>
      <div class="glass-card mt-8 rounded-2xl p-6">
        <div class="space-y-3 text-xs font-mono">{{keys_list_html|safe}}</div>
      </div>
    </div>

    <div id="tab-integrate" class="hidden">
      <h1 class="text-3xl font-black tracking-wide text-white">Anti-Crack Integration Code</h1>
      <div class="glass-card mt-8 rounded-2xl p-8 border-[#00ffcc]/30">
        <p class="text-xs font-black text-[#00ffcc] tracking-wider">SECURE PAYLOAD SIGNING & HARDWARE BINDING SCRIPT</p>
        <pre class="mt-5 bg-black/95 border border-[#00ffcc]/20 rounded-xl p-6 text-xs font-mono overflow-x-auto text-[#00ffcc] leading-relaxed shadow-inner">
import requests
import subprocess
import hashlib

MY_APP_TOKEN = "{{active_token}}"
AUTH_URL = "https://YOUR-DOMAIN.com/api/auth_login"

def get_hwid():
    try:
        raw = subprocess.check_output('wmic baseboard get serialnumber', shell=True).decode()
        return raw.split('\\n')[1].strip()
    except Exception:
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
      </div>
    </div>

    <div id="tab-billing" class="hidden">
      <h1 class="text-3xl font-black tracking-wide text-white">Billing & License Plans</h1>
      <div class="grid grid-cols-2 gap-8 mt-8">
        <div class="glass-card rounded-2xl p-8">
          <p class="font-bold text-xs text-zinc-400 tracking-widest">STANDARD TIER</p>
          <p class="text-5xl font-black mt-3 text-white">₹0</p>
          <p class="text-xs text-zinc-400 mt-4 leading-relaxed font-semibold">✓ 10 Users / Keys Only<br>✓ 2 Applications Max<br>✓ Hardware ID Lock Engine</p>
          <p class="mt-8 text-xs bg-zinc-900 border border-white/10 rounded-full px-5 py-2 inline-block font-black text-yellow-400">CURRENT PLAN: {{plan_text}}</p>
        </div>
        <div class="glass-card rounded-2xl p-8 border-[#00ffcc]/60 bg-[#00ffcc]/10 shadow-[0_0_40px_rgba(0,255,204,0.15)]">
          <p class="font-bold text-xs text-[#00ffcc] tracking-widest">ELITE PRO UNLIMITED</p>
          <p class="text-5xl font-black mt-3 text-white">₹499</p>
          <p class="text-xs text-zinc-200 mt-4 leading-relaxed font-semibold">✓ Unlimited Users & Clients<br>✓ Unlimited Applications<br>✓ Unlimited License Keys<br>✓ Advanced Anti-Crack & Debugger Shield</p>
          <a href="https://wa.me/919999999999" target="_blank" class="mt-8 block text-center bg-gradient-to-r from-[#00ffcc] to-[#ff0055] py-4 rounded-xl text-sm font-black text-black shadow-[0_0_25px_rgba(0,255,204,0.6)] transition hover:scale-[1.02]">⚡ UPGRADE VIA WHATSAPP</a>
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
    if(btn) {
        btn.classList.add('side-active');
        btn.classList.remove('text-zinc-400');
    }
}

async function createApp() {
    let name = document.getElementById('newAppName').value.trim();
    if(!name) {
        alert('Enter Application Name!');
        return;
    }
    let res = await fetch('/api/create_app', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name})
    });
    let data = await res.json();
    if(data.error) {
        alert(data.error);
    } else {
        alert('App Created! Token: ' + data.token);
        location.reload();
    }
}

async function deleteApp(token) {
    if(!confirm('Are you sure you want to delete this application? Associated data will be wiped.')) return;
    let res = await fetch('/api/delete_app', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({token: token})
    });
    let data = await res.json();
    alert(data.message);
    location.reload();
}

function copyToken() {
    let t = document.getElementById('tokenDisplay').innerText;
    navigator.clipboard.writeText(t);
    alert('Token Copied to Clipboard!');
}

function selectApp(token) {
    document.getElementById('tokenDisplay').innerText = token;
}

async function createUser() {
    let u = document.getElementById('newUsername').value.trim();
    let p = document.getElementById('newPassword').value.trim();
    let token = document.getElementById('tokenDisplay').innerText;
    
    if(!u || !p) {
        alert('Fill all user fields!');
        return;
    }
    
    let res = await fetch('/api/create_user', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: u, password: p, app_token: token})
    });
    let data = await res.json();
    alert(data.message);
    location.reload();
}

async function deleteUser(username) {
    if(!confirm('Delete user ' + username + '?')) return;
    let res = await fetch('/api/delete_user', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: username})
    });
    let data = await res.json();
    alert(data.message);
    location.reload();
}

async function resetHwid(username) {
    let res = await fetch('/api/reset_hwid', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: username})
    });
    let data = await res.json();
    alert(data.message);
    location.reload();
}

async function toggleBan(username) {
    let res = await fetch('/api/toggle_ban', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: username})
    });
    let data = await res.json();
    alert(data.message);
    location.reload();
}

async function editUser(oldU, oldP) {
    let newU = prompt("New Username:", oldU); 
    if(newU === null) return;
    
    let newP = prompt("New Password:", oldP); 
    if(newP === null) return;
    
    let res = await fetch('/api/edit_user', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            old_username: oldU, 
            new_username: newU.trim(), 
            new_password: newP.trim()
        })
    });
    let data = await res.json();
    alert(data.message);
    location.reload();
}
</script>
</body>
</html>
"""

# ==========================================
# FLASK WEB ROUTES
# ==========================================

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
        user = token.get("userinfo") or google.get("https://openidconnect.googleapis.com/v1/userinfo").json()
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
    plan_text = "PRO UNLIMITED" if is_paid else "FREE TIER"
    plan_color = "text-green-400" if is_paid else "text-yellow-400"
    
    apps = db("SELECT * FROM apps WHERE owner_email=?", (email,), True)
    
    if not apps:
        app_options = "<option>No Applications Found</option>"
        active_token = "Generate or select an app token"
        app_list_html = "<div class='text-zinc-500 text-xs py-4 px-4 bg-black/40 rounded-xl border border-white/5'>[!] No applications created yet. Use the generator below.</div>"
    else:
        app_options = "".join([
            f"<option value='{a[2]}'>{a[1]}</option>" 
            for a in apps
        ])
        active_token = apps[0][2]
        app_list_html = "".join([
            f"""<div class='bg-black/90 border border-[#00ffcc]/20 rounded-xl px-5 py-4 flex justify-between items-center mb-3 shadow-md'>
                <div>
                    <span class='font-bold text-white text-sm'>{a[1]}</span><br>
                    <span class='text-[10px] text-zinc-400 font-mono'>{a[2]}</span>
                </div>
                <button onclick="deleteApp('{a[2]}')" class='bg-red-950/60 border border-red-500/40 px-3.5 py-1.5 rounded-lg text-xs hover:bg-red-900 transition text-red-300 font-bold'>DELETE</button>
            </div>"""
            for a in apps
        ])
        
    keys = db("SELECT * FROM keys WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True) if apps else []
    
    if keys:
        keys_list_html = "".join([
            f"<div class='flex justify-between items-center bg-black/90 border border-white/10 rounded-xl px-4 py-3'><span>{k[1]}</span><span class='{'text-[#00ffcc]' if k[3] == 'unused' else 'text-red-400'} font-bold'>● {k[3].upper()}</span></div>"
            for k in keys
        ])
    else:
        keys_list_html = "<div class='text-zinc-500 text-xs py-4 px-4 bg-black/40 rounded-xl border border-white/5'>[!] No license keys generated yet.</div>"

    tool_users = db("SELECT * FROM tool_users WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True) if apps else []
    tool_user_count = len(tool_users)
    
    if tool_user_count == 0:
        percent = 5
    else:
        max_limit = 999999 if is_paid else 10
        percent = min(int(tool_user_count / max_limit * 100), 100)
    
    tool_users_list_html = ""
    if not tool_users:
        tool_users_list_html = "<div class='text-zinc-500 text-xs py-4 px-4 bg-black/40 rounded-xl border border-white/5'>[!] No active users registered under your apps yet.</div>"
    else:
        for u in tool_users:
            hwid_short = (u[5][:18] + "...") if u[5] else "UNBOUND"
            status_color = "text-green-400" if u[4] == "active" else "text-red-400"
            ban_text = "BAN" if u[4] == "active" else "UNBAN"
            
            tool_users_list_html += f"""
            <div class='flex justify-between items-center bg-black/90 border border-[#00ffcc]/20 rounded-xl px-5 py-4 mb-3'>
                <div>
                    <span class='text-white font-bold text-sm'>{u[1]}</span><span class='text-zinc-500'> / {u[2]}</span><br>
                    <span class='text-[10px] text-zinc-400'>HWID: <span class='text-[#00ffcc]'>{hwid_short}</span> | STATUS: <span class='{status_color} font-bold'>{u[4].upper()}</span></span>
                </div>
                <div class='flex gap-2 flex-wrap justify-end'>
                    <button onclick="editUser('{u[1]}','{u[2]}')" class='bg-blue-950/60 border border-blue-500/40 px-3 py-1.5 rounded-lg text-[10px] hover:bg-blue-900 transition font-bold'>EDIT</button>
                    <button onclick="toggleBan('{u[1]}')" class='bg-yellow-950/60 border border-yellow-500/40 px-3 py-1.5 rounded-lg text-[10px] hover:bg-yellow-900 transition font-bold'>{ban_text}</button>
                    <button onclick="resetHwid('{u[1]}')" class='bg-zinc-900 border border-white/20 px-3 py-1.5 rounded-lg text-[10px] hover:bg-zinc-800 transition font-bold'>RESET HWID</button>
                    <button onclick="deleteUser('{u[1]}')" class='bg-red-950/60 border border-red-500/40 px-3 py-1.5 rounded-lg text-[10px] hover:bg-red-900 transition font-bold'>DELETE</button>
                </div>
            </div>
            """
        
    return render_template_string(
        DASHBOARD_HTML,
        name=session["user"].get("name", "User"),
        email=email,
        plan_text=plan_text,
        plan_color=plan_color,
        limit_text=limit_text,
        app_options=app_options,
        active_token=active_token,
        app_list_html=app_list_html,
        keys_list_html=keys_list_html,
        tool_users_list_html=tool_users_list_html,
        tool_user_count=tool_user_count,
        percent=percent
    )

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ==========================================
# REST API ENDPOINTS FOR APP & USER MANAGEMENT
# ==========================================

@app.route("/api/create_app", methods=["POST"])
def api_create_app():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}}, 401
        
    email = session["user"]["email"]
    is_paid = email in PAID_USERS
    
    existing_apps = db("SELECT COUNT(*) FROM apps WHERE owner_email=?", (email,), True)
    app_count = existing_apps[0][0] if existing_apps else 0
    
    if not is_paid and app_count >= 2:
        return jsonify({"error": "Free plan is limited to 2 applications. Upgrade to Pro."}), 403
        
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    
    if not name:
        return jsonify({"error": "Application name is required"}), 400
        
    token = "hsl_" + "".join(random.choices(string.ascii_letters + string.digits, k=32))
    created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    
    db("INSERT INTO apps (name, token, owner_email, created_at) VALUES (?, ?, ?, ?)", (name, token, email, created_at))
    return jsonify({"success": True, "token": token, "message": "Application deployed successfully."})

@app.route("/api/delete_app", methods=["POST"])
def api_delete_app():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}}, 401
        
    email = session["user"]["email"]
    data = request.get_json() or {}
    token = data.get("token")
    
    app_record = db("SELECT * FROM apps WHERE token=? AND owner_email=?", (token, email), True)
    if not app_record:
        return jsonify({"error": "Application not found or unauthorized"}), 404
        
    db("DELETE FROM apps WHERE token=?", (token,))
    db("DELETE FROM tool_users WHERE app_token=?", (token,))
    db("DELETE FROM keys WHERE app_token=?", (token,))
    
    return jsonify({"success": True, "message": "Application and dependent records wiped."})

@app.route("/api/create_user", methods=["POST"])
def api_create_user():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}}, 401
        
    email = session["user"]["email"]
    is_paid = email in PAID_USERS
    
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    app_token = data.get("app_token", "").strip()
    
    if not username or not password or not app_token:
        return jsonify({"status": "error", "message": "All fields are required."}), 400
        
    app_check = db("SELECT * FROM apps WHERE token=? AND owner_email=?", (app_token, email), True)
    if not app_check:
        return jsonify({"status": "error", "message": "Invalid application token."}), 403
        
    if not is_paid:
        users_count = db("SELECT COUNT(*) FROM tool_users WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True)
        total_users = users_count[0][0] if users_count else 0
        if total_users >= 10:
            return jsonify({"status": "error", "message": "Free plan user limit (10) reached. Upgrade to Pro."}), 403
            
    existing = db("SELECT * FROM tool_users WHERE username=?", (username,), True)
    if existing:
        return jsonify({"status": "error", "message": "Username already taken."}), 400
        
    created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db("INSERT INTO tool_users (username, password, app_token, status, hwid, created_at) VALUES (?, ?, ?, ?, ?, ?)",
       (username, password, app_token, "active", "", created_at))
       
    return jsonify({"status": "success", "message": f"User '{username}' registered successfully."})

@app.route("/api/delete_user", methods=["POST"])
def api_delete_user():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}}, 401
        
    email = session["user"]["email"]
    data = request.get_json() or {}
    username = data.get("username")
    
    user_record = db("SELECT * FROM tool_users WHERE username=? AND app_token IN (SELECT token FROM apps WHERE owner_email=?)", (username, email), True)
    if not user_record:
        return jsonify({"message": "User not found or unauthorized."}), 404
        
    db("DELETE FROM tool_users WHERE username=?", (username,))
    return jsonify({"message": f"User '{username}' terminated successfully."})

@app.route("/api/reset_hwid", methods=["POST"])
def api_reset_hwid():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}}, 401
        
    email = session["user"]["email"]
    data = request.get_json() or {}
    username = data.get("username")
    
    user_record = db("SELECT * FROM tool_users WHERE username=? AND app_token IN (SELECT token FROM apps WHERE owner_email=?)", (username, email), True)
    if not user_record:
        return jsonify({"message": "User not found or unauthorized."}), 404
        
    db("UPDATE tool_users SET hwid='' WHERE username=?", (username,))
    return jsonify({"message": f"HWID unbound successfully for '{username}'."})

@app.route("/api/toggle_ban", methods=["POST"])
def api_toggle_ban():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}}, 401
        
    email = session["user"]["email"]
    data = request.get_json() or {}
    username = data.get("username")
    
    user_record = db("SELECT * FROM tool_users WHERE username=? AND app_token IN (SELECT token FROM apps WHERE owner_email=?)", (username, email), True)
    if not user_record:
        return jsonify({"message": "User not found or unauthorized."}), 404
        
    current_status = user_record[0][4]
    new_status = "banned" if current_status == "active" else "active"
    
    db("UPDATE tool_users SET status=? WHERE username=?", (new_status, username))
    return jsonify({"message": f"User status updated to '{new_status}' for '{username}'."})

@app.route("/api/edit_user", methods=["POST"])
def api_edit_user():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}}, 401
        
    email = session["user"]["email"]
    data = request.get_json() or {}
    old_username = data.get("old_username")
    new_username = data.get("new_username", "").strip()
    new_password = data.get("new_password", "").strip()
    
    if not new_username or not new_password:
        return jsonify({"message": "Fields cannot be blank."}), 400
        
    user_record = db("SELECT * FROM tool_users WHERE username=? AND app_token IN (SELECT token FROM apps WHERE owner_email=?)", (old_username, email), True)
    if not user_record:
        return jsonify({"message": "User not found or unauthorized."}), 404
        
    db("UPDATE tool_users SET username=?, password=? WHERE username=?", (new_username, new_password, old_username))
    return jsonify({"message": "User credentials modified successfully."})

# ==========================================
# PUBLIC CLIENT AUTHENTICATION ENDPOINT
# ==========================================

@app.route("/api/auth_login", methods=["POST"])
@rate_limit(max_requests=20, window_seconds=60)
def api_auth_login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    hwid = data.get("hwid", "").strip()
    token = data.get("token", "").strip()
    client_sig = data.get("sig", "").strip()
    
    if not username or not password or not hwid or not token or not client_sig:
        return jsonify({"status": "error", "message": "Incomplete payload or signature missing."}), 400
        
    raw_sig = f"{username}:{hwid}:{token}"
    expected_sig = hashlib.sha256(raw_sig.encode()).hexdigest()
    
    if client_sig != expected_sig:
        return jsonify({"status": "error", "message": "Signature verification failed. Anti-crack triggered."}), 403
        
    app_record = db("SELECT * FROM apps WHERE token=?", (token,), True)
    if not app_record:
        return jsonify({"status": "error", "message": "Invalid application token."}), 403
        
    user_record = db("SELECT * FROM tool_users WHERE username=? AND app_token=?", (username, token), True)
    if not user_record:
        return jsonify({"status": "error", "message": "Invalid username or password."}), 401
        
    db_id, db_user, db_pass, db_token, db_status, db_hwid, db_created = user_record[0]
    
    if db_pass != password:
        return jsonify({"status": "error", "message": "Invalid username or password."}), 401
        
    if db_status == "banned":
        return jsonify({"status": "error", "message": "Access denied. Account is banned."}), 403
        
    if not db_hwid:
        db("UPDATE tool_users SET hwid=? WHERE username=?", (hwid, username))
    elif db_hwid != hwid:
        return jsonify({"status": "error", "message": "HWID mismatch. License locked to another machine."}), 403
        
    return jsonify({
        "status": "success",
        "message": "Authentication granted.",
        "session_token": hashlib.sha256((username + str(time.time())).encode()).hexdigest()
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)