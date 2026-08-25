import os
import time
import secrets
import sqlite3
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from html import escape

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
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth


# ============================================================
# HSL CORP AUTH PANEL
# STABLE / LOW-LAG / FIXED VERSION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hsl.db")


# ============================================================
# APP
# ============================================================

app = Flask(__name__)

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
)

SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")

if not SECRET_KEY:
    # Development fallback only.
    # On production, set FLASK_SECRET_KEY in environment variables.
    SECRET_KEY = "CHANGE_THIS_HSL_CORP_SECRET_2026"

app.secret_key = SECRET_KEY

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
)


# ============================================================
# GOOGLE OAUTH
# ============================================================

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

PAID_USERS = {
    "js7876839939@gmail.com",
}


oauth = OAuth(app)

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    google = oauth.register(
        name="google",
        server_metadata_url=(
            "https://accounts.google.com/"
            ".well-known/openid-configuration"
        ),
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        client_kwargs={
            "scope": "openid email profile"
        },
    )
else:
    google = None


# ============================================================
# CONSTANTS
# ============================================================

FREE_APP_LIMIT = 2
FREE_RESOURCE_LIMIT = 10

RATE_HISTORY = {}

MAX_USERNAME = 40
MAX_PASSWORD = 128
MAX_APP_NAME = 50


# ============================================================
# DATABASE
# ============================================================

def get_db():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def db_execute(query, params=()):
    con = get_db()

    try:
        cur = con.cursor()
        cur.execute(query, params)
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def db_fetchone(query, params=()):
    con = get_db()

    try:
        cur = con.cursor()
        cur.execute(query, params)
        return cur.fetchone()
    finally:
        con.close()


def db_fetchall(query, params=()):
    con = get_db()

    try:
        cur = con.cursor()
        cur.execute(query, params)
        return cur.fetchall()
    finally:
        con.close()


def init_db():
    con = get_db()

    try:
        cur = con.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS apps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                owner_email TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tool_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                app_token TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                hwid TEXT,
                created_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_text TEXT UNIQUE NOT NULL,
                app_token TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'unused',
                hwid TEXT,
                used_by TEXT,
                created_at TEXT NOT NULL
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

        con.commit()

    finally:
        con.close()


init_db()


# ============================================================
# HELPERS
# ============================================================

def now_iso():
    return datetime.utcnow().isoformat()


def clean_text(value, max_length):
    if value is None:
        return ""

    value = str(value).strip()

    return value[:max_length]


def generate_app_token():
    return "HSL_" + secrets.token_urlsafe(24).replace("-", "").replace("_", "")[:32]


def hash_password(password):
    return generate_password_hash(password)


def verify_password(stored, password):
    try:
        return check_password_hash(stored, password)
    except Exception:
        # Backward compatibility for old plaintext passwords.
        return secrets.compare_digest(stored, password)


def current_email():
    user = session.get("user")

    if not user:
        return None

    return user.get("email")


def is_logged_in():
    return "user" in session and bool(current_email())


def is_paid(email):
    return email in PAID_USERS


def require_login():
    if not is_logged_in():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    return None


def json_body():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return {}

    return data


# ============================================================
# RATE LIMIT
# ============================================================

def rate_limit(max_requests=10, window_seconds=60):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            ip = request.headers.get(
                "X-Forwarded-For",
                request.remote_addr or "unknown"
            ).split(",")[0].strip()

            key = f"{func.__name__}:{ip}"

            current = time.time()

            history = RATE_HISTORY.get(key, [])

            history = [
                timestamp
                for timestamp in history
                if current - timestamp < window_seconds
            ]

            if len(history) >= max_requests:
                RATE_HISTORY[key] = history

                return jsonify({
                    "status": "rate_limited",
                    "message": "Too many requests. Please try again later."
                }), 429

            history.append(current)
            RATE_HISTORY[key] = history

            # Avoid unlimited memory growth.
            if len(RATE_HISTORY) > 5000:
                old_keys = list(RATE_HISTORY.keys())[:1000]

                for old_key in old_keys:
                    RATE_HISTORY.pop(old_key, None)

            return func(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================
# SECURITY HEADERS
# ============================================================

@app.after_request
def security_headers(response):

    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = (
        "strict-origin-when-cross-origin"
    )
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )

    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https: data: blob: 'unsafe-inline' "
        "'unsafe-eval'; img-src 'self' https: data:;"
    )

    return response


# ============================================================
# LOW-LAG COMMON CSS
# ============================================================

