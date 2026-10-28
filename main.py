import discord
from discord.ext import commands
import asyncio
import os

# הגדרת הרשאות הבוט (Intents)
intents = discord.Intents.default()
intents.message_content = True  # חובה לקריאת פקודות טקסט
intents.members = True          # חובה כדי לתת רולים למשתמשים

bot = commands.Bot(command_prefix='!', intents=intents)

# הגדר כאן את ה-ID של הרול שיתקבל בלחיצה על הכפתור
ROLE_ID = 1550851467361919057  # החלף במספר ה-ID של הרול (לדוגמה: 123456789012345678)

@bot.event
async def on_ready():
    print(f'הבוט מחובר בהצלחה בתור: {bot.user.name}')
    await bot.change_presence(activity=discord.Game(name="עיצובים | !setup_role"))

# מחלקה ליצירת הכפתור האינטראקטיבי
class RulesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # ללא הגבלת זמן לכפתור

    @discord.ui.button(label="אני מסכין לחוקים", style=discord.ButtonStyle.success, emoji="✅")
    async def agree_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        role = guild.get_role(ROLE_ID)

        if not role:
            await interaction.response.send_message("❌ שגיאה: לא נמצא רול עם ה-ID שהוגדר בקוד.", ephemeral=True)
            return

        # בדיקה אם למשתמש כבר יש את הרול
        if role in interaction.user.roles:
            await interaction.response.send_message("✅ אתה כבר מאומת וכבר קיבלת את הרול!", ephemeral=True)
        else:
            try:
                await interaction.user.add_roles(role)
                await interaction.response.send_message("🎉 תודה שקראת והסכמת לחוקים! קיבלת את הרול בהצלחה.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("❌ לבוט אין הרשאה להעניק את הרול הזה. ודא שהרול של הבוט נמצא מעל הרול המבוקש ברשימת הרולים.", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"❌ אירעה שגיאה: {e}", ephemeral=True)

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_role(ctx):
    # מחיקת פקודת ההפעלה לשמירה על נקיון הערוץ
    try:
        await ctx.message.delete()
    except:
        pass

    # שלב 1: בקשת תמונה/GIF מהמשתמש
    prompt_msg = await ctx.send("🖼️ **אנא העלה קובץ תמונה או GIF (לדוגמה: רקע כחול זז) להודעת החוקים...**\n*(יש לך 60 שניות להעלות)*")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and len(m.attachments) > 0

    try:
        msg = await bot.wait_for('message', check=check, timeout=60.0)
        image_url = msg.attachments[0].url
        
        try:
            await msg.delete()
            await prompt_msg.delete()
        except:
            pass

    except asyncio.TimeoutError:
        await prompt_msg.edit(content="⏰ **עבר הזמן!** לא נשלחה תמונה, הפקודה בוטלה.")
        return

    # שלב 2: יצירת Embed מעוצב עם רקע/פס כחול
    embed = discord.Embed(
        title="🎨 חוקי קהילת העיצובים והמדיה",
        description="ברוכים הבאים לשרת העיצובים! כדי לשמור על קהילה מקצועית, נעימה ובטוחה לכולם, יש להישמע לחוקים הבאים:",
        color=discord.Color.blue()
    )

    rules = [
        "**1. כבוד הדדי:** אסור לקלל, להעליב או לדבר בצורה פוגענית כלפי חברי הקהילה.",
        "**2. תוכן הולם:** אסור לשדר, להעלות או לשתף תוכן פורנוגרפי, מיני או אלים.",
        "**3. זכויות יוצרים וקרדיט:** חל איסור מוחלט לגנוב עיצובים, לגנוב קרדיט או להציג עבודות של מעצבים אחרים כשלכם.",
        "**4. ספאם ופרסום לא מאושר:** אין לפרסם שרתי דיסקורד אחרים, קישורים חיצוניים או להציף את הצ'אט בטקסט/תמונות.",
        "**5. ביקורת בונה בלבד:** כשאתם נותנים חוות דעת (Feedback) על עיצוב, עשו זאת בצורה מכבדת, בונה ומקדמת.",
        "**6. פתיחת טיקטים והזמנות:** עבודות בתשלום, בקשות לעיצובים או פניות להנהלה מבוצעות אך ורק בערוצים המיועדים לכך (Tickets).",
        "**7. תיוגים מיותרים:** אין לתייג מנהלים או מעצבים ללא סיבה מוצדקת. סבלנות היא מפתח.",
        "**8. ערוצים ייעודיים:** יש לשלוח קבצים, תמונות ופרויקטים אך ורק בערוצי המדיה והעיצוב המתאימים.",
        "**9. מסחר ובטיחות:** הנהלת השרת אינה אחראית על עסקאות פרטיות בין משתמשים. הקפידו על זהירות בעסקאות.",
        "**10. הקשבה להנחיות הצוות:** הוראות צוות הנהלת השרת הן סופיות ויש להישמע להן בכל עת."
    ]

    embed.add_field(
        name="📜 תקנון השרת",
        value="\n\n".join(rules),
        inline=False
    )

    embed.set_image(url=image_url)
    embed.set_footer(text="קהילת העיצובים | לחץ על הכפתור למטה לאישור החוקים וקבלת הגישה לשרת")

    # שלב 3: שליחת ההודעה יחד עם כפתור האישור
    view = RulesView()
    await ctx.send(embed=embed, view=view)

@setup_role.error
async def setup_role_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ פקודה זו מיועדת למנהלי השרת בלבד!", delete_after=5)

# הפעלת הבוט באמצעות משתנה הסביבה של Render
bot.run(os.getenv("DISCORD_TOKEN"))
