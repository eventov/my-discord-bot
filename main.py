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

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

user_cooldowns = {}
user_link_warnings = {}
invites_cache = {}
user_last_messages = {}

LINK_REGEX = re.compile(r'https?://[^\s]+|discord\.gg/[^\s]+', re.IGNORECASE)

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

# --- Modal (טופס קלטים לשליחת הודעה בפרטי) ---
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
        required=True,
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

        embed = discord.Embed(
            title="📩 קיבלת הודעה מצוות הנהלת השרת",
            description=self.message_input.value,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"נשלח משרת {interaction.guild.name}")

        try:
            await target_user.send(embed=embed)
            await interaction.response.send_message(f"✅ ההודעה נשלחה בהצלחה ל-{target_user.mention}!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ המשתמש {target_user.mention} סגר את ההודעות הפרטיות שלו.", ephemeral=True)

# --- תצוגת הפאנל עם הכפתור לשליחת הודעה ---
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

# --- שאר התצוגות והכפתורים ---
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
    except discord.Forbidden:
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

@bot.event
async def on_ready():
    bot.add_view(CreateTicketView())
    bot.add_view(TicketControlView())
    bot.add_view(CheckInvitesView())
    bot.add_view(DropView())
    bot.add_view(DMPanelView())

    for guild in bot.guilds:
        try:
            invites_cache[guild.id] = await guild.invites()
        except discord.Forbidden:
            invites_cache[guild.id] = []

    print(f'הבוט מחובר בתור {bot.user}')

# --- פקודות מנהלים ---

@bot.command()
@is_allowed_user()
async def senddm(ctx, user: discord.User = None, *, message_text: str = None):
    """פקודה לשליחת הודעה פרטית ישירה + אפשרות לצירוף קבצים"""
    try:
        await ctx.message.delete()
    except Exception:
        pass

    if not user or (not message_text and not ctx.message.attachments):
        await ctx.send("❌ שימוש שגוי! דוגמה: `!senddm @user ההודעה שלך` (ניתן לצרף גם קבצים להודעה)", delete_after=6)
        return

    embed = discord.Embed(
        title="📩 קיבלת הודעה מצוות הנהלת השרת",
        description=message_text if message_text else "",
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"נשלח משרת {ctx.guild.name}")

    # העברת קבצים מצורפים
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
    """פקודה להעמדת פאנל שליחת הודעות פרטיות"""
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
