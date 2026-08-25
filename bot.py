import discord
from discord.ext import commands
import sqlite3

# --- CONFIG ---
BOT_TOKEN = "YOUR_DISCORD_BOT_TOKEN_DALO_YAHAN"
OWNER_ID = 1517901703263944758 # Apni Discord ID dalo (Developer mode on karke copy)
DB_PATH = "hsl.db" # same as website

# Bot setup - Prefix =, (comma)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=",", intents=intents, help_command=None)

def db(q, p=(), fetch=False):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(q, p)
    data = cur.fetchall() if fetch else None
    con.commit()
    con.close()
    return data

def init_whitelist_db():
    db("CREATE TABLE IF NOT EXISTS discord_whitelist (user_id TEXT, command TEXT)")
init_whitelist_db()

def is_owner_or_whitelisted(ctx, cmd_name):
    if ctx.author.id == OWNER_ID:
        return True
    # check whitelist
    res = db("SELECT * FROM discord_whitelist WHERE user_id=? AND command=?", (str(ctx.author.id), cmd_name), True)
    return len(res) > 0

# --- WHITELIST SYSTEM ---
@bot.command(name="whitelist")
async def whitelist_cmd(ctx, action=None, member: discord.Member = None, command_name=None):
    if ctx.author.id!= OWNER_ID:
        return await ctx.send("❌ Sirf Owner chala sakta hai!")

    if action == "add" and member and command_name:
        db("INSERT INTO discord_whitelist (user_id, command) VALUES (?,?)", (str(member.id), command_name.lower()))
        await ctx.send(f"✅ {member.mention} ko `{command_name}` ka access de diya!")
    elif action == "remove" and member and command_name:
        db("DELETE FROM discord_whitelist WHERE user_id=? AND command=?", (str(member.id), command_name.lower()))
        await ctx.send(f"🗑️ {member.mention} ka `{command_name}` access hata diya!")
    elif action == "list":
        rows = db("SELECT user_id, command FROM discord_whitelist", fetch=True)
        if not rows: return await ctx.send("Koi whitelist nahi hai.")
        msg = "**Whitelist:**\n"
        for r in rows: msg += f"<@{r[0]}> -> `{r[1]}`\n"
        await ctx.send(msg)
    else:
        await ctx.send("**Use:**\n`,whitelist add @user reset`\n`,whitelist add @user ban`\n`,whitelist remove @user reset`\n`,whitelist list`")

# --- ALL WEBSITE FUNCTIONS ---

@bot.command(name="list")
async def list_users(ctx):
    if not is_owner_or_whitelisted(ctx, "list"): return await ctx.send("❌ No Access")
    users = db("SELECT username, status, hwid FROM tool_users", fetch=True)
    if not users: return await ctx.send("Koi user nahi hai.")
    msg = "**👤 All Users:**\n"
    for u in users:
        hwid = (u[2][:10]+"...") if u[2] else "No HWID"
        msg += f"`{u[0]}` | {u[1]} | {hwid}\n"
    await ctx.send(msg[:2000])

@bot.command(name="create")
async def create_user(ctx, username=None, password=None):
    if not is_owner_or_whitelisted(ctx, "create"): return await ctx.send("❌ No Access")
    if not username or not password: return await ctx.send("Use: `,create username password`")
    # First app token lete hain default
    app = db("SELECT token FROM apps LIMIT 1", fetch=True)
    if not app: return await ctx.send("Pehle website pe ek App banao!")
    token = app[0][0]
    try:
        db("INSERT INTO tool_users (username, password, app_token, status) VALUES (?,?,?,?)", (username, password, token, 'active'))
        await ctx.send(f"✅ User Created: `{username}` / `{password}`")
    except:
        await ctx.send("❌ Username already exists!")

@bot.command(name="edit")
async def edit_user(ctx, old_user=None, new_user=None, new_pass=None):
    if not is_owner_or_whitelisted(ctx, "edit"): return await ctx.send("❌ No Access")
    if not old_user or not new_user or not new_pass: return await ctx.send("Use: `,edit olduser newuser newpass`")
    try:
        db("UPDATE tool_users SET username=?, password=? WHERE username=?", (new_user, new_pass, old_user))
        await ctx.send(f"✅ Edited: `{old_user}` -> `{new_user}` / `{new_pass}`")
    except:
        await ctx.send("❌ Error! New username exists maybe.")

@bot.command(name="ban")
async def ban_user(ctx, username=None):
    if not is_owner_or_whitelisted(ctx, "ban"): return await ctx.send("❌ No Access")
    if not username: return await ctx.send("Use: `,ban username`")
    db("UPDATE tool_users SET status='banned' WHERE username=?", (username,))
    await ctx.send(f"🔨 `{username}` Banned!")

@bot.command(name="unban")
async def unban_user(ctx, username=None):
    if not is_owner_or_whitelisted(ctx, "unban"): return await ctx.send("❌ No Access")
    if not username: return await ctx.send("Use: `,unban username`")
    db("UPDATE tool_users SET status='active' WHERE username=?", (username,))
    await ctx.send(f"✅ `{username}` Unbanned!")

@bot.command(name="delete")
async def delete_user(ctx, username=None):
    if not is_owner_or_whitelisted(ctx, "delete"): return await ctx.send("❌ No Access")
    if not username: return await ctx.send("Use: `,delete username`")
    db("DELETE FROM tool_users WHERE username=?", (username,))
    await ctx.send(f"🗑️ `{username}` Deleted!")

@bot.command(name="resethwid")
async def reset_hwid(ctx, username=None):
    if not is_owner_or_whitelisted(ctx, "resethwid"): return await ctx.send("❌ No Access")
    if not username: return await ctx.send("Use: `,resethwid username`")
    db("UPDATE tool_users SET hwid=NULL, status='active' WHERE username=?", (username,))
    await ctx.send(f"♻️ `{username}` ka HWID Reset! Ab dusre PC pe login kar sakta hai.")

@bot.command(name="apps")
async def list_apps(ctx):
    if not is_owner_or_whitelisted(ctx, "apps"): return await ctx.send("❌ No Access")
    apps = db("SELECT name, token FROM apps", fetch=True)
    if not apps: return await ctx.send("Koi app nahi.")
    msg = "**📦 Apps:**\n"
    for a in apps: msg += f"`{a[0]}` - `{a[1]}`\n"
    await ctx.send(msg[:2000])

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} | Prefix:, | Owner: {OWNER_ID}")

bot.run(BOT_TOKEN)