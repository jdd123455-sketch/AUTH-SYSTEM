import os
import time
import secrets
import sqlite3
import hashlib
from datetime import timedelta
from functools import wraps

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth


# ============================================================
# HSL-CORP SECURE PANEL
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hsl.db")

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "CHANGE_THIS_SECRET_IN_RAILWAY"
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
)

# ============================================================
# CONFIG
# ============================================================

PAID_USERS = {
    "js7876839939@gmail.com"
}

FREE_APP_LIMIT = 2
FREE_USER_KEY_LIMIT = 10

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

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
# DATABASE
# ============================================================

def get_db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = get_db()
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
            email TEXT NOT NULL,
            hwid TEXT,
            app_token TEXT,
            key_text TEXT,
            first_seen TEXT NOT NULL
        )
    """)

    con.commit()
    con.close()


init_db()


def db_one(query, params=()):
    con = get_db()
    try:
        return con.execute(query, params).fetchone()
    finally:
        con.close()


def db_all(query, params=()):
    con = get_db()
    try:
        return con.execute(query, params).fetchall()
    finally:
        con.close()


def db_exec(query, params=()):
    con = get_db()
    try:
        cur = con.execute(query, params)
        con.commit()
        return cur.rowcount
    finally:
        con.close()


# ============================================================
# RATE LIMIT
# ============================================================

RATE_DATA = {}


def rate_limit(max_requests=10, window_seconds=60):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):

            ip = request.headers.get(
                "X-Forwarded-For",
                request.remote_addr or "unknown"
            ).split(",")[0].strip()

            key = f"{func.__name__}:{ip}"
            now = time.time()

            entries = RATE_DATA.get(key, [])

            entries = [
                t for t in entries
                if now - t < window_seconds
            ]

            if len(entries) >= max_requests:
                return jsonify({
                    "status": "rate_limited",
                    "message": "Too many requests. Try again later."
                }), 429

            entries.append(now)

            # Prevent unlimited memory growth
            RATE_DATA[key] = entries[-max_requests:]

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
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )

    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https: data: blob:; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' https:; "
        "img-src 'self' https: data:;"
    )

    return response


# ============================================================
# HELPERS
# ============================================================

def logged_in():
    return "user" in session


def current_email():
    if not logged_in():
        return None

    return session["user"].get("email")


def is_paid(email):
    return email in PAID_USERS


def generate_app_token():
    return "HSL_" + secrets.token_urlsafe(24)


def get_owned_app(email, token):
    return db_one(
        """
        SELECT *
        FROM apps
        WHERE token = ?
        AND owner_email = ?
        """,
        (token, email)
    )


def get_owned_user(email, username):
    return db_one(
        """
        SELECT tu.*
        FROM tool_users tu
        INNER JOIN apps a
        ON tu.app_token = a.token
        WHERE tu.username = ?
        AND a.owner_email = ?
        """,
        (username, email)
    )


def account_limit_reached(email):
    if is_paid(email):
        return False

    users = db_one(
        """
        SELECT COUNT(*) AS count
        FROM tool_users tu
        INNER JOIN apps a
        ON tu.app_token = a.token
        WHERE a.owner_email = ?
        """,
        (email,)
    )

    keys = db_one(
        """
        SELECT COUNT(*) AS count
        FROM keys k
        INNER JOIN apps a
        ON k.app_token = a.token
        WHERE a.owner_email = ?
        """,
        (email,)
    )

    total = users["count"] + keys["count"]

    return total >= FREE_USER_KEY_LIMIT


# ============================================================
# LIGHTWEIGHT CYBER UI
# ============================================================

COMMON_HEAD = r"""
<script src="https://cdn.tailwindcss.com"></script>

<style>

:root {
    --cyan: #00f6ff;
    --blue: #3b82f6;
    --violet: #7c3aed;
    --red: #ff1744;
    --bg: #03050b;
}

* {
    box-sizing: border-box;
}

html {
    scroll-behavior: smooth;
}

body {
    margin: 0;
    background:
        radial-gradient(
            circle at 50% -15%,
            rgba(0,246,255,.11),
            transparent 35%
        ),
        radial-gradient(
            circle at 100% 100%,
            rgba(124,58,237,.08),
            transparent 30%
        ),
        #03050b;

    color: #f8fafc;
    font-family:
        Inter,
        ui-sans-serif,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    cursor: none;
}

::selection {
    background: rgba(0,246,255,.25);
}

::-webkit-scrollbar {
    width: 6px;
}

::-webkit-scrollbar-track {
    background: #02040a;
}

::-webkit-scrollbar-thumb {
    background: linear-gradient(
        var(--cyan),
        var(--violet)
    );
    border-radius: 20px;
}

/* =========================================================
   LOW COST BACKGROUND
   ========================================================= */

.cyber-grid {
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;

    background-image:
        linear-gradient(
            rgba(255,255,255,.018) 1px,
            transparent 1px
        ),
        linear-gradient(
            90deg,
            rgba(255,255,255,.018) 1px,
            transparent 1px
        );

    background-size: 45px 45px;

    mask-image:
        linear-gradient(
            to bottom,
            black,
            transparent 90%
        );
}

.ambient {
    position: fixed;
    inset: -20%;
    z-index: 0;
    pointer-events: none;

    background:
        radial-gradient(
            circle at 20% 25%,
            rgba(0,246,255,.055),
            transparent 22%
        ),
        radial-gradient(
            circle at 80% 35%,
            rgba(124,58,237,.05),
            transparent 24%
        );

    animation: ambient 14s ease-in-out infinite alternate;
}

