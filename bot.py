import os
import asyncio
import json
import logging
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

# Файл для хранения настроек
SETTINGS_FILE = "settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False
        self.settings = load_settings()  # {guild_id: {"panel_channel_id": int, "log_channel_id": int, "category_id": int}}

    async def setup_hook(self):
        await self.tree.sync()
        logger.info("Слэш-команды синхронизированы")
        self.add_view(TicketButton(self))
        self.add_view(CloseTicketButton(self))

bot = TicketBot()

# ---------- Кнопка создания тикета ----------
class TicketButton(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="📩 Создать тикет", style=discord.ButtonStyle.green, custom_id="ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        settings = self.bot.settings.get(str(interaction.guild_id), {})
        category_id = settings.get("category_id")
        category = None
        if category_id:
            category = interaction.guild.get_channel(category_id)
        if not category:
            category = discord.utils.get(interaction.guild.categories, name="Тикеты")
            if not category:
                category = await interaction.guild.create_category("Тикеты")
                logger.info(f"Создана категория 'Тикеты' на сервере {interaction.guild.id}")

        channel_name = f"тикет-{interaction.user.name.lower()}"
        existing = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if existing:
            await interaction.response.send_message("❌ У вас уже есть открытый тикет!", ephemeral=True)
            return

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        admin_role = discord.utils.get(interaction.guild.roles, name="Admin")
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        support_role = discord.utils.get(interaction.guild.roles, name="Support")
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ticket_channel = await category.create_text_channel(channel_name, overwrites=overwrites)
        logger.info(f"Создан канал {channel_name} для {interaction.user} на сервере {interaction.guild.id}")

        embed = discord.Embed(
            title="📌 Тикет создан",
            description=f"Здравствуйте, {interaction.user.mention}!\nОпишите вашу проблему. Сотрудники поддержки ответят в этом канале.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        await ticket_channel.send(embed=embed, view=CloseTicketButton(self.bot))
        await interaction.response.send_message(f"✅ Тикет создан: {ticket_channel.mention}", ephemeral=True)

        # Отправка уведомления в лог-канал
        log_channel_id = settings.get("log_channel_id")
        if log_channel_id:
            log_channel = interaction.guild.get_channel(log_channel_id)
            if log_channel:
                await log_channel.send(f"📢 Пользователь {interaction.user.mention} создал тикет {ticket_channel.mention}")

# ---------- Кнопка закрытия тикета ----------
class CloseTicketButton(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("🔒 Тикет будет закрыт через 5 секунд...", ephemeral=True)
        await asyncio.sleep(5)

        os.makedirs("ticket_logs", exist_ok=True)
        log_file = f"ticket_logs/{interaction.channel.name}.txt"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"Лог тикета: {interaction.channel.name}\n")
            f.write(f"Дата закрытия: {datetime.utcnow()}\n")
            f.write("="*50 + "\n")
            async for msg in interaction.channel.history(limit=200, oldest_first=True):
                f.write(f"{msg.author} [{msg.created_at}]: {msg.content}\n")
        logger.info(f"Тикет {interaction.channel.name} закрыт, лог сохранён")

        # Отправка уведомления в лог-канал
        settings = self.bot.settings.get(str(interaction.guild_id), {})
        log_channel_id = settings.get("log_channel_id")
        if log_channel_id:
            log_channel = interaction.guild.get_channel(log_channel_id)
            if log_channel:
                await log_channel.send(f"🔒 Тикет {interaction.channel.mention} закрыт. Лог сохранён.")

        await interaction.channel.delete()

# ---------- Слэш-команды настройки ----------
@bot.tree.command(name="setup_panel", description="Отправить панель создания тикетов в текущий канал (админ)")
@app_commands.default_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction):
    """Размещает панель с кнопкой в текущем канале"""
    channel = interaction.channel
    embed = discord.Embed(
        title="🎫 Система поддержки",
        description="Нажмите на кнопку ниже, чтобы создать тикет. Операторы свяжутся с вами в этом канале.",
        color=discord.Color.blue()
    )
    await channel.send(embed=embed, view=TicketButton(bot))
    await interaction.response.send_message(f"✅ Панель тикетов отправлена в канал {channel.mention}", ephemeral=True)

@bot.tree.command(name="set_log_channel", description="Установить канал для уведомлений о тикетах (админ)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel="Канал, куда будут приходить уведомления")
async def set_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    guild_id = str(interaction.guild_id)
    if guild_id not in bot.settings:
        bot.settings[guild_id] = {}
    bot.settings[guild_id]["log_channel_id"] = channel.id
    save_settings(bot.settings)
    await interaction.response.send_message(f"✅ Канал уведомлений установлен: {channel.mention}", ephemeral=True)

@bot.tree.command(name="set_ticket_category", description="Установить категорию для создания тикетов (админ)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(category="Категория, где будут создаваться тикет-каналы")
async def set_ticket_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    guild_id = str(interaction.guild_id)
    if guild_id not in bot.settings:
        bot.settings[guild_id] = {}
    bot.settings[guild_id]["category_id"] = category.id
    save_settings(bot.settings)
    await interaction.response.send_message(f"✅ Категория для тикетов установлена: {category.name}", ephemeral=True)

@bot.tree.command(name="ticket_log", description="Получить лог закрытого тикета (админ)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel_name="Название канала тикета (например, тикет-пользователь)")
async def ticket_log(interaction: discord.Interaction, channel_name: str):
    log_path = f"ticket_logs/{channel_name}.txt"
    if not os.path.exists(log_path):
        await interaction.response.send_message(f"❌ Лог для канала `{channel_name}` не найден.", ephemeral=True)
        return
    await interaction.response.send_message(file=discord.File(log_path))

@bot.tree.command(name="show_settings", description="Показать текущие настройки бота на сервере (админ)")
@app_commands.default_permissions(administrator=True)
async def show_settings(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    settings = bot.settings.get(guild_id, {})
    embed = discord.Embed(title="Настройки бота", color=discord.Color.gold())
    log_channel_id = settings.get("log_channel_id")
    category_id = settings.get("category_id")
    embed.add_field(name="Канал уведомлений", value=f"<#{log_channel_id}>" if log_channel_id else "Не установлен", inline=False)
    embed.add_field(name="Категория для тикетов", value=f"<#{category_id}>" if category_id else "Не установлена (используется 'Тикеты')", inline=False)
    embed.add_field(name="Панель тикетов", value="Используйте `/setup_panel` в нужном канале", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------- Событие готовности ----------
@bot.event
async def on_ready():
    logger.info(f"✅ Бот {bot.user} запущен на хостинге!")
    await bot.change_presence(activity=discord.Game(name="/setup_panel"))
    print(f"Бот {bot.user} готов. Используйте слэш-команды.")

# ---------- Запуск ----------
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