COMMON_HEAD = r"""
<script src="https://cdn.tailwindcss.com"></script>

<style>

:root{
    --cyan:#00eaff;
    --blue:#2563eb;
    --violet:#7c3aed;
    --red:#ff1744;
    --bg:#03050a;
}

*{
    box-sizing:border-box;
}

html{
    scroll-behavior:smooth;
}

body{
    margin:0;
    background:
        radial-gradient(
            circle at 50% -10%,
            rgba(0,234,255,.10),
            transparent 35%
        ),
        radial-gradient(
            circle at 100% 100%,
            rgba(124,58,237,.08),
            transparent 30%
        ),
        #03050a;

    color:#f8fafc;
    font-family:
        Inter,
        ui-sans-serif,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    letter-spacing:.01em;
}

::selection{
    background:rgba(0,234,255,.25);
    color:white;
}

::-webkit-scrollbar{
    width:6px;
}

::-webkit-scrollbar-track{
    background:#020308;
}

::-webkit-scrollbar-thumb{
    background:#155e75;
    border-radius:999px;
}

#particles{
    position:fixed;
    inset:0;
    width:100%;
    height:100%;
    z-index:0;
    pointer-events:none;
    opacity:.72;
}

.ambient{
    position:fixed;
    inset:0;
    z-index:0;
    pointer-events:none;

    background:
        radial-gradient(
            circle at 20% 30%,
            rgba(0,234,255,.045),
            transparent 25%
        ),
        radial-gradient(
            circle at 80% 20%,
            rgba(124,58,237,.045),
            transparent 25%
        );
}

.vignette{
    position:fixed;
    inset:0;
    z-index:2;
    pointer-events:none;

    box-shadow:
        inset 0 0 130px rgba(0,0,0,.82);
}

.grid-bg{
    position:fixed;
    inset:0;
    z-index:1;
    pointer-events:none;

    background-image:
        linear-gradient(
            rgba(255,255,255,.012) 1px,
            transparent 1px
        ),
        linear-gradient(
            90deg,
            rgba(255,255,255,.012) 1px,
            transparent 1px
        );

    background-size:48px 48px;
}

.glass{
    background:
        linear-gradient(
            145deg,
            rgba(13,19,32,.90),
            rgba(3,7,14,.82)
        );

    border:1px solid rgba(0,234,255,.15);

    box-shadow:
        0 15px 50px rgba(0,0,0,.35),
        inset 0 1px 0 rgba(255,255,255,.035);

    backdrop-filter:blur(16px);
    -webkit-backdrop-filter:blur(16px);
}

.card{
    background:
        linear-gradient(
            145deg,
            rgba(12,18,31,.88),
            rgba(3,7,14,.80)
        );

    border:1px solid rgba(0,234,255,.11);

    box-shadow:
        0 10px 35px rgba(0,0,0,.28);

    transition:
        transform .2s ease,
        border-color .2s ease,
        box-shadow .2s ease;
}

.card:hover{
    transform:translateY(-3px);
    border-color:rgba(0,234,255,.28);

    box-shadow:
        0 15px 45px rgba(0,0,0,.40),
        0 0 25px rgba(0,234,255,.06);
}

button,
a{
    transition:
        transform .15s ease,
        filter .15s ease,
        border-color .15s ease;
}

button:hover,
a:hover{
    filter:brightness(1.08);
}

button:active,
a:active{
    transform:scale(.98);
}

input,
select{
    outline:none;
}

input:focus,
select:focus{
    border-color:rgba(0,234,255,.55)!important;
    box-shadow:0 0 0 2px rgba(0,234,255,.06);
}

.side-active{
    color:#67f7ff!important;
    background:rgba(0,234,255,.10)!important;
    border:1px solid rgba(0,234,255,.28)!important;
    box-shadow:
        inset 3px 0 0 var(--cyan),
        0 0 18px rgba(0,234,255,.05);
}

.cursor-dot,
.cursor-ring{
    position:fixed;
    pointer-events:none;
    z-index:99999;
}

.cursor-dot{
    width:6px;
    height:6px;
    border-radius:50%;
    background:var(--cyan);
    box-shadow:
        0 0 8px var(--cyan),
        0 0 18px var(--cyan);
    transform:translate(-50%,-50%);
}

.cursor-ring{
    width:28px;
    height:28px;
    border:1px solid rgba(0,234,255,.55);
    border-radius:50%;
    transform:translate(-50%,-50%);
    transition:
        width .15s ease,
        height .15s ease,
        border-color .15s ease;
}

.cursor-ring::before,
.cursor-ring::after{
    content:"";
    position:absolute;
    background:rgba(0,234,255,.65);
}

.cursor-ring::before{
    width:40px;
    height:1px;
    left:-7px;
    top:13px;
}

.cursor-ring::after{
    width:1px;
    height:40px;
    left:13px;
    top:-7px;
}

@media(max-width:768px){

    .cursor-dot,
    .cursor-ring{
        display:none;
    }

    body{
        cursor:auto;
    }
}

@media(prefers-reduced-motion:reduce){

    *,
    *::before,
    *::after{
        animation:none!important;
        transition:none!important;
    }
}

</style>
"""


# ============================================================
# PARTICLES / CURSOR
# ============================================================

CURSOR_SCRIPT = r"""
<div class="cursor-dot" id="cursorDot"></div>
<div class="cursor-ring" id="cursorRing"></div>

<script>

(() => {

    const canvas = document.getElementById("particles");

    if(!canvas){
        return;
    }

    const ctx = canvas.getContext("2d", {
        alpha:true
    });

    const dot = document.getElementById("cursorDot");
    const ring = document.getElementById("cursorRing");

    let width = 0;
    let height = 0;

    let mouseX = -100;
    let mouseY = -100;

    let ringX = -100;
    let ringY = -100;

    const particles = [];

    const MOBILE =
        window.matchMedia("(max-width: 768px)").matches;

    const COUNT = MOBILE ? 25 : 70;

    function resize(){

        const dpr = Math.min(
            window.devicePixelRatio || 1,
            1.5
        );

        width = window.innerWidth;
        height = window.innerHeight;

        canvas.width = width * dpr;
        canvas.height = height * dpr;

        canvas.style.width = width + "px";
        canvas.style.height = height + "px";

        ctx.setTransform(
            dpr,
            0,
            0,
            dpr,
            0,
            0
        );
    }

    resize();

    window.addEventListener(
        "resize",
        resize,
        {passive:true}
    );

    for(let i = 0; i < COUNT; i++){

        particles.push({
            x:Math.random()*window.innerWidth,
            y:Math.random()*window.innerHeight,
            vx:(Math.random()-.5)*.16,
            vy:(Math.random()-.5)*.16,
            r:Math.random()*1.25+.35,
            a:Math.random()*.55+.15
        });
    }

    window.addEventListener(
        "mousemove",
        e => {

            mouseX = e.clientX;
            mouseY = e.clientY;

            if(dot){
                dot.style.left = mouseX + "px";
                dot.style.top = mouseY + "px";
            }

        },
        {passive:true}
    );

    document.addEventListener(
        "mouseover",
        e => {

            if(
                e.target &&
                (
                    e.target.closest("button") ||
                    e.target.closest("a")
                )
            ){

                if(ring){

                    ring.style.width = "38px";
                    ring.style.height = "38px";
                }
            }

        },
        {passive:true}
    );

    document.addEventListener(
        "mouseout",
        e => {

            if(
                e.target &&
                (
                    e.target.closest("button") ||
                    e.target.closest("a")
                )
            ){

                if(ring){

                    ring.style.width = "28px";
                    ring.style.height = "28px";
                }
            }

        },
        {passive:true}
    );

    function animateCursor(){

        ringX += (mouseX-ringX)*.13;
        ringY += (mouseY-ringY)*.13;

        if(ring){

            ring.style.left = ringX + "px";
            ring.style.top = ringY + "px";
        }

        requestAnimationFrame(
            animateCursor
        );
    }

    animateCursor();


    function draw(){

        ctx.clearRect(
            0,
            0,
            width,
            height
        );

        for(let i=0;i<particles.length;i++){

            const p = particles[i];

            p.x += p.vx;
            p.y += p.vy;

            if(p.x < -10) p.x = width+10;
            if(p.x > width+10) p.x = -10;

            if(p.y < -10) p.y = height+10;
            if(p.y > height+10) p.y = -10;

            ctx.beginPath();

            ctx.arc(
                p.x,
                p.y,
                p.r,
                0,
                Math.PI*2
            );

            ctx.fillStyle =
                "rgba(34,211,238," +
                p.a +
                ")";

            ctx.fill();
        }

        requestAnimationFrame(draw);
    }

    draw();

})();

</script>
"""