@keyframes ambient {
    from {
        transform: translate3d(-1%,0,0) scale(1);
    }

    to {
        transform: translate3d(1%,-1%,0) scale(1.04);
    }
}

.vignette {
    position: fixed;
    inset: 0;
    z-index: 3;
    pointer-events: none;

    box-shadow:
        inset 0 0 130px rgba(0,0,0,.85);
}

/* =========================================================
   PARTICLES
   ========================================================= */

#particleCanvas {
    position: fixed;
    inset: 0;
    z-index: 1;
    pointer-events: none;
    opacity: .7;
}

/* =========================================================
   GLASS
   ========================================================= */

.glass {
    position: relative;
    overflow: hidden;

    background:
        linear-gradient(
            145deg,
            rgba(13,19,34,.90),
            rgba(3,7,15,.80)
        );

    border:
        1px solid rgba(0,246,255,.15);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.04),
        0 20px 60px rgba(0,0,0,.35);

    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
}

.card {
    position: relative;
    overflow: hidden;

    background:
        linear-gradient(
            145deg,
            rgba(12,18,31,.87),
            rgba(3,7,14,.76)
        );

    border:
        1px solid rgba(0,246,255,.11);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.03),
        0 12px 40px rgba(0,0,0,.25);

    transition:
        transform .2s ease,
        border-color .2s ease,
        box-shadow .2s ease;
}

.card:hover {
    transform: translateY(-3px);

    border-color:
        rgba(0,246,255,.32);

    box-shadow:
        0 18px 48px rgba(0,0,0,.4),
        0 0 25px rgba(0,246,255,.07);
}

/* =========================================================
   CURSOR
   ========================================================= */

#cursorDot {
    position: fixed;
    width: 6px;
    height: 6px;

    border-radius: 50%;

    background: var(--cyan);

    pointer-events: none;
    z-index: 9999;

    transform: translate(-50%,-50%);

    box-shadow:
        0 0 7px var(--cyan),
        0 0 18px var(--cyan);
}

#cursorRing {
    position: fixed;

    width: 30px;
    height: 30px;

    border:
        1px solid rgba(0,246,255,.65);

    border-radius: 50%;

    pointer-events: none;
    z-index: 9998;

    transform: translate(-50%,-50%);

    transition:
        width .15s ease,
        height .15s ease,
        border-color .15s ease;
}

#cursorRing::before,
#cursorRing::after {
    content: "";

    position: absolute;

    background:
        rgba(0,246,255,.7);
}

#cursorRing::before {
    width: 42px;
    height: 1px;

    left: -7px;
    top: 14px;
}

#cursorRing::after {
    width: 1px;
    height: 42px;

    left: 14px;
    top: -7px;
}

.cursor-hover #cursorRing {
    width: 42px;
    height: 42px;

    border-color:
        rgba(124,58,237,.9);
}

.cursor-hover #cursorDot {
    box-shadow:
        0 0 10px var(--cyan),
        0 0 30px var(--cyan);
}

/* =========================================================
   BUTTONS
   ========================================================= */

button,
a {
    transition:
        transform .16s ease,
        filter .16s ease,
        box-shadow .16s ease;
}

button:hover,
a:hover {
    filter: brightness(1.08);
}

button:active,
a:active {
    transform: scale(.97);
}

.gradient-btn {
    background:
        linear-gradient(
            100deg,
            #06b6d4,
            #2563eb,
            #7c3aed
        );

    background-size: 200% 100%;

    animation:
        gradientMove 7s ease infinite;

    box-shadow:
        0 0 25px rgba(34,211,238,.22);
}

@keyframes gradientMove {
    0%,100% {
        background-position: 0 50%;
    }

    50% {
        background-position: 100% 50%;
    }
}

/* =========================================================
   SIDEBAR
   ========================================================= */

.side {
    color: #94a3b8;

    border:
        1px solid transparent;
}

.side:hover {
    color: white;

    background:
        rgba(255,255,255,.025);
}

.side-active {
    color: #67f7ff !important;

    background:
        linear-gradient(
            90deg,
            rgba(0,246,255,.13),
            rgba(124,58,237,.07)
        );

    border:
        1px solid rgba(0,246,255,.30);

    box-shadow:
        inset 3px 0 0 var(--cyan),
        0 0 18px rgba(0,246,255,.05);
}

@media(max-width:768px) {
    body {
        cursor: auto;
    }

    #cursorDot,
    #cursorRing {
        display: none;
    }
}

@media(prefers-reduced-motion:reduce) {
    *,
    *::before,
    *::after {
        animation: none !important;
        transition: none !important;
    }
}

</style>
"""


CURSOR_SCRIPT = r"""
<div id="cursorDot"></div>
<div id="cursorRing"></div>
<div class="cyber-grid"></div>
<div class="ambient"></div>
<div class="vignette"></div>
<canvas id="particleCanvas"></canvas>

