import asyncio
import time
import re
import os
from threading import Thread
from datetime import datetime, timedelta, timezone
from flask import Flask
import discord
from discord.ext import commands

# --- שרת WEB קטן כדי לתרצות את Render ---
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
HELPER_ROLE_ID = 1508433031034179704  
TICKET_CATEGORY_ID = 1508436954365165659
WELCOME_CHANNEL_ID = 1508440105273266206  
AUTO_ROLE_ID = 1508443734969417748       

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

user_cooldowns = {}
user_link_warnings = {}

LINK_REGEX = re.compile(r'https?://[^\s]+|discord\.gg/[^\s]+', re.IGNORECASE)

# --- תצוגת הכפתורים בתוך הטיקט ---
class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="סגור טיקט 🔒", style=discord.ButtonStyle.red, custom_id="close_ticket_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        helper_role = interaction.guild.get_role(HELPER_ROLE_ID)
        is_helper = helper_role in interaction.user.roles if helper_role else False
        is_admin = interaction.user.guild_permissions.administrator

        if not (is_helper or is_admin):
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
        helper_role = interaction.guild.get_role(HELPER_ROLE_ID)
        is_helper = helper_role in interaction.user.roles if helper_role else False
        is_admin = interaction.user.guild_permissions.administrator

        if not (is_helper or is_admin):
            await interaction.response.send_message("רק חברי צוות יכולים לקחת טיקטים!", ephemeral=True)
            return

        button.style = discord.ButtonStyle.green
        button.label = f"נלקח על ידי {interaction.user.display_name} 🟢"
        button.disabled = True
        
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"**{interaction.user.display_name}** לקח את הטיקט ויתפנה לעזרתך בהקדם!")

# --- תצוגת כפתור לפתיחת טיקט ---
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

        helper_role = guild.get_role(HELPER_ROLE_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        if helper_role:
            overwrites[helper_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel_name = f"ticket-{user.name}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name, 
            category=category,
            overwrites=overwrites,
            topic=f"Ticket created by {user.id}"
        )

        await interaction.response.send_message(f"הטיקט שלך נפתח בהצלחה! {ticket_channel.mention}", ephemeral=True)

        ticket_embed = discord.Embed(
            title=f"שלום {user.display_name} 👋",
            description="תודה שפנית לצוות התמיכה!\nפרט את סיבת הפנייה וצוות התמיכה יענה לך בהקדם.",
            color=discord.Color.blue()
        )
        ticket_embed.set_footer(text="צוות התמיכה יטפל בפנייתך בהקדם.")

        await ticket_channel.send(embed=ticket_embed, view=TicketControlView())

# --- זיהוי קישורים ---
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    if LINK_REGEX.search(message.content):
        try:
            await message.delete()
        except Exception as e:
            print(f"שגיאה במחיקת ההודעה: {e}")

        user_id = message.author.id
        current_warnings = user_link_warnings.get(user_id, 0) + 1
        user_link_warnings[user_id] = current_warnings

        if current_warnings == 1:
            duration_minutes = 5
            embed_title = "⚠️ קיבלת טיימאוט! (אזהרה ראשונה)"
            warning_text = "חל איסור לשלוח קישורים בשרת. פעם הבאה שתשלח קישור תקבל טיימאוט ל-10 דקות!"
        elif current_warnings == 2:
            duration_minutes = 10
            embed_title = "⚠️ קיבלת טיימאוט! (אזהרה שנייה)"
            warning_text = "זוהי אזהרה שנייה! פעם הבאה שתשלח קישור תקבל טיימאוט ליום שלם (24 שעות)!"
        else:
            duration_minutes = 1440
            embed_title = "🚨 קיבלת טיימאוט ליום שלם!"
            warning_text = "המשכת לשלוח קישורים למרות האזהרות. קיבלת טיימאוט ל-24 שעות."

        timeout_duration = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        try:
            await message.author.timeout(timeout_duration, reason="שליחת קישורים אסורים")
            print(f"ניתן טיימאוט בהצלחה ל-{message.author.name} ל-{duration_minutes} דקות.")
        except discord.Forbidden:
            print(f"[שגיאה] לא ניתן לתת טיימאוט ל-{message.author.name} (משתמש אדמין או רול בוט נמוך).")
        except Exception as e:
            print(f"[שגיאה בטיימאוט] {e}")

        unmute_time_unix = int(time.time()) + (duration_minutes * 60)
        
        embed = discord.Embed(
            title=embed_title,
            description=f"הורחקת זמנית מדיבור בשרת **{message.guild.name}** על שליחת קישור.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="⏳ זמן סיום הטימאוט:", 
            value=f"<t:{unmute_time_unix}:R> (בתאריך <t:{unmute_time_unix}:f>)", 
            inline=False
        )
        embed.add_field(name="📌 הערה:", value=warning_text, inline=False)
        
        deleted_content = message.content[:1000]
        embed.add_field(
            name="💬 ההודעה שנמחקה לך:", 
            value=deleted_content, 
            inline=False
        )
        embed.set_footer(text="יש לשמור על חוקי השרת כדי להימנע מעונשים נוספים.")

        try:
            await message.author.send(embed=embed)
            print(f"נשלחה הודעה פרטית ל-{message.author.name}")
        except discord.Forbidden:
            print(f"לא ניתן לשלוח הודעה פרטית ל-{message.author.name} (הודעות פרטיות חסומות).")

        return

    await bot.process_commands(message)

# --- אירוע הצטרפות משתמש חדש ---
@bot.event
async def on_member_join(member: discord.Member):
    role = member.guild.get_role(AUTO_ROLE_ID)
    if role:
        try:
            await member.add_roles(role)
        except discord.Forbidden:
            print("אין הרשאה לתת את הרול (ודא שרול הבוט גבוה יותר ברשימה).")

    welcome_channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if welcome_channel:
        embed = discord.Embed(
            title="ברוך הבא לשרת! 🎉",
            description=f"שלום {member.mention}, שמחים שהצטרפת אלינו!\nמאחלים לך שהות מהנה בשרת.",
            color=discord.Color.green()
        )
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        embed.set_footer(text=f"חבר שרת מספר #{len(member.guild.members)}")
        
        await welcome_channel.send(content=f"שלום לכולם, תברכו את {member.mention}!", embed=embed)

@bot.event
async def on_ready():
    bot.add_view(CreateTicketView())
    bot.add_view(TicketControlView())
    print(f'הבוט מחובר בתור {bot.user}')

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_ticket(ctx):
    await ctx.message.delete()
    
    embed = discord.Embed(
        title="🎫 מערכת תמיכה ופניות",
        description="זקוק לעזרה? רוצה לפתוח פנייה לצוות השרת?\nלחץ על הכפתור למטה כדי לפתוח טיקט פרטי!",
        color=discord.Color.gold()
    )
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    embed.add_field(name="⏰ שעות פעילות", value="צוות התמיכה עונה בהקדם האפשרי.", inline=False)
    embed.add_field(name="⚠️ שיוך נושאים", value="יש לשמור על שפה נאותה ולהסביר את הבעיה בפירוט.", inline=False)
    
    await ctx.send(embed=embed, view=CreateTicketView())

@bot.command()
@commands.has_permissions(administrator=True)
async def testjoin(ctx):
    await ctx.send("🧪 מריץ בדיקה של מערכת קבלת הפנים...")
    bot.dispatch('member_join', ctx.author)

# הפעלת שרת ה-Web ברקע
keep_alive()

bot.run('MTUwODQ0MDU0NTExMzE0OTQ2MA.GnDqaw.XS13vYup_meP9A7wy4JRwvLf1EgLmjJku9VmvQ')