# ============================================================
# LANDING
# ============================================================

LANDING = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HSL CORP</title>
""" + COMMON_HEAD + r"""
</head>

<body class="min-h-screen overflow-x-hidden">

<canvas id="particles"></canvas>
<div class="grid-bg"></div>
<div class="ambient"></div>
<div class="vignette"></div>

<nav class="
relative z-10
flex items-center justify-between
px-6 md:px-10 py-5
border-b border-cyan-400/10
bg-black/45
">

<div class="flex items-center gap-3">

<div class="
w-10 h-10
rounded-xl
bg-gradient-to-r from-cyan-400 to-indigo-600
flex items-center justify-center
shadow-[0_0_20px_rgba(0,234,255,.4)]
">
👾
</div>

<div>
<p class="font-black text-sm">
HSL CORP
</p>

<p class="text-[9px] text-cyan-400 font-bold tracking-widest">
AUTH INFRASTRUCTURE
</p>
</div>

</div>

<div class="flex gap-3">

<a
href="/login"
class="
px-5 py-2.5
rounded-xl
text-xs font-bold
bg-zinc-900
border border-white/10
">
Sign In
</a>

<a
href="/dashboard"
class="
px-5 py-2.5
rounded-xl
text-xs font-bold
bg-gradient-to-r from-cyan-400 to-indigo-600
shadow-[0_0_20px_rgba(0,234,255,.3)]
">
Dashboard
</a>

</div>

</nav>


<main class="
relative z-10
max-w-6xl
mx-auto
px-6
pt-24
pb-24
">

<div class="text-center">

<div class="
inline-flex
px-4 py-2
rounded-full
border border-cyan-400/20
bg-cyan-400/5
text-cyan-300
text-xs font-bold
">
⚡ NEXT-GEN AUTH PANEL
</div>

<h1 class="
mt-7
text-5xl md:text-7xl
font-black
bg-gradient-to-r
from-cyan-300
via-cyan-400
to-indigo-500
bg-clip-text
text-transparent
">
HSL CORP
</h1>

<p class="
mt-5
text-zinc-400
max-w-2xl
mx-auto
text-sm md:text-lg
">
Hardware-bound application authentication,
license management and developer control panel.
</p>

<a
href="/login"
class="
inline-flex
mt-9
px-8 py-4
rounded-2xl
font-bold text-sm
bg-gradient-to-r
from-cyan-400
to-indigo-600
shadow-[0_0_30px_rgba(0,234,255,.35)]
">
🚀 Enter Console
</a>

</div>


<div class="
grid
md:grid-cols-3
gap-5
mt-24
">

<div class="card rounded-2xl p-7">
<div class="text-3xl">🔐</div>
<h2 class="mt-4 font-bold text-cyan-300">
HWID Protection
</h2>
<p class="mt-2 text-xs text-zinc-400 leading-relaxed">
Bind application users to a hardware identifier
and control resets from the dashboard.
</p>
</div>


<div class="card rounded-2xl p-7">
<div class="text-3xl">🛡️</div>
<h2 class="mt-4 font-bold text-indigo-300">
API Authentication
</h2>
<p class="mt-2 text-xs text-zinc-400 leading-relaxed">
Authenticated API endpoints with rate limiting,
session protection and validation.
</p>
</div>


<div class="card rounded-2xl p-7">
<div class="text-3xl">⚡</div>
<h2 class="mt-4 font-bold text-cyan-300">
Developer Console
</h2>
<p class="mt-2 text-xs text-zinc-400 leading-relaxed">
Manage applications, users, HWID bindings and
account status from one place.
</p>
</div>

</div>

</main>


<footer class="
relative z-10
text-center
border-t border-white/5
py-6
text-xs text-zinc-600
">
© 2026 HSL CORP
</footer>

""" + CURSOR_SCRIPT + r"""

