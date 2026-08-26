import discord
from discord.ext import commands
import sqlite3
import os
import datetime
import requests

RAILWAY_URL = "https://hsl-corp-production-9678.up.railway.app"
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
    db("CREATE TABLE IF NOT EXISTS apps (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, token TEXT UNIQUE)")
    db("CREATE TABLE IF NOT EXISTS tool_users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, app_token TEXT, status TEXT DEFAULT 'active', hwid TEXT)")
    print("✅ DB Ready")

init_db()

def is_owner_or_whitelisted(user_id, cmd_name):
    if user_id == OWNER_ID: return True
    res = db("SELECT * FROM discord_whitelist WHERE user_id=? AND command=?", (str(user_id), cmd_name.lower()), True)
    return len(res) > 0

def stylish_embed(title, desc, color=0x5865F2):
    e = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.datetime.now())
    if bot.user:
        e.set_footer(text="HSL • AUTH SYSTEM", icon_url=bot.user.display_avatar.url)
    else:
        e.set_footer(text="HSL • AUTH SYSTEM")
    return e

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ {bot.user} | Synced {len(synced)} commands")
    except Exception as e:
        print(f"Sync Error: {e}")

# ========== HELP & PING ==========
@bot.tree.command(name="ping", description="⚡ Check latency")
async def ping_s(interaction: discord.Interaction):
    await interaction.response.send_message(embed=stylish_embed("🏓 Pong!", f"```Latency: {round(bot.latency*1000)}ms```", 0x00FF99))

@bot.tree.command(name="help", description="📜 Help menu")
async def help_s(interaction: discord.Interaction):
    desc = "**👑 AUTH:** `/create` `/list` `/ban` `/unban` `/delete` `/resethwid` `/apps`\n**🛡️ WL:** `/whitelist_add` `/whitelist_remove` `/whitelist_list`\n**⚡:** `/ping` `/help`"
    em = stylish_embed("✨ HSL AUTH - Help", desc, 0x5865F2)
    if bot.user: em.set_thumbnail(url=bot.user.display_avatar.url)
    await interaction.response.send_message(embed=em)

# ========== WHITELIST ==========
@bot.tree.command(name="whitelist_add", description="➕ Access do")
async def w_add(interaction: discord.Interaction, member: discord.Member, command_name: str):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message(embed=stylish_embed("❌ No Access", "Sirf Owner!", 0xFF0000), ephemeral=True)
    db("INSERT INTO discord_whitelist (user_id, command) VALUES (?,?)", (str(member.id), command_name.lower()))
    await interaction.response.send_message(embed=stylish_embed("✅ Added", f"{member.mention} → `{command_name}` 🟢", 0x00FF88))

@bot.tree.command(name="whitelist_remove", description="➖ Access hatao")
async def w_rem(interaction: discord.Interaction, member: discord.Member, command_name: str):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message(embed=stylish_embed("❌ No Access", "Sirf Owner!", 0xFF0000), ephemeral=True)
    db("DELETE FROM discord_whitelist WHERE user_id=? AND command=?", (str(member.id), command_name.lower()))
    await interaction.response.send_message(embed=stylish_embed("🗑️ Removed", f"{member.mention} ka `{command_name}` hata diya!", 0xFF5050))

@bot.tree.command(name="whitelist_list", description="📋 Whitelist dekho")
async def w_list(interaction: discord.Interaction):
    await interaction.response.defer()
    rows = db("SELECT user_id, command FROM discord_whitelist", fetch=True)
    if not rows: return await interaction.followup.send(embed=stylish_embed("📭 Empty", "Koi whitelist nahi"))
    desc = "".join([f"<@{r[0]}> → `{r[1]}`\n" for r in rows])
    await interaction.followup.send(embed=stylish_embed("🛡️ Whitelist", desc))

# ========== AUTH COMMANDS ==========
@bot.tree.command(name="list", description="👤 All users")
async def list_s(interaction: discord.Interaction):
    try:
        if not is_owner_or_whitelisted(interaction.user.id, "list"):
            return await interaction.response.send_message(embed=stylish_embed("❌ Denied", "No Access!", 0xFF0000), ephemeral=True)
        await interaction.response.defer()
        
        # Railway API se data lene ke liye fix
        res = requests.get(f"{RAILWAY_URL}/api/bot/users", timeout=10)
        data = res.json()
        users = data.get("users", [])
        
        if not users: 
            return await interaction.followup.send(embed=stylish_embed("📭 No Users", "Database khali hai"))
        
        desc = ""
        for u in users:
            emoji = "🟢" if u['status'] == 'active' else "🔴"
            hwid = (u['hwid'][:8]+"...") if u['hwid'] and u['hwid'] != "Not Bound" else "`No HWID`"
            desc += f"{emoji} `{u['username']}` | {u['status']} | {hwid}\n"
            
        await interaction.followup.send(embed=stylish_embed(f"👥 Total: {len(users)}", desc[:4000]))
    except Exception as e:
        print(e)
        msg = f"Error: {e}"
        if interaction.response.is_done(): await interaction.followup.send(msg, ephemeral=True)
        else: await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="create", description="➕ New user")
async def create_s(interaction: discord.Interaction, username: str, password: str):
    try:
        if not is_owner_or_whitelisted(interaction.user.id, "create"):
            return await interaction.response.send_message(embed=stylish_embed("❌ Denied", "No Access!"), ephemeral=True)

        await interaction.response.defer()

        API_URL = f"{RAILWAY_URL}/api/create_user"
        APP_TOKEN = "HSL_K68EWHIKXG56NBRZHE26"

        payload = {
            "username": username.strip(),
            "password": password.strip(),
            "app_token": APP_TOKEN,
        }

        response = requests.post(API_URL, json=payload, timeout=10)
        data = response.json()

        if response.status_code == 200 and "User Created" in data.get("message", ""):
            await interaction.followup.send(embed=stylish_embed("✅ Created", f"```User: {username}\nPass: {password}