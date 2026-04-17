import os
import asyncio
import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("Переменная окружения DISCORD_TOKEN не установлена!")

# Интенты
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False  # флаг синхронизации команд

    async def setup_hook(self):
        # Синхронизация слэш-команд при запуске
        await self.tree.sync()
        logger.info("Слэш-команды синхронизированы")
        # Добавляем постоянные кнопки
        self.add_view(TicketButton())
        self.add_view(CloseTicketButton())

bot = TicketBot()

# ---------- Кнопка создания тикета ----------
class TicketButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Создать тикет", style=discord.ButtonStyle.green, custom_id="ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        # Категория "Тикеты"
        category = discord.utils.get(interaction.guild.categories, name="Тикеты")
        if not category:
            category = await interaction.guild.create_category("Тикеты")
            logger.info("Создана категория 'Тикеты'")

        channel_name = f"тикет-{interaction.user.name.lower()}"
        existing = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if existing:
            await interaction.response.send_message("❌ У вас уже есть открытый тикет!", ephemeral=True)
            return

        # Права доступа
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        admin_role = discord.utils.get(interaction.guild.roles, name="Admin")
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ticket_channel = await category.create_text_channel(channel_name, overwrites=overwrites)
        logger.info(f"Создан канал {channel_name} для {interaction.user}")

        embed = discord.Embed(
            title="📌 Тикет создан",
            description=f"Здравствуйте, {interaction.user.mention}!\nОпишите вашу проблему. Сотрудники поддержки ответят в этом канале.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        await ticket_channel.send(embed=embed, view=CloseTicketButton())
        await interaction.response.send_message(f"✅ Тикет создан: {ticket_channel.mention}", ephemeral=True)

# ---------- Кнопка закрытия тикета ----------
class CloseTicketButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("🔒 Тикет будет закрыт через 5 секунд...", ephemeral=True)
        await asyncio.sleep(5)

        # Сохраняем лог
        os.makedirs("ticket_logs", exist_ok=True)
        log_file = f"ticket_logs/{interaction.channel.name}.txt"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"Лог тикета: {interaction.channel.name}\n")
            f.write(f"Дата закрытия: {datetime.utcnow()}\n")
            f.write("="*50 + "\n")
            async for msg in interaction.channel.history(limit=200, oldest_first=True):
                f.write(f"{msg.author} [{msg.created_at}]: {msg.content}\n")
        logger.info(f"Тикет {interaction.channel.name} закрыт, лог сохранён")
        await interaction.channel.delete()

# ---------- Слэш-команды ----------
@bot.tree.command(name="ticket_panel", description="Создать панель с кнопкой для открытия тикетов (админ)")
@app_commands.default_permissions(administrator=True)
async def ticket_panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎫 Система поддержки",
        description="Нажмите на кнопку ниже, чтобы создать тикет. Операторы свяжутся с вами в этом канале.",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=TicketButton())
    await interaction.delete_original_response()  # удаляем сообщение с командой, оставляем только панель

@bot.tree.command(name="ticket_log", description="Получить лог закрытого тикета (админ)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel_name="Название канала тикета (например, тикет-пользователь)")
async def ticket_log(interaction: discord.Interaction, channel_name: str = None):
    if not channel_name:
        await interaction.response.send_message("❌ Укажите название канала тикета, например: `тикет-иван`", ephemeral=True)
        return
    log_path = f"ticket_logs/{channel_name}.txt"
    if not os.path.exists(log_path):
        await interaction.response.send_message(f"❌ Лог для канала `{channel_name}` не найден.", ephemeral=True)
        return
    await interaction.response.send_message(file=discord.File(log_path))

# ---------- Событие готовности ----------
@bot.event
async def on_ready():
    logger.info(f"✅ Бот {bot.user} запущен на хостинге!")
    await bot.change_presence(activity=discord.Game(name="/ticket_panel"))
    print(f"Бот {bot.user} готов. Используйте слэш-команды /ticket_panel и /ticket_log")

# ---------- Запуск ----------
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