<script>
(() => {

    const dot = document.getElementById("cursorDot");
    const ring = document.getElementById("cursorRing");
    const canvas = document.getElementById("particleCanvas");

    if (!dot || !ring || !canvas) return;

    let mouseX = window.innerWidth / 2;
    let mouseY = window.innerHeight / 2;

    let ringX = mouseX;
    let ringY = mouseY;

    window.addEventListener("mousemove", e => {
        mouseX = e.clientX;
        mouseY = e.clientY;

        dot.style.left = mouseX + "px";
        dot.style.top = mouseY + "px";
    }, {passive:true});

    document.querySelectorAll("button,a,input,select").forEach(el => {

        el.addEventListener("mouseenter", () => {
            document.body.classList.add("cursor-hover");
        });

        el.addEventListener("mouseleave", () => {
            document.body.classList.remove("cursor-hover");
        });

    });

    function cursorLoop() {

        ringX += (mouseX - ringX) * .15;
        ringY += (mouseY - ringY) * .15;

        ring.style.left = ringX + "px";
        ring.style.top = ringY + "px";

        requestAnimationFrame(cursorLoop);
    }

    cursorLoop();

    /* ------------------------------------------------------
       LOW-LAG PARTICLES
       ------------------------------------------------------ */

    const ctx = canvas.getContext("2d", {
        alpha: true
    });

    let width = 0;
    let height = 0;

    let particles = [];

    function resize() {

        width = window.innerWidth;
        height = window.innerHeight;

        const dpr = Math.min(
            window.devicePixelRatio || 1,
            1.5
        );

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

        const count =
            width < 700 ? 35 :
            width < 1200 ? 55 :
            75;

        particles = [];

        for(let i = 0; i < count; i++) {

            particles.push({
                x: Math.random() * width,
                y: Math.random() * height,
                r: Math.random() * 1.3 + .4,
                speed: Math.random() * .22 + .08,
                alpha: Math.random() * .55 + .15
            });

        }
    }

    resize();

    window.addEventListener(
        "resize",
        resize,
        {passive:true}
    );

    let last = 0;

    function animate(t) {

        if(t - last < 32) {
            requestAnimationFrame(animate);
            return;
        }

        last = t;

        ctx.clearRect(
            0,
            0,
            width,
            height
        );

        for(const p of particles) {

            p.y -= p.speed;

            if(p.y < -5) {
                p.y = height + 5;
                p.x = Math.random() * width;
            }

            ctx.beginPath();

            ctx.arc(
                p.x,
                p.y,
                p.r,
                0,
                Math.PI * 2
            );

            ctx.fillStyle =
                `rgba(34,211,238,${p.alpha})`;

            ctx.fill();
        }

        requestAnimationFrame(animate);
    }

    requestAnimationFrame(animate);

})();
</script>
"""


# ============================================================
# LANDING
# ============================================================

LANDING = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
""" + COMMON_HEAD + """
</head>

<body class="min-h-screen">

<nav class="relative z-10 flex justify-between items-center px-6 md:px-10 py-5 border-b border-cyan-400/10 bg-black/40 backdrop-blur-xl">

    <div class="flex items-center gap-3">

        <div class="w-10 h-10 rounded-xl gradient-btn flex items-center justify-center">
            ⚡
        </div>

        <div>
            <div class="font-black tracking-wider">
                HSL CORP
            </div>

            <div class="text-[9px] text-cyan-400 font-bold tracking-widest">
                SECURE AUTH INFRASTRUCTURE
            </div>
        </div>

    </div>

    <div class="flex gap-3">

        <a href="/login"
           class="px-5 py-2.5 rounded-xl bg-zinc-900 border border-white/10 text-xs font-bold">
            Sign In
        </a>

        <a href="/dashboard"
           class="gradient-btn px-5 py-2.5 rounded-xl text-xs font-bold">
            Dashboard
        </a>

    </div>

</nav>


<main class="relative z-10 max-w-6xl mx-auto px-6">

    <section class="text-center pt-24 pb-20">

        <div class="inline-flex items-center gap-2
                    border border-cyan-400/20
                    bg-cyan-400/5
                    rounded-full
                    px-4 py-2
                    text-xs text-cyan-300
                    font-bold">

            <span>◆</span>
            NEXT-GEN LICENSE CONTROL
        </div>

        <h1 class="mt-8 text-5xl md:text-7xl font-black
                   bg-gradient-to-r
                   from-cyan-300
                   via-cyan-400
                   to-indigo-500
                   bg-clip-text
                   text-transparent">

            HSL CORP

        </h1>

        <p class="max-w-2xl mx-auto mt-6 text-zinc-400">
            Hardware-bound application licensing,
            authentication and developer control infrastructure.
        </p>

        <a href="/login"
           class="inline-block mt-9 gradient-btn
                  px-8 py-4 rounded-2xl
                  text-sm font-black">

            ENTER CONSOLE →
        </a>

    </section>


    <section class="grid md:grid-cols-3 gap-5 pb-20">

        <div class="card rounded-2xl p-7">
            <div class="text-3xl">🔐</div>
            <h2 class="mt-5 font-black text-cyan-300">
                HWID LOCK
            </h2>
            <p class="text-sm text-zinc-500 mt-2">
                Bind client accounts to a hardware identifier.
            </p>
        </div>

        <div class="card rounded-2xl p-7">
            <div class="text-3xl">🛡️</div>
            <h2 class="mt-5 font-black text-indigo-300">
                API SECURITY
            </h2>
            <p class="text-sm text-zinc-500 mt-2">
                Rate limiting, ownership checks and
                hardened authentication endpoints.
            </p>
        </div>

        <div class="card rounded-2xl p-7">
            <div class="text-3xl">⚡</div>
            <h2 class="mt-5 font-black text-cyan-300">
                FAST CONTROL
            </h2>
            <p class="text-sm text-zinc-500 mt-2">
                Manage applications and client accounts
                from one console.
            </p>
        </div>

    </section>

</main>

<footer class="relative z-10 text-center py-6 border-t border-white/5 text-xs text-zinc-600">
    © 2026 HSL CORP
</footer>

""" + CURSOR_SCRIPT + """

</body>
</html>
"""


# ============================================================
# LOGIN
# ============================================================

LOGIN = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
""" + COMMON_HEAD + """
</head>

<body class="min-h-screen flex items-center justify-center px-5">

<div class="relative z-10 glass w-full max-w-md rounded-3xl p-8 text-center">

    <div class="w-16 h-16 mx-auto rounded-2xl gradient-btn
                flex items-center justify-center text-2xl">
        ⚡
    </div>

    <h1 class="mt-5 text-2xl font-black
               bg-gradient-to-r
               from-cyan-300 to-indigo-400
               bg-clip-text text-transparent">
        HSL CORP
    </h1>

    <p class="text-xs text-zinc-500 mt-2">
        Secure Developer Console
    </p>

    {% if error %}
    <div class="mt-5 rounded-xl border border-red-500/20
                bg-red-500/5 text-red-300 text-xs p-3">
        {{ error }}
    </div>
    {% endif %}

    {% if google_enabled %}

    <a href="/auth/google"
       class="mt-7 w-full bg-white text-black
              rounded-xl py-3.5
              flex justify-center items-center gap-3
              font-black text-sm">

        <span class="text-lg">G</span>
        Continue with Google

    </a>

    {% else %}

    <div class="mt-7 rounded-xl
                border border-yellow-500/20
                bg-yellow-500/5
                text-yellow-300
                text-xs p-4">

        Google OAuth is not configured.
        Set GOOGLE_CLIENT_ID and
        GOOGLE_CLIENT_SECRET.

    </div>

    {% endif %}

    <a href="/"
       class="block mt-5 text-xs text-zinc-500 hover:text-cyan-300">
        ← Back
    </a>

</div>

""" + CURSOR_SCRIPT + """

</body>
</html>
"""


# ============================================================
# DASHBOARD
# ============================================================

DASHBOARD = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
""" + COMMON_HEAD + """

<style>

#mobileMenu {
    display:none;
}

@media(max-width:900px) {

    #sidebar {
        position:fixed;
        left:-270px;
        top:0;
        bottom:0;
        z-index:50;
        transition:left .25s ease;
    }

    #sidebar.open {
        left:0;
    }

    #mobileMenu {
        display:block;
    }

    .dashboard-content {
        width:100%;
    }

}

</style>

</head>

<body class="h-screen overflow-hidden">

<div class="flex h-full relative z-10">

    <!-- SIDEBAR -->

    <aside id="sidebar"
           class="w-[260px] shrink-0
                  bg-[#02040a]/95
                  border-r border-cyan-400/10
                  backdrop-blur-2xl
                  flex flex-col">

        <div class="p-5 border-b border-white/10">

            <div class="flex items-center gap-3">

                <div class="w-10 h-10 rounded-xl gradient-btn
                            flex items-center justify-center">
                    ⚡
                </div>

                <div>
                    <div class="font-black text-sm">
                        HSL CORP
                    </div>

                    <div class="text-[9px] text-cyan-400 font-bold">
                        DEVELOPER CONSOLE
                    </div>
                </div>

            </div>

        </div>


        <div class="p-3 space-y-1">

            <button onclick="showTab('overview')"
                    id="btn-overview"
                    class="side side-active w-full text-left
                           rounded-xl px-4 py-3 text-xs font-bold">
                ◈ Overview
            </button>

            <button onclick="showTab('applications')"
                    id="btn-applications"
                    class="side w-full text-left
                           rounded-xl px-4 py-3 text-xs font-bold">
                ◫ Applications
            </button>

            <button onclick="showTab('users')"
                    id="btn-users"
                    class="side w-full text-left
                           rounded-xl px-4 py-3 text-xs font-bold">
                ◉ Users ({{ user_count }}/{{ limit_text }})
            </button>

            <button onclick="showTab('keys')"
                    id="btn-keys"
                    class="side w-full text-left
                           rounded-xl px-4 py-3 text-xs font-bold">
                ◇ License Keys
            </button>

            <button onclick="showTab('integration')"
                    id="btn-integration"
                    class="side w-full text-left
                           rounded-xl px-4 py-3 text-xs font-bold">
                ◈ Integration
            </button>

            <button onclick="showTab('billing')"
                    id="btn-billing"
                    class="side w-full text-left
                           rounded-xl px-4 py-3 text-xs font-bold">
                ◆ Billing
            </button>

        </div>


        <div class="mt-auto p-4 border-t border-white/10">

            <div class="text-xs font-bold truncate">
                {{ email }}
            </div>

            <div class="{{ plan_color }} text-[10px] font-black mt-1">
                {{ plan_text }}
            </div>

            <a href="/logout"
               class="block mt-4 text-xs text-red-400">
                Logout
            </a>

        </div>

    </aside>


    <!-- CONTENT -->

    <main class="dashboard-content flex-1 overflow-y-auto">

        <header class="h-16 flex items-center justify-between
                       px-5 md:px-8
                       bg-black/40
                       backdrop-blur-xl
                       border-b border-cyan-400/10">

            <button id="mobileMenu"
                    onclick="toggleMenu()"
                    class="text-xl">
                ☰
            </button>

            <div class="text-xs font-black text-cyan-300">
                HSL CONSOLE / {{ plan_text }}
            </div>

            <button onclick="showTab('billing')"
                    class="gradient-btn
                           px-4 py-2 rounded-xl
                           text-[10px] font-black">
                UPGRADE
            </button>

        </header>


        <div class="p-5 md:p-8">


            <!-- OVERVIEW -->

            <section id="tab-overview">

                <h1 class="text-2xl font-black">
                    Dashboard Overview
                </h1>

                <div class="grid md:grid-cols-3 gap-4 mt-6">

                    <div class="card rounded-2xl p-5">

                        <div class="text-[10px] text-cyan-400 font-black">
                            APPLICATIONS
                        </div>

                        <div class="text-3xl font-black mt-3">
                            {{ app_count }}
                        </div>

                    </div>


                    <div class="card rounded-2xl p-5">

                        <div class="text-[10px] text-indigo-400 font-black">
                            USERS
                        </div>

                        <div class="text-3xl font-black mt-3">
                            {{ user_count }}
                        </div>

                    </div>


                    <div class="card rounded-2xl p-5">

                        <div class="text-[10px] text-cyan-400 font-black">
                            PLAN
                        </div>

                        <div class="text-xl font-black mt-4">
                            {{ plan_text }}
                        </div>

                    </div>

                </div>


                <div class="card rounded-2xl p-6 mt-6">

                    <div class="font-black">
                        Active Application
                    </div>

                    <select id="appToken"
                            class="mt-4 w-full
                                   bg-black/70
                                   border border-white/10
                                   rounded-xl px-4 py-3
                                   text-xs outline-none">

                        {% for app in apps %}

                        <option value="{{ app['token'] }}">
                            {{ app['name'] }}
                        </option>

                        {% endfor %}

                    </select>

                </div>


                <div class="card rounded-2xl p-6 mt-5">

                    <div class="font-black">
                        Create Secure User
                    </div>

                    <div class="grid md:grid-cols-2 gap-3 mt-4">

                        <input id="newUsername"
                               placeholder="Username"
                               class="bg-black/70 border border-white/10
                                      rounded-xl px-4 py-3 text-sm outline-none">

                        <input id="newPassword"
                               type="password"
                               placeholder="Password"
                               class="bg-black/70 border border-white/10
                                      rounded-xl px-4 py-3 text-sm outline-none">

                    </div>

                    <button onclick="createUser()"
                            class="gradient-btn w-full
                                   mt-4 py-3 rounded-xl
                                   text-xs font-black">
                        CREATE USER
                    </button>

                </div>

            </section>


            <!-- APPLICATIONS -->

            <section id="tab-applications" class="hidden">

                <h1 class="text-2xl font-black">
                    Applications
                </h1>

                <div class="mt-6 space-y-3">

                    {% for app in apps %}

                    <div class="card rounded-xl p-5
                                flex flex-col md:flex-row
                                justify-between gap-4">

                        <div>

                            <div class="font-black">
                                {{ app['name'] }}
                            </div>

                            <div class="text-[10px]
                                        text-zinc-500
                                        font-mono mt-1">
                                {{ app['token'] }}
                            </div>

                        </div>

                        <button
                            onclick="deleteApp('{{ app['token'] }}')"
                            class="bg-red-500/10
                                   border border-red-500/20
                                   text-red-300
                                   px-4 py-2 rounded-xl
                                   text-xs font-bold">
                            DELETE
                        </button>

                    </div>

                    {% endfor %}

                </div>


                <div class="card rounded-2xl p-6 mt-6">

                    <div class="font-black">
                        Create Application
                    </div>

                    <input id="appName"
                           placeholder="Application name"
                           class="mt-4 w-full
                                  bg-black/70
                                  border border-white/10
                                  rounded-xl px-4 py-3
                                  text-sm outline-none">

                    <button onclick="createApp()"
                            class="gradient-btn
                                   mt-4 w-full
                                   py-3 rounded-xl
                                   text-xs font-black">
                        CREATE APPLICATION
                    </button>

                </div>

            </section>


            <!-- USERS -->

            <section id="tab-users" class="hidden">

                <h1 class="text-2xl font-black">
                    Users
                </h1>

                <div class="mt-6 space-y-3">

                    {% for user in users %}

                    <div class="card rounded-xl p-5">

                        <div class="flex flex-col md:flex-row
                                    justify-between gap-4">

                            <div>

                                <div class="font-black">
                                    {{ user['username'] }}
                                </div>

                                <div class="text-[10px] text-zinc-500 mt-1">
                                    Status:
                                    <span class="{{ 'text-green-400' if user['status'] == 'active' else 'text-red-400' }}">
                                        {{ user['status']|upper }}
                                    </span>
                                </div>

                                <div class="text-[10px] text-zinc-600 mt-1">
                                    HWID:
                                    {{ user['hwid'][:20] ~ '...' if user['hwid'] else 'Not Bound' }}
                                </div>

                            </div>

                            <div class="flex flex-wrap gap-2">

                                <button
                                    onclick="toggleBan('{{ user['username'] }}')"
                                    class="bg-yellow-500/10
                                           border border-yellow-500/20
                                           text-yellow-300
                                           px-3 py-2 rounded-lg
                                           text-[10px] font-bold">
                                    BAN/UNBAN
                                </button>

                                <button
                                    onclick="resetHwid('{{ user['username'] }}')"
                                    class="bg-zinc-500/10
                                           border border-white/10
                                           px-3 py-2 rounded-lg
                                           text-[10px] font-bold">
                                    RESET HWID
                                </button>

                                <button
                                    onclick="deleteUser('{{ user['username'] }}')"
                                    class="bg-red-500/10
                                           border border-red-500/20
                                           text-red-300
                                           px-3 py-2 rounded-lg
                                           text-[10px] font-bold">
                                    DELETE
                                </button>

                            </div>

                        </div>

                    </div>

                    {% else %}

                    <div class="text-center text-zinc-600 py-16 text-xs">
                        No users found.
                    </div>

                    {% endfor %}

                </div>

            </section>


            <!-- KEYS -->

            <section id="tab-keys" class="hidden">

                <h1 class="text-2xl font-black">
                    License Keys
                </h1>

                <div class="card rounded-2xl p-6 mt-6">

                    {% for key in keys %}

                    <div class="flex justify-between
                                bg-black/50
                                border border-white/5
                                rounded-xl
                                px-4 py-3 mb-2">

                        <span class="font-mono text-xs">
                            {{ key['key_text'] }}
                        </span>

                        <span class="text-xs
                                     {{ 'text-green-400' if key['status'] == 'unused' else 'text-red-400' }}">
                            {{ key['status'] }}
                        </span>

                    </div>

                    {% else %}

                    <div class="text-center text-zinc-600 text-xs py-10">
                        No license keys.
                    </div>

                    {% endfor %}

                </div>

            </section>


            <!-- INTEGRATION -->

            <section id="tab-integration" class="hidden">

                <h1 class="text-2xl font-black">
                    Client Integration
                </h1>

                <div class="card rounded-2xl p-6 mt-6">

                    <div class="text-xs text-cyan-300 font-black">
                        SECURE AUTHENTICATION EXAMPLE
                    </div>

                    <pre class="mt-5 bg-black/80
                                rounded-xl p-5
                                overflow-x-auto
                                text-[11px]
                                text-green-400"><code>import requests
import hashlib

APP_TOKEN = "YOUR_APP_TOKEN"
AUTH_URL = "https://YOUR-DOMAIN.com/api/auth_login"

def secure_login(username, password, hwid):

    # Note:
    # This signature is only an integrity check.
    # Do not treat a client-side secret as impossible to extract.

    signature = hashlib.sha256(
        f"{username}:{hwid}:{APP_TOKEN}".encode()
    ).hexdigest()

    response = requests.post(
        AUTH_URL,
        json={
            "username": username,
            "password": password,
            "hwid": hwid,
            "token": APP_TOKEN,
            "sig": signature
        },
        timeout=10
    )

    return response.json()</code></pre>

                </div>

            </section>


            <!-- BILLING -->

            <section id="tab-billing" class="hidden">

                <h1 class="text-2xl font-black">
                    Billing
                </h1>

                <div class="grid md:grid-cols-2 gap-5 mt-6">

                    <div class="card rounded-2xl p-7">

                        <div class="text-sm font-black">
                            FREE
                        </div>

                        <div class="text-4xl font-black mt-3">
                            ₹0
                        </div>

                        <div class="text-xs text-zinc-500 mt-4 leading-7">
                            ✓ 10 users/keys<br>
                            ✓ 2 applications<br>
                            ✓ HWID locking
                        </div>

                    </div>


                    <div class="card rounded-2xl p-7
                                border-cyan-400/30">

                        <div class="text-sm text-cyan-400 font-black">
                            PRO UNLIMITED
                        </div>

                        <div class="text-4xl font-black mt-3">
                            ₹499
                        </div>

                        <div class="text-xs text-zinc-300 mt-4 leading-7">
                            ✓ Unlimited users<br>
                            ✓ Unlimited applications<br>
                            ✓ Unlimited keys<br>
                            ✓ Advanced authentication
                        </div>

                        <a href="https://wa.me/919999999999"
                           target="_blank"
                           rel="noopener noreferrer"
                           class="gradient-btn
                                  block text-center
                                  mt-6 py-3 rounded-xl
                                  text-xs font-black">
                            BUY ON WHATSAPP
                        </a>

                    </div>

                </div>

            </section>


        </div>

    </main>

</div>


<script>

function showTab(name) {

    document
        .querySelectorAll('[id^="tab-"]')
        .forEach(el => el.classList.add("hidden"));

    const target =
        document.getElementById("tab-" + name);

    if(target) {
        target.classList.remove("hidden");
    }

    document
        .querySelectorAll("#sidebar .side")
        .forEach(btn => {
            btn.classList.remove("side-active");
        });

    const button =
        document.getElementById("btn-" + name);

    if(button) {
        button.classList.add("side-active");
    }

    document
        .getElementById("sidebar")
        .classList.remove("open");
}


function toggleMenu() {
    document
        .getElementById("sidebar")
        .classList.toggle("open");
}


async function api(url, body) {

    try {

        const response = await fetch(url, {
            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify(body)
        });

        const data =
            await response.json();

        if(!response.ok) {
            throw new Error(
                data.message ||
                data.error ||
                "Request failed"
            );
        }

        return data;

    } catch(error) {

        alert(error.message);
        throw error;
    }
}


async function createApp() {

    const input =
        document.getElementById("appName");

    const name =
        input.value.trim();

    if(!name) {
        alert("Enter application name.");
        return;
    }

    const data =
        await api(
            "/api/create_app",
            {name:name}
        );

    alert(
        "Application created.\n\nToken:\n" +
        data.token
    );

    location.reload();
}


async function deleteApp(token) {

    if(!confirm(
        "Delete this application?"
    )) {
        return;
    }

    const data =
        await api(
            "/api/delete_app",
            {token:token}
        );

    alert(data.message);

    location.reload();
}


async function createUser() {

    const username =
        document
            .getElementById("newUsername")
            .value.trim();

    const password =
        document
            .getElementById("newPassword")
            .value;

    const select =
        document.getElementById("appToken");

    const appToken =
        select ? select.value : "";

    if(!username || !password || !appToken) {

        alert(
            "Username, password and application are required."
        );

        return;
    }

    const data =
        await api(
            "/api/create_user",
            {
                username,
                password,
                app_token: appToken
            }
        );

    alert(data.message);

    location.reload();
}


async function deleteUser(username) {

    if(!confirm(
        "Delete " + username + "?"
    )) {
        return;
    }

    const data =
        await api(
            "/api/delete_user",
            {username:username}
        );

    alert(data.message);

    location.reload();
}


async function resetHwid(username) {

    const data =
        await api(
            "/api/reset_hwid",
            {username:username}
        );

    alert(data.message);

    location.reload();
}


async function toggleBan(username) {

    const data =
        await api(
            "/api/toggle_ban",
            {username:username}
        );

    alert(data.message);

    location.reload();
}

</script>


""" + CURSOR_SCRIPT + """

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
def login():

    return render_template_string(
        LOGIN,
        google_enabled=google is not None,
        error=request.args.get("error")
    )


@app.route("/auth/google")
@rate_limit(5, 60)
def auth_google():

    if google is None:
        return redirect("/login?error=Google+OAuth+is+not+configured")

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
            user_response = google.get(
                "https://openidconnect.googleapis.com/v1/userinfo"
            )

            user = user_response.json()

        email = user.get("email")

        if not email:
            return redirect(
                "/login?error=Google+account+email+missing"
            )

        session.clear()

        session["user"] = {
            "email": email,
            "name": user.get("name", "User")
        }

        session.permanent = True

        return redirect("/dashboard")

    except Exception as exc:

        print(
            "GOOGLE AUTH ERROR:",
            repr(exc)
        )

        return redirect(
            "/login?error=Authentication+failed"
        )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    if not logged_in():
        return redirect("/login")

    email = current_email()

    apps = db_all(
        """
        SELECT *
        FROM apps
        WHERE owner_email = ?
        ORDER BY id DESC
        """,
        (email,)
    )

    users = db_all(
        """
        SELECT tu.*
        FROM tool_users tu
        INNER JOIN apps a
        ON tu.app_token = a.token
        WHERE a.owner_email = ?
        ORDER BY tu.id DESC
        """,
        (email,)
    )

    keys = db_all(
        """
        SELECT k.*
        FROM keys k
        INNER JOIN apps a
        ON k.app_token = a.token
        WHERE a.owner_email = ?
        ORDER BY k.id DESC
        """,
        (email,)
    )

    paid = is_paid(email)

    plan_text = (
        "PRO UNLIMITED"
        if paid
        else "FREE"
    )

    plan_color = (
        "text-green-400"
        if paid
        else "text-yellow-400"
    )

    limit_text = (
        "∞"
        if paid
        else str(FREE_USER_KEY_LIMIT)
    )

    return render_template_string(
        DASHBOARD,

        email=email,

        plan_text=plan_text,
        plan_color=plan_color,

        limit_text=limit_text,

        apps=apps,
        users=users,
        keys=keys,

        app_count=len(apps),
        user_count=len(users),

    )


# ============================================================
# CREATE APP
# ============================================================

@app.route("/api/create_app", methods=["POST"])
@rate_limit(10, 60)
def create_app():

    if not logged_in():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    email = current_email()

    data = request.get_json(
        silent=True
    ) or {}

    name = str(
        data.get("name", "")
    ).strip()

    if not name:
        return jsonify({
            "error": "Application name required"
        }), 400

    if len(name) > 80:
        return jsonify({
            "error": "Application name too long"
        }), 400

    count = db_one(
        """
        SELECT COUNT(*) AS count
        FROM apps
        WHERE owner_email = ?
        """,
        (email,)
    )

    if (
        not is_paid(email)
        and count["count"] >= FREE_APP_LIMIT
    ):
        return jsonify({
            "error":
                "Free Plan limit reached. "
                "Maximum 2 applications."
        }), 403

    token = generate_app_token()

    db_exec(
        """
        INSERT INTO apps
        (name, token, owner_email, created_at)
        VALUES (?, ?, ?, datetime('now'))
        """,
        (name, token, email)
    )

    return jsonify({
        "success": True,
        "token": token
    })


# ============================================================
# DELETE APP
# ============================================================

@app.route("/api/delete_app", methods=["POST"])
@rate_limit(10, 60)
def delete_app():

    if not logged_in():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    email = current_email()

    data = request.get_json(
        silent=True
    ) or {}

    token = data.get("token")

    if not token:
        return jsonify({
            "error": "Missing token"
        }), 400

    owned = get_owned_app(
        email,
        token
    )

    if not owned:
        return jsonify({
            "error": "Application not found"
        }), 404

    # Delete related data first.
    db_exec(
        "DELETE FROM tool_users WHERE app_token=?",
        (token,)
    )

    db_exec(
        "DELETE FROM keys WHERE app_token=?",
        (token,)
    )

    db_exec(
        "DELETE FROM users WHERE app_token=?",
        (token,)
    )

    db_exec(
        "DELETE FROM apps WHERE token=? AND owner_email=?",
        (token, email)
    )

    return jsonify({
        "message":
            "Application deleted successfully."
    })


# ============================================================
# CREATE USER
# ============================================================

@app.route("/api/create_user", methods=["POST"])
@rate_limit(10, 60)
def create_user():

    if not logged_in():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    email = current_email()

    data = request.get_json(
        silent=True
    ) or {}

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    app_token = str(
        data.get("app_token", "")
    ).strip()

    if not username or not password or not app_token:
        return jsonify({
            "message":
                "Username, password and app are required."
        }), 400

    if len(username) < 3 or len(username) > 40:
        return jsonify({
            "message":
                "Username must be 3-40 characters."
        }), 400

    if len(password) < 6:
        return jsonify({
            "message":
                "Password must contain at least 6 characters."
        }), 400

    # IMPORTANT:
    # Verify that this application belongs
    # to the logged-in Google account.

    owned = get_owned_app(
        email,
        app_token
    )

    if not owned:
        return jsonify({
            "message":
                "Invalid or unauthorized application."
        }), 403

    if account_limit_reached(email):
        return jsonify({
            "message":
                "Free Plan user/key limit reached."
        }), 403

    existing = db_one(
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

    password_hash = generate_password_hash(
        password
    )

    db_exec(
        """
        INSERT INTO tool_users
        (username, password, app_token, status, created_at)
        VALUES (?, ?, ?, 'active', datetime('now'))
        """,
        (
            username,
            password_hash,
            app_token
        )
    )

    return jsonify({
        "message":
            f"User '{username}' created successfully."
    })


# ============================================================
# DELETE USER
# ============================================================

@app.route("/api/delete_user", methods=["POST"])
@rate_limit(10, 60)
def delete_user():

    if not logged_in():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    email = current_email()

    data = request.get_json(
        silent=True
    ) or {}

    username = str(
        data.get("username", "")
    ).strip()

    user = get_owned_user(
        email,
        username
    )

    if not user:
        return jsonify({
            "error": "User not found"
        }), 404

    db_exec(
        "DELETE FROM tool_users WHERE id=?",
        (user["id"],)
    )

    return jsonify({
        "message":
            f"{username} deleted successfully."
    })


# ============================================================
# RESET HWID
# ============================================================

@app.route("/api/reset_hwid", methods=["POST"])
@rate_limit(10, 60)
def reset_hwid():

    if not logged_in():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    email = current_email()

    data = request.get_json(
        silent=True
    ) or {}

    username = str(
        data.get("username", "")
    ).strip()

    user = get_owned_user(
        email,
        username
    )

    if not user:
        return jsonify({
            "error": "User not found"
        }), 404

    db_exec(
        """
        UPDATE tool_users
        SET hwid=NULL,
            status='active'
        WHERE id=?
        """,
        (user["id"],)
    )

    return jsonify({
        "message":
            f"HWID reset for {username}."
    })


# ============================================================
# BAN / UNBAN
# ============================================================

@app.route("/api/toggle_ban", methods=["POST"])
@rate_limit(10, 60)
def toggle_ban():

    if not logged_in():
        return jsonify({
            "error": "Unauthorized"
        }), 401

    email = current_email()

    data = request.get_json(
        silent=True
    ) or {}

    username = str(
        data.get("username", "")
    ).strip()

    user = get_owned_user(
        email,
        username
    )

    if not user:
        return jsonify({
            "error": "User not found"
        }), 404

    new_status = (
        "banned"
        if user["status"] == "active"
        else "active"
    )

    db_exec(
        """
        UPDATE tool_users
        SET status=?
        WHERE id=?
        """,
        (
            new_status,
            user["id"]
        )
    )

    return jsonify({
        "message":
            f"{username} is now {new_status.upper()}."
    })


# ============================================================
# CLIENT AUTH LOGIN
# ============================================================

@app.route("/api/auth_login", methods=["POST"])
@rate_limit(10, 60)
def auth_login():

    data = request.get_json(
        silent=True
    ) or {}

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    )

    hwid = str(
        data.get("hwid", "")
    ).strip()

    token = str(
        data.get("token", "")
    ).strip()

    client_sig = str(
        data.get("sig", "")
    ).strip()

    if not username or not password or not hwid or not token:
        return jsonify({
            "status": "invalid",
            "message":
                "Malformed request parameters."
        }), 400

    if len(username) > 100 or len(hwid) > 500:
        return jsonify({
            "status": "invalid",
            "message":
                "Invalid request."
        }), 400

    # Check application token exists.
    app_row = db_one(
        """
        SELECT token
        FROM apps
        WHERE token=?
        """,
        (token,)
    )

    if not app_row:
        return jsonify({
            "status": "invalid",
            "message":
                "Invalid application token."
        }), 403

    # Integrity signature.
    #
    # IMPORTANT:
    # Since the client knows APP_TOKEN,
    # this is NOT a cryptographic anti-crack
    # mechanism. It only detects accidental
    # payload modification.

    expected_sig = hashlib.sha256(
        f"{username}:{hwid}:{token}".encode()
    ).hexdigest()

    if client_sig and not secrets.compare_digest(
        client_sig,
        expected_sig
    ):
        return jsonify({
            "status": "tampered",
            "message":
                "Invalid request signature."
        }), 403

    user = db_one(
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

    # Support older plaintext database rows
    # while transparently upgrading them.

    password_valid = False

    try:
        password_valid = check_password_hash(
            user["password"],
            password
        )
    except Exception:
        password_valid = secrets.compare_digest(
            user["password"],
            password
        )

        if password_valid:

            db_exec(
                """
                UPDATE tool_users
                SET password=?
                WHERE id=?
                """,
                (
                    generate_password_hash(password),
                    user["id"]
                )
            )

    if not password_valid:
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

    # First HWID binding.
    if not user["hwid"]:

        db_exec(
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

    # Existing HWID.
    if secrets.compare_digest(
        str(user["hwid"]),
        hwid
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
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "ok",
        "service": "HSL-CORP",
        "time": int(time.time())
    })


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith("/api/"):
        return jsonify({
            "error": "Endpoint not found"
        }), 404

    return redirect("/")


@app.errorhandler(405)
def method_not_allowed(error):

    if request.path.startswith("/api/"):
        return jsonify({
            "error": "Method not allowed"
        }), 405

    return "Method Not Allowed", 405


@app.errorhandler(500)
def internal_error(error):

    print(
        "INTERNAL SERVER ERROR:",
        repr(error)
    )

    if request.path.startswith("/api/"):
        return jsonify({
            "error":
                "Internal server error"
        }), 500

    return "Internal Server Error", 500


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

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )