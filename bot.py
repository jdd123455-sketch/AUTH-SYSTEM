import os
import datetime
import discord
from discord.ext import commands
import requests

RAILWAY_URL = "https://hsl-corp-production-9678.up.railway.app"
# --- CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip().strip('"').strip("'")
OWNER_ID = int(os.getenv("OWNER_ID", "1517901703263944758"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=",", intents=intents, help_command=None)

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
    desc = "**👑 AUTH:** `/create` `/list` `/ban` `/unban` `/delete` `/resethwid` `/apps`\n**⚡:** `/ping` `/help`"
    em = stylish_embed("✨ HSL AUTH - Help", desc, 0x5865F2)
    if bot.user: em.set_thumbnail(url=bot.user.display_avatar.url)
    await interaction.response.send_message(embed=em)

# ========== AUTH COMMANDS (VIA RAILWAY API) ==========
@bot.tree.command(name="list", description="👤 All users")
async def list_s(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        # Fetching users via backend/dashboard API logic or direct check if exposed, 
        # Since standard web dash uses session, we show a clean message or fetch via an endpoint if available.
        await interaction.followup.send(embed=stylish_embed("📋 Dashboard Sync", f"Manage and view all active users directly at:\n{RAILWAY_URL}/dashboard", 0x5865F2))
    except Exception as e:
        await interaction.followup.send(embed=stylish_embed("❌ Error", str(e), 0xFF0000), ephemeral=True)

@bot.tree.command(name="create", description="➕ New user")
async def create_s(interaction: discord.Interaction, username: str, password: str):
    await interaction.response.defer()
    try:
        API_URL = f"{RAILWAY_URL}/api/create_user"
        APP_TOKEN = "HSL_K68EWHIKXG56NBRZHE26"  # Apna app token yahan ensure karein

        payload = {
            "username": username.strip(),
            "password": password.strip(),
            "app_token": APP_TOKEN,
        }

        response = requests.post(API_URL, json=payload, timeout=10)
        data = response.json()

        if response.status_code == 200 and data.get("status") == "success":
            await interaction.followup.send(
                embed=stylish_embed(
                    "✅ Created",
                    f"```User: {username}\nPass: {password}``` added to Dashboard!",
                    0x00FF99,
                )
            )
        else:
            msg = data.get("message", "User creation failed!")
            await interaction.followup.send(
                embed=stylish_embed("❌ Failed", msg, 0xFF0000)
            )

    except Exception as e:
        await interaction.followup.send(
            embed=stylish_embed("❌ Error", str(e), 0xFF0000)
        )

@bot.tree.command(name="ban", description="🔨 Ban user")
async def ban_s(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    try:
        res = requests.post(
            f"{RAILWAY_URL}/api/toggle_ban",
            json={"username": username.strip()},
            timeout=10,
        )
        msg = res.json().get("message", "Updated")
        await interaction.followup.send(
            embed=stylish_embed("🔨 Ban Toggle", f"`{username}` status updated on dashboard: {msg}", 0xFF0000)
        )
    except Exception as e:
        await interaction.followup.send(
            embed=stylish_embed("❌ Error", str(e), 0xFF0000)
        )

@bot.tree.command(name="unban", description="✅ Unban user")
async def unban_s(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    try:
        res = requests.post(
            f"{RAILWAY_URL}/api/toggle_ban",
            json={"username": username.strip()},
            timeout=10,
        )
        msg = res.json().get("message", "Updated")
        await interaction.followup.send(
            embed=stylish_embed("✅ Unban Toggle", f"`{username}` status updated on dashboard: {msg}", 0x00FF99)
        )
    except Exception as e:
        await interaction.followup.send(
            embed=stylish_embed("❌ Error", str(e), 0xFF0000)
        )

@bot.tree.command(name="delete", description="🗑️ Delete user")
async def delete_s(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    try:
        res = requests.post(
            f"{RAILWAY_URL}/api/delete_user",
            json={"username": username.strip()},
            timeout=10,
        )
        data = res.json()
        if res.status_code == 200 and data.get("status") == "success":
            await interaction.followup.send(
                embed=stylish_embed("🗑️ Deleted", f"`{username}` successfully deleted from Dashboard!")
            )
        else:
            await interaction.followup.send(
                embed=stylish_embed("❌ Failed", data.get("message", "Could not delete user"), 0xFF0000)
            )
    except Exception as e:
        await interaction.followup.send(
            embed=stylish_embed("❌ Error", str(e), 0xFF0000)
        )

@bot.tree.command(name="resethwid", description="♻️ Reset HWID")
async def reset_s(interaction: discord.Interaction, username: str):
    await interaction.response.defer()
    try:
        res = requests.post(
            f"{RAILWAY_URL}/api/reset_hwid",
            json={"username": username.strip()},
            timeout=10,
        )
        data = res.json()
        if res.status_code == 200 and data.get("status") == "success":
            await interaction.followup.send(
                embed=stylish_embed(
                    "♻️ HWID Reset",
                    f"HWID for **{username}** has been reset on the Dashboard!",
                    0x5865F2,
                )
            )
        else:
            await interaction.followup.send(
                embed=stylish_embed("❌ Failed", data.get("message", "Reset failed"), 0xFF0000)
            )
    except Exception as e:
        await interaction.followup.send(
            embed=stylish_embed("❌ Error", str(e), 0xFF0000)
        )

@bot.tree.command(name="apps", description="📦 Apps list")
async def apps_s(interaction: discord.Interaction):
    try:
        await interaction.response.send_message(
            embed=stylish_embed(
                "📦 Application Info",
                f"Manage your apps & tokens directly at:\n{RAILWAY_URL}/dashboard",
                0x5865F2,
            )
        )
    except Exception as e:
        await interaction.response.send_message(f"⚠️ Error: {e}", ephemeral=True)

bot.run(BOT_TOKEN)