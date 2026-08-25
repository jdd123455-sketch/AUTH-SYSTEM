import os
import time
import hmac
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from html import escape

from authlib.integrations.flask_client import OAuth
from flask import Flask, jsonify, redirect, render_template_string, request, session
from werkzeug.middleware.proxy_fix import ProxyFix


# ============================================================
# HSL CORP AUTH PANEL
# ============================================================

app = Flask(__name__)

# Reverse proxy support for Railway / Render / Nginx
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1,
    x_prefix=1,
)

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")

if not SECRET_KEY:
    # Development fallback.
    # For production, set FLASK_SECRET_KEY in environment variables.
    SECRET_KEY = secrets.token_hex(32)

app.secret_key = SECRET_KEY

IS_PRODUCTION = os.environ.get("FLASK_ENV", "").lower() == "production"

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
)

DATABASE = os.environ.get("DATABASE_PATH", "hsl.db")

# Put paid emails here.
PAID_USERS = {
    "js7876839939@gmail.com",
}

FREE_APP_LIMIT = 2
FREE_USER_KEY_LIMIT = 10


# ============================================================
# GOOGLE OAUTH
# ============================================================

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

oauth = OAuth(app)

google = None

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


# ============================================================
# DATABASE
# ============================================================

def get_db():
    con = sqlite3.connect(DATABASE)
    con.row_factory = sqlite3.Row
    return con


def db_execute(query, params=()):
    con = get_db()
    try:
        cur = con.execute(query, params)
        con.commit()
        return cur
    finally:
        con.close()


def db_fetchone(query, params=()):
    con = get_db()
    try:
        return con.execute(query, params).fetchone()
    finally:
        con.close()


def db_fetchall(query, params=()):
    con = get_db()
    try:
        return con.execute(query, params).fetchall()
    finally:
        con.close()


def init_db():
    con = get_db()

    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS apps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                token TEXT NOT NULL UNIQUE,
                owner_email TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_text TEXT NOT NULL UNIQUE,
                app_token TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'unused',
                hwid TEXT,
                used_by TEXT,
                created_at TEXT NOT NULL
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                hwid TEXT,
                app_token TEXT,
                key_text TEXT,
                first_seen TEXT
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS tool_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                app_token TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                hwid TEXT,
                created_at TEXT NOT NULL
            )
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_apps_owner
            ON apps(owner_email)
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_app
            ON tool_users(app_token)
        """)

        con.commit()

    finally:
        con.close()


init_db()


# ============================================================
# SECURITY / HELPERS
# ============================================================

REQUEST_HISTORY = {}


def get_client_ip():
    """
    Uses the address supplied by Flask after ProxyFix.
    """
    return request.remote_addr or "unknown"


def rate_limit(max_requests=10, window_seconds=60):
    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            ip = get_client_ip()
            now = time.time()

            history = REQUEST_HISTORY.setdefault(ip, [])

            history[:] = [
                timestamp
                for timestamp in history
                if now - timestamp < window_seconds
            ]

            if len(history) >= max_requests:
                return jsonify({
                    "status": "rate_limited",
                    "message": "Too many requests. Please try again later."
                }), 429

            history.append(now)

            # Prevent unlimited memory growth.
            if len(REQUEST_HISTORY) > 5000:
                oldest_ip = min(
                    REQUEST_HISTORY,
                    key=lambda key: REQUEST_HISTORY[key][-1]
                    if REQUEST_HISTORY[key]
                    else 0
                )
                REQUEST_HISTORY.pop(oldest_ip, None)

            return func(*args, **kwargs)

        return wrapper

    return decorator


def json_data():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def current_user():
    return session.get("user")


def current_email():
    user = current_user()

    if not user:
        return None

    email = user.get("email")

    if not isinstance(email, str):
        return None

    return email.strip().lower()


def is_paid(email):
    return email.lower() in {
        x.lower()
        for x in PAID_USERS
    }


def generate_app_token():
    while True:
        token = "HSL_" + secrets.token_urlsafe(24)

        exists = db_fetchone(
            "SELECT id FROM apps WHERE token=?",
            (token,)
        )

        if not exists:
            return token


def normalize_username(username):
    if not isinstance(username, str):
        return ""

    username = username.strip()

    if len(username) > 64:
        return ""

    return username


def validate_username(username):
    if not username:
        return False

    if len(username) < 2 or len(username) > 64:
        return False

    allowed = (
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        "_-."
    )

    return all(char in allowed for char in username)


def validate_password(password):
    if not isinstance(password, str):
        return False

    return 6 <= len(password) <= 128


def hash_password(password):
    """
    Passwords are stored as salted PBKDF2 hashes.
    """
    salt = secrets.token_bytes(16)

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        210_000,
    )

    return (
        "pbkdf2_sha256$"
        + salt.hex()
        + "$"
        + derived.hex()
    )


def verify_password(password, stored):
    """
    Supports the new hashed format.
    Also supports old plaintext passwords so existing
    installations don't immediately break.
    """

    if not isinstance(stored, str):
        return False

    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, salt_hex, hash_hex = stored.split("$", 2)

            salt = bytes.fromhex(salt_hex)

            expected = bytes.fromhex(hash_hex)

            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                210_000,
            )

            return hmac.compare_digest(actual, expected)

        except Exception:
            return False

    # Legacy password support.
    return hmac.compare_digest(stored, password)


def login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if not current_email():
            return jsonify({
                "error": "Unauthorized"
            }), 401

        return func(*args, **kwargs)

    return wrapper


def redirect_login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if not current_email():
            return redirect("/login")

        return func(*args, **kwargs)

    return wrapper


def get_owned_app(email, token):
    if not email or not token:
        return None

    return db_fetchone(
        """
        SELECT *
        FROM apps
        WHERE token=?
        AND owner_email=?
        """,
        (token, email),
    )


def get_owned_user(email, username):
    if not email or not username:
        return None

    return db_fetchone(
        """
        SELECT
            tool_users.*,
            apps.owner_email
        FROM tool_users
        INNER JOIN apps
            ON apps.token = tool_users.app_token
        WHERE tool_users.username=?
        AND apps.owner_email=?
        """,
        (username, email),
    )


def count_user_records(email):
    row = db_fetchone(
        """
        SELECT COUNT(*)
        FROM tool_users
        WHERE app_token IN (
            SELECT token
            FROM apps
            WHERE owner_email=?
        )
        """,
        (email,),
    )

    return int(row[0]) if row else 0


def count_key_records(email):
    row = db_fetchone(
        """
        SELECT COUNT(*)
        FROM keys
        WHERE app_token IN (
            SELECT token
            FROM apps
            WHERE owner_email=?
        )
        """,
        (email,),
    )

    return int(row[0]) if row else 0


def limit_reached(email):
    if is_paid(email):
        return False

    total = (
        count_user_records(email)
        + count_key_records(email)
    )

    return total >= FREE_USER_KEY_LIMIT


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
        "default-src 'self' https:; "
        "img-src 'self' https: data:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "script-src 'self' 'unsafe-inline' https:; "
        "font-src 'self' https: data:; "
        "connect-src 'self' https:; "
        "frame-ancestors 'none';"
    )

    return response


# ============================================================
# COMMON CSS
# ============================================================

COMMON_HEAD = r"""
<script src="https://cdn.tailwindcss.com"></script>

<style>
:root {
    --cyan:#00f6ff;
    --blue:#3b82f6;
    --violet:#7c3aed;
    --danger:#ff1744;
    --bg:#03050b;
}

* {
    box-sizing:border-box;
}

html {
    scroll-behavior:smooth;
}

body {
    margin:0;
    background:
        radial-gradient(
            circle at 50% -10%,
            rgba(0,246,255,.13),
            transparent 35%
        ),
        radial-gradient(
            circle at 100% 100%,
            rgba(124,58,237,.12),
            transparent 30%
        ),
        #03050b;
    color:#f8fafc;
    font-family:
        Inter,
        ui-sans-serif,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}

::selection {
    background:rgba(0,246,255,.30);
    color:white;
}

::-webkit-scrollbar {
    width:7px;
}

::-webkit-scrollbar-track {
    background:#02040a;
}

::-webkit-scrollbar-thumb {
    background:linear-gradient(
        var(--cyan),
        var(--violet)
    );
    border-radius:999px;
}

#particles {
    position:fixed;
    inset:0;
    width:100%;
    height:100%;
    z-index:0;
    pointer-events:none;
}

.ambient {
    position:fixed;
    inset:-20%;
    z-index:0;
    pointer-events:none;
    background:
        radial-gradient(
            circle at 15% 20%,
            rgba(0,246,255,.07),
            transparent 22%
        ),
        radial-gradient(
            circle at 85% 30%,
            rgba(124,58,237,.07),
            transparent 25%
        );
    animation:ambientMove 12s ease-in-out infinite alternate;
}

@keyframes ambientMove {
    from {
        transform:scale(1);
    }

    to {
        transform:scale(1.08) translate3d(1%,-1%,0);
    }
}

.grid-bg {
    position:fixed;
    inset:0;
    z-index:1;
    pointer-events:none;
    background:
        linear-gradient(
            rgba(255,255,255,.018) 1px,
            transparent 1px
        ),
        linear-gradient(
            90deg,
            rgba(255,255,255,.018) 1px,
            transparent 1px
        );
    background-size:42px 42px;
    mask-image:linear-gradient(
        to bottom,
        black,
        transparent 90%
    );
}

.vignette {
    position:fixed;
    inset:0;
    z-index:3;
    pointer-events:none;
    box-shadow:
        inset 0 0 180px rgba(0,0,0,.90);
}

.glass {
    background:
        linear-gradient(
            145deg,
            rgba(15,20,35,.90),
            rgba(3,7,15,.78)
        );
    border:1px solid rgba(0,246,255,.18);
    backdrop-filter:blur(22px) saturate(140%);
    -webkit-backdrop-filter:blur(22px) saturate(140%);
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.05),
        0 25px 80px rgba(0,0,0,.45),
        0 0 45px rgba(0,246,255,.06);
}

.card {
    position:relative;
    overflow:hidden;
    background:
        linear-gradient(
            145deg,
            rgba(12,17,30,.88),
            rgba(4,7,14,.75)
        );
    border:1px solid rgba(0,246,255,.13);
    backdrop-filter:blur(18px);
    transition:
        transform .25s ease,
        border-color .25s ease,
        box-shadow .25s ease;
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.035),
        0 12px 45px rgba(0,0,0,.30);
}

.card:hover {
    transform:translateY(-4px);
    border-color:rgba(0,246,255,.36);
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.06),
        0 18px 55px rgba(0,0,0,.48),
        0 0 35px rgba(0,246,255,.12);
}

input,
select {
    outline:none;
}

input:focus,
select:focus {
    border-color:rgba(0,246,255,.65)!important;
    box-shadow:
        0 0 0 3px rgba(0,246,255,.07),
        0 0 22px rgba(0,246,255,.10);
}

button,
a {
    transition:
        transform .2s ease,
        filter .2s ease,
        box-shadow .2s ease;
}

button:hover,
a:hover {
    filter:brightness(1.08);
}

button:active,
a:active {
    transform:scale(.97);
}

.active-side {
    background:
        linear-gradient(
            90deg,
            rgba(0,246,255,.16),
            rgba(124,58,237,.08)
        );
    border:1px solid rgba(0,246,255,.42)!important;
    color:#67f7ff!important;
    font-weight:800;
    box-shadow:
        inset 3px 0 0 var(--cyan),
        0 0 24px rgba(0,246,255,.08);
}

@media(max-width:800px) {
    .desktop-sidebar {
        display:none;
    }
}
</style>
"""


PARTICLE_SCRIPT = r"""
<script>
(function () {

    const canvas = document.getElementById("particles");

    if (!canvas) return;

    const ctx = canvas.getContext("2d");

    let width = 0;
    let height = 0;

    const particles = [];
    const MAX = 180;

    function resize() {
        width = canvas.width = window.innerWidth;
        height = canvas.height = window.innerHeight;
    }

    resize();

    window.addEventListener("resize", resize);

    for (let i = 0; i < MAX; i++) {

        particles.push({
            x: Math.random() * window.innerWidth,
            y: Math.random() * window.innerHeight,
            r: Math.random() * 1.7 + .35,
            vx: (Math.random() - .5) * .28,
            vy: -(Math.random() * .65 + .15),
            a: Math.random() * .7 + .15,
            p: Math.random() * Math.PI * 2
        });
    }

    function animate() {

        ctx.clearRect(0, 0, width, height);

        for (const p of particles) {

            p.x += p.vx;
            p.y += p.vy;
            p.p += .025;

            if (p.y < -10) {
                p.y = height + 10;
                p.x = Math.random() * width;
            }

            if (p.x < -10) p.x = width + 10;
            if (p.x > width + 10) p.x = -10;

            const radius =
                Math.max(
                    .3,
                    p.r + Math.sin(p.p) * .4
                );

            ctx.beginPath();
            ctx.arc(
                p.x,
                p.y,
                radius,
                0,
                Math.PI * 2
            );

            ctx.fillStyle =
                `rgba(34,211,238,${p.a})`;

            ctx.shadowBlur = 9;
            ctx.shadowColor = "#22d3ee";
            ctx.fill();
        }

        ctx.shadowBlur = 0;

        for (let i = 0; i < particles.length; i++) {

            for (let j = i + 1; j < particles.length; j++) {

                const a = particles[i];
                const b = particles[j];

                const dx = a.x - b.x;
                const dy = a.y - b.y;

                const distance =
                    Math.sqrt(dx * dx + dy * dy);

                if (distance < 105) {

                    const alpha =
                        (1 - distance / 105) * .07;

                    ctx.beginPath();

                    ctx.moveTo(a.x, a.y);
                    ctx.lineTo(b.x, b.y);

                    ctx.strokeStyle =
                        `rgba(0,246,255,${alpha})`;

                    ctx.lineWidth = .5;
                    ctx.stroke();
                }
            }
        }

        requestAnimationFrame(animate);
    }

    animate();

})();
</script>
"""


# ============================================================
# LANDING PAGE
# ============================================================

LANDING_HTML = COMMON_HEAD + r"""
</head>
<body class="min-h-screen overflow-x-hidden">

<canvas id="particles"></canvas>
<div class="ambient"></div>
<div class="grid-bg"></div>
<div class="vignette"></div>

<nav class="
    relative z-10
    flex justify-between items-center
    px-6 md:px-10 py-5
    bg-black/50
    backdrop-blur-xl
    border-b border-cyan-400/10
">

    <div class="flex items-center gap-3">

        <div class="
            w-11 h-11
            rounded-xl
            bg-gradient-to-r from-cyan-400 to-indigo-600
            flex items-center justify-center
            text-xl
            shadow-[0_0_22px_rgba(34,211,238,.55)]
        ">
            👾
        </div>

        <div>
            <p class="font-black tracking-wider">
                HSL CORP
            </p>

            <p class="
                text-[9px]
                text-cyan-400
                font-bold
                tracking-[.25em]
            ">
                AUTH INFRASTRUCTURE
            </p>
        </div>

    </div>

    <div class="flex gap-3">

        <a
            href="/login"
            class="
                px-5 py-2.5
                rounded-full
                text-xs
                font-bold
                bg-zinc-900/80
                border border-zinc-700
            "
        >
            Sign In
        </a>

        <a
            href="/dashboard"
            class="
                px-5 py-2.5
                rounded-full
                text-xs
                font-bold
                bg-gradient-to-r
                from-cyan-400
                to-indigo-600
                shadow-[0_0_22px_rgba(34,211,238,.45)]
            "
        >
            Dashboard
        </a>

    </div>

</nav>


<section class="
    relative z-10
    max-w-6xl
    mx-auto
    px-6
    pt-24
    pb-20
    text-center
">

    <div class="
        inline-flex
        items-center
        gap-2
        border border-cyan-500/30
        bg-cyan-500/10
        px-4 py-2
        rounded-full
        text-xs
        text-cyan-300
        font-bold
    ">
        ⚡ NEXT-GEN SOFTWARE AUTHENTICATION
    </div>

    <h1 class="
        mt-8
        text-5xl md:text-7xl
        font-black
        leading-tight
        bg-gradient-to-r
        from-cyan-300
        via-cyan-400
        to-indigo-500
        bg-clip-text
        text-transparent
    ">
        HSL CORP AUTH
    </h1>

    <p class="
        max-w-2xl
        mx-auto
        mt-6
        text-zinc-400
        text-base md:text-lg
    ">
        Hardware-locked software licensing,
        application management and secure
        authentication infrastructure.
    </p>

    <div class="mt-9">

        <a
            href="/login"
            class="
                inline-flex
                items-center
                gap-2
                px-9 py-4
                rounded-2xl
                font-black
                text-sm
                bg-gradient-to-r
                from-cyan-400
                to-indigo-600
                shadow-[0_0_35px_rgba(34,211,238,.5)]
            "
        >
            🚀 GET STARTED
        </a>

    </div>

</section>


<section class="
    relative z-10
    max-w-6xl
    mx-auto
    px-6
    pb-24
">

    <div class="grid md:grid-cols-3 gap-6">

        <div class="card rounded-2xl p-7">

            <div class="
                w-12 h-12
                rounded-xl
                bg-cyan-500/10
                border border-cyan-500/30
                flex items-center justify-center
                text-2xl
            ">
                🔐
            </div>

            <h3 class="
                mt-5
                font-black
                text-lg
                text-cyan-300
            ">
                HWID Protection
            </h3>

            <p class="
                mt-2
                text-xs
                text-zinc-400
                leading-relaxed
            ">
                License sessions can be bound to
                a hardware identifier to reduce
                unauthorized account sharing.
            </p>

        </div>


        <div class="card rounded-2xl p-7">

            <div class="
                w-12 h-12
                rounded-xl
                bg-indigo-500/10
                border border-indigo-500/30
                flex items-center justify-center
                text-2xl
            ">
                🛡️
            </div>

            <h3 class="
                mt-5
                font-black
                text-lg
                text-indigo-300
            ">
                API Security
            </h3>

            <p class="
                mt-2
                text-xs
                text-zinc-400
                leading-relaxed
            ">
                Rate limiting, authenticated
                application tokens and signed
                request support.
            </p>

        </div>


        <div class="card rounded-2xl p-7">

            <div class="
                w-12 h-12
                rounded-xl
                bg-cyan-500/10
                border border-cyan-500/30
                flex items-center justify-center
                text-2xl
            ">
                ⚡
            </div>

            <h3 class="
                mt-5
                font-black
                text-lg
                text-cyan-300
            ">
                Admin Console
            </h3>

            <p class="
                mt-2
                text-xs
                text-zinc-400
                leading-relaxed
            ">
                Manage applications, users,
                HWIDs, account status and
                authentication tokens.
            </p>

        </div>

    </div>

</section>


<footer class="
    relative z-10
    border-t border-white/5
    text-center
    py-6
    text-xs
    text-zinc-600
">
    © 2026 HSL CORP
</footer>

""" + PARTICLE_SCRIPT + r"""
</body>
</html>
"""


# ============================================================
# LOGIN
# ============================================================

LOGIN_HTML = COMMON_HEAD + r"""
</head>
<body class="
    min-h-screen
    flex items-center justify-center
    px-5
">

<canvas id="particles"></canvas>
<div class="ambient"></div>
<div class="grid-bg"></div>
<div class="vignette"></div>

<div class="
    relative z-10
    w-full max-w-md
    glass
    rounded-[28px]
    p-8 md:p-10
    text-center
">

    <div class="
        w-16 h-16
        mx-auto
        rounded-2xl
        bg-gradient-to-r
        from-cyan-400
        to-indigo-600
        flex items-center justify-center
        text-2xl
        shadow-[0_0_28px_rgba(34,211,238,.55)]
    ">
        👾
    </div>

    <h1 class="
        mt-5
        text-2xl
        font-black
        bg-gradient-to-r
        from-cyan-300
        to-indigo-400
        bg-clip-text
        text-transparent
    ">
        HSL CORP
    </h1>

    <p class="
        mt-2
        text-xs
        text-zinc-500
    ">
        Secure Developer Console
    </p>

    {% if error %}
    <div class="
        mt-6
        rounded-xl
        border border-red-500/30
        bg-red-500/10
        px-4 py-3
        text-xs
        text-red-300
    ">
        {{ error }}
    </div>
    {% endif %}

    {% if google_enabled %}

    <a
        href="/auth/google"
        class="
            mt-8
            w-full
            flex items-center justify-center gap-3
            bg-white
            text-black
            rounded-xl
            py-3.5
            font-black
            text-sm
            shadow-xl
        "
    >
        <img
            src="https://www.svgrepo.com/show/475656/google-color.svg"
            width="20"
            height="20"
            alt="Google"
        >

        Continue with Google
    </a>

    {% else %}

    <div class="
        mt-8
        rounded-xl
        border border-yellow-500/30
        bg-yellow-500/10
        p-4
        text-xs
        text-yellow-300
    ">
        Google OAuth is not configured.
        Set GOOGLE_CLIENT_ID and
        GOOGLE_CLIENT_SECRET.
    </div>

    {% endif %}

</div>

""" + PARTICLE_SCRIPT + r"""
</body>
</html>
"""


# ============================================================
# DASHBOARD
# ============================================================

DASHBOARD_HTML = COMMON_HEAD + r"""
</head>

<body class="min-h-screen text-white">

<canvas id="particles"></canvas>
<div class="ambient"></div>
<div class="grid-bg"></div>
<div class="vignette"></div>


<div class="relative z-10 min-h-screen flex">


<!-- ======================================================
     SIDEBAR
     ====================================================== -->

<aside class="
    desktop-sidebar
    w-[260px]
    shrink-0
    min-h-screen
    bg-[#02040a]/90
    backdrop-blur-2xl
    border-r border-cyan-400/10
    flex flex-col
">

    <div class="
        p-5
        border-b border-white/10
        flex items-center gap-3
    ">

        <div class="
            w-10 h-10
            rounded-xl
            bg-gradient-to-r
            from-cyan-400
            to-indigo-600
            flex items-center justify-center
            shadow-[0_0_16px_rgba(34,211,238,.5)]
        ">
            👾
        </div>

        <div>

            <p class="font-black text-sm">
                HSL CORP
            </p>

            <p class="
                text-[9px]
                text-cyan-400
                font-bold
            ">
                DEVELOPER CONSOLE
            </p>

        </div>

    </div>


    <nav
        id="sidebar"
        class="p-3 space-y-1"
    >

        <button
            onclick="showTab('overview')"
            id="btn-overview"
            class="active-side w-full text-left rounded-xl px-4 py-3 text-xs"
        >
            🏠 Overview
        </button>

        <button
            onclick="showTab('applications')"
            id="btn-applications"
            class="w-full text-left rounded-xl px-4 py-3 text-xs text-zinc-400"
        >
            📦 Applications
        </button>

        <button
            onclick="showTab('users')"
            id="btn-users"
            class="w-full text-left rounded-xl px-4 py-3 text-xs text-zinc-400"
        >
            👤 Users ({{ user_count }}/{{ limit_text }})
        </button>

        <button
            onclick="showTab('keys')"
            id="btn-keys"
            class="w-full text-left rounded-xl px-4 py-3 text-xs text-zinc-400"
        >
            🔑 License Keys
        </button>

        <button
            onclick="showTab('integration')"
            id="btn-integration"
            class="w-full text-left rounded-xl px-4 py-3 text-xs text-zinc-400"
        >
            🔌 Integration
        </button>

        <button
            onclick="showTab('billing')"
            id="btn-billing"
            class="w-full text-left rounded-xl px-4 py-3 text-xs text-zinc-400"
        >
            💎 Billing
        </button>

    </nav>


    <div class="
        mt-auto
        p-4
        border-t border-white/10
        bg-black/40
    ">

        <p class="
            text-[10px]
            font-bold
            text-zinc-500
        ">
            SIGNED IN AS
        </p>

        <p class="
            text-xs
            font-bold
            truncate
            mt-1
        ">
            {{ email }}
        </p>

        <p class="
            text-[10px]
            mt-1
            {{ plan_color }}
            font-black
        ">
            {{ plan_text }}
        </p>

        <a
            href="/logout"
            class="
                block
                mt-4
                text-xs
                text-red-400
                font-bold
            "
        >
            Logout
        </a>

    </div>

</aside>


<!-- ======================================================
     MAIN
     ====================================================== -->

<main class="flex-1 min-w-0">

    <header class="
        h-16
        bg-black/55
        backdrop-blur-xl
        border-b border-cyan-400/10
        flex items-center justify-between
        px-5 md:px-8
    ">

        <div>

            <p class="
                text-xs
                text-cyan-300
                font-black
                tracking-wider
            ">
                HSL CONSOLE
            </p>

            <p class="
                text-[9px]
                text-zinc-500
            ">
                {{ plan_text }} PLAN
            </p>

        </div>

        <button
            onclick="showTab('billing')"
            class="
                text-[10px]
                md:text-xs
                font-black
                px-4 py-2
                rounded-full
                bg-gradient-to-r
                from-cyan-400
                to-indigo-600
            "
        >
            Upgrade
        </button>

    </header>


    <div class="p-5 md:p-8">


<!-- ======================================================
     OVERVIEW
     ====================================================== -->

<section id="tab-overview">

    <h1 class="text-2xl font-black">
        Dashboard Overview
    </h1>

    <p class="mt-1 text-xs text-zinc-500">
        Manage your authentication infrastructure.
    </p>


    <div class="
        grid
        md:grid-cols-3
        gap-5
        mt-6
    ">


        <div class="card rounded-2xl p-5">

            <p class="
                text-[10px]
                font-black
                text-cyan-400
            ">
                APPLICATIONS
            </p>

            <p class="
                text-3xl
                font-black
                mt-2
            ">
                {{ app_count }}
            </p>

        </div>


        <div class="card rounded-2xl p-5">

            <p class="
                text-[10px]
                font-black
                text-indigo-400
            ">
                USERS
            </p>

            <p class="
                text-3xl
                font-black
                mt-2
            ">
                {{ user_count }}
            </p>

        </div>


        <div class="card rounded-2xl p-5">

            <p class="
                text-[10px]
                font-black
                text-cyan-400
            ">
                PLAN
            </p>

            <p class="
                text-xl
                font-black
                mt-3
            ">
                {{ plan_text }}
            </p>

        </div>

    </div>


    <div class="
        card
        rounded-2xl
        p-6
        mt-6
    ">

        <p class="
            text-xs
            text-cyan-300
            font-black
        ">
            ACTIVE APPLICATION
        </p>

        {% if apps %}

        <select
            id="appSelect"
            onchange="selectApp(this.value)"
            class="
                mt-3
                w-full
                bg-black/80
                border border-white/10
                rounded-xl
                px-4 py-3
                text-xs
            "
        >

            {% for item in apps %}

            <option value="{{ item['token'] }}">
                {{ item['name'] }}
            </option>

            {% endfor %}

        </select>


        <div class="
            mt-4
            bg-black/80
            border border-white/10
            rounded-xl
            p-4
        ">

            <p class="
                text-[9px]
                text-zinc-500
                font-black
            ">
                APP TOKEN
            </p>

            <div class="
                flex
                gap-3
                items-center
                mt-2
            ">

                <code
                    id="tokenDisplay"
                    class="
                        flex-1
                        text-xs
                        text-cyan-300
                        font-mono
                        truncate
                    "
                >
                    {{ apps[0]['token'] }}
                </code>

                <button
                    onclick="copyToken()"
                    class="
                        px-3 py-2
                        rounded-lg
                        bg-gradient-to-r
                        from-cyan-400
                        to-indigo-600
                        text-[10px]
                        font-black
                    "
                >
                    COPY
                </button>

            </div>

        </div>

        {% else %}

        <p class="
            mt-4
            text-xs
            text-zinc-500
        ">
            No applications created yet.
        </p>

        {% endif %}

    </div>


    <div class="
        card
        rounded-2xl
        p-6
        mt-6
    ">

        <p class="font-black">
            + Create Secure User
        </p>

        <div class="
            grid
            md:grid-cols-2
            gap-3
            mt-4
        ">

            <input
                id="newUsername"
                placeholder="Username"
                maxlength="64"
                class="
                    bg-black/80
                    border border-white/10
                    rounded-xl
                    px-4 py-3
                    text-sm
                "
            >

            <input
                id="newPassword"
                type="password"
                placeholder="Password"
                maxlength="128"
                class="
                    bg-black/80
                    border border-white/10
                    rounded-xl
                    px-4 py-3
                    text-sm
                "
            >

        </div>

        <button
            onclick="createUser()"
            class="
                mt-4
                w-full
                py-3
                rounded-xl
                bg-gradient-to-r
                from-cyan-400
                to-indigo-600
                text-sm
                font-black
            "
        >
            CREATE USER
        </button>

    </div>

</section>


<!-- ======================================================
     APPLICATIONS
     ====================================================== -->

<section id="tab-applications" class="hidden">

    <h1 class="text-2xl font-black">
        Applications
    </h1>

    <div class="
        card
        rounded-2xl
        p-6
        mt-6
    ">

        {% if apps %}

            {% for item in apps %}

            <div class="
                bg-black/70
                border border-white/10
                rounded-xl
                p-4
                mb-3
                flex
                flex-col md:flex-row
                gap-3
                justify-between
                md:items-center
            ">

                <div>

                    <p class="font-black text-sm">
                        {{ item['name'] }}
                    </p>

                    <code class="
                        text-[10px]
                        text-zinc-500
                    ">
                        {{ item['token'] }}
                    </code>

                </div>

                <button
                    onclick="deleteApp('{{ item['token'] }}')"
                    class="
                        bg-red-500/10
                        border border-red-500/30
                        text-red-300
                        px-4 py-2
                        rounded-lg
                        text-[10px]
                        font-black
                    "
                >
                    DELETE
                </button>

            </div>

            {% endfor %}

        {% else %}

            <p class="
                text-xs
                text-zinc-500
            ">
                No applications.
            </p>

        {% endif %}


        <div class="
            border-t
            border-white/10
            pt-6
            mt-6
        ">

            <p class="font-black">
                + Create Application
            </p>

            <input
                id="newAppName"
                maxlength="64"
                placeholder="Application name"
                class="
                    mt-3
                    w-full
                    bg-black/80
                    border border-white/10
                    rounded-xl
                    px-4 py-3
                    text-sm
                "
            >

            <button
                onclick="createApp()"
                class="
                    mt-4
                    w-full
                    py-3
                    rounded-xl
                    bg-gradient-to-r
                    from-cyan-400
                    to-indigo-600
                    text-sm
                    font-black
                "
            >
                CREATE APPLICATION
            </button>

        </div>

    </div>

</section>


<!-- ======================================================
     USERS
     ====================================================== -->

<section id="tab-users" class="hidden">

    <h1 class="text-2xl font-black">
        Users
    </h1>

    <div class="
        card
        rounded-2xl
        p-5
        mt-6
    ">

        {% if users %}

            {% for user in users %}

            <div class="
                bg-black/75
                border border-white/10
                rounded-xl
                p-4
                mb-3
            ">

                <div class="
                    flex
                    flex-col md:flex-row
                    justify-between
                    gap-4
                ">

                    <div>

                        <p class="
                            font-black
                            text-sm
                        ">
                            {{ user['username'] }}
                        </p>

                        <p class="
                            text-[10px]
                            text-zinc-500
                            mt-1
                        ">
                            Status:
                            <span class="
                                {% if user['status'] == 'active' %}
                                text-green-400
                                {% else %}
                                text-red-400
                                {% endif %}
                                font-black
                            ">
                                {{ user['status']|upper }}
                            </span>
                        </p>

                        <p class="
                            text-[10px]
                            text-zinc-500
                            mt-1
                            font-mono
                        ">
                            HWID:
                            {% if user['hwid'] %}
                                {{ user['hwid'][:20] }}...
                            {% else %}
                                NOT BOUND
                            {% endif %}
                        </p>

                    </div>


                    <div class="
                        flex
                        flex-wrap
                        gap-2
                        items-start
                    ">

                        <button
                            onclick="editUser('{{ user['username'] }}')"
                            class="
                                bg-blue-500/10
                                border border-blue-500/30
                                text-blue-300
                                px-3 py-2
                                rounded-lg
                                text-[10px]
                                font-black
                            "
                        >
                            EDIT
                        </button>

                        <button
                            onclick="toggleBan('{{ user['username'] }}')"
                            class="
                                bg-yellow-500/10
                                border border-yellow-500/30
                                text-yellow-300
                                px-3 py-2
                                rounded-lg
                                text-[10px]
                                font-black
                            "
                        >
                            {% if user['status'] == 'active' %}
                                BAN
                            {% else %}
                                UNBAN
                            {% endif %}
                        </button>

                        <button
                            onclick="resetHwid('{{ user['username'] }}')"
                            class="
                                bg-zinc-800
                                border border-white/10
                                px-3 py-2
                                rounded-lg
                                text-[10px]
                                font-black
                            "
                        >
                            RESET HWID
                        </button>

                        <button
                            onclick="deleteUser('{{ user['username'] }}')"
                            class="
                                bg-red-500/10
                                border border-red-500/30
                                text-red-300
                                px-3 py-2
                                rounded-lg
                                text-[10px]
                                font-black
                            "
                        >
                            DELETE
                        </button>

                    </div>

                </div>

            </div>

            {% endfor %}

        {% else %}

            <p class="
                text-center
                text-xs
                text-zinc-600
                py-10
            ">
                No users created.
            </p>

        {% endif %}

    </div>

</section>


<!-- ======================================================
     KEYS
     ====================================================== -->

<section id="tab-keys" class="hidden">

    <h1 class="text-2xl font-black">
        License Keys
    </h1>

    <div class="
        card
        rounded-2xl
        p-6
        mt-6
    ">

        <p class="
            text-xs
            text-zinc-500
        ">
            Key management endpoint is ready.
            Add your preferred key-generation
            workflow here.
        </p>

    </div>

</section>


<!-- ======================================================
     INTEGRATION
     ====================================================== -->

<section id="tab-integration" class="hidden">

    <h1 class="text-2xl font-black">
        Client Integration
    </h1>

    <div class="
        card
        rounded-2xl
        p-6
        mt-6
    ">

        <p class="
            text-xs
            text-cyan-300
            font-black
        ">
            AUTHENTICATION EXAMPLE
        </p>

        <pre class="
            mt-4
            bg-black
            border border-white/10
            rounded-xl
            p-5
            overflow-x-auto
            text-[11px]
            text-green-400
            leading-relaxed
        ">import hashlib
import requests
import subprocess

APP_TOKEN = "YOUR_APP_TOKEN"
AUTH_URL = "https://YOUR-DOMAIN.com/api/auth_login"

def get_hwid():
    try:
        raw = subprocess.check_output(
            "wmic baseboard get serialnumber",
            shell=True
        ).decode(errors="ignore")

        lines = [
            x.strip()
            for x in raw.splitlines()
            if x.strip()
        ]

        return lines[1] if len(lines) > 1 else "UNKNOWN"

    except Exception:
        return "UNKNOWN"


def login(username, password):

    hwid = get_hwid()

    signature = hashlib.sha256(
        f"{username}:{hwid}:{APP_TOKEN}".encode()
    ).hexdigest()

    payload = {
        "username": username,
        "password": password,
        "hwid": hwid,
        "token": APP_TOKEN,
        "sig": signature
    }

    response = requests.post(
        AUTH_URL,
        json=payload,
        timeout=10
    )

    return response.json()</pre>

    </div>

</section>


<!-- ======================================================
     BILLING
     ====================================================== -->

<section id="tab-billing" class="hidden">

    <h1 class="text-2xl font-black">
        Billing / Plans
    </h1>

    <div class="
        grid
        md:grid-cols-2
        gap-6
        mt-6
    ">

        <div class="card rounded-2xl p-7">

            <p class="
                text-sm
                font-black
                text-zinc-300
            ">
                FREE
            </p>

            <p class="
                text-4xl
                font-black
                mt-2
            ">
                ₹0
            </p>

            <div class="
                mt-5
                text-xs
                text-zinc-400
                leading-7
            ">
                ✓ 2 Applications<br>
                ✓ 10 Users / Keys<br>
                ✓ HWID Lock<br>
                ✓ Basic API
            </div>

        </div>


        <div class="
            card
            rounded-2xl
            p-7
            border-cyan-400/40
        ">

            <p class="
                text-sm
                font-black
                text-cyan-400
            ">
                PRO UNLIMITED
            </p>

            <p class="
                text-4xl
                font-black
                mt-2
            ">
                ₹499
            </p>

            <div class="
                mt-5
                text-xs
                text-zinc-300
                leading-7
            ">
                ✓ Unlimited Applications<br>
                ✓ Unlimited Users<br>
                ✓ Unlimited Keys<br>
                ✓ HWID Lock<br>
                ✓ Advanced API
            </div>

            <a
                href="https://wa.me/919999999999"
                target="_blank"
                rel="noopener noreferrer"
                class="
                    mt-6
                    block
                    text-center
                    py-3
                    rounded-xl
                    bg-gradient-to-r
                    from-cyan-400
                    to-indigo-600
                    text-sm
                    font-black
                "
            >
                BUY PRO
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
        .querySelectorAll("[id^='tab-']")
        .forEach(function(el) {
            el.classList.add("hidden");
        });

    const target =
        document.getElementById("tab-" + name);

    if (target) {
        target.classList.remove("hidden");
    }

    document
        .querySelectorAll("#sidebar button")
        .forEach(function(btn) {

            btn.classList.remove("active-side");
            btn.classList.add("text-zinc-400");

        });

    const active =
        document.getElementById("btn-" + name);

    if (active) {
        active.classList.add("active-side");
        active.classList.remove("text-zinc-400");
    }
}


function selectedToken() {

    const el =
        document.getElementById("tokenDisplay");

    if (!el) return "";

    return el.innerText.trim();
}


function selectApp(token) {

    const display =
        document.getElementById("tokenDisplay");

    if (display) {
        display.innerText = token;
    }
}


async function apiRequest(url, body) {

    try {

        const response =
            await fetch(url, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                credentials: "same-origin",
                body: JSON.stringify(body)
            });

        const data =
            await response.json();

        if (!response.ok) {

            if (data.error) {
                alert(data.error);
            } else if (data.message) {
                alert(data.message);
            } else {
                alert("Request failed.");
            }

            return null;
        }

        return data;

    } catch (error) {

        console.error(error);
        alert("Network error. Please try again.");

        return null;
    }
}


async function createApp() {

    const input =
        document.getElementById("newAppName");

    const name =
        input ? input.value.trim() : "";

    if (!name) {
        alert("Enter application name.");
        return;
    }

    const data =
        await apiRequest(
            "/api/create_app",
            {name: name}
        );

    if (!data) return;

    alert(
        "Application created.\n\nToken:\n"
        + data.token
    );

    location.reload();
}


async function deleteApp(token) {

    if (!confirm(
        "Delete this application?\n"
        + "All associated users will also be removed."
    )) {
        return;
    }

    const data =
        await apiRequest(
            "/api/delete_app",
            {token: token}
        );

    if (!data) return;

    alert(data.message || "Deleted.");

    location.reload();
}


async function createUser() {

    const username =
        document
            .getElementById("newUsername")
            .value
            .trim();

    const password =
        document
            .getElementById("newPassword")
            .value;

    const token =
        selectedToken();

    if (!token) {
        alert("Create/select an application first.");
        return;
    }

    if (!username || !password) {
        alert("Enter username and password.");
        return;
    }

    const data =
        await apiRequest(
            "/api/create_user",
            {
                username: username,
                password: password,
                app_token: token
            }
        );

    if (!data) return;

    alert(data.message || "User created.");

    location.reload();
}


async function deleteUser(username) {

    if (!confirm(
        "Delete user " + username + "?"
    )) {
        return;
    }

    const data =
        await apiRequest(
            "/api/delete_user",
            {username: username}
        );

    if (!data) return;

    alert(data.message || "Deleted.");

    location.reload();
}


async function resetHwid(username) {

    if (!confirm(
        "Reset HWID for " + username + "?"
    )) {
        return;
    }

    const data =
        await apiRequest(
            "/api/reset_hwid",
            {username: username}
        );

    if (!data) return;

    alert(data.message || "HWID reset.");

    location.reload();
}


async function toggleBan(username) {

    const data =
        await apiRequest(
            "/api/toggle_ban",
            {username: username}
        );

    if (!data) return;

    alert(data.message || "Status updated.");

    location.reload();
}


async function editUser(oldUsername) {

    const newUsername =
        prompt(
            "New username:",
            oldUsername
        );

    if (newUsername === null) {
        return;
    }

    const newPassword =
        prompt(
            "New password (leave empty to keep current):"
        );

    if (newPassword === null) {
        return;
    }

    const body = {
        old_username: oldUsername,
        new_username: newUsername.trim()
    };

    if (newPassword !== "") {
        body.new_password = newPassword;
    }

    const data =
        await apiRequest(
            "/api/edit_user",
            body
        );

    if (!data) return;

    alert(data.message || "Updated.");

    location.reload();
}


function copyToken() {

    const token =
        selectedToken();

    if (!token) {
        alert("No token available.");
        return;
    }

    navigator.clipboard
        .writeText(token)
        .then(function() {
            alert("Token copied.");
        })
        .catch(function() {
            alert(token);
        });
}

</script>

""" + PARTICLE_SCRIPT + r"""
</body>
</html>
"""


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def home():
    return render_template_string(LANDING_HTML)


@app.route("/login")
def login():
    if current_email():
        return redirect("/dashboard")

    return render_template_string(
        LOGIN_HTML,
        google_enabled=google is not None,
        error=request.args.get("error"),
    )


# ============================================================
# GOOGLE AUTH
# ============================================================

@app.route("/auth/google")
@rate_limit(max_requests=5, window_seconds=60)
def auth_google():

    if google is None:
        return redirect(
            "/login?error="
            "Google%20OAuth%20is%20not%20configured."
        )

    redirect_uri = (
        request.url_root.rstrip("/")
        + "/auth/callback"
    )

    return google.authorize_redirect(
        redirect_uri
    )


@app.route("/auth/callback")
@rate_limit(max_requests=10, window_seconds=60)
def auth_callback():

    if google is None:
        return redirect(
            "/login?error="
            "Google%20OAuth%20is%20not%20configured."
        )

    try:

        token = google.authorize_access_token()

        user_info = token.get("userinfo")

        if not user_info:

            response = google.get(
                "https://openidconnect.googleapis.com/v1/userinfo"
            )

            if not response.ok:
                raise RuntimeError(
                    "Google userinfo request failed"
                )

            user_info = response.json()

        email = user_info.get("email")

        if not email:
            raise RuntimeError(
                "Google did not provide email"
            )

        email = email.strip().lower()

        session.clear()

        session["user"] = {
            "email": email,
            "name": user_info.get(
                "name",
                email.split("@")[0]
            ),
            "picture": user_info.get(
                "picture",
                ""
            ),
        }

        session.permanent = True

        return redirect("/dashboard")

    except Exception as exc:

        app.logger.warning(
            "Google authentication failed: %s",
            exc
        )

        return redirect(
            "/login?error="
            "Google%20authentication%20failed."
        )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
@redirect_login_required
def dashboard():

    email = current_email()

    paid = is_paid(email)

    plan_text = (
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

    limit_text = (
        "Unlimited"
        if paid
        else
        str(FREE_USER_KEY_LIMIT)
    )

    apps = db_fetchall(
        """
        SELECT *
        FROM apps
        WHERE owner_email=?
        ORDER BY id DESC
        """,
        (email,),
    )

    users = db_fetchall(
        """
        SELECT
            tool_users.*
        FROM tool_users
        INNER JOIN apps
            ON apps.token=tool_users.app_token
        WHERE apps.owner_email=?
        ORDER BY tool_users.id DESC
        """,
        (email,),
    )

    return render_template_string(
        DASHBOARD_HTML,
        email=email,
        name=session["user"].get(
            "name",
            "User"
        ),
        apps=apps,
        users=users,
        app_count=len(apps),
        user_count=len(users),
        plan_text=plan_text,
        plan_color=plan_color,
        limit_text=limit_text,
    )


# ============================================================
# CREATE APP
# ============================================================

@app.route("/api/create_app", methods=["POST"])
@login_required
@rate_limit(max_requests=20, window_seconds=60)
def api_create_app():

    email = current_email()

    data = json_data()

    name = data.get("name", "")

    if not isinstance(name, str):
        return jsonify({
            "error": "Invalid application name."
        }), 400

    name = name.strip()

    if not name:
        return jsonify({
            "error": "Application name is required."
        }), 400

    if len(name) > 64:
        return jsonify({
            "error": "Application name is too long."
        }), 400

    row = db_fetchone(
        """
        SELECT COUNT(*)
        FROM apps
        WHERE owner_email=?
        """,
        (email,),
    )

    app_count = int(row[0]) if row else 0

    if not is_paid(email) and app_count >= FREE_APP_LIMIT:
        return jsonify({
            "error": (
                "Free Plan limit reached. "
                "Maximum 2 applications allowed."
            )
        }), 403

    token = generate_app_token()

    db_execute(
        """
        INSERT INTO apps
        (
            name,
            token,
            owner_email,
            created_at
        )
        VALUES (?,?,?,?)
        """,
        (
            name,
            token,
            email,
            datetime.utcnow().isoformat(),
        ),
    )

    return jsonify({
        "status": "success",
        "token": token,
        "message": "Application created."
    })


# ============================================================
# DELETE APP
# ============================================================

@app.route("/api/delete_app", methods=["POST"])
@login_required
@rate_limit(max_requests=20, window_seconds=60)
def api_delete_app():

    email = current_email()

    data = json_data()

    token = data.get("token")

    if not isinstance(token, str) or not token:
        return jsonify({
            "error": "Invalid application token."
        }), 400

    owned_app = get_owned_app(
        email,
        token
    )

    if not owned_app:
        return jsonify({
            "error": "Application not found."
        }), 404

    # Remove dependent records first.
    db_execute(
        """
        DELETE FROM tool_users
        WHERE app_token=?
        """,
        (token,),
    )

    db_execute(
        """
        DELETE FROM keys
        WHERE app_token=?
        """,
        (token,),
    )

    db_execute(
        """
        DELETE FROM users
        WHERE app_token=?
        """,
        (token,),
    )

    db_execute(
        """
        DELETE FROM apps
        WHERE token=?
        AND owner_email=?
        """,
        (token, email),
    )

    return jsonify({
        "status": "success",
        "message": "Application deleted successfully."
    })


# ============================================================
# CREATE USER
# ============================================================

@app.route("/api/create_user", methods=["POST"])
@login_required
@rate_limit(max_requests=20, window_seconds=60)
def api_create_user():

    email = current_email()

    data = json_data()

    username = normalize_username(
        data.get("username", "")
    )

    password = data.get("password", "")

    app_token = data.get("app_token", "")

    if not validate_username(username):
        return jsonify({
            "message": (
                "Invalid username. Use 2-64 "
                "letters, numbers, _, -, or ."
            )
        }), 400

    if not validate_password(password):
        return jsonify({
            "message": (
                "Password must be between "
                "6 and 128 characters."
            )
        }), 400

    if not isinstance(app_token, str):
        return jsonify({
            "message": "Invalid application."
        }), 400

    app_token = app_token.strip()

    owned_app = get_owned_app(
        email,
        app_token
    )

    if not owned_app:
        return jsonify({
            "message": "Application not found."
        }), 404

    if limit_reached(email):
        return jsonify({
            "message": (
                "Free Plan user/key limit reached."
            )
        }), 403

    existing = db_fetchone(
        """
        SELECT id
        FROM tool_users
        WHERE username=?
        """,
        (username,),
    )

    if existing:
        return jsonify({
            "message": "Username already exists."
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
                hwid,
                created_at
            )
            VALUES (?,?,?,?,?,?)
            """,
            (
                username,
                password_hash,
                app_token,
                "active",
                None,
                datetime.utcnow().isoformat(),
            ),
        )

    except sqlite3.IntegrityError:

        return jsonify({
            "message": "Username already exists."
        }), 409

    return jsonify({
        "status": "success",
        "message": (
            f"User {username} created successfully."
        )
    })


# ============================================================
# DELETE USER
# ============================================================

@app.route("/api/delete_user", methods=["POST"])
@login_required
@rate_limit(max_requests=20, window_seconds=60)
def api_delete_user():

    email = current_email()

    data = json_data()

    username = normalize_username(
        data.get("username", "")
    )

    user = get_owned_user(
        email,
        username
    )

    if not user:
        return jsonify({
            "error": "User not found."
        }), 404

    db_execute(
        """
        DELETE FROM tool_users
        WHERE username=?
        """,
        (username,),
    )

    return jsonify({
        "status": "success",
        "message": "User deleted successfully."
    })


# ============================================================
# RESET HWID
# ============================================================

@app.route("/api/reset_hwid", methods=["POST"])
@login_required
@rate_limit(max_requests=20, window_seconds=60)
def api_reset_hwid():

    email = current_email()

    data = json_data()

    username = normalize_username(
        data.get("username", "")
    )

    user = get_owned_user(
        email,
        username
    )

    if not user:
        return jsonify({
            "error": "User not found."
        }), 404

    db_execute(
        """
        UPDATE tool_users
        SET hwid=NULL
        WHERE username=?
        """,
        (username,),
    )

    return jsonify({
        "status": "success",
        "message": (
            f"HWID reset for {username}."
        )
    })


# ============================================================
# BAN / UNBAN
# ============================================================

@app.route("/api/toggle_ban", methods=["POST"])
@login_required
@rate_limit(max_requests=20, window_seconds=60)
def api_toggle_ban():

    email = current_email()

    data = json_data()

    username = normalize_username(
        data.get("username", "")
    )

    user = get_owned_user(
        email,
        username
    )

    if not user:
        return jsonify({
            "error": "User not found."
        }), 404

    old_status = user["status"]

    new_status = (
        "banned"
        if old_status == "active"
        else "active"
    )

    db_execute(
        """
        UPDATE tool_users
        SET status=?
        WHERE username=?
        """,
        (
            new_status,
            username,
        ),
    )

    return jsonify({
        "status": "success",
        "message": (
            f"{username} is now "
            f"{new_status.upper()}."
        )
    })


# ============================================================
# EDIT USER
# ============================================================

@app.route("/api/edit_user", methods=["POST"])
@login_required
@rate_limit(max_requests=20, window_seconds=60)
def api_edit_user():

    email = current_email()

    data = json_data()

    old_username = normalize_username(
        data.get("old_username", "")
    )

    new_username = normalize_username(
        data.get(
            "new_username",
            old_username
        )
    )

    new_password = data.get(
        "new_password"
    )

    user = get_owned_user(
        email,
        old_username
    )

    if not user:
        return jsonify({
            "error": "User not found."
        }), 404

    if not validate_username(new_username):
        return jsonify({
            "error": "Invalid new username."
        }), 400

    if new_username != old_username:

        existing = db_fetchone(
            """
            SELECT id
            FROM tool_users
            WHERE username=?
            """,
            (new_username,),
        )

        if existing:
            return jsonify({
                "error": (
                    "New username already exists."
                )
            }), 409

    if new_password is not None:

        if not validate_password(new_password):
            return jsonify({
                "error": (
                    "Password must be "
                    "6-128 characters."
                )
            }), 400

        password_hash = hash_password(
            new_password
        )

        db_execute(
            """
            UPDATE tool_users
            SET
                username=?,
                password=?
            WHERE username=?
            """,
            (
                new_username,
                password_hash,
                old_username,
            ),
        )

    else:

        db_execute(
            """
            UPDATE tool_users
            SET username=?
            WHERE username=?
            """,
            (
                new_username,
                old_username,
            ),
        )

    return jsonify({
        "status": "success",
        "message": (
            f"User {old_username} updated."
        )
    })


# ============================================================
# CLIENT AUTHENTICATION
# ============================================================

@app.route("/api/auth_login", methods=["POST"])
@rate_limit(
    max_requests=10,
    window_seconds=60
)
def api_auth_login():

    data = json_data()

    username = normalize_username(
        data.get("username", "")
    )

    password = data.get("password", "")
    hwid = data.get("hwid", "")
    token = data.get("token", "")
    client_sig = data.get("sig", "")

    if (
        not username
        or not isinstance(password, str)
        or not password
        or not isinstance(hwid, str)
        or not hwid
        or not isinstance(token, str)
        or not token
    ):

        return jsonify({
            "status": "invalid",
            "message": (
                "Malformed request parameters."
            )
        }), 400

    if len(hwid) > 512:
        return jsonify({
            "status": "invalid",
            "message": "Invalid HWID."
        }), 400

    if len(token) > 256:
        return jsonify({
            "status": "invalid",
            "message": "Invalid token."
        }), 400

    # --------------------------------------------------------
    # Verify that application token exists.
    # --------------------------------------------------------

    app_row = db_fetchone(
        """
        SELECT id
        FROM apps
        WHERE token=?
        """,
        (token,),
    )

    if not app_row:
        return jsonify({
            "status": "invalid",
            "message": "Invalid application token."
        }), 401

    # --------------------------------------------------------
    # Signature verification.
    # --------------------------------------------------------

    expected_sig = hashlib.sha256(
        f"{username}:{hwid}:{token}".encode(
            "utf-8"
        )
    ).hexdigest()

    if not isinstance(client_sig, str):
        return jsonify({
            "status": "tampered",
            "message": "Invalid request signature."
        }), 403

    if not hmac.compare_digest(
        client_sig,
        expected_sig
    ):
        return jsonify({
            "status": "tampered",
            "message": "Request signature mismatch."
        }), 403

    # --------------------------------------------------------
    # Find user.
    # --------------------------------------------------------

    user = db_fetchone(
        """
        SELECT *
        FROM tool_users
        WHERE username=?
        AND app_token=?
        """,
        (
            username,
            token,
        ),
    )

    if not user:
        return jsonify({
            "status": "invalid",
            "message": "Incorrect credentials."
        }), 401

    # --------------------------------------------------------
    # Password verification.
    # --------------------------------------------------------

    if not verify_password(
        password,
        user["password"]
    ):
        return jsonify({
            "status": "invalid",
            "message": "Incorrect credentials."
        }), 401

    # --------------------------------------------------------
    # Ban check.
    # --------------------------------------------------------

    if user["status"] == "banned":
        return jsonify({
            "status": "banned",
            "message": "Account suspended."
        }), 403

    # --------------------------------------------------------
    # First HWID bind.
    # --------------------------------------------------------

    if not user["hwid"]:

        db_execute(
            """
            UPDATE tool_users
            SET
                hwid=?,
                status='active'
            WHERE id=?
            """,
            (
                hwid,
                user["id"],
            ),
        )

        return jsonify({
            "status": "valid",
            "message": (
                "HWID bound successfully."
            )
        })

    # --------------------------------------------------------
    # HWID verification.
    # --------------------------------------------------------

    if hmac.compare_digest(
        str(user["hwid"]),
        str(hwid)
    ):
        return jsonify({
            "status": "valid",
            "message": "Authentication successful."
        })

    return jsonify({
        "status": "hwid_mismatch",
        "message": "Hardware mismatch detected."
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

    try:

        db_fetchone(
            "SELECT 1"
        )

        return jsonify({
            "status": "ok",
            "database": "connected"
        })

    except Exception:

        return jsonify({
            "status": "error",
            "database": "unavailable"
        }), 500


# ============================================================
# 404
# ============================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith("/api/"):

        return jsonify({
            "error": "Endpoint not found."
        }), 404

    return redirect("/")


# ============================================================
# 405
# ============================================================

@app.errorhandler(405)
def method_not_allowed(error):

    if request.path.startswith("/api/"):

        return jsonify({
            "error": "Method not allowed."
        }), 405

    return "Method Not Allowed", 405


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================

@app.errorhandler(Exception)
def handle_exception(error):

    app.logger.exception(
        "Unhandled application error"
    )

    if request.path.startswith("/api/"):

        return jsonify({
            "error": "Internal server error."
        }), 500

    return (
        "<h1>Internal Server Error</h1>",
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

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )