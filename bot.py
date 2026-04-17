import os
import asyncio
import logging
from datetime import datetime

import discord
from discord.ext import commands
from discord.ui import Button, View

# Настройка логирования (полезно для отладки на хостинге)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получаем токен из переменной окружения, которую вы создадите на хостинге
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("Переменная окружения DISCORD_TOKEN не установлена на хостинге!")

# Включаем необходимые интенты
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Кнопка для создания тикета ----------
class TicketButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Создать тикет", style=discord.ButtonStyle.green, custom_id="ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        # Создаём категорию "Тикеты", если её нет
        category = discord.utils.get(interaction.guild.categories, name="Тикеты")
        if not category:
            category = await interaction.guild.create_category("Тикеты")
            logger.info("Создана категория 'Тикеты'")

        # Название канала: ticket-username
        channel_name = f"ticket-{interaction.user.name.lower()}"
        # Проверяем, нет ли уже открытого тикета у этого пользователя
        existing = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if existing:
            await interaction.response.send_message("У вас уже есть открытый тикет!", ephemeral=True)
            return

        # Создаём текстовый канал
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        # Добавим роль администраторов (если есть роль "Admin" или "Support")
        admin_role = discord.utils.get(interaction.guild.roles, name="Admin")
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ticket_channel = await category.create_text_channel(channel_name, overwrites=overwrites)
        logger.info(f"Создан канал {channel_name} для {interaction.user}")

        # Отправляем приветствие в тикет
        embed = discord.Embed(
            title="📌 Тикет создан",
            description=f"Здравствуйте, {interaction.user.mention}!\nОпишите вашу проблему. Поддержка скоро ответит.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        await ticket_channel.send(embed=embed, view=CloseTicketButton())
        await interaction.response.send_message(f"Тикет создан: {ticket_channel.mention}", ephemeral=True)

# ---------- Кнопка закрытия тикета ----------
class CloseTicketButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        # Подтверждение закрытия
        await interaction.response.send_message("Тикет будет закрыт через 5 секунд...", ephemeral=True)
        await asyncio.sleep(5)
        # Сохраняем историю сообщений в лог-файл (опционально)
        os.makedirs("ticket_logs", exist_ok=True)
        log_file = f"ticket_logs/{interaction.channel.name}.txt"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"Лог тикета {interaction.channel.name}\n")
            f.write(f"Дата закрытия: {datetime.utcnow()}\n")
            f.write("="*50 + "\n")
            async for msg in interaction.channel.history(limit=200, oldest_first=True):
                f.write(f"{msg.author} [{msg.created_at}]: {msg.content}\n")
        logger.info(f"Тикет {interaction.channel.name} закрыт, лог сохранён")
        await interaction.channel.delete()

# ---------- Команды бота ----------
@bot.event
async def on_ready():
    logger.info(f"Бот {bot.user} успешно запущен на хостинге!")
    # Регистрируем постоянные кнопки (чтобы они работали после перезапуска)
    bot.add_view(TicketButton())
    bot.add_view(CloseTicketButton())
    # Устанавливаем статус "Играет в помощь"
    await bot.change_presence(activity=discord.Game(name="!ticket_panel"))

@bot.command()
@commands.has_permissions(administrator=True)
async def ticket_panel(ctx):
    """Создаёт панель с кнопкой для открытия тикета (только админ)"""
    embed = discord.Embed(
        title="🎫 Система поддержки",
        description="Нажмите на кнопку ниже, чтобы создать тикет. Наши операторы свяжутся с вами в этом канале.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=TicketButton())
    await ctx.message.delete()  # удаляем команду, чтобы не засорять чат

@bot.command()
@commands.has_permissions(administrator=True)
async def ticket_log(ctx, channel_name: str = None):
    """Отправить лог закрытого тикета (админ)"""
    if not channel_name:
        await ctx.send("Укажите имя канала тикета, например `!ticket_log ticket-username`")
        return
    log_path = f"ticket_logs/{channel_name}.txt"
    if not os.path.exists(log_path):
        await ctx.send(f"Лог для канала `{channel_name}` не найден.")
        return
    await ctx.send(file=discord.File(log_path))

# ---------- Запуск бота ----------
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
