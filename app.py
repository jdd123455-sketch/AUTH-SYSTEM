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


# ============================================================
# HSL CORP AUTH PANEL
# PERFORMANCE OPTIMIZED EDITION
# ============================================================

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "hsl_corp_ultra_secure_key_2026_x89_production_ready"
)

# ------------------------------------------------------------
# SESSION / SECURITY
# ------------------------------------------------------------

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

PAID_USERS = {
    "js7876839939@gmail.com"
}

oauth = OAuth(app)

google = oauth.register(
    name="google",
    server_metadata_url=(
        "https://accounts.google.com/.well-known/"
        "openid-configuration"
    ),
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    client_kwargs={
        "scope": "openid email profile"
    },
)


# ============================================================
# RATE LIMIT
# ============================================================

REQUEST_HISTORY = {}

def rate_limit(max_requests=10, window_seconds=60):
    def decorator(func):

        @wraps(func)
        def wrapped(*args, **kwargs):

            ip = request.headers.get(
                "X-Forwarded-For",
                request.remote_addr or "unknown"
            ).split(",")[0].strip()

            now = time.time()

            history = REQUEST_HISTORY.get(ip, [])

            history = [
                timestamp
                for timestamp in history
                if now - timestamp < window_seconds
            ]

            if len(history) >= max_requests:
                REQUEST_HISTORY[ip] = history

                return jsonify({
                    "status": "rate_limited",
                    "message": (
                        "Too many attempts. "
                        "Request blocked due to security policies."
                    )
                }), 429

            history.append(now)

            REQUEST_HISTORY[ip] = history

            return func(*args, **kwargs)

        return wrapped

    return decorator


# ============================================================
# SECURITY HEADERS
# ============================================================

@app.after_request
def apply_security_headers(response):

    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = (
        "strict-origin-when-cross-origin"
    )

    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )

    response.headers["Cache-Control"] = (
        "no-store, max-age=0"
    )

    return response


# ============================================================
# DATABASE
# ============================================================

DB_FILE = "hsl.db"


def init_db():

    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS apps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            owner_email TEXT NOT NULL,
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

    con = sqlite3.connect(DB_FILE)

    try:
        cur = con.cursor()
        cur.execute(query, params)

        data = cur.fetchall() if fetch else None

        con.commit()

        return data

    finally:
        con.close()


# ============================================================
# PERFORMANCE OPTIMIZED UI
# ============================================================

COMMON_HEAD = r"""
<script src="https://cdn.tailwindcss.com"></script>

<style>

:root {
    --cyan: #00f6ff;
    --blue: #3b82f6;
    --violet: #7c3aed;
    --danger: #ff1744;
    --bg: #03050b;
}

/* =========================================================
   BASIC
   ========================================================= */

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
            circle at 50% -10%,
            rgba(0,246,255,.10),
            transparent 32%
        ),
        radial-gradient(
            circle at 100% 100%,
            rgba(124,58,237,.07),
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
        Roboto,
        sans-serif;

    letter-spacing: .01em;

    cursor: none;
}

::selection {
    background: rgba(0,246,255,.25);
    color: white;
}

::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}

::-webkit-scrollbar-track {
    background: #02040a;
}

::-webkit-scrollbar-thumb {
    background: #00b9c5;
    border-radius: 999px;
}


/* =========================================================
   BACKGROUND CANVAS
   ========================================================= */

#c {
    position: fixed;
    inset: 0;

    width: 100%;
    height: 100%;

    z-index: 0;

    pointer-events: none;

    opacity: .72;
}


/* =========================================================
   LIGHT AMBIENT
   ========================================================= */

.ambient-pulse {
    position: fixed;
    inset: -10%;

    z-index: 0;
    pointer-events: none;

    background:
        radial-gradient(
            circle at 15% 20%,
            rgba(0,246,255,.045),
            transparent 20%
        ),
        radial-gradient(
            circle at 85% 30%,
            rgba(124,58,237,.045),
            transparent 22%
        );

    animation: ambientDrift 16s ease-in-out infinite alternate;

    will-change: transform;
}

@keyframes ambientDrift {

    0% {
        transform: translate3d(-1%, 0, 0);
    }

    100% {
        transform: translate3d(1%, -1%, 0);
    }
}


/* =========================================================
   GRID
   ========================================================= */

body::before {
    content: "";

    position: fixed;
    inset: 0;

    z-index: 1;

    pointer-events: none;

    background:
        linear-gradient(
            rgba(255,255,255,.012) 1px,
            transparent 1px
        ),
        linear-gradient(
            90deg,
            rgba(255,255,255,.012) 1px,
            transparent 1px
        );

    background-size: 50px 50px;

    opacity: .65;
}


/* =========================================================
   VIGNETTE
   ========================================================= */

.hud-vignette {
    position: fixed;
    inset: 0;

    z-index: 3;

    pointer-events: none;

    box-shadow:
        inset 0 0 100px rgba(0,0,0,.72);
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
            rgba(12,17,30,.94),
            rgba(3,7,15,.90)
        );

    border: 1px solid rgba(0,246,255,.15);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.035),
        0 12px 35px rgba(0,0,0,.30);
}


/*
   IMPORTANT:
   backdrop-filter is expensive.
   We use a very small blur instead of huge 24px blur.
*/

.glass-card {
    position: relative;

    overflow: hidden;

    background:
        linear-gradient(
            145deg,
            rgba(12,17,30,.94),
            rgba(4,7,14,.90)
        );

    border: 1px solid rgba(0,246,255,.11);

    transition:
        transform .18s ease,
        border-color .18s ease,
        box-shadow .18s ease;

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.025),
        0 8px 30px rgba(0,0,0,.25);
}

.glass-card:hover {

    transform: translateY(-2px);

    border-color: rgba(0,246,255,.32);

    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.04),
        0 12px 35px rgba(0,0,0,.35),
        0 0 20px rgba(0,246,255,.07);
}


/* =========================================================
   PANEL LIGHT
   ========================================================= */

.glass::before,
.glass-card::before {

    content: "";

    position: absolute;

    inset: 0;

    pointer-events: none;

    background:
        linear-gradient(
            120deg,
            rgba(0,246,255,.025),
            transparent 35%,
            transparent 70%,
            rgba(124,58,237,.025)
        );
}


/* =========================================================
   INPUT
   ========================================================= */

input,
select {

    transition:
        border-color .15s ease,
        box-shadow .15s ease;
}

input:focus,
select:focus {

    border-color: rgba(0,246,255,.60) !important;

    box-shadow:
        0 0 0 2px rgba(0,246,255,.05),
        0 0 12px rgba(0,246,255,.08);
}


/* =========================================================
   BUTTON
   ========================================================= */

button,
a {

    transition:
        transform .15s ease,
        filter .15s ease,
        border-color .15s ease,
        box-shadow .15s ease;
}

button:hover,
a:hover {
    filter: brightness(1.06);
}

button:active,
a:active {
    transform: scale(.985);
}


/* =========================================================
   GRADIENT
   ========================================================= */

.bg-gradient-to-r {

    background-size: 160% 100%;

    animation:
        gradientShift 7s ease infinite;
}

@keyframes gradientShift {

    0%,
    100% {
        background-position: 0% 50%;
    }

    50% {
        background-position: 100% 50%;
    }
}


/* =========================================================
   ACTIVE SIDEBAR
   ========================================================= */

.side-active {

    position: relative;

    overflow: hidden;

    background:
        linear-gradient(
            90deg,
            rgba(0,246,255,.12),
            rgba(124,58,237,.05)
        ) !important;

    border: 1px solid rgba(0,246,255,.34) !important;

    color: #67f7ff !important;

    font-weight: 800;

    box-shadow:
        inset 2px 0 0 var(--cyan);
}

.side-active::after {

    content: "";

    position: absolute;

    top: 0;
    right: 0;

    width: 2px;
    height: 100%;

    background: var(--cyan);

    box-shadow:
        0 0 8px var(--cyan);
}


/* =========================================================
   CURSOR
   ========================================================= */

#cursor-dot {

    position: fixed;

    width: 6px;
    height: 6px;

    left: 0;
    top: 0;

    border-radius: 50%;

    pointer-events: none;

    z-index: 9999;

    background: var(--cyan);

    box-shadow:
        0 0 7px var(--cyan),
        0 0 14px rgba(0,246,255,.55);

    transform:
        translate3d(-50%, -50%, 0);

    will-change:
        transform;
}


#cursor-crosshair {

    position: fixed;

    width: 30px;
    height: 30px;

    left: 0;
    top: 0;

    border:
        1px solid rgba(0,246,255,.65);

    border-radius: 50%;

    pointer-events: none;

    z-index: 9998;

    transform:
        translate3d(-50%, -50%, 0);

    box-shadow:
        0 0 10px rgba(0,246,255,.10);

    will-change:
        transform;
}


/* Crosshair */

#cursor-crosshair::before {

    content: "";

    position: absolute;

    left: -6px;
    top: 50%;

    width: 42px;
    height: 1px;

    background:
        linear-gradient(
            90deg,
            transparent,
            rgba(0,246,255,.75),
            transparent
        );

    transform:
        translateY(-50%);
}

#cursor-crosshair::after {

    content: "";

    position: absolute;

    top: -6px;
    left: 50%;

    height: 42px;
    width: 1px;

    background:
        linear-gradient(
            180deg,
            transparent,
            rgba(0,246,255,.75),
            transparent
        );

    transform:
        translateX(-50%);
}


/* =========================================================
   ORBIT
   ========================================================= */

#cursor-orbit {

    position: fixed;

    width: 48px;
    height: 48px;

    left: 0;
    top: 0;

    border:
        1px dashed rgba(124,58,237,.58);

    border-radius: 50%;

    pointer-events: none;

    z-index: 9997;

    transform:
        translate3d(-50%, -50%, 0);

    animation:
        spinOrbit 7s linear infinite;

    will-change:
        transform;
}

@keyframes spinOrbit {

    from {
        transform:
            translate3d(-50%, -50%, 0)
            rotate(0deg);
    }

    to {
        transform:
            translate3d(-50%, -50%, 0)
            rotate(360deg);
    }
}


/* =========================================================
   MOBILE
   ========================================================= */

@media (max-width: 768px) {

    body {
        cursor: auto;
    }

    #cursor-dot,
    #cursor-crosshair,
    #cursor-orbit {
        display: none;
    }

    #c {
        opacity: .35;
    }

}


/* =========================================================
   LOW POWER / REDUCED MOTION
   ========================================================= */

@media (prefers-reduced-motion: reduce) {

    *,
    *::before,
    *::after {

        animation-duration: .01ms !important;

        animation-iteration-count: 1 !important;

        transition-duration: .01ms !important;
    }

    #c {
        display: none;
    }
}

</style>
"""


# ============================================================
# OPTIMIZED CURSOR + PARTICLES
# ============================================================

CURSOR_SCRIPT = r"""
<div id="cursor-dot"></div>
<div id="cursor-crosshair"></div>
<div id="cursor-orbit"></div>

<script>

(() => {

    "use strict";

    const dot = document.getElementById("cursor-dot");
    const cross = document.getElementById("cursor-crosshair");
    const orbit = document.getElementById("cursor-orbit");

    const canvas = document.getElementById("c");

    if (!canvas) return;

    const ctx = canvas.getContext("2d", {
        alpha: true
    });

    /*
       -------------------------------------------------------
       CURSOR
       -------------------------------------------------------
    */

    let mouseX = window.innerWidth / 2;
    let mouseY = window.innerHeight / 2;

    let cursorX = mouseX;
    let cursorY = mouseY;

    let running = true;

    window.addEventListener(
        "mousemove",
        (event) => {

            mouseX = event.clientX;
            mouseY = event.clientY;

            /*
               Dot follows immediately.
               No layout calculations.
            */

            dot.style.transform =
                `translate3d(${mouseX}px, ${mouseY}px, 0) translate(-50%, -50%)`;

        },
        {
            passive: true
        }
    );


    /*
       Smooth crosshair.
    */

    function cursorLoop() {

        if (!running) return;

        cursorX +=
            (mouseX - cursorX) * 0.20;

        cursorY +=
            (mouseY - cursorY) * 0.20;

        const transform =
            `translate3d(${cursorX}px, ${cursorY}px, 0) translate(-50%, -50%)`;

        cross.style.transform = transform;
        orbit.style.transform = transform;

        requestAnimationFrame(cursorLoop);
    }

    requestAnimationFrame(cursorLoop);


    /*
       -------------------------------------------------------
       PARTICLE SYSTEM
       -------------------------------------------------------

       Old version:
       210+ particles
       + mouse particles
       + every particle against every other particle

       That can become expensive.

       New version:
       ~65 particles
       limited connections
       no unlimited mouse particle creation
    */

    let width = window.innerWidth;
    let height = window.innerHeight;

    let particles = [];

    const isMobile =
        window.innerWidth <= 768;

    const particleCount =
        isMobile ? 20 : 62;

    function resizeCanvas() {

        width = window.innerWidth;
        height = window.innerHeight;

        const dpr =
            Math.min(window.devicePixelRatio || 1, 1.5);

        canvas.width =
            Math.floor(width * dpr);

        canvas.height =
            Math.floor(height * dpr);

        canvas.style.width =
            width + "px";

        canvas.style.height =
            height + "px";

        ctx.setTransform(
            dpr,
            0,
            0,
            dpr,
            0,
            0
        );
    }

    resizeCanvas();

    window.addEventListener(
        "resize",
        resizeCanvas,
        {
            passive: true
        }
    );


    function createParticle() {

        return {

            x: Math.random() * width,

            y: Math.random() * height,

            size:
                Math.random() * 1.25 + .35,

            speed:
                Math.random() * .30 + .08,

            drift:
                (Math.random() - .5) * .12,

            alpha:
                Math.random() * .45 + .15,

            phase:
                Math.random() * Math.PI * 2
        };
    }


    for (
        let i = 0;
        i < particleCount;
        i++
    ) {

        particles.push(
            createParticle()
        );
    }


    /*
       Mouse trail particles.
       Only occasionally generated.
    */

    let lastTrailTime = 0;

    window.addEventListener(
        "mousemove",
        (event) => {

            const now =
                performance.now();

            if (
                now - lastTrailTime < 55
            ) {
                return;
            }

            lastTrailTime = now;

            if (
                particles.length >=
                particleCount + 10
            ) {
                return;
            }

            particles.push({

                x: event.clientX,

                y: event.clientY,

                size:
                    Math.random() * 1.4 + .45,

                speed:
                    Math.random() * .5 + .2,

                drift:
                    (Math.random() - .5) * .4,

                alpha: .65,

                phase:
                    Math.random() * 6.28,

                trail: true
            });

        },
        {
            passive: true
        }
    );


    let lastFrame = 0;

    function animate(now) {

        /*
           Cap animation around 60fps.
        */

        if (
            now - lastFrame < 16
        ) {

            requestAnimationFrame(
                animate
            );

            return;
        }

        lastFrame = now;

        ctx.clearRect(
            0,
            0,
            width,
            height
        );


        /*
           PARTICLES
        */

        for (
            let i = particles.length - 1;
            i >= 0;
            i--
        ) {

            const p =
                particles[i];

            p.y -= p.speed;

            p.x += p.drift;

            p.phase += .018;


            if (p.trail) {

                p.alpha -= .018;

                if (
                    p.alpha <= 0
                ) {

                    particles.splice(
                        i,
                        1
                    );

                    continue;
                }

            }


            if (p.y < -10) {

                p.y = height + 5;

                p.x =
                    Math.random() * width;
            }

            if (p.x < -10) {
                p.x = width + 10;
            }

            if (p.x > width + 10) {
                p.x = -10;
            }


            const size =
                Math.max(
                    .3,
                    p.size +
                    Math.sin(p.phase) * .25
                );


            ctx.beginPath();

            ctx.arc(
                p.x,
                p.y,
                size,
                0,
                Math.PI * 2
            );

            ctx.fillStyle =
                `rgba(34,211,238,${p.alpha})`;

            ctx.fill();
        }


        /*
           ----------------------------------------------------
           NETWORK LINES
           ----------------------------------------------------

           Only connect first ~35 particles.
           This removes the huge O(n²) cost.
        */

        const connectionLimit =
            Math.min(
                particles.length,
                isMobile ? 12 : 35
            );

        for (
            let i = 0;
            i < connectionLimit;
            i++
        ) {

            const a =
                particles[i];

            for (
                let j = i + 1;
                j < connectionLimit;
                j++
            ) {

                const b =
                    particles[j];

                const dx =
                    a.x - b.x;

                const dy =
                    a.y - b.y;

                const distSq =
                    dx * dx +
                    dy * dy;

                /*
                   90px distance.
                   No Math.sqrt unless necessary.
                */

                if (
                    distSq < 8100
                ) {

                    const dist =
                        Math.sqrt(distSq);

                    const alpha =
                        (1 - dist / 90) *
                        .065;

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

                    ctx.lineWidth =
                        .45;

                    ctx.stroke();
                }
            }
        }


        requestAnimationFrame(
            animate
        );
    }

    requestAnimationFrame(
        animate
    );


    /*
       Stop animation when tab is hidden.
       This saves CPU when user switches tabs.
    */

    document.addEventListener(
        "visibilitychange",
        () => {

            running =
                !document.hidden;

        }
    );

})();

</script>
"""


# ============================================================
# LANDING PAGE
# ============================================================

LANDING = """
<!DOCTYPE html>

<html>

<head>
""" + COMMON_HEAD + """
</head>

<body
    class="
        text-white
        overflow-x-hidden
        relative
        min-h-screen
        flex
        flex-col
        justify-between
    "
>

<canvas id="c"></canvas>

<div class="ambient-pulse"></div>

<div class="hud-vignette"></div>


<!-- =======================================================
     NAVBAR
======================================================= -->

<nav
    class="
        relative
        z-10
        flex
        justify-between
        items-center
        px-10
        py-5
        bg-black/70
        border-b
        border-cyan-400/10
    "
>

    <div class="flex items-center gap-3">

        <div
            class="
                w-10
                h-10
                bg-gradient-to-r
                from-cyan-400
                to-indigo-600
                rounded-xl
                flex
                items-center
                justify-center
                shadow-[0_0_14px_#22d3ee]
            "
        >
            👾
        </div>

        <div>

            <p class="font-black text-sm tracking-wider">
                HSL CORP
            </p>

            <p
                class="
                    text-[9px]
                    text-cyan-400
                    font-bold
                    tracking-widest
                "
            >
                SECURE AUTHENTICATION SYSTEM
            </p>

        </div>

    </div>


    <div class="flex gap-3">

        <a
            href="/login"
            class="
                bg-zinc-900
                border
                border-zinc-700
                px-6
                py-2.5
                rounded-full
                text-xs
                font-semibold
            "
        >
            Sign In
        </a>

        <a
            href="/dashboard"
            class="
                bg-gradient-to-r
                from-cyan-400
                to-indigo-600
                px-6
                py-2.5
                rounded-full
                text-xs
                font-bold
                shadow-[0_0_15px_rgba(34,211,238,.35)]
            "
        >
            Dashboard
        </a>

    </div>

</nav>


<!-- =======================================================
     HERO
======================================================= -->

<div
    class="
        relative
        z-10
        flex
        flex-col
        items-center
        text-center
        pt-20
        px-4
    "
>

    <div
        class="
            inline-flex
            items-center
            gap-2
            border
            border-cyan-500/25
            bg-cyan-500/5
            px-4
            py-1.5
            rounded-full
            text-xs
            text-cyan-300
            font-semibold
            mb-8
        "
    >
        <span>⚡</span>
        Next-Gen Secure Software Panel
    </div>


    <h1
        class="
            text-6xl
            md:text-7xl
            font-black
            bg-gradient-to-r
            from-cyan-300
            via-cyan-400
            to-indigo-500
            bg-clip-text
            text-transparent
            max-w-5xl
            leading-tight
        "
    >
        HSL CORP AUTH
    </h1>


    <p
        class="
            text-zinc-400
            mt-6
            font-medium
            text-lg
            max-w-2xl
        "
    >
        Hardware-Locked Licensing &
        Application Protection Infrastructure.
    </p>


    <a
        href="/login"
        class="
            bg-gradient-to-r
            from-cyan-400
            to-indigo-600
            hover:scale-105
            px-9
            py-4
            rounded-2xl
            text-sm
            font-bold
            shadow-[0_0_22px_rgba(34,211,238,.4)]
            mt-9
            flex
            items-center
            gap-2
        "
    >
        🚀 Get Started
    </a>

</div>


<!-- =======================================================
     FEATURES
======================================================= -->

<div
    class="
        relative
        z-10
        w-full
        max-w-6xl
        mx-auto
        px-6
        py-20
    "
>

    <div
        class="
            grid
            md:grid-cols-3
            gap-6
        "
    >

        <div
            class="
                glass-card
                rounded-2xl
                p-7
            "
        >

            <div
                class="
                    w-12
                    h-12
                    rounded-xl
                    bg-cyan-500/10
                    border
                    border-cyan-500/25
                    flex
                    items-center
                    justify-center
                    text-2xl
                    mb-4
                "
            >
                🔐
            </div>

            <h3
                class="
                    font-bold
                    text-lg
                    text-cyan-300
                "
            >
                Hardware-Locked Protection
            </h3>

            <p
                class="
                    text-xs
                    text-zinc-400
                    mt-2
                    leading-relaxed
                "
            >
                Bind application users to a hardware
                identifier and prevent unauthorized
                account sharing.
            </p>

        </div>


        <div
            class="
                glass-card
                rounded-2xl
                p-7
            "
        >

            <div
                class="
                    w-12
                    h-12
                    rounded-xl
                    bg-indigo-500/10
                    border
                    border-indigo-500/25
                    flex
                    items-center
                    justify-center
                    text-2xl
                    mb-4
                "
            >
                🛡️
            </div>

            <h3
                class="
                    font-bold
                    text-lg
                    text-indigo-300
                "
            >
                Hardened API
            </h3>

            <p
                class="
                    text-xs
                    text-zinc-400
                    mt-2
                    leading-relaxed
                "
            >
                API authentication with request
                validation, rate limiting and
                security headers.
            </p>

        </div>


        <div
            class="
                glass-card
                rounded-2xl
                p-7
            "
        >

            <div
                class="
                    w-12
                    h-12
                    rounded-xl
                    bg-cyan-500/10
                    border
                    border-cyan-500/25
                    flex
                    items-center
                    justify-center
                    text-2xl
                    mb-4
                "
            >
                ⚡
            </div>

            <h3
                class="
                    font-bold
                    text-lg
                    text-cyan-300
                "
            >
                Admin Console
            </h3>

            <p
                class="
                    text-xs
                    text-zinc-400
                    mt-2
                    leading-relaxed
                "
            >
                Manage applications, users, HWID
                bindings and account status from
                one dashboard.
            </p>

        </div>

    </div>

</div>


<footer
    class="
        relative
        z-10
        text-center
        py-6
        border-t
        border-white/5
        text-xs
        text-zinc-600
    "
>
    &copy; 2026 HSL CORP. All rights reserved.
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
""" + COMMON_HEAD + """
</head>

<body
    class="
        flex
        items-center
        justify-center
        h-screen
        overflow-hidden
        relative
    "
>

<canvas id="c"></canvas>

<div class="ambient-pulse"></div>

<div class="hud-vignette"></div>


<div
    class="
        relative
        z-10
        w-[420px]
        max-w-[92vw]
        glass
        rounded-[28px]
        p-9
        text-center
        shadow-[0_0_35px_rgba(34,211,238,.14)]
    "
>

    <div
        class="
            w-16
            h-16
            bg-gradient-to-r
            from-cyan-400
            to-indigo-600
            rounded-2xl
            mx-auto
            flex
            items-center
            justify-center
            shadow-[0_0_18px_#22d3ee]
        "
    >
        👾
    </div>


    <h1
        class="
            font-black
            text-2xl
            mt-5
            text-white
            bg-gradient-to-r
            from-cyan-300
            to-indigo-400
            bg-clip-text
            text-transparent
        "
    >
        HSL CORP
    </h1>


    <p class="text-xs text-zinc-400 mt-1">
        Sign in using verified OAuth
    </p>


    <a
        href="/auth/google"
        class="
            mt-8
            w-full
            bg-white
            hover:bg-zinc-100
            text-black
            rounded-xl
            py-3.5
            flex
            justify-center
            items-center
            gap-3
            font-bold
            text-sm
            shadow-lg
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

</div>


""" + CURSOR_SCRIPT + """

</body>
</html>
"""


# ============================================================
# DASHBOARD
# ============================================================

DASHBOARD_HTML = """
<!DOCTYPE html>

<html>

<head>

""" + COMMON_HEAD + """

</head>


<body
    class="
        flex
        h-screen
        text-white
        overflow-hidden
        relative
    "
>

<canvas id="c"></canvas>

<div class="ambient-pulse"></div>

<div class="hud-vignette"></div>


<!-- =======================================================
     SIDEBAR
======================================================= -->

<div
    class="
        w-[260px]
        bg-[#02040a]/95
        border-r
        border-cyan-400/10
        flex
        flex-col
        relative
        z-10
    "
>

    <div
        class="
            p-5
            flex
            items-center
            gap-3
            border-b
            border-white/10
        "
    >

        <div
            class="
                w-9
                h-9
                bg-gradient-to-r
                from-cyan-400
                to-indigo-600
                rounded-xl
                flex
                items-center
                justify-center
                shadow-[0_0_10px_#22d3ee]
            "
        >
            👾
        </div>


        <div>

            <p
                class="
                    font-black
                    text-sm
                    tracking-wide
                "
            >
                HSL CORP
            </p>

            <p
                class="
                    text-[9px]
                    text-cyan-400
                    font-bold
                "
            >
                Developer Console
            </p>

        </div>

    </div>


    <div
        class="
            p-3
            space-y-1
            text-xs
        "
        id="sidebar"
    >

        <button
            onclick="showTab('overview')"
            id="btn-overview"
            class="
                side-active
                w-full
                text-left
                rounded-xl
                px-4
                py-2.5
            "
        >
            🏠 Overview
        </button>


        <button
            onclick="showTab('applications')"
            id="btn-applications"
            class="
                w-full
                text-left
                text-zinc-400
                hover:text-white
                px-4
                py-2.5
            "
        >
            📦 Applications
        </button>


        <button
            onclick="showTab('tool_users')"
            id="btn-tool_users"
            class="
                w-full
                text-left
                text-zinc-400
                hover:text-white
                px-4
                py-2.5
            "
        >
            👤 Users
            ({{tool_user_count}}/{{limit_text}})
        </button>


        <button
            onclick="showTab('keys')"
            id="btn-keys"
            class="
                w-full
                text-left
                text-zinc-400
                hover:text-white
                px-4
                py-2.5
            "
        >
            🔑 License Keys
        </button>


        <button
            onclick="showTab('integrate')"
            id="btn-integrate"
            class="
                w-full
                text-left
                text-zinc-400
                hover:text-white
                px-4
                py-2.5
            "
        >
            🔌 Integration
        </button>


        <button
            onclick="showTab('billing')"
            id="btn-billing"
            class="
                w-full
                text-left
                text-zinc-400
                hover:text-white
                px-4
                py-2.5
            "
        >
            💎 Billing
        </button>

    </div>


    <div
        class="
            mt-auto
            p-4
            border-t
            border-white/10
            flex
            items-center
            gap-3
            bg-black/50
        "
    >

        <img
            src="https://ui-avatars.com/api/?name={{name}}&background=22d3ee&color=fff"
            class="
                w-8
                h-8
                rounded-full
                border
                border-cyan-400/30
            "
            alt="Avatar"
        >


        <div>

            <p
                class="
                    text-[11px]
                    font-bold
                    truncate
                    w-[110px]
                "
            >
                {{email}}
            </p>

            <p
                class="
                    text-[9px]
                    {{plan_color}}
                    font-bold
                "
            >
                {{plan_text}}
            </p>

        </div>


        <a
            href="/logout"
            class="
                ml-auto
                text-[11px]
                text-red-400
                hover:text-red-300
                font-semibold
            "
        >
            Logout
        </a>

    </div>

</div>


<!-- =======================================================
     MAIN
======================================================= -->

<div
    class="
        flex-1
        overflow-y-auto
        relative
        z-10
    "
>


    <div
        class="
            h-14
            bg-black/70
            border-b
            border-cyan-400/10
            flex
            items-center
            justify-between
            px-8
        "
    >

        <p
            class="
                text-xs
                font-semibold
                tracking-wider
                text-cyan-300
            "
        >
            HSL CONSOLE -
            {{plan_text}} PLAN
        </p>


        <button
            onclick="showTab('billing')"
            class="
                text-xs
                bg-gradient-to-r
                from-cyan-400
                to-indigo-600
                text-white
                px-5
                py-2
                rounded-full
                font-bold
            "
        >
            Upgrade
        </button>

    </div>


    <div class="p-8">


        <!-- =================================================
             OVERVIEW
        ================================================= -->

        <div id="tab-overview">

            <h1 class="text-2xl font-black">
                Dashboard Overview
            </h1>


            <div
                class="
                    mt-6
                    grid
                    grid-cols-[1.3fr_1fr_0.7fr]
                    gap-4
                "
            >


                <div
                    class="
                        glass-card
                        rounded-2xl
                        p-5
                    "
                >

                    <p
                        class="
                            text-[10px]
                            font-bold
                            text-cyan-400
                            tracking-wider
                        "
                    >
                        ACTIVE APPLICATION
                    </p>


                    <select
                        id="appSelect"
                        onchange="selectApp(this.value)"
                        class="
                            bg-black/80
                            border
                            border-white/20
                            rounded-xl
                            px-3
                            py-2.5
                            text-xs
                            mt-3
                            w-full
                            font-semibold
                            focus:outline-none
                        "
                    >
                        {{app_options}}
                    </select>

                </div>


                <div
                    class="
                        glass-card
                        rounded-2xl
                        p-5
                    "
                >

                    <p
                        class="
                            text-[10px]
                            font-bold
                            text-zinc-400
                            tracking-wider
                        "
                    >
                        MASTER APP TOKEN
                    </p>


                    <div
                        class="
                            mt-3
                            flex
                            justify-between
                            items-center
                            bg-black/80
                            rounded-xl
                            px-3
                            py-2
                            border
                            border-white/10
                        "
                    >

                        <p
                            id="tokenDisplay"
                            class="
                                text-xs
                                font-mono
                                text-zinc-300
                                truncate
                            "
                        >
                            {{active_token}}
                        </p>


                        <button
                            onclick="copyToken()"
                            class="
                                text-[10px]
                                bg-gradient-to-r
                                from-cyan-400
                                to-indigo-600
                                px-3
                                py-1.5
                                rounded-lg
                                font-bold
                            "
                        >
                            Copy
                        </button>

                    </div>

                </div>


                <div
                    class="
                        glass-card
                        rounded-2xl
                        p-5
                    "
                >

                    <p
                        class="
                            text-[10px]
                            font-bold
                            text-zinc-400
                            tracking-wider
                        "
                    >
                        PLAN LIMIT
                    </p>


                    <p
                        class="
                            text-xs
                            font-bold
                            mt-3
                        "
                    >
                        {{tool_user_count}}
                        /
                        {{limit_text}}
                        Used
                    </p>


                    <div
                        class="
                            w-full
                            bg-zinc-800
                            h-2
                            mt-3
                            rounded-full
                            overflow-hidden
                        "
                    >

                        <div
                            class="
                                bg-gradient-to-r
                                from-cyan-400
                                to-indigo-600
                                h-2
                                rounded-full
                            "
                            style="width:{{percent}}%"
                        ></div>

                    </div>

                </div>

            </div>


            <!-- CREATE USER -->

            <div
                class="
                    mt-6
                    glass-card
                    rounded-2xl
                    p-7
                "
            >

                <p
                    class="
                        text-base
                        font-bold
                        text-white
                    "
                >
                    + Create New Secure User
                </p>


                <div
                    class="
                        flex
                        gap-3
                        mt-4
                    "
                >

                    <input
                        id="newUsername"
                        placeholder="Username"
                        class="
                            flex-1
                            bg-black/80
                            border
                            border-white/15
                            rounded-xl
                            px-4
                            py-3
                            text-sm
                            focus:outline-none
                        "
                    >


                    <input
                        id="newPassword"
                        type="password"
                        placeholder="Password"
                        class="
                            flex-1
                            bg-black/80
                            border
                            border-white/15
                            rounded-xl
                            px-4
                            py-3
                            text-sm
                            focus:outline-none
                        "
                    >

                </div>


                <button
                    onclick="createUser()"
                    class="
                        mt-4
                        w-full
                        bg-gradient-to-r
                        from-cyan-400
                        to-indigo-600
                        py-3
                        rounded-xl
                        text-sm
                        font-bold
                        shadow-[0_0_15px_rgba(34,211,238,.25)]
                    "
                >
                    Create User
                </button>

            </div>

        </div>


        <!-- =================================================
             APPLICATIONS
        ================================================= -->

        <div
            id="tab-applications"
            class="hidden"
        >

            <h1 class="text-2xl font-black">
                Applications
            </h1>


            <div
                class="
                    glass-card
                    mt-6
                    rounded-2xl
                    p-7
                "
            >

                <div class="space-y-3 mb-6">
                    {{app_list_html}}
                </div>


                <div
                    class="
                        border-t
                        border-white/10
                        pt-5
                    "
                >

                    <p class="text-base font-bold">
                        + Create New App
                    </p>


                    <input
                        id="newAppName"
                        placeholder="App Name"
                        class="
                            mt-3
                            w-full
                            bg-black/80
                            border
                            border-white/15
                            rounded-xl
                            px-4
                            py-3
                            text-sm
                            focus:outline-none
                        "
                    >


                    <button
                        onclick="createApp()"
                        class="
                            mt-4
                            w-full
                            bg-gradient-to-r
                            from-cyan-400
                            to-indigo-600
                            py-3
                            rounded-xl
                            text-sm
                            font-bold
                        "
                    >
                        Create Application
                    </button>

                </div>

            </div>

        </div>


        <!-- =================================================
             USERS
        ================================================= -->

        <div
            id="tab-tool_users"
            class="hidden"
        >

            <h1 class="text-2xl font-black">
                Username / Pass Users
                ({{tool_user_count}}/{{limit_text}})
            </h1>


            <div
                class="
                    glass-card
                    mt-6
                    rounded-2xl
                    p-6
                "
            >

                <div
                    class="
                        space-y-3
                        text-xs
                        font-mono
                    "
                >
                    {{tool_users_list_html}}
                </div>

            </div>

        </div>


        <!-- =================================================
             KEYS
        ================================================= -->

        <div
            id="tab-keys"
            class="hidden"
        >

            <h1 class="text-2xl font-black">
                License Keys
            </h1>


            <div
                class="
                    glass-card
                    mt-6
                    rounded-2xl
                    p-6
                "
            >

                <div
                    class="
                        space-y-3
                        text-xs
                        font-mono
                    "
                >
                    {{keys_list_html}}
                </div>

            </div>

        </div>


        <!-- =================================================
             INTEGRATION
        ================================================= -->

        <div
            id="tab-integrate"
            class="hidden"
        >

            <h1 class="text-2xl font-black">
                Secure Client Integration
            </h1>


            <div
                class="
                    glass-card
                    mt-6
                    rounded-2xl
                    p-7
                "
            >

                <p
                    class="
                        text-xs
                        font-bold
                        text-cyan-300
                    "
                >
                    Request Verification Example
                </p>


                <pre
                    class="
                        mt-4
                        bg-black/90
                        border
                        border-white/10
                        rounded-xl
                        p-5
                        text-xs
                        font-mono
                        overflow-x-auto
                        text-green-400
                        leading-relaxed
                    "
>import requests
import hashlib

MY_APP_TOKEN = "{{active_token}}"

AUTH_URL = "https://YOUR-DOMAIN.com/api/auth_login"


def secure_login(username, password, hwid):

    raw_sig = f"{username}:{hwid}:{MY_APP_TOKEN}"

    sig = hashlib.sha256(
        raw_sig.encode()
    ).hexdigest()

    payload = {
        "username": username,
        "password": password,
        "hwid": hwid,
        "token": MY_APP_TOKEN,
        "sig": sig
    }

    response = requests.post(
        AUTH_URL,
        json=payload,
        timeout=10
    )

    return response.json()
</pre>

            </div>

        </div>


        <!-- =================================================
             BILLING
        ================================================= -->

        <div
            id="tab-billing"
            class="hidden"
        >

            <h1 class="text-2xl font-black">
                Billing / Plans
            </h1>


            <div
                class="
                    grid
                    grid-cols-2
                    gap-6
                    mt-6
                "
            >

                <div
                    class="
                        glass-card
                        rounded-2xl
                        p-7
                    "
                >

                    <p
                        class="
                            font-bold
                            text-sm
                            text-zinc-300
                        "
                    >
                        FREE PLAN
                    </p>


                    <p
                        class="
                            text-4xl
                            font-black
                            mt-2
                        "
                    >
                        ₹0
                    </p>


                    <p
                        class="
                            text-xs
                            text-zinc-400
                            mt-3
                            leading-relaxed
                        "
                    >
                        ✓ 10 Users / Keys<br>
                        ✓ 2 Applications<br>
                        ✓ HWID Lock
                    </p>


                    <p
                        class="
                            mt-6
                            text-xs
                            bg-zinc-800
                            rounded-full
                            px-4
                            py-1.5
                            inline-block
                            font-semibold
                        "
                    >
                        Current: {{plan_text}}
                    </p>

                </div>


                <div
                    class="
                        glass-card
                        rounded-2xl
                        p-7
                        border-cyan-400/40
                    "
                >

                    <p
                        class="
                            font-bold
                            text-sm
                            text-cyan-400
                        "
                    >
                        PRO UNLIMITED
                    </p>


                    <p
                        class="
                            text-4xl
                            font-black
                            mt-2
                        "
                    >
                        ₹499
                    </p>


                    <p
                        class="
                            text-xs
                            text-zinc-200
                            mt-3
                            leading-relaxed
                        "
                    >
                        ✓ Unlimited Users<br>
                        ✓ Unlimited Apps<br>
                        ✓ Unlimited Keys<br>
                        ✓ HWID Protection
                    </p>


                    <a
                        href="https://wa.me/919999999999"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="
                            mt-6
                            block
                            text-center
                            bg-gradient-to-r
                            from-cyan-400
                            to-indigo-600
                            py-3
                            rounded-xl
                            text-sm
                            font-bold
                        "
                    >
                        Buy on WhatsApp
                    </a>

                </div>

            </div>

        </div>

    </div>

</div>


""" + CURSOR_SCRIPT + """


<script>

/* ==========================================================
   TAB SYSTEM
========================================================== */

function showTab(name) {

    document
        .querySelectorAll('[id^="tab-"]')
        .forEach(element => {

            element.classList.add("hidden");

        });


    const selected =
        document.getElementById(
            "tab-" + name
        );


    if (selected) {
        selected.classList.remove("hidden");
    }


    document
        .querySelectorAll("#sidebar button")
        .forEach(button => {

            button.classList.remove(
                "side-active"
            );

            button.classList.add(
                "text-zinc-400"
            );

        });


    const active =
        document.getElementById(
            "btn-" + name
        );


    if (active) {

        active.classList.add(
            "side-active"
        );

        active.classList.remove(
            "text-zinc-400"
        );

    }
}


/* ==========================================================
   CREATE APP
========================================================== */

async function createApp() {

    const input =
        document.getElementById(
            "newAppName"
        );

    const name =
        input.value.trim();


    if (!name) {

        alert("Enter App Name!");

        return;
    }


    try {

        const response =
            await fetch(
                "/api/create_app",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            name: name
                        })
                }
            );


        const data =
            await response.json();


        if (data.error) {

            alert(data.error);

            return;
        }


        alert(
            "Application Created!\\n\\nToken:\\n" +
            data.token
        );


        location.reload();

    } catch (error) {

        alert(
            "Network error. Please try again."
        );

    }

}


/* ==========================================================
   DELETE APP
========================================================== */

async function deleteApp(token) {

    if (
        !confirm(
            "Delete this application?"
        )
    ) {
        return;
    }


    try {

        const response =
            await fetch(
                "/api/delete_app",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            token: token
                        })
                }
            );


        const data =
            await response.json();


        alert(
            data.message ||
            data.error ||
            "Done"
        );


        location.reload();

    } catch (error) {

        alert(
            "Network error."
        );

    }

}


/* ==========================================================
   COPY TOKEN
========================================================== */

async function copyToken() {

    const element =
        document.getElementById(
            "tokenDisplay"
        );


    if (!element) return;


    const token =
        element.innerText.trim();


    try {

        await navigator.clipboard.writeText(
            token
        );

        alert("Token copied!");

    } catch (error) {

        alert(
            "Could not copy token."
        );

    }

}


/* ==========================================================
   SELECT APP
========================================================== */

function selectApp(token) {

    const display =
        document.getElementById(
            "tokenDisplay"
        );


    if (display) {

        display.innerText =
            token;

    }

}


/* ==========================================================
   CREATE USER
========================================================== */

async function createUser() {

    const username =
        document
            .getElementById(
                "newUsername"
            )
            .value
            .trim();


    const password =
        document
            .getElementById(
                "newPassword"
            )
            .value
            .trim();


    const token =
        document
            .getElementById(
                "tokenDisplay"
            )
            .innerText
            .trim();


    if (
        !username ||
        !password ||
        !token
    ) {

        alert(
            "Fill all fields!"
        );

        return;
    }


    try {

        const response =
            await fetch(
                "/api/create_user",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            username:
                                username,

                            password:
                                password,

                            app_token:
                                token
                        })
                }
            );


        const data =
            await response.json();


        alert(
            data.message ||
            "Done"
        );


        if (
            response.ok &&
            !data.error
        ) {
            location.reload();
        }

    } catch (error) {

        alert(
            "Network error."
        );

    }

}


/* ==========================================================
   DELETE USER
========================================================== */

async function deleteUser(username) {

    if (
        !confirm(
            "Delete " + username + "?"
        )
    ) {
        return;
    }


    try {

        const response =
            await fetch(
                "/api/delete_user",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            username:
                                username
                        })
                }
            );


        const data =
            await response.json();


        alert(
            data.message ||
            data.error ||
            "Done"
        );


        location.reload();

    } catch (error) {

        alert(
            "Network error."
        );

    }

}


/* ==========================================================
   RESET HWID
========================================================== */

async function resetHwid(username) {

    if (
        !confirm(
            "Reset HWID for " +
            username +
            "?"
        )
    ) {
        return;
    }


    try {

        const response =
            await fetch(
                "/api/reset_hwid",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            username:
                                username
                        })
                }
            );


        const data =
            await response.json();


        alert(
            data.message ||
            "Done"
        );


        location.reload();

    } catch (error) {

        alert(
            "Network error."
        );

    }

}


/* ==========================================================
   BAN
========================================================== */

async function toggleBan(username) {

    try {

        const response =
            await fetch(
                "/api/toggle_ban",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            username:
                                username
                        })
                }
            );


        const data =
            await response.json();


        alert(
            data.message ||
            "Done"
        );


        location.reload();

    } catch (error) {

        alert(
            "Network error."
        );

    }

}


/* ==========================================================
   EDIT USER
========================================================== */

async function editUser(
    oldUsername,
    oldPassword
) {

    const newUsername =
        prompt(
            "New Username:",
            oldUsername
        );


    if (
        newUsername === null
    ) {
        return;
    }


    const newPassword =
        prompt(
            "New Password:",
            oldPassword
        );


    if (
        newPassword === null
    ) {
        return;
    }


    const username =
        newUsername.trim();

    const password =
        newPassword.trim();


    if (
        !username ||
        !password
    ) {

        alert(
            "Username and password cannot be empty."
        );

        return;
    }


    try {

        const response =
            await fetch(
                "/api/edit_user",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({

                            old_username:
                                oldUsername,

                            new_username:
                                username,

                            new_password:
                                password
                        })
                }
            );


        const data =
            await response.json();


        alert(
            data.message ||
            data.error ||
            "Done"
        );


        location.reload();

    } catch (error) {

        alert(
            "Network error."
        );

    }

}

</script>


</body>
</html>
"""


# ============================================================
# HELPERS
# ============================================================

def current_user():

    return session.get("user")


def require_login():

    if "user" not in session:
        return False

    return True


def generate_app_token():

    while True:

        random_str = "".join(
            random.choices(
                string.ascii_uppercase +
                string.digits,
                k=24
            )
        )

        token = "HSL_" + random_str

        existing = db(
            "SELECT id FROM apps WHERE token=?",
            (token,),
            True
        )

        if not existing:
            return token


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def home():

    return render_template_string(
        LANDING
    )


@app.route("/login")
def login():

    return render_template_string(
        LOGIN
    )


# ============================================================
# GOOGLE AUTH
# ============================================================

@app.route("/auth/google")
@rate_limit(
    max_requests=5,
    window_seconds=60
)
def auth_google():

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:

        return (
            "Google OAuth is not configured. "
            "Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET environment variables.",
            500
        )


    redirect_uri = (
        request.url_root.rstrip("/")
        + "/auth/callback"
    )


    return google.authorize_redirect(
        redirect_uri
    )


@app.route("/auth/callback")
def callback():

    try:

        token =
            google.authorize_access_token()

        user =
            token.get("userinfo")


        if not user:

            response =
                google.get(
                    "https://openidconnect.googleapis.com/v1/userinfo"
                )

            user =
                response.json()


        email =
            user.get("email")


        if not email:

            return redirect(
                "/login"
            )


        session.permanent = True

        session["user"] = {
            "email": email,

            "name":
                user.get(
                    "name",
                    email.split("@")[0]
                )
        }


        return redirect(
            "/dashboard"
        )


    except Exception as error:

        print(
            "Google OAuth error:",
            error
        )

        return redirect(
            "/login"
        )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dash():

    if not require_login():

        return redirect(
            "/login"
        )


    user =
        session["user"]


    email =
        user.get("email", "")


    is_paid =
        email in PAID_USERS


    limit_text =
        "Unlimited" if is_paid else "10"


    plan_text =
        "PRO UNLIMITED" if is_paid else "FREE"


    plan_color =
        "text-green-400" if is_paid \
        else "text-yellow-400"


    apps = db(
        """
        SELECT *
        FROM apps
        WHERE owner_email=?
        ORDER BY id DESC
        """,
        (email,),
        True
    )


    # --------------------------------------------------------
    # APPLICATIONS
    # --------------------------------------------------------

    if not apps:

        app_options = (
            "<option value=''>"
            "No Apps Created"
            "</option>"
        )

        active_token =
            "Create an app to get Token"

        app_list_html = (
            "<p class='text-zinc-500 text-sm'>"
            "No apps yet - Create one below"
            "</p>"
        )

    else:

        option_parts = []

        for app_row in apps:

            app_name =
                app_row[1]

            token =
                app_row[2]

            option_parts.append(
                f"<option value='{token}'>"
                f"{app_name}"
                f"</option>"
            )


        app_options =
            "".join(option_parts)


        active_token =
            apps[0][2]


        app_parts = []


        for app_row in apps:

            app_id =
                app_row[0]

            app_name =
                app_row[1]

            token =
                app_row[2]


            safe_name =
                app_name.replace(
                    "'",
                    "\\'"
                )


            safe_token =
                token.replace(
                    "'",
                    "\\'"
                )


            app_parts.append(
                f"""
                <div
                    class="
                        bg-black/80
                        border
                        border-white/10
                        rounded-xl
                        px-4
                        py-3
                        flex
                        justify-between
                        items-center
                        mb-2
                    "
                >

                    <div>

                        <span
                            class="
                                font-bold
                                text-white
                            "
                        >
                            {app_name}
                        </span>

                        <br>

                        <span
                            class="
                                text-xs
                                text-zinc-500
                                font-mono
                            "
                        >
                            {token[:25]}...
                        </span>

                    </div>


                    <button
                        onclick="deleteApp('{safe_token}')"
                        class="
                            bg-red-900/40
                            border
                            border-red-500/25
                            px-3
                            py-1.5
                            rounded-lg
                            text-xs
                            text-red-300
                        "
                    >
                        Delete
                    </button>

                </div>
                """
            )


        app_list_html =
            "".join(app_parts)


    # --------------------------------------------------------
    # KEYS
    # --------------------------------------------------------

    if apps:

        keys = db(
            """
            SELECT *
            FROM keys
            WHERE app_token IN
            (
                SELECT token
                FROM apps
                WHERE owner_email=?
            )
            ORDER BY id DESC
            """,
            (email,),
            True
        )

    else:

        keys = []


    if keys:

        key_parts = []


        for key in keys:

            key_text =
                key[1]

            status =
                key[3]


            status_class =
                (
                    "text-green-400"
                    if status == "unused"
                    else
                    "text-red-400"
                )


            key_parts.append(
                f"""
                <div
                    class="
                        flex
                        justify-between
                        bg-black/80
                        border
                        border-white/10
                        rounded-xl
                        px-4
                        py-3
                    "
                >

                    <span>
                        {key_text}
                    </span>

                    <span
                        class="{status_class}"
                    >
                        ● {status}
                    </span>

                </div>
                """
            )


        keys_list_html =
            "".join(key_parts)

    else:

        keys_list_html = (
            "<p class='text-center "
            "text-zinc-600 text-xs mt-10'>"
            "No keys generated yet."
            "</p>"
        )


    # --------------------------------------------------------
    # TOOL USERS
    # --------------------------------------------------------

    if apps:

        tool_users = db(
            """
            SELECT *
            FROM tool_users
            WHERE app_token IN
            (
                SELECT token
                FROM apps
                WHERE owner_email=?
            )
            ORDER BY id DESC
            """,
            (email,),
            True
        )

    else:

        tool_users = []


    tool_user_count =
        len(tool_users)


    if is_paid:

        percent = 5

    else:

        percent =
            min(
                int(
                    tool_user_count /
                    10 *
                    100
                ),
                100
            )


    # --------------------------------------------------------
    # USER LIST
    # --------------------------------------------------------

    tool_users_parts = []


    for row in tool_users:

        username =
            row[1]

        password =
            row[2]

        status =
            row[4]

        hwid =
            row[5]


        if hwid:

            hwid_short =
                hwid[:15] + "..."

        else:

            hwid_short =
                "Not Bound"


        status_color =
            (
                "text-green-400"
                if status == "active"
                else
                "text-red-400"
            )


        ban_text =
            "Ban" if status == "active" \
            else "Unban"


        safe_username =
            username.replace(
                "\\",
                "\\\\"
            ).replace(
                "'",
                "\\'"
            )


        safe_password =
            password.replace(
                "\\",
                "\\\\"
            ).replace(
                "'",
                "\\'"
            )


        tool_users_parts.append(
            f"""
            <div
                class="
                    flex
                    justify-between
                    items-center
                    bg-black/80
                    border
                    border-white/10
                    rounded-xl
                    px-4
                    py-3
                    mb-2
                "
            >

                <div>

                    <span
                        class="
                            text-white
                            font-bold
                        "
                    >
                        {username}
                    </span>

                    <span class="text-zinc-500">
                        / {password}
                    </span>

                    <br>

                    <span
                        class="
                            text-[10px]
                            text-zinc-500
                        "
                    >
                        HWID:
                        {hwid_short}

                        |

                        Status:

                        <span
                            class="{status_color}"
                        >
                            {status.upper()}
                        </span>

                    </span>

                </div>


                <div
                    class="
                        flex
                        gap-2
                        flex-wrap
                        justify-end
                    "
                >

                    <button
                        onclick="editUser(
                            '{safe_username}',
                            '{safe_password}'
                        )"
                        class="
                            bg-blue-900/40
                            border
                            border-blue-500/25
                            px-3
                            py-1
                            rounded-lg
                            text-[10px]
                        "
                    >
                        Edit
                    </button>


                    <button
                        onclick="toggleBan(
                            '{safe_username}'
                        )"
                        class="
                            bg-yellow-900/40
                            border
                            border-yellow-500/25
                            px-3
                            py-1
                            rounded-lg
                            text-[10px]
                        "
                    >
                        {ban_text}
                    </button>


                    <button
                        onclick="resetHwid(
                            '{safe_username}'
                        )"
                        class="
                            bg-zinc-800
                            border
                            border-white/10
                            px-3
                            py-1
                            rounded-lg
                            text-[10px]
                        "
                    >
                        Reset HWID
                    </button>


                    <button
                        onclick="deleteUser(
                            '{safe_username}'
                        )"
                        class="
                            bg-red-900/40
                            border
                            border-red-500/25
                            px-3
                            py-1
                            rounded-lg
                            text-[10px]
                        "
                    >
                        Delete
                    </button>

                </div>

            </div>
            """
        )


    if tool_users_parts:

        tool_users_list_html =
            "".join(
                tool_users_parts
            )

    else:

        tool_users_list_html = (
            "<p class='text-center "
            "text-zinc-600 text-xs mt-10'>"
            "No registered users found."
            "</p>"
        )


    # --------------------------------------------------------
    # TEMPLATE
    # --------------------------------------------------------

    html = (
        DASHBOARD_HTML
        .replace(
            "{{name}}",
            user.get(
                "name",
                "User"
            )
        )
        .replace(
            "{{email}}",
            email
        )
        .replace(
            "{{app_options}}",
            app_options
        )
        .replace(
            "{{active_token}}",
            active_token
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
# LIMIT CHECK
# ============================================================

def check_limit(email):

    if email in PAID_USERS:

        return False


    user_count_result = db(
        """
        SELECT COUNT(*)
        FROM tool_users
        WHERE app_token IN
        (
            SELECT token
            FROM apps
            WHERE owner_email=?
        )
        """,
        (email,),
        True
    )


    key_count_result = db(
        """
        SELECT COUNT(*)
        FROM keys
        WHERE app_token IN
        (
            SELECT token
            FROM apps
            WHERE owner_email=?
        )
        """,
        (email,),
        True
    )


    user_count =
        user_count_result[0][0] \
        if user_count_result \
        else 0


    key_count =
        key_count_result[0][0] \
        if key_count_result \
        else 0


    return (
        user_count +
        key_count
    ) >= 10


# ============================================================
# CREATE APP
# ============================================================

@app.route(
    "/api/create_app",
    methods=["POST"]
)
def api_create_app():

    if not require_login():

        return jsonify({
            "error": "Unauthorized"
        }), 401


    user =
        session["user"]


    email =
        user.get("email", "")


    result = db(
        """
        SELECT COUNT(*)
        FROM apps
        WHERE owner_email=?
        """,
        (email,),
        True
    )


    app_count =
        result[0][0] \
        if result \
        else 0


    if (
        email not in PAID_USERS
        and app_count >= 2
    ):

        return jsonify({
            "error":
                "Free Plan limit reached. "
                "Maximum 2 applications allowed."
        }), 403


    data =
        request.get_json(
            silent=True
        ) or {}


    name =
        str(
            data.get(
                "name",
                ""
            )
        ).strip()


    if not name:

        return jsonify({
            "error":
                "Invalid app name"
        }), 400


    if len(name) > 60:

        return jsonify({
            "error":
                "App name is too long."
        }), 400


    token =
        generate_app_token()


    db(
        """
        INSERT INTO apps
        (
            name,
            token,
            owner_email,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            name,
            token,
            email,
            datetime.now().isoformat()
        )
    )


    return jsonify({
        "token": token
    })


# ============================================================
# DELETE APP
# ============================================================

@app.route(
    "/api/delete_app",
    methods=["POST"]
)
def api_delete_app():

    if not require_login():

        return jsonify({
            "error": "Unauthorized"
        }), 401


    email =
        session["user"].get(
            "email",
            ""
        )


    data =
        request.get_json(
            silent=True
        ) or {}


    token =
        data.get("token")


    if not token:

        return jsonify({
            "error":
                "Missing token"
        }), 400


    app_check = db(
        """
        SELECT id
        FROM apps
        WHERE token=?
        AND owner_email=?
        """,
        (
            token,
            email
        ),
        True
    )


    if not app_check:

        return jsonify({
            "message":
                "App not found or unauthorized!"
        }), 404


    # Delete dependent records first.

    db(
        "DELETE FROM tool_users WHERE app_token=?",
        (token,)
    )

    db(
        "DELETE FROM keys WHERE app_token=?",
        (token,)
    )

    db(
        "DELETE FROM users WHERE app_token=?",
        (token,)
    )

    db(
        """
        DELETE FROM apps
        WHERE token=?
        AND owner_email=?
        """,
        (
            token,
            email
        )
    )


    return jsonify({
        "message":
            "Application deleted successfully."
    })


# ============================================================
# CREATE TOOL USER
# ============================================================

@app.route(
    "/api/create_user",
    methods=["POST"]
)
def api_create_user():

    if not require_login():

        return jsonify({
            "message":
                "Unauthorized"
        }), 401


    data =
        request.get_json(
            silent=True
        ) or {}


    app_token =
        str(
            data.get(
                "app_token",
                ""
            )
        ).strip()


    username =
        str(
            data.get(
                "username",
                ""
            )
        ).strip()


    password =
        str(
            data.get(
                "password",
                ""
            )
        ).strip()


    if (
        not username
        or not password
        or not app_token
    ):

        return jsonify({
            "message":
                "Missing required fields!"
        }), 400


    if len(username) > 64:

        return jsonify({
            "message":
                "Username too long."
        }), 400


    if len(password) > 256:

        return jsonify({
            "message":
                "Password too long."
        }), 400


    email =
        session["user"].get(
            "email",
            ""
        )


    # Important:
    # Verify that the currently logged-in user owns
    # this app token.

    app_data = db(
        """
        SELECT owner_email
        FROM apps
        WHERE token=?
        """,
        (app_token,),
        True
    )


    if not app_data:

        return jsonify({
            "message":
                "Invalid App Token!"
        }), 404


    owner_email =
        app_data[0][0]


    if owner_email != email:

        return jsonify({
            "message":
                "You do not own this application."
        }), 403


    if check_limit(email):

        return jsonify({
            "message":
                "Plan limit reached!"
        }), 403


    try:

        db(
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
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                password,
                app_token,
                "active",
                None,
                datetime.now().isoformat()
            )
        )


        return jsonify({
            "message":
                f"User Created: {username}"
        })


    except sqlite3.IntegrityError:

        return jsonify({
            "message":
                "Username already exists!"
        }), 409


# ============================================================
# DELETE USER
# ============================================================

@app.route(
    "/api/delete_user",
    methods=["POST"]
)
def api_delete_user():

    if not require_login():

        return jsonify({
            "error":
                "Unauthorized"
        }), 401


    email =
        session["user"].get(
            "email",
            ""
        )


    data =
        request.get_json(
            silent=True
        ) or {}


    username =
        data.get("username")


    if not username:

        return jsonify({
            "error":
                "Missing username"
        }), 400


    ownership = db(
        """
        SELECT id
        FROM tool_users
        WHERE username=?
        AND app_token IN
        (
            SELECT token
            FROM apps
            WHERE owner_email=?
        )
        """,
        (
            username,
            email
        ),
        True
    )


    if not ownership:

        return jsonify({
            "error":
                "User not found or unauthorized."
        }), 404


    db(
        "DELETE FROM tool_users WHERE username=?",
        (username,)
    )


    return jsonify({
        "message":
            "Deleted successfully"
    })


# ============================================================
# RESET HWID
# ============================================================

@app.route(
    "/api/reset_hwid",
    methods=["POST"]
)
def api_reset_hwid():

    if not require_login():

        return jsonify({
            "error":
                "Unauthorized"
        }), 401


    email =
        session["user"].get(
            "email",
            ""
        )


    data =
        request.get_json(
            silent=True
        ) or {}


    username =
        data.get("username")


    ownership = db(
        """
        SELECT id
        FROM tool_users
        WHERE username=?
        AND app_token IN
        (
            SELECT token
            FROM apps
            WHERE owner_email=?
        )
        """,
        (
            username,
            email
        ),
        True
    )


    if not ownership:

        return jsonify({
            "error":
                "User not found or unauthorized."
        }), 404


    db(
        """
        UPDATE tool_users
        SET hwid=NULL,
            status='active'
        WHERE username=?
        """,
        (username,)
    )


    return jsonify({
        "message":
            f"HWID Reset for {username}"
    })


# ============================================================
# BAN / UNBAN
# ============================================================

@app.route(
    "/api/toggle_ban",
    methods=["POST"]
)
def api_toggle_ban():

    if not require_login():

        return jsonify({
            "error":
                "Unauthorized"
        }), 401


    email =
        session["user"].get(
            "email",
            ""
        )


    data =
        request.get_json(
            silent=True
        ) or {}


    username =
        data.get("username")


    result = db(
        """
        SELECT status
        FROM tool_users
        WHERE username=?
        AND app_token IN
        (
            SELECT token
            FROM apps
            WHERE owner_email=?
        )
        """,
        (
            username,
            email
        ),
        True
    )


    if not result:

        return jsonify({
            "message":
                "User not found"
        }), 404


    current_status =
        result[0][0]


    new_status =
        "banned" \
        if current_status == "active" \
        else "active"


    db(
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
        "message":
            f"{username} status updated to "
            f"{new_status.upper()}"
    })


# ============================================================
# EDIT USER
# ============================================================

@app.route(
    "/api/edit_user",
    methods=["POST"]
)
def api_edit_user():

    if not require_login():

        return jsonify({
            "error":
                "Unauthorized"
        }), 401


    email =
        session["user"].get(
            "email",
            ""
        )


    data =
        request.get_json(
            silent=True
        ) or {}


    old_username =
        data.get(
            "old_username"
        )


    new_username =
        data.get(
            "new_username"
        ) or old_username


    new_password =
        data.get(
            "new_password"
        )


    if (
        not old_username
        or not new_username
        or not new_password
    ):

        return jsonify({
            "message":
                "All fields are required."
        }), 400


    ownership = db(
        """
        SELECT id
        FROM tool_users
        WHERE username=?
        AND app_token IN
        (
            SELECT token
            FROM apps
            WHERE owner_email=?
        )
        """,
        (
            old_username,
            email
        ),
        True
    )


    if not ownership:

        return jsonify({
            "message":
                "User not found or unauthorized."
        }), 404


    try:

        db(
            """
            UPDATE tool_users
            SET username=?,
                password=?
            WHERE username=?
            """,
            (
                new_username,
                new_password,
                old_username
            )
        )


        return jsonify({
            "message":
                f"Updated {old_username}"
        })


    except sqlite3.IntegrityError:

        return jsonify({
            "message":
                "Username already exists."
        }), 409


# ============================================================
# CLIENT AUTH LOGIN
# ============================================================

@app.route(
    "/api/auth_login",
    methods=["POST"]
)
@rate_limit(
    max_requests=10,
    window_seconds=60
)
def api_auth_login():

    data =
        request.get_json(
            silent=True
        ) or {}


    username =
        data.get("username")


    password =
        data.get("password")


    hwid =
        data.get("hwid")


    token =
        data.get("token")


    client_sig =
        data.get("sig")


    if (
        not username
        or not password
        or not token
        or not hwid
    ):

        return jsonify({
            "status":
                "invalid",

            "message":
                "Malformed request parameters"
        }), 400


    # --------------------------------------------------------
    # Signature verification
    # --------------------------------------------------------

    expected_sig =
        hashlib.sha256(
            f"{username}:{hwid}:{token}"
            .encode()
        ).hexdigest()


    if (
        not client_sig
        or client_sig != expected_sig
    ):

        return jsonify({
            "status":
                "tampered",

            "message":
                "Request payload validation failed."
        }), 403


    # --------------------------------------------------------
    # Verify user + token
    # --------------------------------------------------------

    result = db(
        """
        SELECT *
        FROM tool_users
        WHERE username=?
        AND password=?
        AND app_token=?
        """,
        (
            username,
            password,
            token
        ),
        True
    )


    if not result:

        return jsonify({
            "status":
                "invalid",

            "message":
                "Incorrect credentials"
        }), 401


    user_row =
        result[0]


    # row layout:
    #
    # 0 = id
    # 1 = username
    # 2 = password
    # 3 = app_token
    # 4 = status
    # 5 = hwid
    # 6 = created_at


    if user_row[4] == "banned":

        return jsonify({
            "status":
                "banned",

            "message":
                "Account suspended"
        }), 403


    stored_hwid =
        user_row[5]


    # --------------------------------------------------------
    # First HWID binding
    # --------------------------------------------------------

    if not stored_hwid:

        db(
            """
            UPDATE tool_users
            SET hwid=?,
                status='active'
            WHERE username=?
            AND app_token=?
            """,
            (
                hwid,
                username,
                token
            )
        )


        return jsonify({
            "status":
                "valid",

            "message":
                "HWID Bound Successfully"
        })


    # --------------------------------------------------------
    # Existing HWID
    # --------------------------------------------------------

    if stored_hwid == hwid:

        return jsonify({
            "status":
                "valid",

            "message":
                "Authentication Success"
        })


    return jsonify({
        "status":
            "hwid_mismatch",

        "message":
            "Hardware mismatch detected"
    }), 403


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# ============================================================
# SERVER
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True
    )