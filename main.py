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
from google import genai

# --- שרת WEB קטן לשמירה על הבוט ער ב-Render ---
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

# --- הגדרות מזהים (IDs) ---
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
    000000000000000000,
    000000000000000000,
]

INVITES_FILE = "invites_data.json"
TICKETS_FILE = "tickets_data.json"
SETTINGS_FILE = "settings_data.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

user_cooldowns = {}
user_link_warnings = {}
invites_cache = {}
user_last_messages = {}

LINK_REGEX = re.compile(r'https?://[^\s]+|discord\.gg/[^\s]+', re.IGNORECASE)

# ========== אתחול מנוע ה-AI (Google Gemini) ==========
gemini_key = os.environ.get("GEMINI_API_KEY")
client_ai = genai.Client(api_key=gemini_key) if gemini_key else None

async def ask_ai(prompt: str) -> str:
    """פונקציה לשליחת בקשה ל-Gemini API"""
    if not client_ai:
        return "❌ שגיאה: מפתח ה-API (GEMINI_API_KEY) לא מוגדר במשתני הסביבה ב-Render!"

    loop = asyncio.get_running_loop()
    def _fetch():
        try:
            response = client_ai.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt,
            )
            return response.text
        except Exception as e:
            print(f"AI Error: {e}")
            return f"מצטער, הייתה שגיאה בחיבור ל-AI: {e}"

    return await loop.run_in_executor(None, _fetch)

# ========== פונקציות שמירה והטענת הגדרות ==========
def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {"ai_channel_id": None}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"ai_channel_id": None}

def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

# ========== מערכת ביקורות ==========
class ReviewModal(discord.ui.Modal, title='✍️ כתיבת ביקורת'):
    system_name = discord.ui.TextInput(
        label='שם המערכת / השירות',
        placeholder='לדוגמה: תמיכה טכנית, השרת באופן כללי, בוטים וכו...',
        min_length=2,
        max_length=50,
        required=True
    )

    rating = discord.ui.TextInput(
        label='דירוג (בין 1 ל-5 כוכבים)',
        placeholder='רשום מספר מ-1 עד 5',
        min_length=1,
        max_length=1,
        required=True
    )

    review_text = discord.ui.TextInput(
        label='תוכן הביקורת',
        style=discord.TextStyle.paragraph,
        placeholder='תכתוב את כל מה שמי שתרצה על השרת והתמיכה שלנו...',
        min_length=5,
        max_length=1000,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        stars_input = self.rating.value.strip()
        if not stars_input.isdigit() or not (1 <= int(stars_input) <= 5):
            await interaction.response.send_message("❌ נא להזין מספר תקין של כוכבים בין 1 ל-5!", ephemeral=True)
            return

        num_stars = int(stars_input)
        stars_display = "⭐" * num_stars

        reviews_channel = interaction.guild.get_channel(REVIEWS_CHANNEL_ID)
        if not reviews_channel:
            await interaction.response.send_message("❌ ערוץ הביקורות לא נמצא. אנא פנה להנהלה.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"⭐ ביקורת חדשה: {self.system_name.value}",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 נכתב על ידי:", value=interaction.user.mention, inline=True)
        embed.add_field(name="⭐ דירוג:", value=f"{stars_display} ({num_stars}/5)", inline=True)
        embed.add_field(name="📌 שם המערכת:", value=self.system_name.value, inline=False)
        embed.add_field(name="📝 תיאור וחוות דעת:", value=self.review_text.value, inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"שרת {interaction.guild.name}", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)

        await reviews_channel.send(embed=embed)
        await interaction.response.send_message("✅ תודה רבה! הביקורת שלך נשלחה בהצלחה.", ephemeral=True)


class ReviewPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✍️ כתוב ביקורת",
        style=discord.ButtonStyle.success,
        custom_id="write_review_btn"
    )
    async def open_review_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReviewModal())


@bot.command()
@commands.has_permissions(administrator=True)
async def setup_reviews(ctx):
    try:
        await ctx.message.delete()
    except Exception:
        pass

    embed = discord.Embed(
        title="⭐ מערכת ביקורות וחוות דעת",
        description="נשמח לשמוע את דעתך על השרת והתמיכה שלנו!\nלחץ על הכפתור למטה כדי לכתוב ביקורת.",
        color=discord.Color.gold()
    )
    embed.set_footer(text="כל הביקורות עוזרות לנו להשתפר!")
    await ctx.send(embed=embed, view=ReviewPanelView())