</body>
</html>
"""


# ============================================================
# LOGIN
# ============================================================

LOGIN = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HSL CORP Login</title>
""" + COMMON_HEAD + r"""
</head>

<body class="min-h-screen flex items-center justify-center">

<canvas id="particles"></canvas>
<div class="grid-bg"></div>
<div class="ambient"></div>
<div class="vignette"></div>


<div class="
relative z-10
w-[92%] max-w-[420px]
glass
rounded-3xl
p-8
text-center
">

<div class="
w-16 h-16
mx-auto
rounded-2xl
bg-gradient-to-r
from-cyan-400 to-indigo-600
flex items-center justify-center
text-2xl
shadow-[0_0_25px_rgba(0,234,255,.35)]
">
👾
</div>

<h1 class="
mt-5
text-2xl
font-black
bg-gradient-to-r
from-cyan-300 to-indigo-400
bg-clip-text
text-transparent
">
HSL CORP
</h1>

<p class="
mt-2
text-xs text-zinc-500
">
Secure developer authentication
</p>


{% if oauth_enabled %}

<a
href="/auth/google"
class="
mt-8
w-full
flex items-center justify-center
gap-3
bg-white
text-black
rounded-xl
py-3.5
font-bold text-sm
">
<img
src="https://www.svgrepo.com/show/475656/google-color.svg"
width="20"
height="20"
alt="Google">
Continue with Google
</a>

{% else %}

<div class="
mt-8
p-4
rounded-xl
border border-yellow-500/20
bg-yellow-500/5
text-yellow-300
text-xs
">
Google OAuth is not configured.
Set GOOGLE_CLIENT_ID and
GOOGLE_CLIENT_SECRET.
</div>

{% endif %}


<a
href="/"
class="
block
mt-5
text-xs
text-zinc-500
hover:text-cyan-300
">
← Back to home
</a>

</div>


""" + CURSOR_SCRIPT + r"""

</body>
</html>
"""


# ============================================================
# DASHBOARD
# ============================================================

