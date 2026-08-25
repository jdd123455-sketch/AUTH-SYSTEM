from flask import Flask, session, redirect, render_template_string, request, jsonify
from authlib.integrations.flask_client import OAuth
import sqlite3, random, string, os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "hsl_corp_final_2026_pro"

import os
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

# --- YAHAN PAID EMAILS DALO JINKO UNLIMITED DENA HAI ---
PAID_USERS = ["js7876839939@gmail.com"]

oauth = OAuth(app)
google = oauth.register(name='google', server_metadata_url='https://accounts.google.com/.well-known/openid-configuration', client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET, client_kwargs={'scope': 'openid email profile'})

def init_db():
    con = sqlite3.connect('hsl.db')
    cur = con.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS apps (id INTEGER PRIMARY KEY, name TEXT, token TEXT UNIQUE, owner_email TEXT, created_at TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS keys (id INTEGER PRIMARY KEY, key_text TEXT UNIQUE, app_token TEXT, status TEXT, hwid TEXT, used_by TEXT, created_at TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT, hwid TEXT, app_token TEXT, key_text TEXT, first_seen TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS tool_users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, app_token TEXT, status TEXT, hwid TEXT, created_at TEXT)''')
    con.commit(); con.close()
init_db()

def db(query, params=(), fetch=False):
    con = sqlite3.connect('hsl.db')
    cur = con.cursor()
    cur.execute(query, params)
    data = cur.fetchall() if fetch else None
    con.commit(); con.close()
    return data

LANDING = """<!DOCTYPE html><html><head><script src="https://cdn.tailwindcss.com"></script><style>body{background:#05010a}#c{position:fixed;inset:0;z-index:0}</style></head><body class="text-white overflow-x-hidden"><canvas id="c"></canvas><nav class="relative z-10 flex justify-between items-center px-8 py-4 bg-black/60 border-b border-white/5"><div class="flex items-center gap-2"><div class="w-7 h-7 bg-[#ff2d55] rounded-full flex items-center justify-center">👾</div><div><p class="font-black text-[13px]">HSL CORP</p><p class="text-[8px] text-red-400">NEXT-GEN SOFTWARE PROTECTION</p></div></div><div class="flex gap-2"><a href="/login" class="bg-zinc-900 border border-zinc-800 px-4 py-1.5 rounded-full text-[11px]">Sign In</a><a href="/login" class="bg-[#ff2d55] px-4 py-1.5 rounded-full text-[11px] font-bold">Create Account</a></div></nav><div class="relative z-10 flex flex-col items-center text-center pt-24"><h1 class="text-7xl font-black bg-gradient-to-r from-white to-[#ff5a7d] bg-clip-text text-transparent">HSL CORP AUTH</h1><p class="text-zinc-300 mt-4 font-bold text-[14px]">Next-Gen HWID Protection & Licensing Infrastructure</p><a href="/login" class="bg-[#ff2d55] px-6 py-2.5 rounded-xl text-xs font-bold shadow-[0_0_20px_rgba(255,45,85,0.6)] mt-8">🚀 Get Started - It's Free</a><div class="mt-24 w-full max-w-5xl px-6 pb-20"><p class="font-bold text-lg text-left">Core Infrastructure</p><div class="grid md:grid-cols-3 gap-4 mt-6 text-left"><div class="bg-black/60 border border-white/5 rounded-xl p-5"><p>🔒</p><p class="font-bold text-sm mt-2">Motherboard HWID Lock</p></div><div class="bg-black/60 border border-white/5 rounded-xl p-5"><p>🛡️</p><p class="font-bold text-sm mt-2">Dynamic AES-256 Session</p></div><div class="bg-black/60 border border-white/5 rounded-xl p-5"><p>🤖</p><p class="font-bold text-sm mt-2">Username/Pass Auth</p></div></div></div></div><script>const c=document.getElementById('c'),x=c.getContext('2d');function R(){c.width=innerWidth;c.height=innerHeight}R();onresize=R;let p=[];for(let i=0;i<90;i++)p.push({x:Math.random()*c.width,y:Math.random()*c.height,r:Math.random()*1.8+0.6,vy:Math.random()*0.7+0.2});function A(){x.clearRect(0,0,c.width,c.height);p.forEach(o=>{o.y-=o.vy;if(o.y<0){o.y=c.height;o.x=Math.random()*c.width}x.beginPath();x.arc(o.x,o.y,o.r,0,6.28);x.fillStyle='#ff2d55';x.shadowBlur=10;x.shadowColor='#ff2d55';x.fill();});requestAnimationFrame(A)}A();</script></body></html>"""
LOGIN = """<!DOCTYPE html><html><head><script src="https://cdn.tailwindcss.com"></script><style>body{background:#05010a}#c{position:fixed;inset:0;z-index:0}.glass{backdrop-filter:blur(20px); background:rgba(0,0,0,0.85); border:1px solid rgba(255,255,255,0.08)}</style></head><body class="flex items-center justify-center h-screen overflow-hidden"><canvas id="c"></canvas><div class="relative z-10 w-[420px] glass rounded-[24px] p-8 text-center"><div class="w-14 h-14 bg-[#ff2d55] rounded-full mx-auto flex items-center justify-center">👾</div><h1 class="font-black mt-4 text-white">HSL CORP</h1><a href="/auth/google" class="mt-6 w-full bg-white text-black rounded-full py-3.5 flex justify-center gap-2 font-bold text-sm"><img src="https://www.svgrepo.com/show/475656/google-color.svg" width=18> Continue with Google</a></div><script>const c=document.getElementById('c'),x=c.getContext('2d');function R(){c.width=innerWidth;c.height=innerHeight}R();onresize=R;let p=[];for(let i=0;i<110;i++)p.push({x:Math.random()*c.width,y:Math.random()*c.height,r:Math.random()*2+0.6,vy:Math.random()*0.8+0.2});function A(){x.clearRect(0,0,c.width,c.height);p.forEach(o=>{o.y-=o.vy;if(o.y<0){o.y=c.height;o.x=Math.random()*c.width}x.beginPath();x.arc(o.x,o.y,o.r,0,6.28);x.fillStyle='#ff2d55';x.shadowBlur=12;x.shadowColor='#ff2d55';x.fill();});requestAnimationFrame(A)}A();</script></body></html>"""

DASHBOARD_HTML = """
<!DOCTYPE html><html><head><script src="https://cdn.tailwindcss.com"></script>
<style>body{background:#08020a}#c{position:fixed;inset:0;z-index:0;opacity:1}.card{background:rgba(25,10,15,0.85); border:1px solid rgba(255,45,85,0.18)}.side-active{background:rgba(255,45,85,0.15); border:1px solid rgba(255,45,85,0.3); color:#ff2d55!important}</style></head>
<body class="flex h-screen text-white overflow-hidden relative"><canvas id="c"></canvas>
<div class="w-[240px] bg-black/90 border-r border-white/5 flex flex-col relative z-10">
<div class="p-4 flex items-center gap-2 border-b border-white/5"><div class="w-8 h-8 bg-[#ff2d55] rounded-full flex items-center justify-center">👾</div><div><p class="font-black text-[12px]">HSL CORP</p><p class="text-[8px] text-[#ff2d55]">Developer Console</p></div></div>
<div class="p-3 space-y-1 text-[11px]" id="sidebar">
<button onclick="showTab('overview')" id="btn-overview" class="side-active w-full text-left rounded-lg px-3 py-2">🏠 Overview</button>
<button onclick="showTab('applications')" id="btn-applications" class="w-full text-left text-zinc-500 px-3 py-2">📦 Applications</button>
<button onclick="showTab('tool_users')" id="btn-tool_users" class="w-full text-left text-zinc-500 px-3 py-2">👤 Users ({{tool_user_count}}/{{limit_text}})</button>
<button onclick="showTab('keys')" id="btn-keys" class="w-full text-left text-zinc-500 px-3 py-2">🔑 License Keys</button>
<button onclick="showTab('integrate')" id="btn-integrate" class="w-full text-left text-zinc-500 px-3 py-2">🔌 How to Integrate</button>
<button onclick="showTab('billing')" id="btn-billing" class="w-full text-left text-zinc-500 px-3 py-2">💎 Billing / Upgrade</button>
</div>
<div class="mt-auto p-3 border-t border-white/5 flex items-center gap-2"><img src="https://ui-avatars.com/api/?name={{name}}&background=ff2d55&color=fff" class="w-7 h-7 rounded-full"><div><p class="text-[10px] font-bold truncate w-[110px]">{{email}}</p><p class="text-[8px] {{plan_color}}">{{plan_text}}</p></div><a href="/logout" class="ml-auto text-[10px] text-red-400">Logout</a></div>
</div>
<div class="flex-1 overflow-y-auto relative z-10">
<div class="h-12 bg-black/60 border-b border-white/5 flex items-center justify-between px-6"><p class="text-[10px]">HSL CONSOLE - {{plan_text}} PLAN</p><div class="flex gap-2"><button onclick="showTab('billing')" class="text-[10px] bg-yellow-500 text-black px-4 py-1.5 rounded-full font-bold">Upgrade to Unlimited</button></div></div>
<div class="p-6">

<div id="tab-overview"><h1 class="text-xl font-bold">Dashboard Overview</h1>
<div class="mt-6 grid grid-cols-[1.3fr_1fr_0.7fr] gap-3">
<div class="card rounded-xl p-4"><p class="text-[9px] text-[#ff2d55]">ACTIVE APPLICATION</p><select id="appSelect" onchange="selectApp(this.value)" class="bg-black border border-white/10 rounded-lg px-3 py-2 text-[12px] mt-2 w-full">{{app_options}}</select></div>
<div class="card rounded-xl p-4"><p class="text-[9px] text-zinc-500">MASTER APP TOKEN</p><div class="mt-2 flex justify-between bg-black rounded-lg px-3 py-2 border border-white/5"><p id="tokenDisplay" class="text-[11px] text-zinc-400 truncate">{{active_token}}</p><button onclick="copyToken()" class="text-[9px] bg-[#ff2d55] px-3 py-1 rounded-full">Copy</button></div></div>
<div class="card rounded-xl p-4"><p class="text-[9px] text-zinc-500">PLAN LIMIT</p><p class="text-[11px] mt-2">{{tool_user_count}} / {{limit_text}} Used</p><div class="w-full bg-zinc-800 h-1.5 mt-2 rounded-full"><div class="bg-[#ff2d55] h-1.5 rounded-full" style="width:{{percent}}%"></div></div></div>
</div>
<div class="mt-6 card rounded-xl p-6">
<p class="text-sm font-bold">+ Create New Username / Password</p>
<div class="flex gap-2 mt-3">
<input id="newUsername" placeholder="Username" class="flex-1 bg-black border border-white/10 rounded-lg px-3 py-2.5 text-sm">
<input id="newPassword" placeholder="Password" class="flex-1 bg-black border border-white/10 rounded-lg px-3 py-2.5 text-sm">
</div>
<button onclick="createUser()" class="mt-3 w-full bg-[#ff2d55] py-2.5 rounded-full text-sm font-bold">Create User</button>
<p class="text-[10px] text-zinc-500 mt-2">Free plan me sirf 10 users bana sakte ho. Unlimited ke liye Billing dekho.</p>
</div>
</div>

<div id="tab-applications" class="hidden"><h1 class="text-xl font-bold">Applications</h1><div class="card mt-6 rounded-xl p-6"><div class="space-y-2 mb-6">{{app_list_html}}</div><div class="border-t border-white/10 pt-4"><p class="text-sm font-bold">+ Create New App</p><input id="newAppName" placeholder="App Name e.g. HSL Tool v1" class="mt-3 w-full bg-black border border-white/10 rounded-lg px-3 py-2.5 text-sm"><button onclick="createApp()" class="mt-3 w-full bg-[#ff2d55] py-2.5 rounded-full text-sm font-bold">Create Application</button></div></div></div>

<div id="tab-tool_users" class="hidden"><h1 class="text-xl font-bold">Username / Pass Users ({{tool_user_count}}/{{limit_text}})</h1><div class="card mt-6 rounded-xl p-5"><div class="space-y-2 text-[12px] font-mono">{{tool_users_list_html}}</div></div></div>

<div id="tab-keys" class="hidden"><h1 class="text-xl font-bold">License Keys (Old System)</h1><div class="card mt-6 rounded-xl p-5"><p class="text-[10px] text-zinc-500 mb-4">Ye purana system hai, ab Username/Pass use karo. Free plan me ye bhi 10 limit me count hoga.</p><div class="mt-4 space-y-2 text-[12px] font-mono">{{keys_list_html}}</div></div></div>

<div id="tab-integrate" class="hidden"><h1 class="text-xl font-bold">How to Integrate in Your Tool</h1><div class="card mt-6 rounded-xl p-6">
<p class="text-[12px] text-zinc-400">Step 1: Your App Token (Auto Generated for selected app)</p>
<div class="mt-2 bg-black border border-[#ff2d55]/30 rounded-lg px-3 py-2 flex justify-between"><p id="tokenDisplay2" class="text-[12px] text-[#ff2d55] truncate">{{active_token}}</p><button onclick="copyToken2()" class="text-[9px] bg-[#ff2d55] px-3 py-1 rounded-full">Copy</button></div>
<p class="text-[12px] text-zinc-400 mt-6">Step 2: Add this code in your Python Tool's app.py</p>
<pre class="mt-2 bg-black border border-white/10 rounded-lg p-4 text-[11px] overflow-x-auto text-green-300">import requests, subprocess
MY_APP_TOKEN = "{{active_token}}"
AUTH_URL = "https://YOUR-DOMAIN.com/api/auth_login" # apne domain se change karo

def get_hwid():
    try:
        import subprocess
        r = subprocess.check_output('wmic baseboard get serialnumber', shell=True).decode().split('\\n')[1].strip()
        return r
    except:
        return "UNKNOWN"

# --- login check ---
# r = requests.post(AUTH_URL, json={'username':u,'password':p,'hwid':get_hwid(),'token':MY_APP_TOKEN}).json()
# if r['status']=='valid': login success
</pre>
<p class="text-[12px] text-zinc-400 mt-6">Step 3: Dashboard > Overview se Username/Password banao aur apne customer ko do. Bas!</p>
<p class="text-[11px] text-zinc-500 mt-3">Ban/Reset: Agar customer ka PC change ho toh Dashboard > Users > Reset HWID dabao. Agar ban karna ho toh Ban dabao.</p>
</div></div>

<div id="tab-billing" class="hidden"><h1 class="text-xl font-bold">Billing / Plans</h1>
<div class="grid grid-cols-2 gap-4 mt-6">
<div class="card rounded-xl p-6 border border-zinc-700"><p class="font-bold">FREE PLAN</p><p class="text-3xl font-black mt-2">₹0</p><p class="text-[12px] text-zinc-400 mt-2">✓ 10 Users / Keys Only<br>✓ 1 Application<br>✓ HWID Lock</p><p class="mt-4 text-[11px] bg-zinc-800 rounded-full px-3 py-1 inline-block">Current: {{plan_text}}</p></div>
<div class="card rounded-xl p-6 border border-[#ff2d55] bg-[#ff2d55]/10"><p class="font-bold text-[#ff2d55]">PRO UNLIMITED</p><p class="text-3xl font-black mt-2">₹499</p><p class="text-[12px] text-zinc-300 mt-2">✓ Unlimited Users<br>✓ Unlimited Apps<br>✓ Unlimited Keys<br>✓ Priority Support</p><a href="https://wa.me/919999999999?text=Hi%20I%20want%20HSL%20PRO%20Plan%20{{email}}" target="_blank" class="mt-4 block text-center bg-[#ff2d55] py-2.5 rounded-full text-sm font-bold">Buy on WhatsApp</a></div>
</div>
</div>

</div></div>
<script>
const c=document.getElementById('c'),x=c.getContext('2d');function R(){c.width=innerWidth;c.height=innerHeight}R();addEventListener('resize',R);let p=[];for(let i=0;i<150;i++)p.push({x:Math.random()*c.width,y:Math.random()*c.height,r:Math.random()*2+0.8,vy:Math.random()*0.7+0.3,opacity:Math.random()*0.7+0.3});function A(){x.clearRect(0,0,c.width,c.height);p.forEach(o=>{o.y-=o.vy;if(o.y<0){o.y=c.height;o.x=Math.random()*c.width}x.beginPath();x.arc(o.x,o.y,o.r,0,6.28);x.fillStyle=`rgba(255,45,85,${o.opacity})`;x.shadowBlur=15;x.shadowColor='#ff2d55';x.fill();});requestAnimationFrame(A)}A();
function showTab(name){document.querySelectorAll('[id^="tab-"]').forEach(d=>d.classList.add('hidden'));document.getElementById('tab-'+name).classList.remove('hidden');document.querySelectorAll('#sidebar button').forEach(b=>{b.classList.remove('side-active');b.classList.add('text-zinc-500')});let btn=document.getElementById('btn-'+name);if(btn){btn.classList.add('side-active');btn.classList.remove('text-zinc-500')}}
async function createApp(){let name=document.getElementById('newAppName').value.trim();if(!name){alert('Name likh!');return;}let res=await fetch('/api/create_app',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})});let data=await res.json();if(data.error){alert(data.error);}else{alert('App Created! Token: '+data.token);location.reload();}}
function copyToken(){let t=document.getElementById('tokenDisplay').innerText;navigator.clipboard.writeText(t);alert('Copied: '+t);}
function copyToken2(){let t=document.getElementById('tokenDisplay2').innerText;navigator.clipboard.writeText(t);alert('Token Copied!');}
function selectApp(token){document.getElementById('tokenDisplay').innerText=token;document.getElementById('tokenDisplay2').innerText=token;}
async function createUser(){let u=document.getElementById('newUsername').value.trim();let p=document.getElementById('newPassword').value.trim();let token=document.getElementById('tokenDisplay').innerText;if(!u||!p){alert('Username Pass likh!');return;}let res=await fetch('/api/create_user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p,app_token:token})});let data=await res.json();alert(data.message);location.reload();}
async function deleteUser(username){if(!confirm('Delete '+username+'?'))return;let res=await fetch('/api/delete_user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:username})});let data=await res.json();alert(data.message);location.reload();}
async function resetHwid(username){let res=await fetch('/api/reset_hwid',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:username})});let data=await res.json();alert(data.message);location.reload();}
async function toggleBan(username){let res=await fetch('/api/toggle_ban',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:username})});let data=await res.json();alert(data.message);location.reload();}
async function editUser(oldU, oldP){
    let newU = prompt("New Username (khali chhode toh same rahega):", oldU);
    if(newU===null) return;
    let newP = prompt("New Password:", oldP);
    if(newP===null) return;
    let res=await fetch('/api/edit_user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old_username:oldU, new_username:newU.trim(), new_password:newP.trim()})});
    let data=await res.json(); alert(data.message); location.reload();
}
</script></body></html>
"""

@app.route("/")
def home(): return render_template_string(LANDING)
@app.route("/login")
def login(): return render_template_string(LOGIN)
@app.route("/auth/google")
def auth_google(): return google.authorize_redirect("http://127.0.0.1:5000/auth/callback")
@app.route("/auth/callback")
def callback():
    token = google.authorize_access_token()
    user = token.get('userinfo') or google.get('https://openidconnect.googleapis.com/v1/userinfo').json()
    session['user'] = user
    return redirect("/dashboard")

@app.route("/dashboard")
def dash():
    if 'user' not in session: return redirect("/login")
    email = session['user']['email']
    is_paid = email in PAID_USERS
    limit = 999999 if is_paid else 10
    limit_text = "Unlimited" if is_paid else "10"
    plan_text = "PRO UNLIMITED" if is_paid else "FREE"
    plan_color = "text-green-400" if is_paid else "text-yellow-400"

    apps = db("SELECT * FROM apps WHERE owner_email=?", (email,), True)
    if not apps:
        app_options = "<option>No Apps Created</option>"
        active_token = "Create an app to get Token"
        app_list_html = "<p class='text-zinc-500 text-sm'>No apps yet - Create one below</p>"
    else:
        app_options = "".join([f"<option value='{a[2]}'>{a[1]}</option>" for a in apps])
        active_token = apps[0][2]
        app_list_html = "".join([f"<div class='bg-black border border-white/10 rounded-lg px-3 py-2 flex justify-between'><span>{a[1]}</span><span class='text-[10px] text-zinc-500'>{a[2][:20]}...</span></div>" for a in apps])

    keys = db("SELECT * FROM keys WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True) if apps else []
    keys_list_html = "".join([f"<div class='flex justify-between bg-black border border-white/10 rounded-lg px-3 py-2'><span>{k[1]}</span><span class='{ 'text-green-400' if k[3]=='unused' else 'text-red-400'}'>● {k[3]}</span></div>" for k in keys]) if keys else "<p class='text-center text-zinc-600 text-xs mt-10'>No keys</p>"

    tool_users = db("SELECT * FROM tool_users WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True) if apps else []
    tool_user_count = len(tool_users)
    percent = 10 if tool_user_count==0 else min(int(tool_user_count/limit*100),100) if not is_paid else 100

    tool_users_list_html = ""
    for u in tool_users:
        hwid_short = (u[5][:15] + '...') if u[5] else 'Not Logged Yet'
        status_color = "text-green-400" if u[4]=='active' else "text-red-400"
        ban_text = "Ban" if u[4]=='active' else "Unban"
        tool_users_list_html += f"""
        <div class='flex justify-between items-center bg-black border border-white/10 rounded-lg px-3 py-3 mb-2'>
            <div>
                <span class='text-white font-bold'>{u[1]}</span><span class='text-zinc-500'> / {u[2]}</span><br>
                <span class='text-[10px] text-zinc-500'>HWID: {hwid_short} | Status: <span class='{status_color}'>{u[4].upper()}</span></span>
            </div>
            <div class='flex gap-1.5 flex-wrap justify-end max-w-[60%]'>
                <button onclick="editUser('{u[1]}','{u[2]}')" class='bg-blue-900/50 border border-blue-500/30 px-2.5 py-1 rounded text-[10px] hover:bg-blue-800'>Edit</button>
                <button onclick="toggleBan('{u[1]}')" class='bg-yellow-900/50 border border-yellow-500/30 px-2.5 py-1 rounded text-[10px] hover:bg-yellow-800'>{ban_text}</button>
                <button onclick="resetHwid('{u[1]}')" class='bg-zinc-800 border border-white/10 px-2.5 py-1 rounded text-[10px]'>Reset HWID</button>
                <button onclick="deleteUser('{u[1]}')" class='bg-red-900/50 border border-red-500/30 px-2.5 py-1 rounded text-[10px]'>Delete</button>
            </div>
        </div>
        """
    if not tool_users_list_html:
        tool_users_list_html = "<p class='text-center text-zinc-600 text-xs mt-10'>No users yet. Create from Overview.</p>"

    html = DASHBOARD_HTML.replace("{{name}}", session['user']['name']).replace("{{email}}", email).replace("{{app_options}}", app_options).replace("{{active_token}}", active_token).replace("{{app_list_html}}", app_list_html).replace("{{keys_list_html}}", keys_list_html).replace("{{tool_user_count}}", str(tool_user_count)).replace("{{limit_text}}", limit_text).replace("{{plan_text}}", plan_text).replace("{{plan_color}}", plan_color).replace("{{percent}}", str(percent)).replace("{{tool_users_list_html}}", tool_users_list_html)
    return render_template_string(html)

def check_limit(email):
    if email in PAID_USERS:
        return False
    tool_users = db("SELECT COUNT(*) FROM tool_users WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True)
    keys = db("SELECT COUNT(*) FROM keys WHERE app_token IN (SELECT token FROM apps WHERE owner_email=?)", (email,), True)
    total = (tool_users[0][0] if tool_users else 0) + (keys[0][0] if keys else 0)
    return total >= 10

@app.route("/api/create_app", methods=['POST'])
def api_create_app():
    if 'user' not in session: return jsonify({"error":"not logged"}), 401
    email = session['user']['email']
    apps = db("SELECT COUNT(*) FROM apps WHERE owner_email=?", (email,), True)
    if email not in PAID_USERS and apps[0][0] >= 1:
        return jsonify({"error":"FREE plan me sirf 1 App bana sakte ho. PRO lo Unlimited ke liye! 💎"})
    name = request.json.get('name')
    token = 'HSL_'+''.join(random.choices(string.ascii_uppercase+string.digits, k=20))
    db("INSERT INTO apps (name, token, owner_email, created_at) VALUES (?,?,?,?)", (name, token, email, datetime.now().isoformat()))
    return jsonify({"token":token})

@app.route("/api/create_user", methods=['POST'])
def api_create_user():
    if 'user' not in session: return jsonify({"message":"not logged"}), 401
    email = session['user']['email']
    if check_limit(email):
        return jsonify({"message":"LIMIT REACHED! Free plan me sirf 10 Users/Keys. PRO Plan lo Unlimited ke liye - Billing tab dekho! 💎"})
    data = request.json
    username = data.get('username').strip()
    password = data.get('password').strip()
    app_token = data.get('app_token')
    if "Create an app" in app_token:
        return jsonify({"message":"Pehle ek Application banao!"})
    try:
        db("INSERT INTO tool_users (username, password, app_token, status, created_at) VALUES (?,?,?,?,?)", (username, password, app_token, 'active', datetime.now().isoformat()))
        return jsonify({"message":f"User Created: {username}"})
    except:
        return jsonify({"message":"Username already exists!"})

@app.route("/api/delete_user", methods=['POST'])
def api_delete_user():
    username = request.json.get('username')
    db("DELETE FROM tool_users WHERE username=?", (username,))
    return jsonify({"message":"Deleted"})

@app.route("/api/reset_hwid", methods=['POST'])
def api_reset_hwid():
    username = request.json.get('username')
    db("UPDATE tool_users SET hwid=NULL, status='active' WHERE username=?", (username,))
    return jsonify({"message":f"HWID Reset for {username} - Ab dusre PC pe login kar sakta hai"})

@app.route("/api/toggle_ban", methods=['POST'])
def api_toggle_ban():
    username = request.json.get('username')
    res = db("SELECT status FROM tool_users WHERE username=?", (username,), True)
    if not res: return jsonify({"message":"User not found"})
    cur_status = res[0][0]
    new_status = 'banned' if cur_status=='active' else 'active'
    db("UPDATE tool_users SET status=? WHERE username=?", (new_status, username))
    return jsonify({"message":f"{username} is now {new_status.upper()}"})

@app.route("/api/edit_user", methods=['POST'])
def api_edit_user():
    old_u = request.json.get('old_username')
    new_u = request.json.get('new_username')
    new_p = request.json.get('new_password')
    if not new_u: new_u = old_u
    try:
        db("UPDATE tool_users SET username=?, password=? WHERE username=?", (new_u, new_p, old_u))
        return jsonify({"message":f"Updated: {old_u} -> {new_u}"})
    except:
        return jsonify({"message":"Username already exists! Choose different"})

@app.route("/api/validate", methods=['POST'])
def api_validate():
    data = request.json
    token = data.get('token')
    key_text = data.get('key')
    hwid = data.get('hwid')
    res = db("SELECT * FROM keys WHERE key_text=? AND app_token=?", (key_text, token), True)
    if not res: return jsonify({"status":"invalid"})
    key_row = res[0]
    if key_row[3] == 'unused':
        db("UPDATE keys SET status='used', hwid=?, used_by=? WHERE key_text=?", (hwid, hwid, key_text))
        return jsonify({"status":"valid"})
    else:
        if key_row[4] == hwid: return jsonify({"status":"valid"})
        else: return jsonify({"status":"hwid_mismatch"})

@app.route("/api/auth_login", methods=['POST'])
def api_auth_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    hwid = data.get('hwid')
    token = data.get('token')
    res = db("SELECT * FROM tool_users WHERE username=? AND password=? AND app_token=?", (username, password, token), True)
    if not res:
        return jsonify({"status":"invalid", "message":"Wrong Username/Password"})
    user_row = res[0]
    if user_row[4] == 'banned':
        return jsonify({"status":"banned", "message":"User Banned by Admin"})
    if not user_row[5]:
        db("UPDATE tool_users SET hwid=?, status='active' WHERE username=?", (hwid, username))
        return jsonify({"status":"valid", "message":"First Login - HWID Locked"})
    else:
        if user_row[5] == hwid:
            return jsonify({"status":"valid", "message":"Welcome back"})
        else:
            return jsonify({"status":"hwid_mismatch", "message":"Locked to another PC. Ask Admin to Reset HWID."})

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(port=5000, debug=True)