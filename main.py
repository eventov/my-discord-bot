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

# --- שרת WEB קטן כדי לשמור על הבוט ער ב-Render ---
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

# רשימת המורשים: ה-ID שלך + 4 ה-IDs של החברים שלך
ALLOWED_USER_IDS = [
    1228062821690904748,  # ה-ID שלך
    1519071293519953974,  # ID חבר 1
    1359539374496284917,  # ID חבר 2
    000000000000000000,  # ID חבר 3
    000000000000000000,  # ID חבר 4
]

INVITES_FILE = "invites_data.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

user_cooldowns = {}
user_link_warnings = {}
invites_cache = {}
user_last_messages = {}  # מעקב אחרי ספאם של הודעות זהות

LINK_REGEX = re.compile(r'https?://[^\s]+|discord\.gg/[^\s]+', re.IGNORECASE)


# --- פונקציות שמירה וטעינה של הזמנות למאגר קבוע ---
def load_invites_data():
    if not os.path.exists(INVITES_FILE):
        return {}
    try:
        with open(INVITES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"שגיאה שטעינת קובץ ההזמנות: {e}")
        return {}


def save_invites_data(data):
    try:
        with open(INVITES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"שגיאה בשמירת קובץ ההזמנות: {e}")


def add_invite_count(user_id: int):
    data = load_invites_data()
    str_id = str(user_id)
    data[str_id] = data.get(str_id, 0) + 1
    save_invites_data(data)


def get_invite_count(user_id: int) -> int:
    data = load_invites_data()
    return data.get(str(user_id), 0)


# פונקציית עזר לבדיקה אם המשתמש הוא Helper או Admin
def is_staff(user: discord.Member) -> bool:
    if user.guild_permissions.administrator:
        return True
    user_role_ids = [r.id for r in user.roles]
    return any(role_id in user_role_ids for role_id in HELPER_ROLE_IDS)


# בדיקת הרשאה לפקודות ניהול (מוחקת הודעה ושולחת הודעה פרטית בכחול)
def is_allowed_user():
    async def predicate(ctx):
        if (
            ctx.author.id in ALLOWED_USER_IDS
            or ctx.author.guild_permissions.administrator
        ):
            return True

        # מחיקת הודעת הניסיון של המשתמש הלא מורשה
        try:
            await ctx.message.delete()
        except Exception:
            pass

        # שליחת הודעה פרטית למשתמש הלא מורשה בלבד
        embed = discord.Embed(
            description="מה אתה מנסה בכלל",
            color=discord.Color.blue()
        )
        try:
            await ctx.author.send(embed=embed)
        except discord.Forbidden:
            pass

        return False

    return commands.check(predicate)