DASHBOARD = r"""
<!DOCTYPE html>
<html>

<head>

<meta charset="UTF-8">

<meta
name="viewport"
content="width=device-width,initial-scale=1">

<title>HSL CORP Console</title>

""" + COMMON_HEAD + r"""

</head>


<body class="min-h-screen">

<canvas id="particles"></canvas>
<div class="grid-bg"></div>
<div class="ambient"></div>
<div class="vignette"></div>


<div class="
relative z-10
min-h-screen
flex
">


<!-- SIDEBAR -->

<aside class="
w-[250px]
shrink-0
hidden md:flex
flex-col
border-r
border-cyan-400/10
bg-black/65
backdrop-blur-xl
">

<div class="
p-5
border-b border-white/5
flex items-center gap-3
">

<div class="
w-9 h-9
rounded-xl
bg-gradient-to-r
from-cyan-400 to-indigo-600
flex items-center justify-center
">
👾
</div>

<div>

<p class="font-black text-sm">
HSL CORP
</p>

<p class="text-[9px] text-cyan-400">
Developer Console
</p>

</div>

</div>


<nav
id="sidebar"
class="p-3 space-y-1 text-xs"
>

<button
onclick="showTab('overview')"
id="btn-overview"
class="side-active w-full text-left rounded-xl px-4 py-3">
🏠 Overview
</button>

<button
onclick="showTab('applications')"
id="btn-applications"
class="w-full text-left text-zinc-400 rounded-xl px-4 py-3">
📦 Applications
</button>

<button
onclick="showTab('users')"
id="btn-users"
class="w-full text-left text-zinc-400 rounded-xl px-4 py-3">
👤 Users
</button>

<button
onclick="showTab('keys')"
id="btn-keys"
class="w-full text-left text-zinc-400 rounded-xl px-4 py-3">
🔑 License Keys
</button>

<button
onclick="showTab('integration')"
id="btn-integration"
class="w-full text-left text-zinc-400 rounded-xl px-4 py-3">
🔌 Integration
</button>

<button
onclick="showTab('billing')"
id="btn-billing"
class="w-full text-left text-zinc-400 rounded-xl px-4 py-3">
💎 Billing
</button>

</nav>


<div class="mt-auto p-4 border-t border-white/5">

<p class="text-xs font-bold truncate">
{{ email }}
</p>

<p class="
text-[9px]
mt-1
{{ plan_color }}
font-bold
">
{{ plan }}
</p>

<a
href="/logout"
class="
block
mt-4
text-xs
text-red-400
">
Logout
</a>

</div>

</aside>


<!-- MAIN -->

<main class="flex-1 min-w-0">


<header class="
h-16
border-b
border-cyan-400/10
bg-black/45
backdrop-blur-xl
flex items-center
justify-between
px-5 md:px-8
">

<div>

<p class="text-xs font-bold text-cyan-300">
HSL CONSOLE
</p>

<p class="text-[9px] text-zinc-600">
{{ plan }}
</p>

</div>


<a
href="/logout"
class="
text-xs
text-red-400
md:hidden
">
Logout
</a>

</header>


<div class="p-5 md:p-8">


<!-- OVERVIEW -->

<section id="tab-overview">

<h1 class="text-2xl font-black">
Dashboard Overview
</h1>


<div class="
grid
md:grid-cols-3
gap-4
mt-6
">


<div class="card rounded-2xl p-5">

<p class="text-[9px] text-cyan-400 font-bold">
APPLICATIONS
</p>

<p class="text-3xl font-black mt-2">
{{ app_count }}
</p>

</div>


<div class="card rounded-2xl p-5">

<p class="text-[9px] text-indigo-400 font-bold">
USERS
</p>

<p class="text-3xl font-black mt-2">
{{ user_count }}
</p>

</div>


<div class="card rounded-2xl p-5">

<p class="text-[9px] text-cyan-400 font-bold">
PLAN
</p>

<p class="text-xl font-black mt-3">
{{ plan }}
</p>

</div>

</div>


<div class="card rounded-2xl p-6 mt-6">

<h2 class="font-bold">
Create Secure User
</h2>

<div class="
grid
md:grid-cols-2
gap-3
mt-4
">

<input
id="newUsername"
maxlength="40"
placeholder="Username"
class="
bg-black/70
border border-white/10
rounded-xl
px-4 py-3
text-sm
">

<input
id="newPassword"
maxlength="128"
type="password"
placeholder="Password"
class="
bg-black/70
border border-white/10
rounded-xl
px-4 py-3
text-sm
">

</div>


<select
id="userApp"
class="
mt-3
w-full
bg-black/70
border border-white/10
rounded-xl
px-4 py-3
text-sm
">

{{ app_options }}

</select>


<button
onclick="createUser()"
class="
mt-4
w-full
py-3
rounded-xl
font-bold
text-sm
bg-gradient-to-r
from-cyan-400 to-indigo-600
">
Create User
</button>

</div>

</section>


<!-- APPLICATIONS -->

<section
id="tab-applications"
class="hidden">

<h1 class="text-2xl font-black">
Applications
</h1>


<div class="card rounded-2xl p-6 mt-6">

{{ app_list }}


<div class="border-t border-white/5 mt-6 pt-6">

<h2 class="font-bold">
Create Application
</h2>

<input
id="newAppName"
maxlength="50"
placeholder="Application name"
class="
mt-3
w-full
bg-black/70
border border-white/10
rounded-xl
px-4 py-3
text-sm
">

<button
onclick="createApp()"
class="
mt-3
w-full
py-3
rounded-xl
font-bold
bg-gradient-to-r
from-cyan-400 to-indigo-600
">
Create Application
</button>

</div>

</div>

</section>


<!-- USERS -->

<section
id="tab-users"
class="hidden">

<h1 class="text-2xl font-black">
Users
</h1>

<div class="mt-6 space-y-3">

{{ users_list }}

</div>

</section>


<!-- KEYS -->

<section
id="tab-keys"
class="hidden">

<h1 class="text-2xl font-black">
License Keys
</h1>

<div class="card rounded-2xl p-6 mt-6">

<p class="text-xs text-zinc-600">
No key generator is enabled in this version.
</p>

</div>

</section>


<!-- INTEGRATION -->

<section
id="tab-integration"
class="hidden">

<h1 class="text-2xl font-black">
API Integration
</h1>


<div class="card rounded-2xl p-6 mt-6">

<p class="text-xs text-cyan-300 font-bold">
Authentication Endpoint
</p>

<pre class="
mt-4
bg-black
border border-white/5
rounded-xl
p-5
overflow-x-auto
text-xs
text-green-400
">POST /api/auth_login

{
    "username": "USER",
    "password": "PASSWORD",
    "hwid": "HWID",
    "token": "APP_TOKEN"
}</pre>

<p class="
mt-5
text-xs
text-zinc-500
">
Use HTTPS in production.
Do not expose your Flask secret key or Google credentials
inside the client application.
</p>

</div>

</section>


<!-- BILLING -->

<section
id="tab-billing"
class="hidden">

<h1 class="text-2xl font-black">
Billing
</h1>


<div class="
grid
md:grid-cols-2
gap-5
mt-6
">


<div class="card rounded-2xl p-7">

<p class="font-bold">
FREE
</p>

<p class="text-4xl font-black mt-3">
₹0
</p>

<p class="text-xs text-zinc-500 mt-4 leading-6">
2 Applications<br>
10 combined users/resources<br>
HWID Lock
</p>

</div>


<div class="
card
rounded-2xl
p-7
border-cyan-400/30
">

<p class="font-bold text-cyan-300">
PRO UNLIMITED
</p>

<p class="text-4xl font-black mt-3">
₹499
</p>

<p class="text-xs text-zinc-400 mt-4 leading-6">
Unlimited Applications<br>
Unlimited Users<br>
Unlimited Resources
</p>

<a
href="https://wa.me/919999999999"
target="_blank"
rel="noopener"
class="
block
mt-6
text-center
py-3
rounded-xl
font-bold
bg-gradient-to-r
from-cyan-400 to-indigo-600
">
Contact / Upgrade
</a>

</div>

</div>

</section>


</div>

</main>

</div>


<script>

function showTab(name){

    document
        .querySelectorAll("[id^='tab-']")
        .forEach(el => {
            el.classList.add("hidden");
        });

    const target =
        document.getElementById(
            "tab-" + name
        );

    if(target){
        target.classList.remove("hidden");
    }

    document
        .querySelectorAll("#sidebar button")
        .forEach(btn => {
            btn.classList.remove("side-active");
        });

    const button =
        document.getElementById(
            "btn-" + name
        );

    if(button){
        button.classList.add("side-active");
    }
}


async function api(url, options = {}){

    try{

        const response =
            await fetch(url, {
                credentials:"same-origin",
                ...options
            });

        const data =
            await response.json();

        if(!response.ok){

            throw new Error(
                data.error ||
                data.message ||
                "Request failed"
            );
        }

        return data;

    }catch(error){

        alert(error.message);
        throw error;
    }
}


async function createApp(){

    const input =
        document.getElementById(
            "newAppName"
        );

    const name =
        input.value.trim();

    if(!name){
        alert("Enter application name.");
        return;
    }

    const data =
        await api(
            "/api/create_app",
            {
                method:"POST",
                headers:{
                    "Content-Type":
                        "application/json"
                },
                body:JSON.stringify({
                    name:name
                })
            }
        );

    alert(
        "Application created.\nToken: " +
        data.token
    );

    location.reload();
}


async function deleteApp(token){

    if(
        !confirm(
            "Delete this application?"
        )
    ){
        return;
    }

    const data =
        await api(
            "/api/delete_app",
            {
                method:"POST",
                headers:{
                    "Content-Type":
                        "application/json"
                },
                body:JSON.stringify({
                    token:token
                })
            }
        );

    alert(data.message);

    location.reload();
}


async function createUser(){

    const username =
        document
        .getElementById("newUsername")
        .value
        .trim();

    const password =
        document
        .getElementById("newPassword")
        .value
        .trim();

    const appToken =
        document
        .getElementById("userApp")
        .value;

    if(!username || !password || !appToken){

        alert(
            "Username, password and application are required."
        );

        return;
    }

    const data =
        await api(
            "/api/create_user",
            {
                method:"POST",
                headers:{
                    "Content-Type":
                        "application/json"
                },
                body:JSON.stringify({
                    username:username,
                    password:password,
                    app_token:appToken
                })
            }
        );

    alert(data.message);

    location.reload();
}


async function deleteUser(username){

    if(
        !confirm(
            "Delete " + username + "?"
        )
    ){
        return;
    }

    const data =
        await api(
            "/api/delete_user",
            {
                method:"POST",
                headers:{
                    "Content-Type":
                        "application/json"
                },
                body:JSON.stringify({
                    username:username
                })
            }
        );

    alert(data.message);

    location.reload();
}


async function resetHwid(username){

    const data =
        await api(
            "/api/reset_hwid",
            {
                method:"POST",
                headers:{
                    "Content-Type":
                        "application/json"
                },
                body:JSON.stringify({
                    username:username
                })
            }
        );

    alert(data.message);

    location.reload();
}


async function toggleBan(username){

    const data =
        await api(
            "/api/toggle_ban",
            {
                method:"POST",
                headers:{
                    "Content-Type":
                        "application/json"
                },
                body:JSON.stringify({
                    username:username
                })
            }
        );

    alert(data.message);

    location.reload();
}

</script>


""" + CURSOR_SCRIPT + r"""

</body>
</html>
"""


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def home():
    return render_template_string(LANDING)


