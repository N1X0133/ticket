import os
import asyncio
import logging
import json
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("Переменная окружения DISCORD_TOKEN не установлена!")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ========== НАСТРОЙКИ ==========
WHITE_SERVER_ID = 1475458561050939523
PANEL_CHANNEL_ID = 1494790569560506408
TICKET_CATEGORY_ID = 1494790799827664956

ROLE_IDS = [
    1475470962379067392,
    1491509114034192384,
    1491508543432687666
]

ticket_status = {}

def check_roles(interaction: discord.Interaction) -> bool:
    for role_id in ROLE_IDS:
        role = interaction.user.get_role(role_id)
        if role:
            return True
    return interaction.user.guild_permissions.administrator()

class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False
        self.config_file = "ticket_config.json"
        self.config = self.load_config()

    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"panel_channel_id": PANEL_CHANNEL_ID, "log_channel_id": None}

    def save_config(self):
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    async def setup_hook(self):
        await self.tree.sync()
        logger.info("Слэш-команды синхронизированы")
        self.add_view(TicketButton(self))

bot = TicketBot()

# ========== КНОПКА СОЗДАНИЯ ТИКЕТА ==========
class TicketButton(View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot_instance = bot_instance

    @discord.ui.button(label="📩 Подать жалобу в Прокуратуру", style=discord.ButtonStyle.green, custom_id="ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        
        category = interaction.guild.get_channel(TICKET_CATEGORY_ID)
        if not category:
            category = await interaction.guild.create_category("Жалобы в Прокуратуру")
        
        channel_name = f"жалоба-{interaction.user.name.lower()}"
        existing = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if existing:
            await interaction.followup.send("❌ У вас уже есть открытая жалоба!", ephemeral=True)
            return
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        for role_id in ROLE_IDS:
            role = interaction.guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True, attach_files=True)
        
        ticket_channel = await category.create_text_channel(channel_name, overwrites=overwrites)
        
        ticket_status[ticket_channel.id] = {
            "status": "waiting",
            "author_id": interaction.user.id
        }
        
        embed = discord.Embed(
            title="⚖️ Прокуратура Нижегородской области",
            description=(
                "**Форма подачи жалобы:**\n\n"
                "**Жалоба в Прокуратуру № XXX**\n\n"
                "**Кому:** Прокуратуре Нижегородской области\n"
                f"**От кого:** {interaction.user.name}\n\n"
                f"**Я, гражданин Нижегородской области ({interaction.user.name}), подаю жалобу в прокуратуру на гражданина**\n"
                "(напишите ФИО / Удостоверение / Нашивку / Неизвестного)\n\n"
                "**Подробное описание ситуации:**\n"
                "(напишите здесь подробное описание)\n\n"
                "**Доказательства, подтверждающие правонарушение**\n"
                "(на видео или скриншоте должна быть обязательно системная боди-камера, вставьте ссылку)\n\n"
                "**Дата и время нарушения:**\n"
                "(пример: 29.05.2025, 18:30)\n\n"
                "**К жалобе в прокуратуру прилагаю:**\n"
                "Копию паспорта: (вставьте ссылку)\n\n"
                "**Контактные данные:**\n"
                "(номер телефона; почта; Discord)\n\n"
                "**Дата:**\n"
                f"(пример: {datetime.now().strftime('%d.%m.%Y')})\n"
                "**Подпись:**\n"
                "(ваша подпись)\n\n"
                "**Статус:** 🟢 ОЖИДАЕТ РАССМОТРЕНИЯ"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="by Ilya Vetrov")
        
        await ticket_channel.send(
            f"{interaction.user.mention}, **ваша жалоба зарегистрирована!**\nЗаполните форму выше.\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n**by Ilya Vetrov**",
            view=TicketControlButtons(interaction.user.id, ticket_channel.id)
        )
        await ticket_channel.send(embed=embed)
        
        await interaction.followup.send(f"✅ Жалоба создана! Перейдите в канал {ticket_channel.mention}\n\n**by Ilya Vetrov**", ephemeral=True)

# ========== КНОПКИ УПРАВЛЕНИЯ ТИКЕТОМ ==========
class TicketControlButtons(View):
    def __init__(self, author_id, channel_id):
        super().__init__(timeout=None)
        self.author_id = author_id
        self.channel_id = channel_id

    @discord.ui.button(label="🔒 Закрыть жалобу", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        # Проверка что нажал автор
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Только автор жалобы может её закрыть!", ephemeral=True)
            return
        
        # Проверка статуса
        if self.channel_id in ticket_status and ticket_status[self.channel_id].get("status") == "review":
            await interaction.response.send_message("❌ Жалоба уже на рассмотрении! Вы не можете её закрыть.", ephemeral=True)
            return
        
        # Отвечаем сразу, чтобы не было ошибки
        await interaction.response.send_message("🔒 Жалоба будет закрыта через 3 секунды...", ephemeral=True)
        
        # Сохраняем лог
        os.makedirs("complaint_logs", exist_ok=True)
        log_file = f"complaint_logs/{interaction.channel.name}.txt"
        
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"Лог жалобы: {interaction.channel.name}\n")
                f.write(f"Дата закрытия: {datetime.utcnow()}\n")
                f.write(f"Закрыл: {interaction.user}\n")
                f.write("by Ilya Vetrov\n")
                f.write("="*50 + "\n")
                async for msg in interaction.channel.history(limit=500, oldest_first=True):
                    f.write(f"{msg.author} [{msg.created_at}]: {msg.content}\n")
        except Exception as e:
            logger.error(f"Ошибка сохранения лога: {e}")
        
        await asyncio.sleep(3)
        
        # Удаляем канал
        try:
            if self.channel_id in ticket_status:
                del ticket_status[self.channel_id]
            await interaction.channel.delete()
        except Exception as e:
            logger.error(f"Ошибка удаления канала: {e}")

    @discord.ui.button(label="📋 На рассмотрении", style=discord.ButtonStyle.primary, custom_id="review_ticket")
    async def review_ticket(self, interaction: discord.Interaction, button: Button):
        # Только сотрудники
        if not check_roles(interaction):
            await interaction.response.send_message("❌ Только сотрудники могут перевести жалобу в режим рассмотрения!\n\nby Ilya Vetrov", ephemeral=True)
            return
        
        if self.channel_id in ticket_status and ticket_status[self.channel_id].get("status") == "review":
            await interaction.response.send_message("ℹ️ Эта жалоба уже на рассмотрении!", ephemeral=True)
            return
        
        # Обновляем статус
        ticket_status[self.channel_id] = {
            "status": "review",
            "author_id": self.author_id
        }
        
        embed = discord.Embed(
            title="⚖️ Прокуратура Нижегородской области",
            description=(
                "**Статус жалобы:** 🟡 НА РАССМОТРЕНИИ\n\n"
                "Жалоба принята в работу сотрудниками прокуратуры.\n"
                "Ожидайте решения в этом канале."
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="by Ilya Vetrov")
        
        # Отправляем новое сообщение и удаляем старые кнопки
        await interaction.response.send_message("✅ Жалоба переведена в статус «На рассмотрении»\n\nby Ilya Vetrov", ephemeral=True)
        await interaction.channel.send(embed=embed, view=StaffCloseButton(self.channel_id))
        
        # Удаляем старые кнопки
        await interaction.channel.purge(limit=1)

# ========== КНОПКА ЗАКРЫТИЯ ДЛЯ СОТРУДНИКОВ ==========
class StaffCloseButton(View):
    def __init__(self, channel_id):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="🔒 Закрыть жалобу (сотрудник)", style=discord.ButtonStyle.red, custom_id="staff_close")
    async def staff_close(self, interaction: discord.Interaction, button: Button):
        # Только сотрудники
        if not check_roles(interaction):
            await interaction.response.send_message("❌ Только сотрудники могут закрыть жалобу!\n\nby Ilya Vetrov", ephemeral=True)
            return
        
        # Отвечаем сразу
        await interaction.response.send_message("🔒 Жалоба будет закрыта через 3 секунды...\n\nby Ilya Vetrov", ephemeral=True)
        
        # Сохраняем лог
        os.makedirs("complaint_logs", exist_ok=True)
        log_file = f"complaint_logs/{interaction.channel.name}.txt"
        
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"Лог жалобы: {interaction.channel.name}\n")
                f.write(f"Дата закрытия: {datetime.utcnow()}\n")
                f.write(f"Закрыл сотрудник: {interaction.user}\n")
                f.write("by Ilya Vetrov\n")
                f.write("="*50 + "\n")
                async for msg in interaction.channel.history(limit=500, oldest_first=True):
                    f.write(f"{msg.author} [{msg.created_at}]: {msg.content}\n")
        except Exception as e:
            logger.error(f"Ошибка сохранения лога: {e}")
        
        await asyncio.sleep(3)
        
        # Удаляем канал
        try:
            if self.channel_id in ticket_status:
                del ticket_status[self.channel_id]
            await interaction.channel.delete()
        except Exception as e:
            logger.error(f"Ошибка удаления канала: {e}")

# ========== СЛЭШ-КОМАНДЫ ==========
@bot.tree.command(name="setup", description="🔧 Настройка системы жалоб (админ)")
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    channel = interaction.guild.get_channel(PANEL_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message(f"❌ Канал {PANEL_CHANNEL_ID} не найден!", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="⚖️ Прокуратура Нижегородской области",
        description=(
            "**Форма подачи жалобы:**\n\n"
            "**Жалоба в Прокуратуру № XXX**\n\n"
            "**Кому:** Прокуратуре Нижегородской области\n"
            "**От кого:** (Имя фамилия)\n\n"
            "Я, гражданин Нижегородской области (Имя и Фамилия), подаю жалобу в прокуратуру на гражданина "
            "(Имя и Фамилия /Удостоверение /Нашивка/ Неизвестного).\n\n"
            "**Подробное описание ситуации:** (подробное описание)\n\n"
            "**Доказательства, подтверждающие правонарушение** "
            "(на видео или скриншоте должна быть обязательно системная боди-камера): (под ссылку)\n\n"
            "**Дата и время нарушения:** (пример: 29.05.2025, 18:30)\n\n"
            "**К жалобе в прокуратуру прилагаю:**\n"
            "Копию паспорта: (под ссылку)\n\n"
            "**Контактные данные:** (номер телефона; почта; Discord)\n\n"
            "**Дата:** (пример: 29.05.2025)\n"
            "**Подпись:** (ваша подпись)\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "**Нажмите на кнопку ниже, чтобы подать жалобу**"
        ),
        color=discord.Color.red()
    )
    embed.set_footer(text="by Ilya Vetrov")
    
    await channel.send(embed=embed, view=TicketButton(bot))
    await interaction.response.send_message(f"✅ Панель отправлена в канал {channel.mention}\n\nby Ilya Vetrov", ephemeral=True)

@bot.tree.command(name="complaint_log", description="📄 Получить лог закрытой жалобы")
@app_commands.describe(channel_name="Название канала жалобы")
async def complaint_log(interaction: discord.Interaction, channel_name: str = None):
    if not check_roles(interaction):
        await interaction.response.send_message("❌ Нет прав!\n\nby Ilya Vetrov", ephemeral=True)
        return
    
    if not channel_name:
        await interaction.response.send_message("❌ Укажите название канала", ephemeral=True)
        return
    
    log_path = f"complaint_logs/{channel_name}.txt"
    if not os.path.exists(log_path):
        await interaction.response.send_message(f"❌ Лог не найден", ephemeral=True)
        return
    
    await interaction.response.send_message(file=discord.File(log_path))

@bot.tree.command(name="closed_list", description="📋 Список закрытых жалоб")
async def closed_list(interaction: discord.Interaction):
    if not check_roles(interaction):
        await interaction.response.send_message("❌ Нет прав!\n\nby Ilya Vetrov", ephemeral=True)
        return
    
    os.makedirs("complaint_logs", exist_ok=True)
    files = [f.replace(".txt", "") for f in os.listdir("complaint_logs") if f.endswith(".txt")]
    
    if not files:
        await interaction.response.send_message("📭 Нет закрытых жалоб.\n\nby Ilya Vetrov", ephemeral=True)
        return
    
    embed = discord.Embed(title="📋 Список закрытых жалоб", description="\n".join([f"📄 `{f}`" for f in files]), color=discord.Color.blue())
    embed.set_footer(text="by Ilya Vetrov")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="info", description="ℹ️ Информация о боте")
async def info(interaction: discord.Interaction):
    embed = discord.Embed(
        title="ℹ️ О боте",
        description="**Система подачи жалоб в Прокуратуру Нижегородской области**\n\n👨‍💻 **Разработчик:** Ilya Vetrov\n🛡️ **Версия:** 1.0",
        color=discord.Color.blue()
    )
    embed.set_footer(text="by Ilya Vetrov")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_ready():
    logger.info(f"✅ Бот {bot.user} запущен!")
    await bot.change_presence(activity=discord.Game(name="by Ilya Vetrov"))
    print(f"✅ Бот {bot.user} готов!")
    print(f"👨‍💻 by Ilya Vetrov")

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
