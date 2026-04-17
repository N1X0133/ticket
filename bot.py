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

# ВАШИ ID
PANEL_CHANNEL_ID = 1494790569560506408
TICKET_CATEGORY_ID = 1494790799827664956

# ВАШИ РОЛИ (которые будут видеть все тикеты и использовать команды)
ROLE_IDS = [
    1475470962379067392,  # Роль 1
    1491509114034192384,  # Роль 2
    1491508543432687666   # Роль 3
]

def check_roles(interaction: discord.Interaction) -> bool:
    """Проверяет, есть ли у пользователя одна из разрешённых ролей"""
    for role_id in ROLE_IDS:
        role = interaction.user.get_role(role_id)
        if role:
            return True
    # Также проверяем права администратора
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
        self.add_view(CloseTicketButton(self))

bot = TicketBot()

# ---------- КНОПКА СОЗДАНИЯ ТИКЕТА ----------
class TicketButton(View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot_instance = bot_instance

    @discord.ui.button(label="📩 Подать жалобу в Прокуратуру", style=discord.ButtonStyle.green, custom_id="ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        # Получаем категорию
        category = interaction.guild.get_channel(TICKET_CATEGORY_ID)
        if not category:
            category = await interaction.guild.create_category("Жалобы в Прокуратуру")
        
        # Проверяем, нет ли уже открытого тикета
        channel_name = f"жалоба-{interaction.user.name.lower()}"
        existing = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if existing:
            await interaction.response.send_message("❌ У вас уже есть открытая жалоба! Дождитесь рассмотрения.", ephemeral=True)
            return
        
        # НАСТРОЙКА ПРАВ ДОСТУПА
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(
                read_messages=True, 
                send_messages=True, 
                attach_files=True,
                read_message_history=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                read_messages=True, 
                send_messages=True
            )
        }
        
        # ДОБАВЛЯЕМ ВАШИ РОЛИ (будут видеть ВСЕ тикеты)
        for role_id in ROLE_IDS:
            role = interaction.guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True
                )
        
        # Создаём канал
        ticket_channel = await category.create_text_channel(channel_name, overwrites=overwrites)
        
        # Отправляем приветствие с формой
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
                "(ваша подпись)"
            ),
            color=discord.Color.red()
        )
        
        await ticket_channel.send(
            f"{interaction.user.mention}, **ваша жалоба зарегистрирована!**\n"
            "Заполните форму выше, отправив сообщение с заполненными данными в этот канал.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔒 **Для закрытия жалобы нажмите красную кнопку ниже**",
            view=CloseTicketButton(self.bot_instance)
        )
        await ticket_channel.send(embed=embed)
        
        await interaction.response.send_message(f"✅ Жалоба создана! Перейдите в канал {ticket_channel.mention}", ephemeral=True)
        logger.info(f"Создана жалоба {channel_name} от {interaction.user}")

# ---------- КНОПКА ЗАКРЫТИЯ ----------
class CloseTicketButton(View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot_instance = bot_instance

    @discord.ui.button(label="🔒 Закрыть жалобу", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        if not interaction.channel.name.startswith("жалоба-"):
            await interaction.response.send_message("❌ Эта команда работает только в канале жалобы!", ephemeral=True)
            return
        
        # Сохраняем лог
        os.makedirs("complaint_logs", exist_ok=True)
        log_file = f"complaint_logs/{interaction.channel.name}.txt"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"Лог жалобы: {interaction.channel.name}\n")
            f.write(f"Дата закрытия: {datetime.utcnow()}\n")
            f.write("="*50 + "\n")
            async for msg in interaction.channel.history(limit=500, oldest_first=True):
                f.write(f"{msg.author} [{msg.created_at}]: {msg.content}\n")
        
        await interaction.response.send_message("🔒 Жалоба будет закрыта через 5 секунд...", ephemeral=True)
        await asyncio.sleep(5)
        await interaction.channel.delete()
        logger.info(f"Жалоба {interaction.channel.name} закрыта")

# ---------- СЛЭШ-КОМАНДЫ (С ПРОВЕРКОЙ РОЛЕЙ) ----------

@bot.tree.command(name="setup", description="🔧 Настройка системы жалоб (админ)")
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    """Отправляет панель с кнопкой в настроенный канал (только админ)"""
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
    
    await channel.send(embed=embed, view=TicketButton(bot))
    await interaction.response.send_message(f"✅ Панель отправлена в канал {channel.mention}", ephemeral=True)

# КОМАНДА ДЛЯ ПРОСМОТРА ЛОГА (доступна вашим ролям)
@bot.tree.command(name="complaint_log", description="📄 Получить лог закрытой жалобы")
@app_commands.describe(channel_name="Название канала жалобы (например, жалоба-иван)")
async def complaint_log(interaction: discord.Interaction, channel_name: str = None):
    """Просмотр лога закрытой жалобы (доступно вашим ролям)"""
    # Проверяем права
    if not check_roles(interaction):
        await interaction.response.send_message("❌ У вас нет прав для использования этой команды!", ephemeral=True)
        return
    
    if not channel_name:
        await interaction.response.send_message("❌ Укажите название канала жалобы, например: `жалоба-иван`", ephemeral=True)
        return
    
    log_path = f"complaint_logs/{channel_name}.txt"
    if not os.path.exists(log_path):
        await interaction.response.send_message(f"❌ Лог для канала `{channel_name}` не найден.", ephemeral=True)
        return
    
    await interaction.response.send_message(file=discord.File(log_path))

# КОМАНДА ДЛЯ СПИСКА ЗАКРЫТЫХ (доступна вашим ролям)
@bot.tree.command(name="closed_list", description="📋 Список всех закрытых жалоб")
async def closed_list(interaction: discord.Interaction):
    """Показывает список всех закрытых тикетов (доступно вашим ролям)"""
    # Проверяем права
    if not check_roles(interaction):
        await interaction.response.send_message("❌ У вас нет прав для использования этой команды!", ephemeral=True)
        return
    
    os.makedirs("complaint_logs", exist_ok=True)
    
    files = [f.replace(".txt", "") for f in os.listdir("complaint_logs") if f.endswith(".txt")]
    
    if not files:
        await interaction.response.send_message("📭 Нет закрытых жалоб.", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📋 Список закрытых жалоб",
        description="\n".join([f"📄 `{f}`" for f in files]),
        color=discord.Color.blue()
    )
    embed.set_footer(text="Используйте /complaint_log <название> для просмотра")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# КОМАНДА ДЛЯ ПРОВЕРКИ РОЛЕЙ (доступна вашим ролям)
@bot.tree.command(name="check_roles", description="👥 Проверить какие роли видят тикеты")
async def check_roles_cmd(interaction: discord.Interaction):
    """Проверяет, какие роли настроены для просмотра тикетов (доступно вашим ролям)"""
    # Проверяем права
    if not check_roles(interaction):
        await interaction.response.send_message("❌ У вас нет прав для использования этой команды!", ephemeral=True)
        return
    
    roles_list = []
    for role_id in ROLE_IDS:
        role = interaction.guild.get_role(role_id)
        if role:
            roles_list.append(f"✅ {role.name} (`{role_id}`)")
        else:
            roles_list.append(f"❌ Роль не найдена (`{role_id}`)")
    
    embed = discord.Embed(
        title="👥 Роли с доступом к тикетам",
        description="\n".join(roles_list),
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="reload_panel", description="🔄 Пересоздать панель с формой жалобы (админ)")
@app_commands.default_permissions(administrator=True)
async def reload_panel(interaction: discord.Interaction):
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
    
    await channel.send(embed=embed, view=TicketButton(bot))
    await interaction.response.send_message(f"✅ Панель пересоздана в канале {channel.mention}", ephemeral=True)

# ---------- ЗАПУСК ----------
@bot.event
async def on_ready():
    logger.info(f"✅ Бот {bot.user} запущен!")
    await bot.change_presence(activity=discord.Game(name="/setup - подача жалоб"))
    print(f"Бот {bot.user} готов. Используйте /setup")
    print(f"Настроены роли с ID: {ROLE_IDS}")

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