@app.route("/login")
def login_page():

    return render_template_string(
        LOGIN,
        oauth_enabled=bool(google)
    )


@app.route("/favicon.ico")
def favicon():
    # Explicitly prevents the common browser 404.
    return "", 204


@app.route("/auth/google")
@rate_limit(
    max_requests=5,
    window_seconds=60
)
def auth_google():

    if google is None:
        return jsonify({
            "error":
                "Google OAuth is not configured."
        }), 503

    redirect_uri = (
        request.url_root.rstrip("/")
        + "/auth/callback"
    )

    return google.authorize_redirect(
        redirect_uri
    )


@app.route("/auth/callback")
def auth_callback():

    if google is None:
        return redirect("/login")

    try:

        token = google.authorize_access_token()

        user = token.get("userinfo")

        if not user:

            response = google.get(
                "https://openidconnect.googleapis.com/v1/userinfo"
            )

            response.raise_for_status()

            user = response.json()

        email = user.get("email")

        if not email:
            return redirect("/login")

        session.clear()

        session["user"] = {
            "email": email,
            "name": user.get(
                "name",
                email.split("@")[0]
            ),
            "picture": user.get("picture", "")
        }

        session.permanent = True

        return redirect("/dashboard")

    except Exception as exc:

        app.logger.exception(
            "Google OAuth callback failed: %s",
            exc
        )

        return redirect(
            "/login?error=oauth_failed"
        )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    if not is_logged_in():
        return redirect("/login")

    email = current_email()

    paid = is_paid(email)

    plan = (
        "PRO UNLIMITED"
        if paid
        else
        "FREE"
    )

    plan_color = (
        "text-green-400"
        if paid
        else
        "text-yellow-400"
    )

    apps = db_fetchall(
        """
        SELECT *
        FROM apps
        WHERE owner_email=?
        ORDER BY id DESC
        """,
        (email,)
    )

    app_count = len(apps)

    app_tokens = [
        row["token"]
        for row in apps
    ]

    user_count = 0

    if app_tokens:

        placeholders = ",".join(
            "?"
            for _ in app_tokens
        )

        row = db_fetchone(
            f"""
            SELECT COUNT(*) AS count
            FROM tool_users
            WHERE app_token IN ({placeholders})
            """,
            tuple(app_tokens)
        )

        user_count = row["count"] if row else 0


    if apps:

        app_options = ""

        for app_row in apps:

            app_options += (
                "<option value=\""
                + escape(app_row["token"], quote=True)
                + "\">"
                + escape(app_row["name"])
                + "</option>"
            )

    else:

        app_options = (
            "<option value=\"\">"
            "No applications"
            "</option>"
        )


    # --------------------------------------------
    # APPLICATION LIST
    # --------------------------------------------

    if not apps:

        app_list = (
            "<p class='text-xs text-zinc-600'>"
            "No applications created yet."
            "</p>"
        )

    else:

        chunks = []

        for app_row in apps:

            token = escape(
                app_row["token"],
                quote=True
            )

            name = escape(
                app_row["name"]
            )

            short_token = escape(
                app_row["token"][:22]
            )

            chunks.append(
                f"""
                <div class="
                    flex flex-col md:flex-row
                    md:items-center
                    justify-between
                    gap-4
                    p-4
                    mb-3
                    rounded-xl
                    bg-black/60
                    border border-white/5
                ">

                    <div>

                        <p class="
                            font-bold
                            text-sm
                        ">
                            {name}
                        </p>

                        <p class="
                            text-[10px]
                            text-zinc-600
                            font-mono
                            mt-1
                        ">
                            {short_token}...
                        </p>

                    </div>

                    <button
                        onclick="deleteApp('{token}')"
                        class="
                            px-4 py-2
                            rounded-lg
                            text-xs
                            font-bold
                            text-red-300
                            bg-red-500/5
                            border border-red-500/20
                        ">
                        Delete
                    </button>

                </div>
                """
            )

        app_list = "".join(chunks)


    # --------------------------------------------
    # USERS
    # --------------------------------------------

    if app_tokens:

        placeholders = ",".join(
            "?"
            for _ in app_tokens
        )

        users = db_fetchall(
            f"""
            SELECT *
            FROM tool_users
            WHERE app_token IN ({placeholders})
            ORDER BY id DESC
            """,
            tuple(app_tokens)
        )

    else:

        users = []


    if not users:

        users_list = (
            "<div class='card rounded-xl p-6'>"
            "<p class='text-xs text-zinc-600'>"
            "No users found."
            "</p>"
            "</div>"
        )

    else:

        user_chunks = []

        for user in users:

            username = escape(
                user["username"],
                quote=True
            )

            status = user["status"]

            status_color = (
                "text-green-400"
                if status == "active"
                else
                "text-red-400"
            )

            hwid = (
                user["hwid"][:18] + "..."
                if user["hwid"]
                else
                "Not Bound"
            )

            hwid = escape(hwid)

            user_chunks.append(
                f"""
                <div class="
                    card
                    rounded-xl
                    p-4
                    flex flex-col
                    lg:flex-row
                    lg:items-center
                    justify-between
                    gap-4
                ">

                    <div>

                        <p class="font-bold text-sm">
                            {username}
                        </p>

                        <p class="
                            text-[10px]
                            text-zinc-600
                            mt-1
                        ">
                            HWID:
                            {hwid}
                        </p>

                        <p class="
                            text-[10px]
                            mt-1
                            {status_color}
                        ">
                            {escape(status.upper())}
                        </p>

                    </div>

                    <div class="
                        flex
                        flex-wrap
                        gap-2
                    ">

                        <button
                            onclick="toggleBan('{username}')"
                            class="
                                px-3 py-2
                                rounded-lg
                                text-[10px]
                                bg-yellow-500/5
                                border border-yellow-500/20
                            ">
                            Ban / Unban
                        </button>

                        <button
                            onclick="resetHwid('{username}')"
                            class="
                                px-3 py-2
                                rounded-lg
                                text-[10px]
                                bg-zinc-900
                                border border-white/10
                            ">
                            Reset HWID
                        </button>

                        <button
                            onclick="deleteUser('{username}')"
                            class="
                                px-3 py-2
                                rounded-lg
                                text-[10px]
                                text-red-300
                                bg-red-500/5
                                border border-red-500/20
                            ">
                            Delete
                        </button>

                    </div>

                </div>
                """
            )

        users_list = "".join(
            user_chunks
        )


    return render_template_string(
        DASHBOARD,
        email=escape(email),
        plan=plan,
        plan_color=plan_color,
        app_count=app_count,
        user_count=user_count,
        app_options=app_options,
        app_list=app_list,
        users_list=users_list
    )


