import discord
from discord.ext import commands
import sqlite3
import os

# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip().strip('"').strip("'")
OWNER_ID = int(os.getenv("OWNER_ID", "1517901703263944758"))
DB_PATH = "hsl.db"

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

def init_db():
    db("CREATE TABLE IF NOT EXISTS discord_whitelist (user_id TEXT, command TEXT)")
init_db()

def is_owner_or_whitelisted(user_id, cmd_name):
    if user_id == OWNER_ID: return True
    res = db("SELECT * FROM discord_whitelist WHERE user_id=? AND command=?", (str(user_id), cmd_name), True)
    return len(res) > 0

# --- SYNC SLASH ---
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands - {bot.user}")
    except Exception as e:
        print(f"Sync Error: {e}")

# --- WHITELIST (SLASH) ---
@bot.tree.command(name="whitelist", description="Manage whitelist")
@discord.app_commands.describe(action="add/remove/list", member="user", command_name="command like reset/ban/create")
async def whitelist_slash(interaction: discord.Interaction, action: str, member: discord.Member = None, command_name: str = None):
    if interaction.user.id!= OWNER_ID:
        return await interaction.response.send_message("❌ Sirf Owner!", ephemeral=True)
    if action == "add" and member and command_name:
        db("INSERT INTO discord_whitelist (user_id, command) VALUES (?,?)", (str(member.id), command_name.lower()))
        await interaction.response.send_message(f"✅ {member.mention} ko `{command_name}` access de diya!")
    elif action == "remove" and member and command_name:
        db("DELETE FROM discord_whitelist WHERE user_id=? AND command=?", (str(member.id), command_name.lower()))
        await interaction.response.send_message(f"🗑️ {member.mention} ka `{command_name}` hata diya!")
    elif action == "list":
        rows = db("SELECT user_id, command FROM discord_whitelist", fetch=True)
        if not rows: return await interaction.response.send_message("Koi whitelist nahi hai.")
        msg = "**Whitelist:**\n"
        for r in rows: msg += f"<@{r[0]}> -> `{r[1]}`\n"
        await interaction.response.send_message(msg)
    else:
        await interaction.response.send_message("Use: `/whitelist add @user reset` / `remove` / `list`", ephemeral=True)

# --- SLASH COMMANDS FOR WEBSITE ---
@bot.tree.command(name="ping", description="Check latency")
async def ping_s(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! {round(bot.latency*1000)}ms")

@bot.tree.command(name="list", description="List all tool users")
async def list_s(interaction: discord.Interaction):
    if not is_owner_or_whitelisted(interaction.user.id, "list"): return await interaction.response.send_message("❌ No Access", ephemeral=True)
    users = db("SELECT username, status, hwid FROM tool_users", fetch=True)
    if not users: return await interaction.response.send_message("Koi user nahi.")
    msg = "**👤 All Users:**\n"
    for u in users:
        hwid = (u[2][:10]+"...") if u[2] else "No HWID"
        msg += f"`{u[0]}` | {u[1]} | {hwid}\n"
    await interaction.response.send_message(msg[:2000])

@bot.tree.command(name="create", description="Create new user")
@discord.app_commands.describe(username="username", password="password")
async def create_s(interaction: discord.Interaction, username: str, password: str):
    if not is_owner_or_whitelisted(interaction.user.id, "create"): return await interaction.response.send_message("❌ No Access", ephemeral=True)
    app = db("SELECT token FROM apps LIMIT 1", fetch=True)
    if not app: return await interaction.response.send_message("Pehle website pe App banao!")
    token = app[0][0]
    try:
        db("INSERT INTO tool_users (username, password, app_token, status) VALUES (?,?,?,?)", (username, password, token, 'active'))
        await interaction.response.send_message(f"✅ Created: `{username}` / `{password}`")
    except:
        await interaction.response.send_message("❌ Username already exists!")

@bot.tree.command(name="ban", description="Ban a user")
async def ban_s(interaction: discord.Interaction, username: str):
    if not is_owner_or_whitelisted(interaction.user.id, "ban"): return await interaction.response.send_message("❌ No Access", ephemeral=True)
    db("UPDATE tool_users SET status='banned' WHERE username=?", (username,))
    await interaction.response.send_message(f"🔨 `{username}` Banned!")

@bot.tree.command(name="unban", description="Unban a user")
async def unban_s(interaction: discord.Interaction, username: str):
    if not is_owner_or_whitelisted(interaction.user.id, "unban"): return await interaction.response.send_message("❌ No Access", ephemeral=True)
    db("UPDATE tool_users SET status='active' WHERE username=?", (username,))
    await interaction.response.send_message(f"✅ `{username}` Unbanned!")

@bot.tree.command(name="delete", description="Delete a user")
async def delete_s(interaction: discord.Interaction, username: str):
    if not is_owner_or_whitelisted(interaction.user.id, "delete"): return await interaction.response.send_message("❌ No Access", ephemeral=True)
    db("DELETE FROM tool_users WHERE username=?", (username,))
    await interaction.response.send_message(f"🗑️ `{username}` Deleted!")

@bot.tree.command(name="resethwid", description="Reset HWID of user")
async def resethwid_s(interaction: discord.Interaction, username: str):
    if not is_owner_or_whitelisted(interaction.user.id, "resethwid"): return await interaction.response.send_message("❌ No Access", ephemeral=True)
    db("UPDATE tool_users SET hwid=NULL, status='active' WHERE username=?", (username,))
    await interaction.response.send_message(f"♻️ `{username}` HWID Reset!")

@bot.tree.command(name="apps", description="List apps")
async def apps_s(interaction: discord.Interaction):
    if not is_owner_or_whitelisted(interaction.user.id, "apps"): return await interaction.response.send_message("❌ No Access", ephemeral=True)
    apps = db("SELECT name, token FROM apps", fetch=True)
    if not apps: return await interaction.response.send_message("Koi app nahi.")
    msg = "**📦 Apps:**\n"
    for a in apps: msg += f"`{a[0]}` - `{a[1]}`\n"
    await interaction.response.send_message(msg[:2000])

# --- OLD PREFIX COMMANDS (keep backup) ---
@bot.command(name="list")
async def list_users(ctx):
    if not is_owner_or_whitelisted(ctx.author.id, "list"): return await ctx.send("❌ No Access")
    users = db("SELECT username, status, hwid FROM tool_users", fetch=True)
    if not users: return await ctx.send("Koi user nahi hai.")
    msg = "**👤 All Users:**\n"
    for u in users:
        hwid = (u[2][:10]+"...") if u[2] else "No HWID"
        msg += f"`{u[0]}` | {u[1]} | {hwid}\n"
    await ctx.send(msg[:2000])

@bot.command(name="create")
async def create_user(ctx, username=None, password=None):
    if not is_owner_or_whitelisted(ctx.author.id, "create"): return await ctx.send("❌ No Access")
    if not username or not password: return await ctx.send("Use: `,create username password`")
    app = db("SELECT token FROM apps LIMIT 1", fetch=True)
    if not app: return await ctx.send("Pehle website pe ek App banao!")
    token = app[0][0]
    try:
        db("INSERT INTO tool_users (username, password, app_token, status) VALUES (?,?,?,?)", (username, password, token, 'active'))
        await ctx.send(f"✅ User Created: `{username}` / `{password}`")
    except:
        await ctx.send("❌ Username already exists!")

@bot.command(name="ban")
async def ban_user(ctx, username=None):
    if not is_owner_or_whitelisted(ctx.author.id, "ban"): return await ctx.send("❌ No Access")
    if not username: return await ctx.send("Use: `,ban username`")
    db("UPDATE tool_users SET status='banned' WHERE username=?", (username,))
    await ctx.send(f"🔨 `{username}` Banned!")

@bot.command(name="unban")
async def unban_user(ctx, username=None):
    if not is_owner_or_whitelisted(ctx.author.id, "unban"): return await ctx.send("❌ No Access")
    if not username: return await ctx.send("Use: `,unban username`")
    db("UPDATE tool_users SET status='active' WHERE username=?", (username,))
    await ctx.send(f"✅ `{username}` Unbanned!")

@bot.command(name="delete")
async def delete_user(ctx, username=None):
    if not is_owner_or_whitelisted(ctx.author.id, "delete"): return await ctx.send("❌ No Access")
    if not username: return await ctx.send("Use: `,delete username`")
    db("DELETE FROM tool_users WHERE username=?", (username,))
    await ctx.send(f"🗑️ `{username}` Deleted!")

@bot.command(name="resethwid")
async def reset_hwid(ctx, username=None):
    if not is_owner_or_whitelisted(ctx.author.id, "resethwid"): return await ctx.send("❌ No Access")
    if not username: return await ctx.send("Use: `,resethwid username`")
    db("UPDATE tool_users SET hwid=NULL, status='active' WHERE username=?", (username,))
    await ctx.send(f"♻️ `{username}` ka HWID Reset!")

bot.run(BOT_TOKEN)