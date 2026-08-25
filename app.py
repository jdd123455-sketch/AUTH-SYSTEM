import os
import random
import sqlite3
import string
import time
import hashlib
import secrets
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
from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# HSL CORP — SECURE AUTH PANEL
# ============================================================

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    secrets.token_hex(32)
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

PAID_USERS = {
    "js7876839939@gmail.com"
}

FREE_APP_LIMIT = 2
FREE_USER_LIMIT = 10


# ============================================================
# GOOGLE OAUTH
# ============================================================

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
# RATE LIMITER
# ============================================================

REQUEST_HISTORY = {}


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()

    return request.remote_addr or "unknown"


def rate_limit(max_requests=10, window_seconds=60):
    def decorator(func):

        @wraps(func)
        def wrapped(*args, **kwargs):
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

            return func(*args, **kwargs)

        return wrapped

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
    response.headers["Cache-Control"] = "no-store"

    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https: 'unsafe-inline' 'unsafe-eval'; "
        "img-src 'self' data: https:; "
        "font-src 'self' https: data:; "
        "connect-src 'self' https:; "
        "frame-ancestors 'none';"
    )

    return response


# ============================================================
# DATABASE
# ============================================================

DB_FILE = "hsl.db"


def get_db():
    con = sqlite3.connect(DB_FILE)
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

    con.commit()
    con.close()


init_db()


def db(query, params=(), fetch=False, one=False):
    con = get_db()

    try:
        cur = con.cursor()
        cur.execute(query, params)

        if fetch:
            if one:
                result = cur.fetchone()
            else:
                result = cur.fetchall()
        else:
            result = None

        con.commit()
        return result

    finally:
        con.close()


# ============================================================
# HELPERS
# ============================================================

def is_paid(email):
    return email.lower() in {
        x.lower() for x in PAID_USERS
    }


def generate_app_token():
    while True:
        token = "HSL_" + secrets.token_urlsafe(24)

        exists = db(
            "SELECT id FROM apps WHERE token=?",
            (token,),
            fetch=True,
            one=True
        )

        if not exists:
            return token


def generate_license_key():
    parts = []

    for _ in range(4):
        parts.append(
            "".join(
                random.choices(
                    string.ascii_uppercase + string.digits,
                    k=5
                )
            )
        )

    return "HSL-" + "-".join(parts)


def current_email():
    user = session.get("user")

    if not user:
        return None

    return user.get("email")


def owns_app(email, token):
    row = db(
        """
        SELECT id
        FROM apps
        WHERE token=? AND owner_email=?
        """,
        (token, email),
        fetch=True,
        one=True
    )

    return row is not None


def get_owned_user(email, username):
    row = db(
        """
        SELECT tu.*
        FROM tool_users tu
        JOIN apps a ON a.token = tu.app_token
        WHERE tu.username=? AND a.owner_email=?
        """,
        (username, email),
        fetch=True,
        one=True
    )

    return row


def get_user_counts(email):
    user_count = db(
        """
        SELECT COUNT(*)
        FROM tool_users tu
        JOIN apps a ON a.token = tu.app_token
        WHERE a.owner_email=?
        """,
        (email,),
        fetch=True,
        one=True
    )[0]

    key_count = db(
        """
        SELECT COUNT(*)
        FROM keys k
        JOIN apps a ON a.token = k.app_token
        WHERE a.owner_email=?
        """,
        (email,),
        fetch=True,
        one=True
    )[0]

    return user_count, key_count


def limit_reached(email):
    if is_paid(email):
        return False

    user_count, key_count = get_user_counts(email)

    return user_count >= FREE_USER_LIMIT or key_count >= FREE_USER_LIMIT


def escape_js(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


# ============================================================
# COMMON CSS
# ============================================================

COMMON_HEAD = r"""
<script src="https://cdn.tailwindcss.com"></script>

<style>

:root {
    --cyan: #00f6ff;
    --cyan2: #22d3ee;
    --blue: #2563eb;
    --purple: #7c3aed;
    --pink: #d946ef;
    --red: #ff1744;
    --green: #00ff9d;
    --bg: #020308;
}

* {
    box-sizing: border-box;
}

html {
    scroll-behavior: smooth;
}

body {
    margin: 0;
    color: #f8fafc;
    background:
        radial-gradient(
            circle at 50% -15%,
            rgba(0,246,255,.16),
            transparent 32%
        ),
        radial-gradient(
            circle at 100% 80%,
            rgba(124,58,237,.13),
            transparent 30%
        ),
        radial-gradient(
            circle at 0% 70%,
            rgba(0,246,255,.07),
            transparent 27%
        ),
        #020308;

    font-family:
        Inter,
        ui-sans-serif,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    cursor: none;
    overflow-x: hidden;
}

::selection {
    color: white;
    background: rgba(0,246,255,.3);
}

::-webkit-scrollbar {
    width: 6px;
}

::-webkit-scrollbar-track {
    background: #010208;
}

::-webkit-scrollbar-thumb {
    background: linear-gradient(
        #00f6ff,
        #7c3aed
    );
    border-radius: 999px;
}


/* =========================================================
   PARTICLE CANVAS
========================================================= */

#c {
    position: fixed;
    inset: 0;
    z-index: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
}


/* =========================================================
   CYBER GRID
========================================================= */

.cyber-grid {
    position: fixed;
    inset: 0;
    z-index: 1;
    pointer-events: none;

    background-image:
        linear-gradient(
            rgba(0,246,255,.025) 1px,
            transparent 1px
        ),
        linear-gradient(
            90deg,
            rgba(0,246,255,.025) 1px,
            transparent 1px
        );

    background-size: 45px 45px;

    mask-image:
        linear-gradient(
            to bottom,
            black 0%,
            black 55%,
            transparent 100%
        );
}


/* =========================================================
   SCANLINES
========================================================= */

.scanlines {
    position: fixed;
    inset: 0;
    z-index: 5;
    pointer-events: none;

    background:
        repeating-linear-gradient(
            0deg,
            rgba(255,255,255,.018) 0px,
            rgba(255,255,255,.018) 1px,
            transparent 1px,
            transparent 4px
        );

    opacity: .35;
}


/* =========================================================
   VIGNETTE
========================================================= */

.vignette {
    position: fixed;
    inset: 0;
    z-index: 6;
    pointer-events: none;

    box-shadow:
        inset 0 0 180px rgba(0,0,0,.92),
        inset 0 0 60px rgba(0,246,255,.035);
}


/* =========================================================
   AMBIENT LIGHT
========================================================= */

.ambient {
    position: fixed;
    inset: -20%;
    z-index: 0;
    pointer-events: none;

    background:
        radial-gradient(
            circle at 20% 20%,
            rgba(0,246,255,.08),
            transparent 23%
        ),
        radial-gradient(
            circle at 80% 30%,
            rgba(124,58,237,.09),
            transparent 25%
        ),
        radial-gradient(
            circle at 50% 90%,
            rgba(37,99,235,.06),
            transparent 30%
        );

    animation:
        ambientMove 12s ease-in-out infinite alternate;
}

@keyframes ambientMove {
    0% {
        transform:
            scale(1)
            translate3d(-1%,0,0);
    }

    50% {
        transform:
            scale(1.06)
            translate3d(1%,-1%,0);
    }

    100% {
        transform:
            scale(1.02)
            translate3d(0,1%,0);
    }
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
            rgba(13,20,35,.91),
            rgba(2,6,14,.80)
        );

    border:
        1px solid rgba(0,246,255,.18);

    backdrop-filter:
        blur(25px)
        saturate(145%);

    -webkit-backdrop-filter:
        blur(25px)
        saturate(145%);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.05),
        0 30px 90px rgba(0,0,0,.55),
        0 0 50px rgba(0,246,255,.05);
}

.glass::before {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;

    background:
        linear-gradient(
            120deg,
            rgba(0,246,255,.07),
            transparent 30%,
            transparent 70%,
            rgba(124,58,237,.06)
        );
}


/* =========================================================
   CARDS
========================================================= */

.glass-card {
    position: relative;
    overflow: hidden;

    background:
        linear-gradient(
            145deg,
            rgba(12,18,31,.88),
            rgba(3,7,15,.76)
        );

    border:
        1px solid rgba(0,246,255,.13);

    backdrop-filter:
        blur(18px)
        saturate(135%);

    -webkit-backdrop-filter:
        blur(18px)
        saturate(135%);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.035),
        0 15px 50px rgba(0,0,0,.32);

    transition:
        transform .28s cubic-bezier(.2,.8,.2,1),
        border-color .28s ease,
        box-shadow .28s ease;
}

.glass-card:hover {
    transform: translateY(-5px);

    border-color:
        rgba(0,246,255,.42);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.07),
        0 22px 65px rgba(0,0,0,.5),
        0 0 40px rgba(0,246,255,.12);
}

.glass-card::after {
    content: "";

    position: absolute;
    width: 60px;
    height: 60px;

    right: -30px;
    bottom: -30px;

    border:
        1px solid rgba(0,246,255,.22);

    transform: rotate(45deg);

    pointer-events: none;
}


/* =========================================================
   BUTTONS
========================================================= */

button,
a {
    transition:
        transform .2s ease,
        filter .2s ease,
        box-shadow .2s ease,
        border-color .2s ease;
}

button:hover,
a:hover {
    filter: brightness(1.08);
}

button:active,
a:active {
    transform: scale(.97);
}

.bg-gradient-to-r {
    background-size: 180% 100%;
    animation: gradientFlow 5s ease infinite;
}

@keyframes gradientFlow {
    0%,100% {
        background-position: 0% 50%;
    }

    50% {
        background-position: 100% 50%;
    }
}


/* =========================================================
   CURSOR
========================================================= */

#cursor-dot {
    position: fixed;

    width: 6px;
    height: 6px;

    background: #ffffff;

    border-radius: 50%;

    pointer-events: none;

    z-index: 99999;

    transform:
        translate(-50%, -50%);

    box-shadow:
        0 0 6px #00f6ff,
        0 0 15px #00f6ff,
        0 0 35px rgba(0,246,255,.9);
}

#cursor-ring {
    position: fixed;

    width: 32px;
    height: 32px;

    border:
        1px solid rgba(0,246,255,.9);

    border-radius: 50%;

    pointer-events: none;

    z-index: 99998;

    transform:
        translate(-50%, -50%);

    box-shadow:
        0 0 15px rgba(0,246,255,.18),
        inset 0 0 10px rgba(0,246,255,.05);

    transition:
        width .18s ease,
        height .18s ease,
        border-color .18s ease;
}

#cursor-ring::before,
#cursor-ring::after {
    content: "";

    position: absolute;

    background:
        linear-gradient(
            90deg,
            transparent,
            #00f6ff,
            transparent
        );
}

#cursor-ring::before {
    width: 48px;
    height: 1px;

    left: -9px;
    top: 50%;
}

#cursor-ring::after {
    width: 1px;
    height: 48px;

    top: -9px;
    left: 50%;

    background:
        linear-gradient(
            180deg,
            transparent,
            #00f6ff,
            transparent
        );
}

#cursor-orbit {
    position: fixed;

    width: 55px;
    height: 55px;

    border:
        1px dashed rgba(124,58,237,.8);

    border-radius: 50%;

    pointer-events: none;

    z-index: 99997;

    transform:
        translate(-50%, -50%);

    animation:
        orbitSpin 3.5s linear infinite;

    box-shadow:
        0 0 18px rgba(124,58,237,.12);
}

@keyframes orbitSpin {
    from {
        transform:
            translate(-50%, -50%)
            rotate(0deg);
    }

    to {
        transform:
            translate(-50%, -50%)
            rotate(360deg);
    }
}

.cursor-hover #cursor-ring {
    width: 48px;
    height: 48px;

    border-color:
        #7c3aed;

    box-shadow:
        0 0 25px rgba(124,58,237,.4);
}


/* =========================================================
   ACTIVE SIDEBAR
========================================================= */

.side-active {
    position: relative;

    color: #67f7ff !important;

    font-weight: 800;

    background:
        linear-gradient(
            90deg,
            rgba(0,246,255,.18),
            rgba(124,58,237,.08)
        ) !important;

    border:
        1px solid rgba(0,246,255,.42) !important;

    box-shadow:
        inset 3px 0 0 #00f6ff,
        0 0 25px rgba(0,246,255,.09);
}

.side-active::after {
    content: "";

    position: absolute;

    right: 0;
    top: 0;

    width: 2px;
    height: 100%;

    background:
        #00f6ff;

    box-shadow:
        0 0 15px #00f6ff;
}


/* =========================================================
   INPUT
========================================================= */

input,
select {
    outline: none;

    transition:
        border-color .2s ease,
        box-shadow .2s ease;
}

input:focus,
select:focus {
    border-color:
        rgba(0,246,255,.7) !important;

    box-shadow:
        0 0 0 3px rgba(0,246,255,.07),
        0 0 25px rgba(0,246,255,.10);
}


/* =========================================================
   RESPONSIVE
========================================================= */

@media(max-width: 768px) {
    body {
        cursor: auto;
    }

    #cursor-dot,
    #cursor-ring,
    #cursor-orbit {
        display: none;
    }
}

@media(prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        animation-duration: .01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: .01ms !important;
    }
}

</style>
"""


# ============================================================
# ANIMATED CURSOR + PARTICLES
# ============================================================

CURSOR_SCRIPT = r"""
<div id="cursor-dot"></div>
<div id="cursor-ring"></div>
<div id="cursor-orbit"></div>

<script>

(() => {

const dot = document.getElementById("cursor-dot");
const ring = document.getElementById("cursor-ring");
const orbit = document.getElementById("cursor-orbit");
const canvas = document.getElementById("c");

if (!canvas) return;

const ctx = canvas.getContext("2d");

let mouse = {
    x: window.innerWidth / 2,
    y: window.innerHeight / 2
};

let smooth = {
    x: mouse.x,
    y: mouse.y
};

let width = window.innerWidth;
let height = window.innerHeight;

let particles = [];
let trails = [];
let sparks = [];

const PARTICLE_COUNT =
    Math.min(
        260,
        Math.max(
            120,
            Math.floor(
                window.innerWidth *
                window.innerHeight /
                7500
            )
        )
    );


function resize() {

    width = window.innerWidth;
    height = window.innerHeight;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    canvas.width = width * dpr;
    canvas.height = height * dpr;

    canvas.style.width = width + "px";
    canvas.style.height = height + "px";

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

resize();

window.addEventListener("resize", resize);


function createParticle(randomY = true) {

    return {
        x: Math.random() * width,
        y: randomY
            ? Math.random() * height
            : height + Math.random() * 50,

        r: Math.random() * 1.6 + .35,

        vx: (Math.random() - .5) * .35,

        vy: -(Math.random() * .75 + .12),

        alpha: Math.random() * .65 + .15,

        phase: Math.random() * Math.PI * 2,

        speed:
            Math.random() * .025 + .01
    };
}


for(let i = 0; i < PARTICLE_COUNT; i++) {
    particles.push(createParticle());
}


window.addEventListener("mousemove", e => {

    mouse.x = e.clientX;
    mouse.y = e.clientY;

    dot.style.left = mouse.x + "px";
    dot.style.top = mouse.y + "px";

    trails.push({
        x: mouse.x,
        y: mouse.y,
        alpha: .75,
        size: Math.random() * 2.5 + 1
    });

    if(trails.length > 45) {
        trails.shift();
    }

    if(Math.random() < .75) {

        sparks.push({
            x: mouse.x,
            y: mouse.y,

            vx:
                (Math.random() - .5) *
                3.5,

            vy:
                (Math.random() - .5) *
                3.5,

            alpha: 1,

            size:
                Math.random() * 2.4 + .5
        });
    }
});


function hoverCursor() {

    document.querySelectorAll("a, button, input, select").forEach(el => {

        el.addEventListener("mouseenter", () => {
            document.body.classList.add("cursor-hover");
        });

        el.addEventListener("mouseleave", () => {
            document.body.classList.remove("cursor-hover");
        });

    });
}

hoverCursor();


function animate() {

    ctx.clearRect(0, 0, width, height);

    smooth.x +=
        (mouse.x - smooth.x) * .16;

    smooth.y +=
        (mouse.y - smooth.y) * .16;

    ring.style.left = smooth.x + "px";
    ring.style.top = smooth.y + "px";

    orbit.style.left = smooth.x + "px";
    orbit.style.top = smooth.y + "px";


    /* mouse trail */

    for(let i = 0; i < trails.length; i++) {

        const t = trails[i];

        t.alpha -= .035;

        t.size *= .97;

        if(t.alpha <= 0) {
            trails.splice(i, 1);
            i--;
            continue;
        }

        ctx.beginPath();

        ctx.arc(
            t.x,
            t.y,
            t.size,
            0,
            Math.PI * 2
        );

        ctx.fillStyle =
            `rgba(0,246,255,${t.alpha})`;

        ctx.shadowBlur = 15;
        ctx.shadowColor = "#00f6ff";

        ctx.fill();
    }


    /* particles */

    for(let i = 0; i < particles.length; i++) {

        const p = particles[i];

        p.x += p.vx;
        p.y += p.vy;

        p.phase += p.speed;

        if(p.y < -20) {
            particles[i] = createParticle(false);
        }

        if(p.x < -20) p.x = width + 20;
        if(p.x > width + 20) p.x = -20;

        const pulse =
            p.r +
            Math.sin(p.phase) * .35;

        ctx.beginPath();

        ctx.arc(
            p.x,
            p.y,
            Math.max(.3, pulse),
            0,
            Math.PI * 2
        );

        ctx.fillStyle =
            `rgba(34,211,238,${p.alpha})`;

        ctx.shadowBlur = 10;
        ctx.shadowColor = "#00f6ff";

        ctx.fill();
    }


    /* network lines */

    for(let i = 0; i < particles.length; i++) {

        const a = particles[i];

        for(
            let j = i + 1;
            j < particles.length;
            j++
        ) {

            const b = particles[j];

            const dx = a.x - b.x;
            const dy = a.y - b.y;

            const distance =
                Math.sqrt(
                    dx * dx +
                    dy * dy
                );

            if(distance < 110) {

                const alpha =
                    (1 - distance / 110) * .12;

                ctx.beginPath();

                ctx.moveTo(
                    a.x,
                    a.y
                );

                ctx.lineTo(
                    b.x,
                    b.y
                );

                ctx.strokeStyle =
                    `rgba(0,246,255,${alpha})`;

                ctx.lineWidth = .5;

                ctx.stroke();
            }
        }
    }


    /* mouse connection */

    for(const p of particles) {

        const dx =
            p.x - mouse.x;

        const dy =
            p.y - mouse.y;

        const distance =
            Math.sqrt(
                dx * dx +
                dy * dy
            );

        if(distance < 150) {

            const alpha =
                (1 - distance / 150) * .25;

            ctx.beginPath();

            ctx.moveTo(
                p.x,
                p.y
            );

            ctx.lineTo(
                mouse.x,
                mouse.y
            );

            ctx.strokeStyle =
                `rgba(124,58,237,${alpha})`;

            ctx.lineWidth = .7;

            ctx.stroke();
        }
    }


    /* sparks */

    for(let i = 0; i < sparks.length; i++) {

        const s = sparks[i];

        s.x += s.vx;
        s.y += s.vy;

        s.vx *= .96;
        s.vy *= .96;

        s.alpha -= .035;

        if(s.alpha <= 0) {
            sparks.splice(i, 1);
            i--;
            continue;
        }

        ctx.beginPath();

        ctx.arc(
            s.x,
            s.y,
            s.size,
            0,
            Math.PI * 2
        );

        ctx.fillStyle =
            `rgba(124,58,237,${s.alpha})`;

        ctx.shadowBlur = 15;
        ctx.shadowColor = "#7c3aed";

        ctx.fill();
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

LANDING = r"""
<!DOCTYPE html>
<html>
<head>
""" + COMMON_HEAD + """
</head>

<body class="min-h-screen flex flex-col">

<canvas id="c"></canvas>
<div class="ambient"></div>
<div class="cyber-grid"></div>
<div class="scanlines"></div>
<div class="vignette"></div>


<nav class="relative z-20
    flex items-center justify-between
    px-6 md:px-10 py-5
    border-b border-cyan-400/10
    bg-black/50 backdrop-blur-xl">

    <div class="flex items-center gap-3">

        <div class="
            w-11 h-11
            rounded-xl
            bg-gradient-to-br
            from-cyan-300
            via-blue-500
            to-purple-600
            flex items-center justify-center
            text-xl
            shadow-[0_0_25px_rgba(0,246,255,.55)]
        ">
            ⚡
        </div>

        <div>
            <p class="font-black tracking-widest">
                HSL CORP
            </p>

            <p class="
                text-[8px]
                text-cyan-400
                tracking-[.25em]
                font-bold
            ">
                SECURE AUTH INFRASTRUCTURE
            </p>
        </div>

    </div>


    <div class="flex gap-3">

        <a
            href="/login"
            class="
                px-5 py-2.5
                rounded-xl
                bg-black/60
                border border-white/10
                text-xs font-bold
            "
        >
            SIGN IN
        </a>

        <a
            href="/dashboard"
            class="
                hidden sm:block
                px-5 py-2.5
                rounded-xl
                bg-gradient-to-r
                from-cyan-400
                to-purple-600
                text-xs font-black
                shadow-[0_0_25px_rgba(0,246,255,.35)]
            "
        >
            CONSOLE
        </a>

    </div>

</nav>


<main class="
    relative z-10
    flex-1
    flex flex-col
    items-center
    text-center
    px-5
">

    <div class="mt-20
        inline-flex items-center gap-2
        px-4 py-2
        rounded-full
        border border-cyan-400/20
        bg-cyan-400/5
        text-cyan-300
        text-[10px]
        font-black
        tracking-widest
        shadow-[0_0_25px_rgba(0,246,255,.12)]
    ">
        <span class="animate-pulse">●</span>
        SYSTEM ONLINE
    </div>


    <h1 class="
        mt-8
        text-6xl
        md:text-8xl
        font-black
        tracking-tight
        bg-gradient-to-r
        from-cyan-200
        via-cyan-400
        to-purple-500
        bg-clip-text
        text-transparent
        drop-shadow-[0_0_40px_rgba(0,246,255,.35)]
    ">
        HSL CORP
    </h1>


    <p class="
        mt-5
        max-w-2xl
        text-zinc-400
        text-sm
        md:text-lg
        leading-relaxed
    ">
        Hardware-locked authentication,
        application management and
        secure licensing infrastructure.
    </p>


    <div class="mt-9 flex gap-3">

        <a
            href="/login"
            class="
                px-8 py-4
                rounded-2xl
                bg-gradient-to-r
                from-cyan-400
                to-purple-600
                text-black
                font-black
                text-sm
                shadow-[0_0_35px_rgba(0,246,255,.45)]
            "
        >
            ENTER CONSOLE →
        </a>

    </div>


    <div class="
        w-full max-w-6xl
        grid md:grid-cols-3
        gap-5
        mt-24 mb-20
    ">

        <div class="glass-card rounded-2xl p-7 text-left">

            <div class="
                w-12 h-12
                rounded-xl
                bg-cyan-400/10
                border border-cyan-400/20
                flex items-center justify-center
                text-xl
            ">
                🔐
            </div>

            <h2 class="mt-5 font-black text-lg">
                HWID LOCK
            </h2>

            <p class="mt-2 text-xs text-zinc-500 leading-relaxed">
                Bind application accounts to a
                hardware identifier and prevent
                unauthorized account sharing.
            </p>

        </div>


        <div class="glass-card rounded-2xl p-7 text-left">

            <div class="
                w-12 h-12
                rounded-xl
                bg-purple-400/10
                border border-purple-400/20
                flex items-center justify-center
                text-xl
            ">
                🛡️
            </div>

            <h2 class="mt-5 font-black text-lg">
                SECURE API
            </h2>

            <p class="mt-2 text-xs text-zinc-500 leading-relaxed">
                Signed authentication requests,
                rate limiting and server-side
                validation.
            </p>

        </div>


        <div class="glass-card rounded-2xl p-7 text-left">

            <div class="
                w-12 h-12
                rounded-xl
                bg-cyan-400/10
                border border-cyan-400/20
                flex items-center justify-center
                text-xl
            ">
                ⚡
            </div>

            <h2 class="mt-5 font-black text-lg">
                FAST CONSOLE
            </h2>

            <p class="mt-2 text-xs text-zinc-500 leading-relaxed">
                Manage applications, users,
                HWID locks and account status
                from one dashboard.
            </p>

        </div>

    </div>

</main>


<footer class="
    relative z-10
    text-center
    py-5
    border-t border-white/5
    text-[10px]
    text-zinc-600
">
    HSL CORP © 2026 — SECURE INFRASTRUCTURE
</footer>


""" + CURSOR_SCRIPT + """

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
""" + COMMON_HEAD + """
</head>

<body class="min-h-screen flex items-center justify-center px-5">

<canvas id="c"></canvas>
<div class="ambient"></div>
<div class="cyber-grid"></div>
<div class="scanlines"></div>
<div class="vignette"></div>


<div class="
    relative z-10
    w-full max-w-md
    glass
    rounded-[30px]
    p-9
    text-center
">

    <div class="
        mx-auto
        w-20 h-20
        rounded-2xl
        bg-gradient-to-br
        from-cyan-300
        via-blue-500
        to-purple-600
        flex items-center justify-center
        text-3xl
        shadow-[0_0_40px_rgba(0,246,255,.45)]
    ">
        ⚡
    </div>


    <p class="
        mt-6
        text-[9px]
        text-cyan-400
        font-black
        tracking-[.35em]
    ">
        HSL CORP AUTH
    </p>


    <h1 class="
        mt-2
        text-3xl
        font-black
    ">
        ACCESS CONSOLE
    </h1>


    <p class="
        mt-2
        text-xs
        text-zinc-500
    ">
        Continue using verified Google authentication.
    </p>


    {% if google_enabled %}

    <a
        href="/auth/google"
        class="
            mt-8
            w-full
            flex items-center justify-center gap-3
            py-4
            rounded-2xl
            bg-white
            text-black
            font-black
            text-sm
            shadow-[0_10px_40px_rgba(0,0,0,.3)]
        "
    >

        <img
            src="https://www.svgrepo.com/show/475656/google-color.svg"
            width="21"
            height="21"
        >

        CONTINUE WITH GOOGLE

    </a>

    {% else %}

    <div class="
        mt-8
        rounded-2xl
        border border-red-500/20
        bg-red-500/5
        p-4
        text-xs
        text-red-300
    ">
        Google OAuth is not configured.
        Add GOOGLE_CLIENT_ID and
        GOOGLE_CLIENT_SECRET environment variables.
    </div>

    {% endif %}


    <a
        href="/"
        class="
            inline-block
            mt-6
            text-[10px]
            text-zinc-600
            hover:text-cyan-400
        "
    >
        ← BACK TO HOME
    </a>

</div>


""" + CURSOR_SCRIPT + """

</body>
</html>
"""


# ============================================================
# DASHBOARD
# ============================================================

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html>
<head>
""" + COMMON_HEAD + """

<style>

.dashboard-sidebar {
    width: 270px;
    min-width: 270px;
}

@media(max-width: 900px) {

    .dashboard-sidebar {
        width: 75px;
        min-width: 75px;
    }

    .sidebar-label,
    .sidebar-user-info {
        display: none;
    }

    .sidebar-item {
        justify-content: center;
        padding-left: 0 !important;
        padding-right: 0 !important;
    }

}

</style>

</head>

<body class="h-screen overflow-hidden">

<canvas id="c"></canvas>
<div class="ambient"></div>
<div class="cyber-grid"></div>
<div class="scanlines"></div>
<div class="vignette"></div>


<div class="relative z-10 flex h-full">


<!-- ======================================================
     SIDEBAR
======================================================= -->

<aside class="
    dashboard-sidebar
    flex flex-col
    bg-black/70
    backdrop-blur-2xl
    border-r border-cyan-400/10
">

    <div class="
        p-5
        border-b border-white/10
        flex items-center gap-3
    ">

        <div class="
            w-10 h-10
            min-w-[40px]
            rounded-xl
            bg-gradient-to-br
            from-cyan-300
            to-purple-600
            flex items-center justify-center
            font-black
            shadow-[0_0_20px_rgba(0,246,255,.35)]
        ">
            ⚡
        </div>

        <div class="sidebar-user-info">

            <p class="
                font-black
                text-sm
                tracking-wider
            ">
                HSL CORP
            </p>

            <p class="
                text-[8px]
                text-cyan-400
                font-bold
                tracking-widest
            ">
                DEVELOPER CONSOLE
            </p>

        </div>

    </div>


    <nav id="sidebar" class="p-3 space-y-1">

        <button
            onclick="showTab('overview')"
            id="btn-overview"
            class="
                sidebar-item
                side-active
                w-full
                flex items-center gap-3
                text-left
                rounded-xl
                px-4 py-3
                text-xs
            "
        >
            🏠
            <span class="sidebar-label">Overview</span>
        </button>


        <button
            onclick="showTab('applications')"
            id="btn-applications"
            class="
                sidebar-item
                w-full
                flex items-center gap-3
                text-left
                rounded-xl
                px-4 py-3
                text-xs
                text-zinc-400
            "
        >
            📦
            <span class="sidebar-label">Applications</span>
        </button>


        <button
            onclick="showTab('tool_users')"
            id="btn-tool_users"
            class="
                sidebar-item
                w-full
                flex items-center gap-3
                text-left
                rounded-xl
                px-4 py-3
                text-xs
                text-zinc-400
            "
        >
            👤
            <span class="sidebar-label">
                Users {{tool_user_count}}/{{limit_text}}
            </span>
        </button>


        <button
            onclick="showTab('keys')"
            id="btn-keys"
            class="
                sidebar-item
                w-full
                flex items-center gap-3
                text-left
                rounded-xl
                px-4 py-3
                text-xs
                text-zinc-400
            "
        >
            🔑
            <span class="sidebar-label">
                License Keys
            </span>
        </button>


        <button
            onclick="showTab('integrate')"
            id="btn-integrate"
            class="
                sidebar-item
                w-full
                flex items-center gap-3
                text-left
                rounded-xl
                px-4 py-3
                text-xs
                text-zinc-400
            "
        >
            🔌
            <span class="sidebar-label">
                Integration
            </span>
        </button>


        <button
            onclick="showTab('billing')"
            id="btn-billing"
            class="
                sidebar-item
                w-full
                flex items-center gap-3
                text-left
                rounded-xl
                px-4 py-3
                text-xs
                text-zinc-400
            "
        >
            💎
            <span class="sidebar-label">
                Billing
            </span>
        </button>

    </nav>


    <div class="
        mt-auto
        p-4
        border-t border-white/10
        bg-black/30
        flex items-center gap-3
    ">

        <img
            src="https://ui-avatars.com/api/?name={{name}}&background=0f172a&color=22d3ee"
            class="
                w-9 h-9
                rounded-full
                border border-cyan-400/30
            "
        >

        <div class="sidebar-user-info min-w-0">

            <p class="
                text-[10px]
                font-bold
                truncate
                max-w-[130px]
            ">
                {{email}}
            </p>

            <p class="
                text-[9px]
                {{plan_color}}
                font-black
            ">
                {{plan_text}}
            </p>

        </div>


        <a
            href="/logout"
            class="
                ml-auto
                text-[10px]
                text-red-400
                font-bold
            "
        >
            EXIT
        </a>

    </div>

</aside>


<!-- ======================================================
     MAIN
======================================================= -->

<main class="flex-1 min-w-0 overflow-y-auto">


<header class="
    h-16
    sticky top-0
    z-20
    flex items-center justify-between
    px-5 md:px-8
    bg-black/65
    backdrop-blur-xl
    border-b border-cyan-400/10
">

    <div>

        <p class="
            text-[9px]
            text-cyan-400
            font-black
            tracking-[.25em]
        ">
            HSL // CONTROL
        </p>

        <p class="text-xs font-bold">
            {{plan_text}} PLAN
        </p>

    </div>


    <button
        onclick="showTab('billing')"
        class="
            px-4 py-2
            rounded-xl
            bg-gradient-to-r
            from-cyan-400
            to-purple-600
            text-[10px]
            font-black
        "
    >
        UPGRADE
    </button>

</header>


<div class="p-5 md:p-8">


<!-- ======================================================
     OVERVIEW
======================================================= -->

<section id="tab-overview">

    <div class="flex items-end justify-between">

        <div>

            <p class="
                text-[9px]
                text-cyan-400
                font-black
                tracking-[.25em]
            ">
                SYSTEM STATUS
            </p>

            <h1 class="
                text-2xl
                md:text-3xl
                font-black
                mt-1
            ">
                Dashboard
            </h1>

        </div>

        <div class="
            hidden sm:flex
            items-center gap-2
            text-[9px]
            text-green-400
            font-bold
        ">
            <span class="animate-pulse">●</span>
            ONLINE
        </div>

    </div>


    <div class="
        mt-7
        grid
        lg:grid-cols-[1.3fr_1fr_.7fr]
        gap-4
    ">


        <div class="glass-card rounded-2xl p-5">

            <p class="
                text-[9px]
                text-cyan-400
                font-black
                tracking-widest
            ">
                ACTIVE APPLICATION
            </p>

            <select
                id="appSelect"
                onchange="selectApp(this.value)"
                class="
                    mt-3
                    w-full
                    bg-black/70
                    border border-white/10
                    rounded-xl
                    px-3 py-3
                    text-xs
                    font-bold
                "
            >
                {{app_options}}
            </select>

        </div>


        <div class="glass-card rounded-2xl p-5">

            <p class="
                text-[9px]
                text-zinc-500
                font-black
                tracking-widest
            ">
                MASTER TOKEN
            </p>

            <div class="
                mt-3
                flex items-center gap-2
                bg-black/70
                rounded-xl
                p-2
                border border-white/10
            ">

                <span
                    id="tokenDisplay"
                    class="
                        text-[9px]
                        font-mono
                        text-zinc-300
                        truncate
                        flex-1
                    "
                >
                    {{active_token}}
                </span>

                <button
                    onclick="copyToken()"
                    class="
                        px-3 py-2
                        rounded-lg
                        bg-gradient-to-r
                        from-cyan-400
                        to-purple-600
                        text-[9px]
                        font-black
                    "
                >
                    COPY
                </button>

            </div>

        </div>


        <div class="glass-card rounded-2xl p-5">

            <p class="
                text-[9px]
                text-zinc-500
                font-black
                tracking-widest
            ">
                USER LIMIT
            </p>

            <p class="mt-3 text-sm font-black">
                {{tool_user_count}} / {{limit_text}}
            </p>

            <div class="
                mt-3
                h-2
                bg-black
                rounded-full
                overflow-hidden
            ">
                <div
                    class="
                        h-full
                        bg-gradient-to-r
                        from-cyan-400
                        to-purple-600
                    "
                    style="width: {{percent}}%"
                ></div>
            </div>

        </div>

    </div>


    <div class="
        glass-card
        rounded-2xl
        p-6
        mt-5
    ">

        <div class="flex items-center gap-3">

            <div class="
                w-10 h-10
                rounded-xl
                bg-cyan-400/10
                border border-cyan-400/20
                flex items-center justify-center
            ">
                +
            </div>

            <div>

                <p class="font-black text-sm">
                    Create Secure User
                </p>

                <p class="
                    text-[10px]
                    text-zinc-500
                ">
                    Create a username/password
                    authentication account.
                </p>

            </div>

        </div>


        <div class="
            grid md:grid-cols-2
            gap-3
            mt-5
        ">

            <input
                id="newUsername"
                placeholder="Username"
                class="
                    bg-black/70
                    border border-white/10
                    rounded-xl
                    px-4 py-3
                    text-xs
                "
            >

            <input
                id="newPassword"
                type="password"
                placeholder="Password"
                class="
                    bg-black/70
                    border border-white/10
                    rounded-xl
                    px-4 py-3
                    text-xs
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
                to-purple-600
                text-xs
                font-black
            "
        >
            CREATE USER
        </button>

    </div>

</section>


<!-- ======================================================
     APPLICATIONS
======================================================= -->

<section id="tab-applications" class="hidden">

    <h1 class="text-2xl font-black">
        Applications
    </h1>

    <div class="
        glass-card
        rounded-2xl
        mt-6
        p-6
    ">

        {{app_list_html}}


        <div class="
            mt-7
            pt-6
            border-t border-white/10
        ">

            <p class="font-black text-sm">
                Create New Application
            </p>

            <input
                id="newAppName"
                placeholder="Application name"
                class="
                    mt-4
                    w-full
                    bg-black/70
                    border border-white/10
                    rounded-xl
                    px-4 py-3
                    text-xs
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
                    to-purple-600
                    text-xs
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
======================================================= -->

<section id="tab-tool_users" class="hidden">

    <h1 class="text-2xl font-black">
        Users
    </h1>

    <div class="
        glass-card
        rounded-2xl
        mt-6
        p-5
    ">

        {{tool_users_list_html}}

    </div>

</section>


<!-- ======================================================
     KEYS
======================================================= -->

<section id="tab-keys" class="hidden">

    <h1 class="text-2xl font-black">
        License Keys
    </h1>

    <div class="
        glass-card
        rounded-2xl
        mt-6
        p-5
    ">

        {{keys_list_html}}

    </div>

</section>


<!-- ======================================================
     INTEGRATION
======================================================= -->

<section id="tab-integrate" class="hidden">

    <h1 class="text-2xl font-black">
        Client Integration
    </h1>


    <div class="
        glass-card
        rounded-2xl
        mt-6
        p-6
    ">

        <p class="
            text-xs
            text-cyan-300
            font-black
        ">
            SECURE AUTHENTICATION EXAMPLE
        </p>


        <pre class="
            mt-5
            p-5
            rounded-xl
            bg-black/90
            border border-white/10
            text-[10px]
            text-green-400
            overflow-x-auto
            leading-relaxed
        ">import requests
import hashlib
import subprocess

APP_TOKEN = "{{active_token}}"

AUTH_URL = "https://YOUR-DOMAIN.com/api/auth_login"


def get_hwid():

    try:
        output = subprocess.check_output(
            "wmic baseboard get serialnumber",
            shell=True
        ).decode(errors="ignore")

        lines = [
            x.strip()
            for x in output.splitlines()
            if x.strip()
        ]

        if len(lines) >= 2:
            return lines[1]

    except Exception:
        pass

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

    return response.json()
</pre>

    </div>

</section>


<!-- ======================================================
     BILLING
======================================================= -->

<section id="tab-billing" class="hidden">

    <h1 class="text-2xl font-black">
        Plans
    </h1>


    <div class="
        grid md:grid-cols-2
        gap-5
        mt-6
    ">


        <div class="
            glass-card
            rounded-2xl
            p-7
        ">

            <p class="
                text-xs
                text-zinc-400
                font-black
            ">
                FREE
            </p>

            <p class="
                text-5xl
                font-black
                mt-2
            ">
                ₹0
            </p>

            <div class="
                mt-5
                text-xs
                text-zinc-400
                leading-8
            ">
                ✓ 10 users<br>
                ✓ 10 keys<br>
                ✓ 2 applications<br>
                ✓ HWID locking<br>
                ✓ Secure API
            </div>

        </div>


        <div class="
            glass-card
            rounded-2xl
            p-7
            border-cyan-400/40
        ">

            <p class="
                text-xs
                text-cyan-400
                font-black
            ">
                PRO UNLIMITED
            </p>

            <p class="
                text-5xl
                font-black
                mt-2
            ">
                ₹499
            </p>

            <div class="
                mt-5
                text-xs
                text-zinc-300
                leading-8
            ">
                ✓ Unlimited users<br>
                ✓ Unlimited keys<br>
                ✓ Unlimited applications<br>
                ✓ HWID locking<br>
                ✓ Advanced authentication
            </div>

            <a
                href="https://wa.me/919999999999"
                target="_blank"
                rel="noopener noreferrer"
                class="
                    block
                    mt-6
                    text-center
                    py-3
                    rounded-xl
                    bg-gradient-to-r
                    from-cyan-400
                    to-purple-600
                    text-xs
                    font-black
                "
            >
                CONTACT TO UPGRADE
            </a>

        </div>

    </div>

</section>


</div>

</main>

</div>


""" + CURSOR_SCRIPT + r"""

<script>

function showTab(name) {

    document
        .querySelectorAll('[id^="tab-"]')
        .forEach(el => {
            el.classList.add("hidden");
        });

    const target =
        document.getElementById("tab-" + name);

    if(target) {
        target.classList.remove("hidden");
    }


    document
        .querySelectorAll("#sidebar button")
        .forEach(button => {

            button.classList.remove("side-active");

            button.classList.add(
                "text-zinc-400"
            );

        });


    const active =
        document.getElementById(
            "btn-" + name
        );

    if(active) {

        active.classList.add(
            "side-active"
        );

        active.classList.remove(
            "text-zinc-400"
        );
    }
}


async function api(url, options = {}) {

    try {

        const response =
            await fetch(url, {
                ...options,
                headers: {
                    "Content-Type":
                        "application/json",
                    ...(options.headers || {})
                }
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

        alert(
            error.message ||
            "Request failed"
        );

        throw error;
    }
}


async function createApp() {

    const input =
        document.getElementById(
            "newAppName"
        );

    const name =
        input.value.trim();

    if(!name) {

        alert(
            "Enter application name."
        );

        return;
    }


    const data =
        await api(
            "/api/create_app",
            {
                method: "POST",
                body: JSON.stringify({
                    name: name
                })
            }
        );


    alert(
        "Application created!\n\nToken:\n" +
        data.token
    );

    location.reload();
}


async function deleteApp(token) {

    if(
        !confirm(
            "Delete this application?"
        )
    ) {
        return;
    }


    const data =
        await api(
            "/api/delete_app",
            {
                method: "POST",
                body: JSON.stringify({
                    token: token
                })
            }
        );


    alert(data.message);

    location.reload();
}


function copyToken() {

    const element =
        document.getElementById(
            "tokenDisplay"
        );

    const token =
        element.innerText.trim();

    if(
        !token ||
        token.startsWith("Create")
    ) {
        alert(
            "No application token available."
        );
        return;
    }


    navigator.clipboard
        .writeText(token)
        .then(() => {
            alert("Token copied.");
        })
        .catch(() => {
            alert(
                "Clipboard access failed."
            );
        });
}


function selectApp(token) {

    const display =
        document.getElementById(
            "tokenDisplay"
        );

    if(display) {
        display.innerText = token;
    }
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
            .value
            .trim();

    const token =
        document
            .getElementById("tokenDisplay")
            .innerText
            .trim();


    if(!username || !password) {

        alert(
            "Username and password required."
        );

        return;
    }


    if(
        !token ||
        token.startsWith("Create")
    ) {

        alert(
            "Create an application first."
        );

        return;
    }


    const data =
        await api(
            "/api/create_user",
            {
                method: "POST",
                body: JSON.stringify({
                    username,
                    password,
                    app_token: token
                })
            }
        );


    alert(data.message);

    location.reload();
}


async function deleteUser(username) {

    if(
        !confirm(
            "Delete " + username + "?"
        )
    ) {
        return;
    }


    const data =
        await api(
            "/api/delete_user",
            {
                method: "POST",
                body: JSON.stringify({
                    username
                })
            }
        );


    alert(data.message);

    location.reload();
}


async function resetHwid(username) {

    const data =
        await api(
            "/api/reset_hwid",
            {
                method: "POST",
                body: JSON.stringify({
                    username
                })
            }
        );


    alert(data.message);

    location.reload();
}


async function toggleBan(username) {

    const data =
        await api(
            "/api/toggle_ban",
            {
                method: "POST",
                body: JSON.stringify({
                    username
                })
            }
        );


    alert(data.message);

    location.reload();
}


async function editUser(
    oldUsername,
    oldPassword
) {

    const newUsername =
        prompt(
            "New username:",
            oldUsername
        );

    if(newUsername === null) {
        return;
    }


    const newPassword =
        prompt(
            "New password:",
            ""
        );

    if(newPassword === null) {
        return;
    }


    if(!newUsername.trim()) {

        alert(
            "Username cannot be empty."
        );

        return;
    }


    if(!newPassword.trim()) {

        alert(
            "Password cannot be empty."
        );

        return;
    }


    const data =
        await api(
            "/api/edit_user",
            {
                method: "POST",
                body: JSON.stringify({
                    old_username:
                        oldUsername,
                    new_username:
                        newUsername.trim(),
                    new_password:
                        newPassword.trim()
                })
            }
        );


    alert(data.message);

    location.reload();
}

</script>

</body>
</html>
"""


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return render_template_string(
        LANDING
    )


# ============================================================
# LOGIN
# ============================================================

@app.route("/login")
def login():
    return render_template_string(
        LOGIN,
        google_enabled=google is not None
    )


# ============================================================
# GOOGLE AUTH
# ============================================================

@app.route("/auth/google")
@rate_limit(5, 60)
def auth_google():

    if google is None:
        return redirect("/login")

    redirect_uri = (
        request.url_root.rstrip("/")
        + "/auth/callback"
    )

    return google.authorize_redirect(
        redirect_uri
    )


@app.route("/auth/callback")
@rate_limit(10, 60)
def callback():

    if google is None:
        return redirect("/login")

    try:

        token = (
            google.authorize_access_token()
        )

        user = (
            token.get("userinfo")
        )

        if not user:

            response = google.get(
                "https://openidconnect.googleapis.com/v1/userinfo"
            )

            user = response.json()

        email = (
            user.get("email")
            if user
            else None
        )

        if not email:
            return redirect("/login")

        session.clear()

        session["user"] = {
            "email": email,
            "name": user.get(
                "name",
                email.split("@")[0]
            ),
            "picture": user.get(
                "picture",
                ""
            )
        }

        session.permanent = True

        return redirect("/dashboard")

    except Exception:
        return redirect("/login")


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    email = current_email()

    if not email:
        return redirect("/login")


    paid = is_paid(email)

    limit_text = (
        "Unlimited"
        if paid
        else str(FREE_USER_LIMIT)
    )

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


    apps = db(
        """
        SELECT *
        FROM apps
        WHERE owner_email=?
        ORDER BY id DESC
        """,
        (email,),
        fetch=True
    )


    # --------------------------------------------------------
    # APP OPTIONS
    # --------------------------------------------------------

    if not apps:

        app_options = (
            "<option value=''>"
            "No Applications"
            "</option>"
        )

        active_token = (
            "Create an application first"
        )

        app_list_html = """
        <div class="
            text-center
            py-12
            text-zinc-600
            text-xs
        ">
            No applications created yet.
        </div>
        """

    else:

        app_options = ""

        for app_row in apps:

            app_options += (
                "<option value='"
                + escape_js(app_row["token"])
                + "'>"
                + escape_js(app_row["name"])
                + "</option>"
            )


        active_token = apps[0]["token"]

        app_list_html = ""

        for app_row in apps:

            token = app_row["token"]

            app_list_html += f"""
            <div class="
                flex flex-col md:flex-row
                md:items-center
                justify-between
                gap-4
                bg-black/60
                border border-white/10
                rounded-xl
                p-4
                mb-3
            ">

                <div class="min-w-0">

                    <p class="font-black text-sm">
                        {escape_js(app_row["name"])}
                    </p>

                    <p class="
                        mt-1
                        text-[9px]
                        font-mono
                        text-zinc-600
                        truncate
                    ">
                        {escape_js(token)}
                    </p>

                </div>

                <button
                    onclick="deleteApp('{escape_js(token)}')"
                    class="
                        px-4 py-2
                        rounded-lg
                        bg-red-500/10
                        border border-red-500/20
                        text-red-300
                        text-[9px]
                        font-black
                    "
                >
                    DELETE
                </button>

            </div>
            """


    # --------------------------------------------------------
    # KEYS
    # --------------------------------------------------------

    keys = db(
        """
        SELECT k.*
        FROM keys k
        JOIN apps a ON a.token=k.app_token
        WHERE a.owner_email=?
        ORDER BY k.id DESC
        """,
        (email,),
        fetch=True
    )


    if keys:

        keys_list_html = ""

        for key in keys:

            if key["status"] == "unused":
                color = "text-green-400"
            else:
                color = "text-red-400"

            keys_list_html += f"""
            <div class="
                flex justify-between
                items-center
                gap-3
                bg-black/60
                border border-white/10
                rounded-xl
                px-4 py-3
                mb-2
            ">

                <span class="
                    font-mono
                    text-[10px]
                    text-zinc-300
                ">
                    {escape_js(key["key_text"])}
                </span>

                <span class="
                    {color}
                    text-[9px]
                    font-black
                ">
                    ● {escape_js(key["status"]).upper()}
                </span>

            </div>
            """

    else:

        keys_list_html = """
        <div class="
            text-center
            py-12
            text-zinc-600
            text-xs
        ">
            No license keys yet.
        </div>
        """


    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    tool_users = db(
        """
        SELECT tu.*
        FROM tool_users tu
        JOIN apps a ON a.token=tu.app_token
        WHERE a.owner_email=?
        ORDER BY tu.id DESC
        """,
        (email,),
        fetch=True
    )


    tool_user_count = len(
        tool_users
    )


    if paid:

        percent = 0
        if tool_user_count:
            percent = 35

    else:

        percent = min(
            int(
                tool_user_count /
                FREE_USER_LIMIT *
                100
            ),
            100
        )


    if not tool_users:

        tool_users_list_html = """
        <div class="
            text-center
            py-12
            text-zinc-600
            text-xs
        ">
            No registered users.
        </div>
        """

    else:

        tool_users_list_html = ""

        for user_row in tool_users:

            hwid = (
                user_row["hwid"]
                or "Not Bound"
            )

            hwid_short = (
                hwid[:20] + "..."
                if len(hwid) > 20
                else hwid
            )

            status = user_row["status"]

            if status == "active":
                status_color = "text-green-400"
                action = "BAN"
            else:
                status_color = "text-red-400"
                action = "UNBAN"


            username_js = escape_js(
                user_row["username"]
            )

            password_js = escape_js(
                user_row["password"]
            )


            tool_users_list_html += f"""
            <div class="
                bg-black/60
                border border-white/10
                rounded-xl
                p-4
                mb-3
            ">

                <div class="
                    flex flex-col
                    xl:flex-row
                    xl:items-center
                    justify-between
                    gap-4
                ">

                    <div>

                        <p class="
                            text-sm
                            font-black
                        ">
                            {escape_js(user_row["username"])}
                        </p>

                        <p class="
                            mt-1
                            text-[9px]
                            text-zinc-600
                            font-mono
                        ">
                            HWID:
                            {escape_js(hwid_short)}
                        </p>

                        <p class="
                            text-[9px]
                            {status_color}
                            font-black
                        ">
                            {escape_js(status).upper()}
                        </p>

                    </div>


                    <div class="
                        flex
                        flex-wrap
                        gap-2
                    ">

                        <button
                            onclick="editUser(
                                '{username_js}',
                                '{password_js}'
                            )"
                            class="
                                px-3 py-2
                                rounded-lg
                                bg-blue-500/10
                                border border-blue-500/20
                                text-blue-300
                                text-[9px]
                                font-black
                            "
                        >
                            EDIT
                        </button>


                        <button
                            onclick="toggleBan(
                                '{username_js}'
                            )"
                            class="
                                px-3 py-2
                                rounded-lg
                                bg-yellow-500/10
                                border border-yellow-500/20
                                text-yellow-300
                                text-[9px]
                                font-black
                            "
                        >
                            {action}
                        </button>


                        <button
                            onclick="resetHwid(
                                '{username_js}'
                            )"
                            class="
                                px-3 py-2
                                rounded-lg
                                bg-white/5
                                border border-white/10
                                text-zinc-300
                                text-[9px]
                                font-black
                            "
                        >
                            RESET HWID
                        </button>


                        <button
                            onclick="deleteUser(
                                '{username_js}'
                            )"
                            class="
                                px-3 py-2
                                rounded-lg
                                bg-red-500/10
                                border border-red-500/20
                                text-red-300
                                text-[9px]
                                font-black
                            "
                        >
                            DELETE
                        </button>

                    </div>

                </div>

            </div>
            """


    html = (
        DASHBOARD_HTML

        .replace(
            "{{name}}",
            escape_js(
                session["user"].get(
                    "name",
                    "User"
                )
            )
        )

        .replace(
            "{{email}}",
            escape_js(email)
        )

        .replace(
            "{{app_options}}",
            app_options
        )

        .replace(
            "{{active_token}}",
            escape_js(active_token)
        )

        .replace(
            "{{app_list_html}}",
            app_list_html
        )

        .replace(
            "{{keys_list_html}}",
            keys_list_html
        )

        .replace(
            "{{tool_user_count}}",
            str(tool_user_count)
        )

        .replace(
            "{{limit_text}}",
            limit_text
        )

        .replace(
            "{{plan_text}}",
            plan_text
        )

        .replace(
            "{{plan_color}}",
            plan_color
        )

        .replace(
            "{{percent}}",
            str(percent)
        )

        .replace(
            "{{tool_users_list_html}}",
            tool_users_list_html
        )
    )


    return render_template_string(
        html
    )


# ============================================================
# CREATE APP
# ============================================================

@app.route(
    "/api/create_app",
    methods=["POST"]
)
@rate_limit(15, 60)
def api_create_app():

    email = current_email()

    if not email:
        return jsonify({
            "error": "Unauthorized"
        }), 401


    data = request.get_json(
        silent=True
    ) or {}

    name = str(
        data.get("name", "")
    ).strip()


    if not name:
        return jsonify({
            "error": "Application name required."
        }), 400


    if len(name) > 50:
        return jsonify({
            "error": "Application name too long."
        }), 400


    count = db(
        """
        SELECT COUNT(*)
        FROM apps
        WHERE owner_email=?
        """,
        (email,),
        fetch=True,
        one=True
    )[0]


    if not is_paid(email) and count >= FREE_APP_LIMIT:

        return jsonify({
            "error":
                "Free plan allows maximum "
                "2 applications."
        }), 403


    token = generate_app_token()


    try:

        db(
            """
            INSERT INTO apps
            (name, token, owner_email, created_at)
            VALUES (?,?,?,?)
            """,
            (
                name,
                token,
                email,
                datetime.utcnow().isoformat()
            )
        )

    except sqlite3.IntegrityError:

        return jsonify({
            "error":
                "Could not create application."
        }), 500


    return jsonify({
        "message":
            "Application created.",
        "token":
            token
    })


# ============================================================
# DELETE APP
# ============================================================

@app.route(
    "/api/delete_app",
    methods=["POST"]
)
@rate_limit(10, 60)
def api_delete_app():

    email = current_email()

    if not email:
        return jsonify({
            "error": "Unauthorized"
        }), 401


    data = request.get_json(
        silent=True
    ) or {}

    token = data.get("token")


    if not token:
        return jsonify({
            "error": "Token required."
        }), 400


    if not owns_app(email, token):

        return jsonify({
            "error":
                "Application not found."
        }), 404


    con = get_db()

    try:

        cur = con.cursor()

        cur.execute(
            "DELETE FROM tool_users WHERE app_token=?",
            (token,)
        )

        cur.execute(
            "DELETE FROM keys WHERE app_token=?",
            (token,)
        )

        cur.execute(
            "DELETE FROM users WHERE app_token=?",
            (token,)
        )

        cur.execute(
            "DELETE FROM apps WHERE token=?",
            (token,)
        )

        con.commit()

    finally:
        con.close()


    return jsonify({
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
@rate_limit(10, 60)
def api_create_user():

    email = current_email()

    if not email:
        return jsonify({
            "message": "Unauthorized"
        }), 401


    data = request.get_json(
        silent=True
    ) or {}

    username = str(
        data.get("username", "")
    ).strip()

    password = str(
        data.get("password", "")
    ).strip()

    token = str(
        data.get("app_token", "")
    ).strip()


    if not username or not password or not token:

        return jsonify({
            "message":
                "All fields are required."
        }), 400


    if len(username) < 3:

        return jsonify({
            "message":
                "Username must contain at least 3 characters."
        }), 400


    if len(username) > 32:

        return jsonify({
            "message":
                "Username too long."
        }), 400


    if len(password) < 4:

        return jsonify({
            "message":
                "Password must contain at least 4 characters."
        }), 400


    if not owns_app(email, token):

        return jsonify({
            "message":
                "Invalid application."
        }), 403


    if limit_reached(email):

        return jsonify({
            "message":
                "Plan user/key limit reached."
        }), 403


    password_hash = generate_password_hash(
        password
    )


    try:

        db(
            """
            INSERT INTO tool_users
            (username,password,app_token,status,hwid,created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                username,
                password_hash,
                token,
                "active",
                None,
                datetime.utcnow().isoformat()
            )
        )

    except sqlite3.IntegrityError:

        return jsonify({
            "message":
                "Username already exists."
        }), 409


    return jsonify({
        "message":
            f"User created: {username}"
    })


# ============================================================
# DELETE USER
# ============================================================

@app.route(
    "/api/delete_user",
    methods=["POST"]
)
@rate_limit(10, 60)
def api_delete_user():

    email = current_email()

    if not email:
        return jsonify({
            "error": "Unauthorized"
        }), 401


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
            "error":
                "User not found."
        }), 404


    db(
        "DELETE FROM tool_users WHERE id=?",
        (user["id"],)
    )


    return jsonify({
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
@rate_limit(10, 60)
def api_reset_hwid():

    email = current_email()

    if not email:
        return jsonify({
            "error": "Unauthorized"
        }), 401


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
            "error":
                "User not found."
        }), 404


    db(
        """
        UPDATE tool_users
        SET hwid=NULL, status='active'
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

@app.route(
    "/api/toggle_ban",
    methods=["POST"]
)
@rate_limit(10, 60)
def api_toggle_ban():

    email = current_email()

    if not email:
        return jsonify({
            "error": "Unauthorized"
        }), 401


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
            "error":
                "User not found."
        }), 404


    new_status = (
        "banned"
        if user["status"] == "active"
        else "active"
    )


    db(
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
            f"{username} -> {new_status.upper()}"
    })


# ============================================================
# EDIT USER
# ============================================================

@app.route(
    "/api/edit_user",
    methods=["POST"]
)
@rate_limit(10, 60)
def api_edit_user():

    email = current_email()

    if not email:
        return jsonify({
            "error": "Unauthorized"
        }), 401


    data = request.get_json(
        silent=True
    ) or {}

    old_username = str(
        data.get("old_username", "")
    ).strip()

    new_username = str(
        data.get("new_username", "")
    ).strip()

    new_password = str(
        data.get("new_password", "")
    ).strip()


    if not old_username:
        return jsonify({
            "message":
                "Old username required."
        }), 400


    if not new_username:
        return jsonify({
            "message":
                "New username required."
        }), 400


    if not new_password:
        return jsonify({
            "message":
                "New password required."
        }), 400


    user = get_owned_user(
        email,
        old_username
    )

    if not user:

        return jsonify({
            "message":
                "User not found."
        }), 404


    password_hash = generate_password_hash(
        new_password
    )


    try:

        db(
            """
            UPDATE tool_users
            SET username=?, password=?
            WHERE id=?
            """,
            (
                new_username,
                password_hash,
                user["id"]
            )
        )

    except sqlite3.IntegrityError:

        return jsonify({
            "message":
                "Username already exists."
        }), 409


    return jsonify({
        "message":
            f"Updated {old_username}."
    })


# ============================================================
# AUTH LOGIN API
# ============================================================

@app.route(
    "/api/auth_login",
    methods=["POST"]
)
@rate_limit(10, 60)
def api_auth_login():

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


    # --------------------------------------------------------
    # APP TOKEN CHECK
    # --------------------------------------------------------

    app_row = db(
        """
        SELECT id
        FROM apps
        WHERE token=?
        """,
        (token,),
        fetch=True,
        one=True
    )


    if not app_row:

        return jsonify({
            "status": "invalid",
            "message":
                "Invalid application token."
        }), 401


    # --------------------------------------------------------
    # SIGNATURE CHECK
    # --------------------------------------------------------

    expected_sig = hashlib.sha256(
        f"{username}:{hwid}:{token}".encode()
    ).hexdigest()


    if not secrets.compare_digest(
        client_sig,
        expected_sig
    ):

        return jsonify({
            "status": "tampered",
            "message":
                "Invalid request signature."
        }), 403


    # --------------------------------------------------------
    # USER LOOKUP
    # --------------------------------------------------------

    user = db(
        """
        SELECT *
        FROM tool_users
        WHERE username=? AND app_token=?
        """,
        (
            username,
            token
        ),
        fetch=True,
        one=True
    )


    if not user:

        return jsonify({
            "status": "invalid",
            "message":
                "Incorrect credentials."
        }), 401


    # --------------------------------------------------------
    # PASSWORD CHECK
    # --------------------------------------------------------

    password_ok = check_password_hash(
        user["password"],
        password
    )


    # Backward compatibility for old plaintext users.
    if not password_ok and user["password"] == password:

        password_ok = True

        db(
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


    if not password_ok:

        return jsonify({
            "status": "invalid",
            "message":
                "Incorrect credentials."
        }), 401


    # --------------------------------------------------------
    # BAN
    # --------------------------------------------------------

    if user["status"] == "banned":

        return jsonify({
            "status": "banned",
            "message":
                "Account suspended."
        }), 403


    # --------------------------------------------------------
    # HWID BIND
    # --------------------------------------------------------

    stored_hwid = user["hwid"]


    if not stored_hwid:

        db(
            """
            UPDATE tool_users
            SET hwid=?, status='active'
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


    # --------------------------------------------------------
    # HWID MATCH
    # --------------------------------------------------------

    if secrets.compare_digest(
        stored_hwid,
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
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith("/api/"):

        return jsonify({
            "error":
                "Endpoint not found."
        }), 404

    return redirect("/")


@app.errorhandler(500)
def server_error(error):

    if request.path.startswith("/api/"):

        return jsonify({
            "error":
                "Internal server error."
        }), 500

    return """
    <html>
    <body style="
        background:#020308;
        color:white;
        font-family:Arial;
        display:flex;
        align-items:center;
        justify-content:center;
        height:100vh;
    ">
        <h2>HSL CORP — Internal Server Error</h2>
    </body>
    </html>
    """, 500


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