# ============================================================
# CREATE APP
# ============================================================

@app.route(
    "/api/create_app",
    methods=["POST"]
)
@rate_limit(15, 60)
def create_app():

    auth_error = require_login()

    if auth_error:
        return auth_error

    data = json_body()

    name = clean_text(
        data.get("name"),
        MAX_APP_NAME
    )

    if not name:
        return jsonify({
            "error": "Invalid application name."
        }), 400

    email = current_email()

    count_row = db_fetchone(
        """
        SELECT COUNT(*) AS count
        FROM apps
        WHERE owner_email=?
        """,
        (email,)
    )

    count = (
        count_row["count"]
        if count_row
        else 0
    )

    if not is_paid(email) and count >= FREE_APP_LIMIT:

        return jsonify({
            "error":
                "Free plan limit reached. "
                "Maximum 2 applications."
        }), 403


    token = generate_app_token()

    try:

        db_execute(
            """
            INSERT INTO apps
            (name, token, owner_email, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                name,
                token,
                email,
                now_iso()
            )
        )

    except sqlite3.IntegrityError:

        return jsonify({
            "error":
                "Could not generate unique application token."
        }), 500


    return jsonify({
        "success": True,
        "token": token
    })


# ============================================================
# DELETE APP
# ============================================================

@app.route(
    "/api/delete_app",
    methods=["POST"]
)
@rate_limit(15, 60)
def delete_app():

    auth_error = require_login()

    if auth_error:
        return auth_error

    data = json_body()

    token = clean_text(
        data.get("token"),
        100
    )

    if not token:
        return jsonify({
            "error": "Missing application token."
        }), 400

    email = current_email()

    app_row = db_fetchone(
        """
        SELECT id
        FROM apps
        WHERE token=?
        AND owner_email=?
        """,
        (token, email)
    )

    if not app_row:

        return jsonify({
            "error":
                "Application not found."
        }), 404


    db_execute(
        "DELETE FROM tool_users WHERE app_token=?",
        (token,)
    )

    db_execute(
        "DELETE FROM keys WHERE app_token=?",
        (token,)
    )

    db_execute(
        "DELETE FROM apps WHERE token=?",
        (token,)
    )


    return jsonify({
        "success": True,
        "message":
            "Application deleted successfully."
    })


# ============================================================
# CREATE USER
# ============================================================

@app.route(
    "/api/create_user",
    methods=["POST"]
)
@rate_limit(15, 60)
def create_user():

    auth_error = require_login()

    if auth_error:
        return auth_error

    data = json_body()

    username = clean_text(
        data.get("username"),
        MAX_USERNAME
    )

    password = clean_text(
        data.get("password"),
        MAX_PASSWORD
    )

    app_token = clean_text(
        data.get("app_token"),
        100
    )

    if not username or not password or not app_token:

        return jsonify({
            "message":
                "Username, password and application are required."
        }), 400


    email = current_email()

    # Important:
    # verify that this application belongs
    # to the logged-in account.

    app_row = db_fetchone(
        """
        SELECT id
        FROM apps
        WHERE token=?
        AND owner_email=?
        """,
        (app_token, email)
    )

    if not app_row:

        return jsonify({
            "message":
                "Application not found or unauthorized."
        }), 403


    # --------------------------------------------
    # LIMIT
    # --------------------------------------------

    if not is_paid(email):

        row = db_fetchone(
            """
            SELECT COUNT(*) AS count
            FROM tool_users
            WHERE app_token IN (
                SELECT token
                FROM apps
                WHERE owner_email=?
            )
            """,
            (email,)
        )

        user_count = (
            row["count"]
            if row
            else 0
        )

        if user_count >= FREE_RESOURCE_LIMIT:

            return jsonify({
                "message":
                    "Free plan user limit reached."
            }), 403


    # --------------------------------------------
    # DUPLICATE
    # --------------------------------------------

    existing = db_fetchone(
        """
        SELECT id
        FROM tool_users
        WHERE username=?
        """,
        (username,)
    )

    if existing:

        return jsonify({
            "message":
                "Username already exists."
        }), 409


    password_hash = hash_password(
        password
    )


    try:

        db_execute(
            """
            INSERT INTO tool_users
            (
                username,
                password,
                app_token,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                username,
                password_hash,
                app_token,
                "active",
                now_iso()
            )
        )

    except sqlite3.IntegrityError:

        return jsonify({
            "message":
                "Username already exists."
        }), 409


    return jsonify({
        "success": True,
        "message":
            f"User created: {username}"
    })