# --- תצוגת כפתור בדיקת הזמנות ---
class CheckInvitesView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="לחץ פה כדי לראות כמה אנשים הבאת! 📩",
        style=discord.ButtonStyle.green,
        custom_id="check_invites_btn",
    )
    async def check_invites(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        guild = interaction.guild
        user = interaction.user

        total_invites = get_invite_count(user.id)

        dm_embed = discord.Embed(
            title="📊 נתוני ההזמנות שלך",
            description=f"שלום {user.display_name},\nבדיקת ההזמנות שלך בשרת **{guild.name}**:",
            color=discord.Color.blue(),
        )
        dm_embed.add_field(
            name="✉️ סך הכל אנשים שהבאת:",
            value=f"**{total_invites}** משתמשים",
            inline=False,
        )
        dm_embed.set_footer(text="תודה שאתה עוזר להגדיל את הקהילה שלנו!")

        dm_sent = False
        try:
            await user.send(embed=dm_embed)
            dm_sent = True
        except discord.Forbidden:
            dm_sent = False

        if dm_sent:
            await interaction.response.send_message(
                "📩 נתוני ההזמנות שלך נשלחו אליך בהודעה פרטית!",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ לא הצלחנו לשלוח לך הודעה פרטית. יש לך כרגע **{total_invites}** הזמנות.",
                ephemeral=True,
            )


# --- תצוגת כפתור דרופ ---
class DropView(discord.ui.View):

    def __init__(self, prize: str = ""):
        super().__init__(timeout=None)
        self.prize = prize
        self.claimed = False

    @discord.ui.button(
        label="לקחת זכייה 🎁",
        style=discord.ButtonStyle.blurple,
        custom_id="claim_drop_btn",
    )
    async def claim_drop(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if self.claimed:
            await interaction.response.send_message(
                "הדרופ הזה כבר נלקח!", ephemeral=True
            )
            return

        self.claimed = True
        button.style = discord.ButtonStyle.green
        button.label = f"נלקח על ידי {interaction.user.display_name} 🎉"
        button.disabled = True

        await interaction.response.edit_message(view=self)

        ticket_link = "https://discord.com/channels/1539658262046048349/1542157535514075328"
        await interaction.followup.send(
            f"🎉 {interaction.user.mention} זכית בדרופ!\n"
            f"תפתח טיקט פה: {ticket_link}"
        )


# --- תצוגת הכפתורים בתוך הטיקט ---
class TicketControlView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="סגור טיקט 🔒",
        style=discord.ButtonStyle.red,
        custom_id="close_ticket_btn",
    )
    async def close_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "אין לך הרשאה לסגור טיקט זה! רק צוות התמיכה יכול לסגור טיקטים.",
                ephemeral=True,
            )
            return

        button.disabled = True
        await interaction.response.edit_message(view=self)

        if (
            interaction.channel.topic
            and "Ticket created by " in interaction.channel.topic
        ):
            try:
                creator_id = int(
                    interaction.channel.topic.replace("Ticket created by ", "")
                )
                user_cooldowns[creator_id] = time.time() + 120
            except ValueError:
                pass

        await interaction.followup.send("הטיקט ייסגר בעוד 5 שניות...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

    @discord.ui.button(
        label="קח טיקט 🖐️",
        style=discord.ButtonStyle.grey,
        custom_id="claim_ticket_btn",
    )
    async def claim_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "רק חברי צוות יכולים לקחת טיקטים!", ephemeral=True
            )
            return

        button.style = discord.ButtonStyle.green
        button.label = f"נלקח על ידי {interaction.user.display_name} 🟢"
        button.disabled = True

        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"**{interaction.user.display_name}** לקח את הטיקט ויתפנה לעזרתך בהקדם!"
        )


# --- תצוגת כפתור לפתיחת טיקט ---
class CreateTicketView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="פתח טיקט תמיכה 📩",
        style=discord.ButtonStyle.green,
        custom_id="create_ticket_btn",
    )
    async def create_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        guild = interaction.guild
        user = interaction.user
        category = guild.get_channel(TICKET_CATEGORY_ID)

        for channel in category.channels if category else guild.channels:
            if (
                channel.topic
                and f"Ticket created by {user.id}" in channel.topic
            ):
                await interaction.response.send_message(
                    f"כבר יש לך טיקט פתוח: {channel.mention}", ephemeral=True
                )
                return

        current_time = time.time()
        if user.id in user_cooldowns:
            remaining = int(user_cooldowns[user.id] - current_time)
            if remaining > 0:
                await interaction.response.send_message(
                    f"עליך להמתין עוד {remaining} שניות לפני שתוכל לפתוח טיקט חדש.",
                    ephemeral=True,
                )
                return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                read_messages=False
            ),
            user: discord.PermissionOverwrite(
                read_messages=True, send_messages=True, attach_files=True
            ),
            guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_channels=True,
            ),
        }

        for role_id in HELPER_ROLE_IDS:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True
                )

        channel_name = f"ticket-{user.name}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Ticket created by {user.id}",
        )

        await interaction.response.send_message(
            f"הטיקט שלך נפתח בהצלחה! {ticket_channel.mention}", ephemeral=True
        )

        ticket_embed = discord.Embed(
            title=f"שלום {user.display_name} 👋",
            description=(
                "תודה שפנית לצוות התמיכה!\nפרט את סיבת הפנייה וצוות התמיכה יענה לך בהקדם."
            ),
            color=discord.Color.blue(),
        )
        ticket_embed.set_footer(text="צוות התמיכה יטפל בפנייתך בהקדם.")

        await ticket_channel.send(
            embed=ticket_embed, view=TicketControlView()
        )


# --- זיהוי קישורים וספאם של הודעות ---
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    user_id = message.author.id
    now = time.time()
    clean_content = message.content.strip().lower()

    # --- מנגנון זיהוי ספאם של אותה הודעה ---
    if clean_content:
        user_history = user_last_messages.get(user_id, [])
        # סינון הודעות ישנות יותר מ-60 שניות
        user_history = [item for item in user_history if now - item['time'] < 60]

        # בדיקה כמה פעמים נשלחה אותה הודעה exact
        same_msg_count = sum(1 for item in user_history if item['content'] == clean_content) + 1

        user_history.append({'content': clean_content, 'time': now})
        user_last_messages[user_id] = user_history

        if same_msg_count >= 3:  # אם שלח את אותה הודעה 3 פעמים רצוף
            try:
                await message.delete()
            except Exception:
                pass

            timeout_duration = datetime.now(timezone.utc) + timedelta(minutes=5)
            try:
                await message.author.timeout(timeout_duration, reason="ספאם של אותה הודעה רצוף")
            except Exception as e:
                print(f"[שגיאת ספאם] {e}")

            unmute_time = int(now) + 300
            embed = discord.Embed(
                title="⚠️ קיבלת טיימאוט על ספאם!",
                description=f"הורחקת זמנית מדיבור בשרת **{message.guild.name}** ל-5 דקות עקב שליחת אותה הודעה בלולאה.",
                color=discord.Color.orange()
            )
            embed.add_field(name="⏳ זמן סיום הטיימאוט:", value=f"<t:{unmute_time}:R>", inline=False)
            embed.add_field(name="💬 ההודעה שהספמת:", value=message.content[:500], inline=False)
            embed.set_footer(text="יש להימנע משליחת הודעות כפולות כדי לשמור על סדר בצ'אט.")

            try:
                await message.author.send(embed=embed)
            except discord.Forbidden:
                pass

            return

    # --- מנגנון זיהוי קישורים ---
    if LINK_REGEX.search(message.content):
        try:
            await message.delete()
        except Exception as e:
            print(f"שגיאה במחיקת ההודעה: {e}")

        current_warnings = user_link_warnings.get(user_id, 0) + 1
        user_link_warnings[user_id] = current_warnings

        if current_warnings == 1:
            duration_minutes = 5
            embed_title = "⚠️ קיבלת טיימאוט! (אזהרה ראשונה)"
            warning_text = (
                "חל איסור לשלוח קישורים בשרת. פעם הבאה שתשלח קישור תקבל טיימאוט ל-10 דקות!"
            )
        elif current_warnings == 2:
            duration_minutes = 10
            embed_title = "⚠️ קיבלת טיימאוט! (אזהרה שנייה)"
            warning_text = (
                "זוהי אזהרה שנייה! פעם הבאה שתשלח קישור תקבל טיימאוט ליום שלם (24 שעות)!"
            )
        else:
            duration_minutes = 1440
            embed_title = "🚨 קיבלת טיימאוט ליום שלם!"
            warning_text = (
                "המשכת לשלוח קישורים למרות האזהרות. קיבלת טיימאוט ל-24 שעות."
            )

        timeout_duration = datetime.now(timezone.utc) + timedelta(
            minutes=duration_minutes
        )
        try:
            await message.author.timeout(
                timeout_duration, reason="שליחת קישורים אסורים"
            )
        except Exception as e:
            print(f"[שגיאה בטיימאוט] {e}")

        unmute_time_unix = int(time.time()) + (duration_minutes * 60)

        embed = discord.Embed(
            title=embed_title,
            description=(
                f"הורחקת זמנית מדיבור בשרת **{message.guild.name}** על שליחת קישור."
            ),
            color=discord.Color.red(),
        )
        embed.add_field(
            name="⏳ זמן סיום הטימאוט:",
            value=(
                f"<t:{unmute_time_unix}:R> (בתאריך <t:{unmute_time_unix}:f>)"
            ),
            inline=False,
        )
        embed.add_field(name="📌 הערה:", value=warning_text, inline=False)

        deleted_content = message.content[:1000]
        embed.add_field(
            name="💬 ההודעה שנמחקה לך:",
            value=deleted_content,
            inline=False,
        )
        embed.set_footer(
            text="יש לשמור על חוקי השרת כדי להימנע מעונשים נוספים."
        )

        try:
            await message.author.send(embed=embed)
        except discord.Forbidden:
            pass

        return

    await bot.process_commands(message)


# --- אירוע הצטרפות משתמש חדש + מעקב והוספת ניקוד ---
@bot.event
async def on_member_join(member: discord.Member):
    role = member.guild.get_role(AUTO_ROLE_ID)
    if role:
        try:
            await member.add_roles(role)
        except discord.Forbidden:
            print(
                "אין הרשאה לתת את הרול (ודא שרול הבוט גבוה יותר ברשימה)."
            )

    inviter = None
    old_invites = invites_cache.get(member.guild.id, [])
    try:
        new_invites = await member.guild.invites()
        for old_inv in old_invites:
            for new_inv in new_invites:
                if old_inv.code == new_inv.code:
                    if new_inv.uses > old_inv.uses:
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
            description=(
                f"שלום {member.mention}, שמחים שהצטרפת אלינו!\n"
                f"📌 **ממי הגיע:** {inviter_text}\n"
                "מאחלים לך שהות מהנה בשרת."
            ),
            color=discord.Color.green(),
        )
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        embed.set_footer(text=f"חבר שרת מספר #{len(member.guild.members)}")

        await welcome_channel.send(
            content=f"שלום לכולם, תברכו את {member.mention}!", embed=embed
        )


@bot.event
async def on_ready():
    bot.add_view(CreateTicketView())
    bot.add_view(TicketControlView())
    bot.add_view(CheckInvitesView())
    bot.add_view(DropView())

    for guild in bot.guilds:
        try:
            invites_cache[guild.id] = await guild.invites()
        except discord.Forbidden:
            invites_cache[guild.id] = []

    print(f'הבוט מחובר בתור {bot.user}')


# --- פקודות מוגבלות למשתמשים מורשים בלבד ---

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
        warning_msg = await ctx.send(
            "❌ יש לציין מספר הודעות למחיקה! לדוגמה: `!מחיקה 10`"
        )
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
        description=(
            "רוצה לדעת כמה חברים הזמנת לשרת?\nלחץ על הכפתור למטה והבוט ישלח"
            " לך את הנתונים בפרטי!"
        ),
        color=discord.Color.blue(),
    )
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)

    await ctx.send(embed=embed, view=CheckInvitesView())


@bot.command(name="drop", aliases=["DROP"])
@is_allowed_user()
async def drop_command(ctx, *, prize: str = None):
    try:
        await ctx.message.delete()
    except Exception:
        pass

    if not prize:
        warning_msg = await ctx.send(
            "❌ יש לציין את מהות הזכייה! לדוגמה: `!drop משתמש נדיר`"
        )
        await asyncio.sleep(5)
        await warning_msg.delete()
        return

    embed = discord.Embed(
        title="🎁 דרופ חדש בשרת!",
        description="מי שלוחץ ראשון על הכפתור למטה זוכה בדרופ!",
        color=discord.Color.gold(),
    )
    embed.add_field(name="🏆 זכייה:", value=f"**{prize}**", inline=False)
    embed.set_footer(text="בהצלחה לכולם!")

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
        description=(
            "זקוק לעזרה? רוצה לפתוח פנייה לצוות השרת?\nלחץ על הכפתור למטה כדי"
            " לפתוח טיקט פרטי!"
        ),
        color=discord.Color.gold(),
    )
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    embed.add_field(
        name="⏰ שעות פעילות",
        value="צוות התמיכה עונה בהקדם האפשרי.",
        inline=False,
    )
    embed.add_field(
        name="⚠️ שיוך נושאים",
        value="יש לשמור על שפה נאותה ולהסביר את הבעיה בפירוט.",
        inline=False,
    )

    await ctx.send(embed=embed, view=CreateTicketView())


@bot.command()
@is_allowed_user()
async def testjoin(ctx):
    await ctx.send("🧪 מריץ בדיקה של מערכת קבלת הפנים...")
    bot.dispatch('member_join', ctx.author)


# הפעלת שרת ה-Web ברקע
keep_alive()

TOKEN = os.environ.get(
    "DISCORD_TOKEN",
    "MTUwODQ0MDU0NTExMzE0OTQ2MA.GnDqaw.XS13vYup_meP9A7wy4JRwvLf1EgLmjJku9VmvQ",
)
bot.run(TOKEN)
