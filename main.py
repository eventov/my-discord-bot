import discord
from discord.ext import commands
import asyncio
import os

# הגדרת הרשאות הבוט (Intents)
intents = discord.Intents.default()
intents.message_content = True  # חובה לקריאת פקודות טקסט
intents.members = True          # חובה כדי לתת רולים למשתמשים

bot = commands.Bot(command_prefix='!', intents=intents)

# החלף כאן את מספר ה-ID של הרול שיתקבל בלחיצה על הכפתור
ROLE_ID = 1550851467361919057  

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
    prompt_msg = await ctx.send("🖼️ **אנא העלה קובץ תמונה או GIF להודעת החוקים...**\n*(יש לך 60 שניות להעלות)*")

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

    # שלב 2: יצירת Embed מעוצב בסגנון מוקפד עם אימוג'ים כפי שביקשת
    embed = discord.Embed(
        title="📜 חוקי קהילת העיצובים והמדיה",
        description="ברוכים הבאים לשרת! כדי לשמור על סביבה מקצועית ונעימה לכולם, יש להקפיד על הכללים הבאים:",
        color=discord.Color.blue()
    )

    # הוספת שדות (Fields) מחולקים בדיוק כמו בתמונה ששלחת
    embed.add_field(
        name="🤠 כבוד הדדי והתנהגות נאותה",
        value="• אין להתחזות לאדם אחר, כולל משתמשים, צוות או דמויות ציבוריות\n• אין לקלל, לאיים, לזלזל או להתנהג בגסות כלפי משתמשים אחרים\n• יש להתנהג בכבוד כלפי חברי השרת, ללא יוצא מן הכלל",
        inline=False
    )

    embed.add_field(
        name="🚫 תוכן פוגעני אסור",
        value="• אין לפרסם או לשתף תוכן גזעני, מיני, חוֹשפני, אלים או שנאה מכל סוג\n• אין לשתף תמונות, סרטונים או טקסטים העלולים לפגע לאחרים",
        inline=False
    )

    embed.add_field(
        name="💬 שימוש נכון בקול ובכתב",
        value="• אין להשתמש בווֹיס צ'אנגר באופן העלול לפגוע בריווחת המשתמשים\n• שמרו על שיח נעים ומכבד גם בצ'אט הקולי וגם בצ'אט הכתוב\n• אין לצעוק, לקרב את המיקרופון באופן מוגזם או לנשוף לתוכו",
        inline=False
    )

    embed.add_field(
        name="🔗 איסור פרסום",
        value="• אין לפרסם לינקים, לייבים, סרטונים, קודים או שרתי דיסקורד אחרים\n• אין לפרסם תכנים לקידום עצמי או של אחרים, גם לא בפרטי\n• פרסום מכל סוג למטרת רווח - אסור בהחלט",
        inline=False
    )

    embed.add_field(
        name="🛑 מניעת ספאֹם והצפה",
        value="• יש להימנע משימוש מופרז באימוג'ים בהודעה אחת\n• אין להספים את הצ'אט בתום לב או בכוונה תחילה\n• יש להימנע משליחת מעל ל-4 הודעות רצופות",
        inline=False
    )

    embed.add_field(
        name="👤 פעולות אסורות נוספות",
        value="• אין לבצע טריידים, מכירה של מוצרים, משתמשים, או כל דבר אחר\n• השיח מותר בעברית ובאנגלית בלבד (אלא אם צוין אחרת)\n• אין להשתמש בפקודות בוטים בצורה מציפה או מטרידה",
        inline=False
    )

    embed.add_field(
        name="⚠️ אי ידיעת החוקים אינה פוטרת מעונש",
        value="העונשים האפשריים כוללים אזהרה, השתקה, הרחקה זמנית או קבועה מן השרת, בהתאם שיקול דעת הצוות והנהלה.",
        inline=False
    )

    # הגדרת התמונה שהעלית בתור תמונה מרכזית (Banner) בתחתית ה-Embed
    embed.set_image(url=image_url)
    
    # פוטר
    embed.set_footer(text="קהילת העיצובים והמדיה | לחץ על הכפתור למטה לאישור החוקים")

    # שלב 3: שליחת ההודעה יחד עם כפתור האישור
    view = RulesView()
    await ctx.send(embed=embed, view=view)

@setup_role.error
async def setup_role_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ פקודה זו מיועדת למנהלי השרת בלבד!", delete_after=5)

# הפעלת הבוט באמצעות משתנה הסביבה של Render
bot.run(os.getenv("DISCORD_TOKEN"))