# ============================================================
# USER OWNERSHIP HELPER
# ============================================================

def get_owned_user(username):

    email = current_email()

    return db_fetchone(
        """
        SELECT
            tool_users.*
        FROM tool_users
        INNER JOIN apps
            ON apps.token=tool_users.app_token
        WHERE tool_users.username=?
        AND apps.owner_email=?
        """,
        (
            username,
            email
        )
    )


# ============================================================
# DELETE USER
# ============================================================

@app.route(
    "/api/delete_user",
    methods=["POST"]
)
@rate_limit(20, 60)
def delete_user():

    auth_error = require_login()

    if auth_error:
        return auth_error

    username = clean_text(
        json_body().get("username"),
        MAX_USERNAME
    )

    user = get_owned_user(
        username
    )

    if not user:

        return jsonify({
            "error":
                "User not found."
        }), 404


    db_execute(
        """
        DELETE FROM tool_users
        WHERE username=?
        """,
        (username,)
    )


    return jsonify({
        "success": True,
        "message":
            "User deleted successfully."
    })


# ============================================================
# RESET HWID
# ============================================================

@app.route(
    "/api/reset_hwid",
    methods=["POST"]
)
@rate_limit(20, 60)
def reset_hwid():

    auth_error = require_login()

    if auth_error:
        return auth_error

    username = clean_text(
        json_body().get("username"),
        MAX_USERNAME
    )

    user = get_owned_user(
        username
    )

    if not user:

        return jsonify({
            "error":
                "User not found."
        }), 404


    db_execute(
        """
        UPDATE tool_users
        SET hwid=NULL,
            status='active'
        WHERE username=?
        """,
        (username,)
    )


    return jsonify({
        "success": True,
        "message":
            f"HWID reset for {username}."
    })


# ============================================================
# BAN / UNBAN
# ============================================================

@app.route(
    "/api/toggle_ban",
    methods=["POST"]
)
@rate_limit(20, 60)
def toggle_ban():

    auth_error = require_login()

    if auth_error:
        return auth_error

    username = clean_text(
        json_body().get("username"),
        MAX_USERNAME
    )

    user = get_owned_user(
        username
    )

    if not user:

        return jsonify({
            "error":
                "User not found."
        }), 404


    new_status = (
        "banned"
        if user["status"] == "active"
        else
        "active"
    )


    db_execute(
        """
        UPDATE tool_users
        SET status=?
        WHERE username=?
        """,
        (
            new_status,
            username
        )
    )


    return jsonify({
        "success": True,
        "message":
            f"{username} is now {new_status.upper()}."
    })


# ============================================================
# AUTH LOGIN API
# ============================================================

@app.route(
    "/api/auth_login",
    methods=["POST"]
)
@rate_limit(10, 60)
def auth_login():

    data = json_body()

    username = clean_text(
        data.get("username"),
        MAX_USERNAME
    )

    password = clean_text(
        data.get("password"),
        MAX_PASSWORD
    )

    hwid = clean_text(
        data.get("hwid"),
        255
    )

    token = clean_text(
        data.get("token"),
        100
    )


    if not username or not password or not hwid or not token:

        return jsonify({
            "status": "invalid",
            "message":
                "Malformed request parameters."
        }), 400


    user = db_fetchone(
        """
        SELECT *
        FROM tool_users
        WHERE username=?
        AND app_token=?
        """,
        (
            username,
            token
        )
    )


    if not user:

        return jsonify({
            "status": "invalid",
            "message":
                "Incorrect credentials."
        }), 401


    if user["status"] == "banned":

        return jsonify({
            "status": "banned",
            "message":
                "Account suspended."
        }), 403


    if not verify_password(
        user["password"],
        password
    ):

        return jsonify({
            "status": "invalid",
            "message":
                "Incorrect credentials."
        }), 401


    # --------------------------------------------
    # FIRST HWID BIND
    # --------------------------------------------

    if not user["hwid"]:

        db_execute(
            """
            UPDATE tool_users
            SET hwid=?
            WHERE id=?
            """,
            (
                hwid,
                user["id"]
            )
        )

        return jsonify({
            "status": "valid",
            "message":
                "HWID bound successfully."
        })


    # --------------------------------------------
    # HWID MATCH
    # --------------------------------------------

    if secrets.compare_digest(
        str(user["hwid"]),
        str(hwid)
    ):

        return jsonify({
            "status": "valid",
            "message":
                "Authentication successful."
        })


    return jsonify({
        "status": "hwid_mismatch",
        "message":
            "Hardware mismatch detected."
    }), 403


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# ============================================================
# 404
# ============================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith("/api/"):

        return jsonify({
            "error":
                "API endpoint not found.",
            "path":
                request.path
        }), 404

    return (
        "<h1 style='font-family:Arial;"
        "background:#03050a;color:#00eaff;"
        "height:100vh;margin:0;padding:50px'>"
        "404 — Page Not Found"
        "</h1>",
        404
    )


# ============================================================
# 405
# ============================================================

@app.errorhandler(405)
def method_not_allowed(error):

    if request.path.startswith("/api/"):

        return jsonify({
            "error":
                "HTTP method not allowed."
        }), 405

    return "Method Not Allowed", 405


# ============================================================
# 500
# ============================================================

@app.errorhandler(500)
def server_error(error):

    app.logger.exception(
        "Internal server error"
    )

    if request.path.startswith("/api/"):

        return jsonify({
            "error":
                "Internal server error."
        }), 500

    return (
        "<h1 style='font-family:Arial;"
        "background:#03050a;color:#ff1744;"
        "height:100vh;margin:0;padding:50px'>"
        "500 — Internal Server Error"
        "</h1>",
        500
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.logger.info(
        "HSL CORP starting on port %s",
        port
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )