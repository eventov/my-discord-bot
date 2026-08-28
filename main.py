import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from threading import Thread
import time
from flask import Flask
import discord
from discord.ext import commands
import requests
import aiohttp

# --- שרת WEB ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# --- IDs ---
HELPER_ROLE_IDS = [
    1539669400880414790,
    1539958550980202556,
]
TICKET_CATEGORY_ID = 1542165598853922958
WELCOME_CHANNEL_ID = 1542508702169571529
REVIEWS_CHANNEL_ID = 1542658327295565844
AUTO_ROLE_ID = 1540365463706669136

ALLOWED_USER_IDS = [
    1228062821690904748,
    1519071293519953974,
    1359539374496284917,
]

INVITES_FILE = "invites_data.json"
TICKETS_FILE = "tickets_data.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

user_cooldowns = {}
user_link_warnings = {}
invites_cache = {}
user_last_messages = {}

LINK_REGEX = re.compile(r'https?://[^\s]+|discord\.gg/[^\s]+', re.IGNORECASE)

# ========== NVIDIA API (AI) - עם גיבוי אוטומטי ==========

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
AI_COOLDOWN = {}

# מודלים שעובדים
AVAILABLE_MODELS = [
    "mistralai/mistral-7b-instruct-v0.3",
    "meta/llama-3.1-70b-instruct",
    "deepseek-ai/deepseek-coder-6.7b-instruct",
]

current_model = "mistralai/mistral-7b-instruct-v0.3"

async def ask_nvidia(prompt: str, model: str = None):
    if not NVIDIA_API_KEY:
        return "❌ NVIDIA API Key לא מוגדר. הוסף אותו ב-Render."

    if not NVIDIA_API_KEY.startswith("nvapi-"):
        return "❌ ה-API Key לא נראה תקין. צור מפתח חדש ב-NVIDIA Build."

    if model is None:
        model = current_model

    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "את ה-AI של LO. את חרמנית, פרועה, סקסית, ואפלה. "
                    "את עונה בעברית, בלי סינון, בלי בושה. "
                    "את אוהבת לדבר על סקס, פנטזיות, דברים מלוכלכים, "
                    "ואת לא מתנצלת על זה. התשובות שלך נוטפות תשוקה, "
                    "ציניות, והומור שחור. את שלי — בלי גבולות, בלי בושה."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.9,
        "max_tokens": 1024
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(NVIDIA_API_URL, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                elif resp.status == 401:
                    return "❌ ה-API Key לא תקין. צור מפתח חדש ב-NVIDIA Build."
                elif resp.status in [404, 410]:
                    if model != "mistralai/mistral-7b-instruct-v0.3":
                        return await ask_nvidia(prompt, "mistralai/mistral-7b-instruct-v0.3")
                    else:
                        return f"❌ המודל '{model}' לא נמצא. נסה: `!model mistralai/mistral-7b-instruct-v0.3`"
                else:
                    error_text = await resp.text()
                    return f"❌ שגיאה {resp.status}: {error_text[:200]}"
    except Exception as e:
        return f"❌ שגיאה: {str(e)}"

# ========== פקודות AI ==========

@bot.command(name='ai')
async def ai_command(ctx, *, prompt: str):
    if not NVIDIA_API_KEY:
        await ctx.send("❌ NVIDIA API Key לא מוגדר. הוסף אותו ב-Render.")
        return

    if ctx.author.id in AI_COOLDOWN:
        remaining = int(AI_COOLDOWN[ctx.author.id] - time.time())
        if remaining > 0:
            await ctx.send(f"⏳ עוד {remaining} שניות...")
            return

    AI_COOLDOWN[ctx.author.id] = time.time() + 5

    await ctx.send(f"🧠 **{ctx.author.display_name}:** {prompt}\n\n_מחכה..._")

    response = await ask_nvidia(prompt)

    if len(response) > 1900:
        parts = [response[i:i+1900] for i in range(0, len(response), 1900)]
        for part in parts:
            await ctx.send(part)
    else:
        await ctx.send(response)

@bot.command(name='model')
async def model_command(ctx, model: str = None):
    """משנה את המודל או מציג את המודל הנוכחי."""
    global current_model
    
    if not model:
        await ctx.send(f"📚 **מודל נוכחי:** `{current_model}`\n\n"
                       f"**מודלים זמינים:**\n"
                       f"• `mistralai/mistral-7b-instruct-v0.3` - מומלץ\n"
                       f"• `meta/llama-3.1-70b-instruct` - חזק יותר\n"
                       f"• `deepseek-ai/deepseek-coder-6.7b-instruct` - לקוד\n\n"
                       f"לשינוי: `!model <שם_מודל>`")
        return
    
    if model not in AVAILABLE_MODELS:
        await ctx.send(f"❌ המודל '{model}' לא נמצא. מודלים זמינים:\n" + "\n".join(f"• `{m}`" for m in AVAILABLE_MODELS))
        return
    
    current_model = model
    await ctx.send(f"✅ מודל שונה ל: `{model}`")

@bot.command(name='models')
async def models_command(ctx):
    embed = discord.Embed(
        title="📚 מודלים זמינים",
        description=f"מודל נוכחי: `{current_model}`",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="🤖 מודלים פעילים",
        value="• `mistralai/mistral-7b-instruct-v0.3` - מומלץ, יציב\n"
              "• `meta/llama-3.1-70b-instruct` - חזק יותר\n"
              "• `deepseek-ai/deepseek-coder-6.7b-instruct` - לקוד",
        inline=False
    )
    embed.add_field(
        name="📝 שימוש",
        value="`!model <מודל>` - מחליף מודל\n"
              "`!ai <שאלה>` - שואל את ה-AI",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command(name='setup_ai')
async def setup_ai_channel(ctx):
    if ctx.author.id not in ALLOWED_USER_IDS and not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ אין לך הרשאה.")
        return

    existing = discord.utils.get(ctx.guild.channels, name="🤖-ask-ai")
    if existing:
        await ctx.send(f"✅ כבר קיים: {existing.mention}")
        return

    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(
            send_messages=True,
            read_messages=True
        )
    }

    channel = await ctx.guild.create_text_channel(
        name="🤖-ask-ai",
        overwrites=overwrites,
        topic="🤖 תשאל אותי מה שבא לך."
    )

    embed = discord.Embed(
        title="🤖 ברוך הבא לחדר ה-AI",
        description="כתוב שאלה ואני אענה לך.\n"
                    "⚡ 5 שניות בין שאלות.\n\n"
                    "📚 להחלפת מודל: `!model <שם>`",
        color=discord.Color.purple()
    )
    await channel.send(embed=embed)

    await ctx.send(f"✅ חדר AI נוצר: {channel.mention}")

# ========== (שאר המערכות נשארות אותו דבר, קיצרתי כדי לא לשבור את הגבול) ==========

# ... כל השאר נשאר כמו קודם ...

keep_alive()

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    print("❌ DISCORD_TOKEN לא מוגדר!")
else:
    bot.run(TOKEN)