# ========== פונקציות IP ==========
def get_ip_info(ip):
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,zip,lat,lon,timezone,isp,org,as,reverse,mobile,proxy,hosting,query")
        data = response.json()

        if data['status'] == 'success':
            private_ips = ['127.', '10.', '192.168.', '172.16.', '172.17.', '172.18.', '172.19.', '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', '172.25.', '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.']
            is_private = any(ip.startswith(prefix) for prefix in private_ips)

            info = {
                'IP': data['query'],
                'סוג IP': 'פרטי' if is_private else 'ציבורי',
                'מדינה': data.get('country', 'לא ידוע'),
                'אזור': data.get('regionName', 'לא ידוע'),
                'עיר': data.get('city', 'לא ידוע'),
                'מיקוד': data.get('zip', 'לא ידוע'),
                'קואורדינטות': f"{data.get('lat', '')}, {data.get('lon', '')}",
                'אזור זמן': data.get('timezone', 'לא ידוע'),
                'ספק אינטרנט (ISP)': data.get('isp', 'לא ידוע'),
                'ארגון': data.get('org', 'לא ידוע'),
                'AS (Autonomous System)': data.get('as', 'לא ידוע'),
                'שם הפוך (DNS)': data.get('reverse', 'לא נמצא'),
                'חיבור סלולרי': 'כן' if data.get('mobile', False) else 'לא',
                'Proxy/VPN': 'כן' if data.get('proxy', False) else 'לא',
                'חוות שרתים': 'כן' if data.get('hosting', False) else 'לא'
            }
            return info, True
        else:
            return data.get('message', 'שגיאה לא ידועה'), False
    except Exception as e:
        return f"שגיאה: {str(e)}", False

class IPModal(discord.ui.Modal, title='🔍 בדיקת IP'):
    ip_input = discord.ui.TextInput(
        label='הזן כתובת IP',
        placeholder='לדוגמה: 8.8.8.8',
        min_length=1,
        max_length=45,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ip = self.ip_input.value.strip()
        await interaction.followup.send(f"🔄 בודק IP: `{ip}`...", ephemeral=True)
        result, success = get_ip_info(ip)

        if not success:
            embed = discord.Embed(
                title='❌ שגיאה',
                description=f'לא ניתן לקבל מידע על IP זה:\n{result}',
                color=discord.Color.red()
            )
            await interaction.user.send(embed=embed)
            await interaction.followup.send("✅ המידע נשלח לך ב-DM!", ephemeral=True)
            return

        embed = discord.Embed(
            title='🌐 מידע על IP',
            description=f'מידע מלא עבור **{result["IP"]}**',
            color=discord.Color.blue()
        )

        fields = [
            ('📋 מידע כללי', f'**סוג IP:** {result["סוג IP"]}\n**מדינה:** {result["מדינה"]}\n**אזור:** {result["אזור"]}\n**עיר:** {result["עיר"]}\n**מיקוד:** {result["מיקוד"]}'),
            ('📍 מיקום', f'**קואורדינטות:** {result["קואורדינטות"]}\n**אזור זמן:** {result["אזור זמן"]}'),
            ('🔌 מידע על ספק', f'**ספק אינטרנט:** {result["ספק אינטרנט (ISP)"]}\n**ארגון:** {result["ארגון"]}\n**AS:** {result["AS (Autonomous System)"]}'),
            ('🛠 מידע טכני', f'**DNS Reverse:** {result["שם הפוך (DNS)"]}\n**חיבור סלולרי:** {result["חיבור סלולרי"]}\n**Proxy/VPN:** {result["Proxy/VPN"]}\n**חוות שרתים:** {result["חוות שרתים"]}')
        ]

        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)

        embed.set_footer(text=f'🕒 {discord.utils.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC')
        embed.set_thumbnail(url='https://cdn-icons-png.flaticon.com/512/5337/5337582.png')

        try:
            await interaction.user.send(embed=embed)
            await interaction.followup.send("✅ המידע נשלח לך ב-DM!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ לא ניתן לשלוח לך DM. אנא פתח את ה-DMs שלך.", ephemeral=True)

class IPButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='🔍 בדוק IP', style=discord.ButtonStyle.primary, emoji='🌐')
    async def ip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IPModal())

# --- פונקציות עזר ונתונים ---
def load_invites_data():
    if not os.path.exists(INVITES_FILE):
        return {}
    try:
        with open(INVITES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_invites_data(data):
    try:
        with open(INVITES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

def add_invite_count(user_id: int):
    data = load_invites_data()
    str_id = str(user_id)
    data[str_id] = data.get(str_id, 0) + 1
    save_invites_data(data)

def get_invite_count(user_id: int) -> int:
    data = load_invites_data()
    return data.get(str(user_id), 0)

def load_tickets_data():
    if not os.path.exists(TICKETS_FILE):
        return {"channel_id": None, "message_id": None, "users": {}}
    try:
        with open(TICKETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"channel_id": None, "message_id": None, "users": {}}

def save_tickets_data(data):
    try:
        with open(TICKETS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

def add_ticket_count(user_id: int):
    data = load_tickets_data()
    str_id = str(user_id)
    data["users"][str_id] = data["users"].get(str_id, 0) + 1
    save_tickets_data(data)

def create_leaderboard_embed(guild: discord.Guild) -> discord.Embed:
    data = load_tickets_data()
    users_data = data.get("users", {})
    sorted_users = sorted(users_data.items(), key=lambda x: x[1], reverse=True)

    embed = discord.Embed(
        title="🏆 לוח מובילים - טיקטים שטופלו",
        description="דירוג חברי הצוות לפי כמות הטיקטים שלקחו:",
        color=discord.Color.gold(),
    )

    if not sorted_users:
        embed.add_field(name="מידע:", value="טרם נלקחו טיקטים במערכת.", inline=False)
    else:
        medals = ["🥇", "🥈", "🥉"]
        leaderboard_text = ""
        for index, (user_id_str, count) in enumerate(sorted_users, start=1):
            user_id = int(user_id_str)
            member = guild.get_member(user_id)
            name = member.mention if member else f"<@{user_id}>"
            prefix = medals[index - 1] if index <= 3 else f"**#{index}**"
            leaderboard_text += f"{prefix} {name} - **{count}** טיקטים\n"

        embed.add_field(name="דירוג צוות:", value=leaderboard_text, inline=False)

    embed.set_footer(text="הנתונים מתעדכנים אוטומטית בכל פעם שאיש צוות לוקח טיקט!")
    return embed

async def update_leaderboard(guild: discord.Guild):
    data = load_tickets_data()
    channel_id = data.get("channel_id")
    message_id = data.get("message_id")
    if not channel_id or not message_id:
        return
    channel = guild.get_channel(channel_id)
    if not channel:
        return
    try:
        message = await channel.fetch_message(message_id)
        embed = create_leaderboard_embed(guild)
        await message.edit(embed=embed)
    except Exception as e:
        print(f"שגיאה בעדכון לוח המובילים: {e}")

def is_staff(user: discord.Member) -> bool:
    if user.guild_permissions.administrator:
        return True
    user_role_ids = [r.id for r in user.roles]
    return any(role_id in user_role_ids for role_id in HELPER_ROLE_IDS)

def is_allowed_user():
    async def predicate(ctx):
        if ctx.author.id in ALLOWED_USER_IDS or ctx.author.guild_permissions.administrator:
            return True
        try:
            await ctx.message.delete()
        except Exception:
            pass
        embed = discord.Embed(description="מה אתה מנסה בכלל", color=discord.Color.blue())
        try:
            await ctx.author.send(embed=embed)
        except discord.Forbidden:
            pass
        return False
    return commands.check(predicate)

class SendDMModal(discord.ui.Modal, title="שליחת הודעה פרטית למשתמש"):
    user_id_input = discord.ui.TextInput(
        label="ID של המשתמש",
        placeholder="הכנס את ה-ID של המשתמש כאן...",
        required=True,
        max_length=20
    )

    message_input = discord.ui.TextInput(
        label="מה לשלוח?",
        style=discord.TextStyle.paragraph,
        placeholder="כתוב את ההודעה שברצונך לשלוח...",
        required=False,
        max_length=2000
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target_user_id = int(self.user_id_input.value.strip())
            target_user = await interaction.client.fetch_user(target_user_id)
        except ValueError:
            await interaction.response.send_message("❌ ה-ID שהכנסת אינו תקין!", ephemeral=True)
            return
        except discord.NotFound:
            await interaction.response.send_message("❌ לא נמצא משתמש עם ה-ID הזה!", ephemeral=True)
            return

        message_text = self.message_input.value or ""

        await interaction.response.send_message(
            "⏳ **רוצה לצרף קובץ/תמונה להודעה?**\n"
            "שלח עכשיו את הקובץ בצ'אט בתוך **30 שניות** (או כתוב `no` / חכה לסיום הזמן כדי לשלוח רק טקסט).",
            ephemeral=True
        )

        files_to_send = []

        def check(m):
            return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id

        try:
            msg = await interaction.client.wait_for('message', timeout=30.0, check=check)
            if msg.attachments:
                for attachment in msg.attachments:
                    file = await attachment.to_file()
                    files_to_send.append(file)
                try:
                    await msg.delete()
                except Exception:
                    pass
            elif msg.content.lower() == 'no':
                try:
                    await msg.delete()
                except Exception:
                    pass
        except asyncio.TimeoutError:
            pass

        if not message_text and not files_to_send:
            await interaction.followup.send("❌ לא הזנת טקסט ולא צירפת קובץ, השליחה בוטלה.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📩 קיבלת הודעה מצוות הנהלת השרת",
            description=message_text if message_text else None,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"נשלח משרת {interaction.guild.name}")

        try:
            await target_user.send(embed=embed, files=files_to_send)
            await interaction.followup.send(f"✅ ההודעה (והקבצים) נשלחו בהצלחה ל-{target_user.mention}!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"❌ המשתמש {target_user.mention} סגר את ההודעות הפרטיות שלו.", ephemeral=True)

class DMPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="שלח הודעה פרטית למשתמש ✉️",
        style=discord.ButtonStyle.blurple,
        custom_id="send_dm_btn"
    )
    async def open_dm_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (interaction.user.id in ALLOWED_USER_IDS or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("אין לך הרשאה להשתמש בפאנל זה!", ephemeral=True)
            return

        await interaction.response.send_modal(SendDMModal())

class IPPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔍 בדוק IP",
        style=discord.ButtonStyle.primary,
        custom_id="ip_check_btn",
        emoji="🌐"
    )
    async def open_ip_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (interaction.user.id in ALLOWED_USER_IDS or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("אין לך הרשאה להשתמש בפאנל זה!", ephemeral=True)
            return

        await interaction.response.send_modal(IPModal())

class CheckInvitesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="לחץ פה כדי לראות כמה אנשים הבאת! 📩", style=discord.ButtonStyle.green, custom_id="check_invites_btn")
    async def check_invites(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        total_invites = get_invite_count(user.id)
        dm_embed = discord.Embed(
            title="📊 נתוני ההזמנות שלך",
            description=f"שלום {user.display_name},\nבדיקת ההזמנות שלך בשרת **{interaction.guild.name}**:",
            color=discord.Color.blue(),
        )
        dm_embed.add_field(name="✉️ סך הכל אנשים שהבאת:", value=f"**{total_invites}** משתמשים", inline=False)
        try:
            await user.send(embed=dm_embed)
            await interaction.response.send_message("📩 נתוני ההזמנות שלך נשלחו אליך בהודעה פרטית!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ לא הצלחנו לשלוח לך הודעה פרטית. יש לך כרגע **{total_invites}** הזמנות.", ephemeral=True)

class DropView(discord.ui.View):
    def __init__(self, prize: str = ""):
        super().__init__(timeout=None)
        self.prize = prize
        self.claimed = False

    @discord.ui.button(label="לקחת זכייה 🎁", style=discord.ButtonStyle.blurple, custom_id="claim_drop_btn")
    async def claim_drop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.claimed:
            await interaction.response.send_message("הדרופ הזה כבר נלקח!", ephemeral=True)
            return
        self.claimed = True
        button.style = discord.ButtonStyle.green
        button.label = f"נלקח על ידי {interaction.user.display_name} 🎉"
        button.disabled = True
        await interaction.response.edit_message(view=self)
        ticket_link = "https://discord.com/channels/1539658262046048349/1542157535514075328"
        await interaction.followup.send(f"🎉 {interaction.user.mention} זכית בדרופ!\nתפתח טיקט פה: {ticket_link}")

class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="סגור טיקט 🔒", style=discord.ButtonStyle.red, custom_id="close_ticket_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("אין לך הרשאה לסגור טיקט זה! רק צוות התמיכה יכול לסגור טיקטים.", ephemeral=True)
            return
        button.disabled = True
        await interaction.response.edit_message(view=self)
        if interaction.channel.topic and "Ticket created by " in interaction.channel.topic:
            try:
                creator_id = int(interaction.channel.topic.replace("Ticket created by ", ""))
                user_cooldowns[creator_id] = time.time() + 120
            except ValueError:
                pass
        await interaction.followup.send("הטיקט ייסגר בעוד 5 שניות...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

    @discord.ui.button(label="קח טיקט 🖐️", style=discord.ButtonStyle.grey, custom_id="claim_ticket_btn")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("רק חברי צוות יכולים לקחת טיקטים!", ephemeral=True)
            return
        button.style = discord.ButtonStyle.green
        button.label = f"נלקח על ידי {interaction.user.display_name} 🟢"
        button.disabled = True
        add_ticket_count(interaction.user.id)
        await update_leaderboard(interaction.guild)
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"**{interaction.user.display_name}** לקח את הטיקט ויתפנה לעזרתך בהקדם!")

class CreateTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="פתח טיקט תמיכה 📩", style=discord.ButtonStyle.green, custom_id="create_ticket_btn")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        category = guild.get_channel(TICKET_CATEGORY_ID)
        for channel in category.channels if category else guild.channels:
            if channel.topic and f"Ticket created by {user.id}" in channel.topic:
                await interaction.response.send_message(f"כבר יש לך טיקט פתוח: {channel.mention}", ephemeral=True)
                return
        current_time = time.time()
        if user.id in user_cooldowns:
            remaining = int(user_cooldowns[user.id] - current_time)
            if remaining > 0:
                await interaction.response.send_message(f"עליך להמתין עוד {remaining} שניות לפני שתוכל לפתוח טיקט חדש.", ephemeral=True)
                return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        }
        for role_id in HELPER_ROLE_IDS:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{user.name}",
            category=category,
            overwrites=overwrites,
            topic=f"Ticket created by {user.id}",
        )
        await interaction.response.send_message(f"הטיקט שלך נפתח בהצלחה! {ticket_channel.mention}", ephemeral=True)
        ticket_embed = discord.Embed(
            title=f"שלום {user.display_name} 👋",
            description="תודה שפנית לצוות התמיכה!\nפרט את סיבת הפנייה וצוות התמיכה יענה לך בהקדם.",
            color=discord.Color.blue(),
        )
        await ticket_channel.send(embed=ticket_embed, view=TicketControlView())

# --- אירוע הודעות ---
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    user_id = message.author.id
    now = time.time()
    clean_content = message.content.strip().lower()

    settings = load_settings()
    ai_channel_id = settings.get("ai_channel_id")

    is_mentioned = bot.user in message.mentions
    is_reply_to_bot = (
        message.reference 
        and message.reference.resolved 
        and isinstance(message.reference.resolved, discord.Message)
        and message.reference.resolved.author == bot.user
    )
    is_ai_channel = (ai_channel_id is not None and message.channel.id == ai_channel_id)

    if is_mentioned or is_reply_to_bot or is_ai_channel:
        ai_prompt = message.content.replace(f'<@{bot.user.id}>', '').strip()
        if not ai_prompt:
            ai_prompt = "שלום"

        async with message.channel.typing():
            response = await ask_ai(ai_prompt)
            if len(response) > 2000:
                for i in range(0, len(response), 1900):
                    await message.reply(response[i:i+1900])
            else:
                await message.reply(response)
        return

    if clean_content:
        user_history = user_last_messages.get(user_id, [])
        user_history = [item for item in user_history if now - item['time'] < 60]
        same_msg_count = sum(1 for item in user_history if item['content'] == clean_content) + 1
        user_history.append({'content': clean_content, 'time': now})
        user_last_messages[user_id] = user_history

        if same_msg_count >= 3:
            try:
                await message.delete()
            except Exception:
                pass
            timeout_duration = datetime.now(timezone.utc) + timedelta(minutes=5)
            try:
                await message.author.timeout(timeout_duration, reason="ספאם של אותה הודעה")
            except Exception:
                pass
            return

    if LINK_REGEX.search(message.content):
        try:
            await message.delete()
        except Exception:
            pass
        current_warnings = user_link_warnings.get(user_id, 0) + 1
        user_link_warnings[user_id] = current_warnings
        duration_minutes = 5 if current_warnings == 1 else (10 if current_warnings == 2 else 1440)
        timeout_duration = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        try:
            await message.author.timeout(timeout_duration, reason="שליחת קישורים")
        except Exception:
            pass
        return

    await bot.process_commands(message)

# ========== פונקציית עדכון הסטטוס ==========
async def update_bot_presence():
    total_members = sum(guild.member_count for guild in bot.guilds if guild.member_count)
    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name=f"{total_members} members"
    )
    await bot.change_presence(activity=activity)

@bot.event
async def on_member_join(member: discord.Member):
    role = member.guild.get_role(AUTO_ROLE_ID)
    if role:
        try:
            await member.add_roles(role)
        except discord.Forbidden:
            pass

    inviter = None
    old_invites = invites_cache.get(member.guild.id, [])
    try:
        new_invites = await member.guild.invites()
        for old_inv in old_invites:
            for new_inv in new_invites:
                if old_inv.code == new_inv.code and new_inv.uses > old_inv.uses:
                    inviter = new_inv.inviter
                    break
        invites_cache[member.guild.id] = new_invites
    except Exception:
        pass

    if inviter and not inviter.bot:
        add_invite_count(inviter.id)

    welcome_channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if welcome_channel:
        inviter_text = f"הוזמן/ה על ידי {inviter.mention}" if inviter else "הצטרף/ה באופן עצמאי"
        embed = discord.Embed(
            title="ברוך הבא לשרת! 🎉",
            description=f"שלום {member.mention}, שמחים שהצטרפת אלינו!\n📌 **ממי הגיע:** {inviter_text}",
            color=discord.Color.green(),
        )
        await welcome_channel.send(content=f"שלום לכולם, תברכו את {member.mention}!", embed=embed)

    try:
        await update_bot_presence()
    except Exception:
        pass

@bot.event
async def on_member_remove(member: discord.Member):
    try:
        await update_bot_presence()
    except Exception:
        pass

# ========== אירוע להתחברות הבוט (מוגן) ==========
@bot.event
async def on_ready():
    try:
        bot.add_view(CreateTicketView())
        bot.add_view(TicketControlView())
        bot.add_view(CheckInvitesView())
        bot.add_view(DropView())
        bot.add_view(DMPanelView())
        bot.add_view(IPButton())
        bot.add_view(IPPanelView())
        bot.add_view(ReviewPanelView())
    except Exception as e:
        print(f"Error adding views: {e}")

    try:
        await update_bot_presence()
        print("Bot status successfully set!")
    except Exception as e:
        print(f"Error setting bot presence: {e}")

    print(f'הבוט מחובר בתור {bot.user}')

# ========== פקודות ==========
@bot.command(name='setup_ai', aliases=['ai_setup'])
@is_allowed_user()
async def setup_ai_channel(ctx):
    try:
        await ctx.message.delete()
    except Exception:
        pass

    settings = load_settings()
    settings["ai_channel_id"] = ctx.channel.id
    save_settings(settings)

    embed = discord.Embed(
        title="🤖 ערוץ AI הוגדר בהצלחה!",
        description=f"מהיום הערוץ {ctx.channel.mention} מוגדר כערוץ AI רשמי.\nכל הודעה שנשלחת כאן תקבל מענה אוטומטי מה-AI!",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

@bot.command(name='ip')
async def ip_command(ctx):
    await ctx.send("🌐 **לחץ על הכפתור לבדיקת IP:**", view=IPButton())

@bot.command(name='ipbutton')
@is_allowed_user()
async def ipbutton_command(ctx):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.send("🌐 **לחץ על הכפתור לבדיקת IP:**", view=IPButton())

@bot.command(name='setup_ip')
@is_allowed_user()
async def setup_ip_panel(ctx):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    embed = discord.Embed(
        title="🌐 בדיקת IP",
        description="לחץ על הכפתור למטה לבדיקת כתובת IP.\nכל התוצאות יישלחו אליך בהודעה פרטית!",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=IPPanelView())

@bot.command()
@is_allowed_user()
async def senddm(ctx, user: discord.User = None, *, message_text: str = None):
    try:
        await ctx.message.delete()
    except Exception:
        pass

    if not user or (not message_text and not ctx.message.attachments):
        await ctx.send("❌ שימוש שגוי! דוגמה: `!senddm @user ההודעה שלך`", delete_after=6)
        return

    embed = discord.Embed(
        title="📩 קיבלת הודעה מצוות הנהלת השרת",
        description=message_text if message_text else "",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"נשלח משרת {ctx.guild.name}")

    files_to_send = []
    for attachment in ctx.message.attachments:
        file = await attachment.to_file()
        files_to_send.append(file)

    try:
        await user.send(embed=embed, files=files_to_send)
        await ctx.send(f"✅ ההודעה (והקבצים) נשלחו בהצלחה ל-{user.mention}!", delete_after=5)
    except discord.Forbidden:
        await ctx.send(f"❌ המשתמש {user.mention} סגר את ההודעות הפרטיות שלו.", delete_after=5)

@bot.command()
@is_allowed_user()
async def setup_dmpanel(ctx):
    try:
        await ctx.message.delete()
    except Exception:
        pass

    embed = discord.Embed(
        title="✉️ פאנל שליחת הודעות פרטיות",
        description="לחץ על הכפתור למטה כדי לפתוח חלון לשליחת הודעה פרטית בדיסקורד לפי ID.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=DMPanelView())

@bot.command()
@is_allowed_user()
async def setup_leaderboard(ctx):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    embed = create_leaderboard_embed(ctx.guild)
    msg = await ctx.send(embed=embed)
    data = load_tickets_data()
    data["channel_id"] = ctx.channel.id
    data["message_id"] = msg.id
    save_tickets_data(data)
    await ctx.send("✅ ערוץ לוח המובילים של הטיקטים הוגדר בהצלחה!", delete_after=5)

@bot.command()
@is_allowed_user()
async def reset_tickets(ctx):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    data = load_tickets_data()
    data["users"] = {}
    save_tickets_data(data)
    await update_leaderboard(ctx.guild)
    await ctx.send("🧹 ספירת הטיקטים אופסה בהצלחה!", delete_after=5)

@bot.command()
@is_allowed_user()
async def setinvites(ctx, member: discord.Member = None, amount: int = None):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    if not member or amount is None:
        await ctx.send("❌ שימוש שגוי! דוגמה: `!setinvites @user 5`", delete_after=5)
        return
    data = load_invites_data()
    data[str(member.id)] = amount
    save_invites_data(data)
    await ctx.send(f"✅ עודכן בהצלחה! ל-{member.mention} יש עכשיו **{amount}** הזמנות.")

@bot.command(name="מחיקה", aliases=["clear", "purge"])
@is_allowed_user()
async def clear_messages(ctx, amount: int = None):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    if amount is None or amount <= 0:
        warning_msg = await ctx.send("❌ יש לציין מספר הודעות למחיקה!")
        await asyncio.sleep(4)
        await warning_msg.delete()
        return
    deleted = await ctx.channel.purge(limit=amount)
    info_msg = await ctx.send(f"🧹 נמחקו בהצלחה **{len(deleted)}** הודעות!")
    await asyncio.sleep(3)
    await info_msg.delete()

@bot.command()
@is_allowed_user()
async def setup_invites(ctx):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    embed = discord.Embed(
        title="📊 בדיקת הזמנות",
        description="רוצה לדעת כמה חברים הזמנת לשרת?\nלחץ על הכפתור למטה והבוט ישלח לך את הנתונים בפרטי!",
        color=discord.Color.blue(),
    )
    await ctx.send(embed=embed, view=CheckInvitesView())

@bot.command(name="drop", aliases=["DROP"])
@is_allowed_user()
async def drop_command(ctx, *, prize: str = None):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    if not prize:
        warning_msg = await ctx.send("❌ יש לציין את מהות הזכייה!")
        await asyncio.sleep(5)
        await warning_msg.delete()
        return
    embed = discord.Embed(
        title="🎁 דרופ חדש בשרת!",
        description="מי שלוחץ ראשון על הכפתור למטה זוכה בדרופ!",
        color=discord.Color.gold(),
    )
    embed.add_field(name="🏆 זכייה:", value=f"**{prize}**", inline=False)
    await ctx.send(embed=embed, view=DropView(prize=prize))

@bot.command()
@is_allowed_user()
async def setup_ticket(ctx):
    try:
        await ctx.message.delete()
    except Exception:
        pass
    embed = discord.Embed(
        title="🎫 מערכת תמיכה ופניות",
        description="זקוק לעזרה? רוצה לפתוח פנייה לצוות השרת?\nלחץ על הכפתור למטה כדי לפתוח טיקט פרטי!",
        color=discord.Color.gold(),
    )
    await ctx.send(embed=embed, view=CreateTicketView())

keep_alive()

TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(TOKEN)
