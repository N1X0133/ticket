import os
import asyncio
import logging
import json
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("Переменная окружения DISCORD_TOKEN не установлена!")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False
        # Файл для хранения настроек
        self.config_file = "ticket_config.json"
        self.config = self.load_config()

    def load_config(self):
        """Загружает настройки из файла"""
        if os.path.exists(self.config_file):
            with open(self.config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"panel_channel_id": None, "log_channel_id": None}

    def save_config(self):
        """Сохраняет настройки в файл"""
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    async def setup_hook(self):
        await self.tree.sync()
        logger.info("Слэш-команды синхронизированы")
        self.add_view(TicketButton(self))
        self.add_view(CloseTicketButton(self))

bot = TicketBot()

# ---------- Модальное окно для создания тикета (через кнопку) ----------
class TicketModal(Modal):
    def __init__(self, bot_instance):
        super().__init__(title="📝 Создание тикета")
        self.bot_instance = bot_instance
        self.topic = TextInput(
            label="Тема обращения",
            placeholder="Например: Проблема с доступом, Вопрос по боту...",
            required=True,
            max_length=100
        )
        self.description = TextInput(
            label="Описание проблемы",
            placeholder="Опишите подробно вашу проблему...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000
        )
        self.add_item(self.topic)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Получаем настройки
        panel_channel_id = self.bot_instance.config.get("panel_channel_id")
        log_channel_id = self.bot_instance.config.get("log_channel_id")
        
        # Создаём канал для тикета
        category = discord.utils.get(interaction.guild.categories, name="Тикеты")
        if not category:
            category = await interaction.guild.create_category("Тикеты")
        
        channel_name = f"тикет-{interaction.user.name.lower()}"
        existing = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if existing:
            await interaction.followup.send("❌ У вас уже есть открытый тикет! Закройте его перед созданием нового.", ephemeral=True)
            return
        
        # Права доступа
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        admin_role = discord.utils.get(interaction.guild.roles, name="Admin")
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        ticket_channel = await category.create_text_channel(channel_name, overwrites=overwrites)
        
        # Приветственное сообщение в тикете
        embed = discord.Embed(
            title="📌 Тикет создан",
            description=f"**Тема:** {self.topic.value}\n\n**Описание:**\n{self.description.value}",
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=f"Пользователь: {interaction.user}")
        await ticket_channel.send(f"{interaction.user.mention}, ваше обращение принято!", embed=embed, view=CloseTicketButton(bot))
        
        # Уведомление в лог-канал (если настроен)
        if log_channel_id:
            log_channel = interaction.guild.get_channel(log_channel_id)
            if log_channel:
                log_embed = discord.Embed(
                    title="🆕 Новый тикет",
                    description=f"**Пользователь:** {interaction.user.mention}\n**Канал:** {ticket_channel.mention}\n**Тема:** {self.topic.value}",
                    color=discord.Color.blue(),
                    timestamp=datetime.utcnow()
                )
                await log_channel.send(embed=log_embed)
        
        await interaction.followup.send(f"✅ Тикет создан! Перейдите в канал {ticket_channel.mention}", ephemeral=True)
        logger.info(f"Создан тикет {channel_name} от {interaction.user}")

# ---------- Кнопка создания тикета ----------
class TicketButton(View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot_instance = bot_instance

    @discord.ui.button(label="📩 Создать тикет", style=discord.ButtonStyle.green, custom_id="ticket_create")
    async def create_ticket(self, interaction: discord.Interaction, button: Button):
        # Открываем модальное окно
        await interaction.response.send_modal(TicketModal(self.bot_instance))

# ---------- Кнопка закрытия тикета ----------
class CloseTicketButton(View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot_instance = bot_instance

    @discord.ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.red, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        # Проверяем, что канал - тикет
        if not interaction.channel.name.startswith("тикет-"):
            await interaction.response.send_message("❌ Эта команда работает только в каналах тикетов!", ephemeral=True)
            return
        
        # Подтверждение
        view = ConfirmClose()
        await interaction.response.send_message("⚠️ Вы уверены, что хотите закрыть этот тикет?", ephemeral=True, view=view)
        
        # Ждём ответа
        await view.wait()
        if view.value is True:
            # Сохраняем лог
            os.makedirs("ticket_logs", exist_ok=True)
            log_file = f"ticket_logs/{interaction.channel.name}.txt"
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"Лог тикета: {interaction.channel.name}\n")
                f.write(f"Дата закрытия: {datetime.utcnow()}\n")
                f.write("="*50 + "\n")
                async for msg in interaction.channel.history(limit=200, oldest_first=True):
                    f.write(f"{msg.author} [{msg.created_at}]: {msg.content}\n")
            
            # Уведомление в лог-канал
            log_channel_id = self.bot_instance.config.get("log_channel_id")
            if log_channel_id:
                log_channel = interaction.guild.get_channel(log_channel_id)
                if log_channel:
                    await log_channel.send(f"✅ Тикет {interaction.channel.mention} закрыт пользователем {interaction.user}")
            
            await interaction.edit_original_response(content="🔒 Тикет закрывается...", view=None)
            await asyncio.sleep(2)
            await interaction.channel.delete()
            logger.info(f"Тикет {interaction.channel.name} закрыт")

class ConfirmClose(View):
    def __init__(self):
        super().__init__(timeout=30)
        self.value = None
    
    @discord.ui.button(label="✅ Да, закрыть", style=discord.ButtonStyle.red)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        self.value = True
        self.stop()
        await interaction.response.edit_message(content="✅ Подтверждено", view=None)
    
    @discord.ui.button(label="❌ Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        self.value = False
        self.stop()
        await interaction.response.edit_message(content="❌ Отменено", view=None)

# ---------- Слэш-команды ----------

@bot.tree.command(name="setup", description="🔧 Настройка системы тикетов (админ)")
@app_commands.default_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    """Главная команда настройки"""
    embed = discord.Embed(
        title="🔧 Настройка системы тикетов",
        description="Используйте кнопки ниже для настройки:",
        color=discord.Color.blue()
    )
    embed.add_field(name="1️⃣ Канал с кнопкой", value="Выберите канал, где будет отображаться кнопка «Создать тикет»", inline=False)
    embed.add_field(name="2️⃣ Канал уведомлений", value="Выберите канал, куда будут приходить уведомления о новых тикетах", inline=False)
    
    view = SetupView(bot)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class SetupView(View):
    def __init__(self, bot_instance):
        super().__init__(timeout=60)
        self.bot_instance = bot_instance
    
    @discord.ui.button(label="📢 Настроить канал с кнопкой", style=discord.ButtonStyle.primary, custom_id="setup_panel")
    async def setup_panel_channel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            "📢 **Настройка канала с кнопкой**\n"
            "Напишите в этот чат **ID** канала или **упомяните** канал, где будет кнопка.\n"
            "Пример: `#канал-тикетов` или `123456789012345678`\n\n"
            "Введите `отмена` для отмены.",
            ephemeral=True
        )
        
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        
        try:
            msg = await self.bot_instance.wait_for("message", timeout=30, check=check)
            if msg.content.lower() == "отмена":
                await interaction.followup.send("❌ Настройка отменена", ephemeral=True)
                return
            
            # Парсим канал
            channel = None
            if msg.channel_mentions:
                channel = msg.channel_mentions[0]
            elif msg.content.isdigit():
                channel = interaction.guild.get_channel(int(msg.content))
            
            if channel:
                self.bot_instance.config["panel_channel_id"] = channel.id
                self.bot_instance.save_config()
                
                # Отправляем панель в выбранный канал
                embed = discord.Embed(
                    title="🎫 Система поддержки",
                    description="Нажмите на кнопку «Создать тикет», чтобы открыть обращение в службу поддержки.",
                    color=discord.Color.green()
                )
                await channel.send(embed=embed, view=TicketButton(self.bot_instance))
                
                await interaction.followup.send(f"✅ Канал с кнопкой установлен: {channel.mention}", ephemeral=True)
            else:
                await interaction.followup.send("❌ Канал не найден. Попробуйте ещё раз.", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Время вышло. Начните настройку заново.", ephemeral=True)
    
    @discord.ui.button(label="📝 Настроить канал уведомлений", style=discord.ButtonStyle.secondary, custom_id="setup_logs")
    async def setup_log_channel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            "📝 **Настройка канала уведомлений**\n"
            "Напишите в этот чат **ID** канала или **упомяните** канал, куда будут приходить уведомления о новых тикетах.\n"
            "Пример: `#логи-тикетов` или `123456789012345678`\n\n"
            "Введите `отмена` для отмены.\n"
            "Введите `удалить` чтобы отключить уведомления.",
            ephemeral=True
        )
        
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        
        try:
            msg = await self.bot_instance.wait_for("message", timeout=30, check=check)
            if msg.content.lower() == "отмена":
                await interaction.followup.send("❌ Настройка отменена", ephemeral=True)
                return
            
            if msg.content.lower() == "удалить":
                self.bot_instance.config["log_channel_id"] = None
                self.bot_instance.save_config()
                await interaction.followup.send("✅ Уведомления отключены", ephemeral=True)
                return
            
            channel = None
            if msg.channel_mentions:
                channel = msg.channel_mentions[0]
            elif msg.content.isdigit():
                channel = interaction.guild.get_channel(int(msg.content))
            
            if channel:
                self.bot_instance.config["log_channel_id"] = channel.id
                self.bot_instance.save_config()
                await interaction.followup.send(f"✅ Канал уведомлений установлен: {channel.mention}", ephemeral=True)
                
                # Тестовое уведомление
                test_embed = discord.Embed(
                    title="✅ Настройка завершена",
                    description="Уведомления о тикетах будут приходить сюда.",
                    color=discord.Color.green()
                )
                await channel.send(embed=test_embed)
            else:
                await interaction.followup.send("❌ Канал не найден. Попробуйте ещё раз.", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Время вышло. Начните настройку заново.", ephemeral=True)
    
    @discord.ui.button(label="ℹ️ Информация", style=discord.ButtonStyle.gray, custom_id="setup_info")
    async def show_info(self, interaction: discord.Interaction, button: Button):
        panel_status = f"<#{self.bot_instance.config['panel_channel_id']}>" if self.bot_instance.config['panel_channel_id'] else "❌ Не настроен"
        log_status = f"<#{self.bot_instance.config['log_channel_id']}>" if self.bot_instance.config['log_channel_id'] else "❌ Не настроен"
        
        embed = discord.Embed(
            title="ℹ️ Текущие настройки",
            description=f"**Канал с кнопкой:** {panel_status}\n**Канал уведомлений:** {log_status}",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ticket_log", description="📄 Получить лог закрытого тикета (админ)")
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

@bot.tree.command(name="reload_panel", description="🔄 Пересоздать панель с кнопкой в настроенном канале (админ)")
@app_commands.default_permissions(administrator=True)
async def reload_panel(interaction: discord.Interaction):
    panel_channel_id = bot.config.get("panel_channel_id")
    if not panel_channel_id:
        await interaction.response.send_message("❌ Сначала настройте канал с кнопкой через `/setup`", ephemeral=True)
        return
    
    channel = interaction.guild.get_channel(panel_channel_id)
    if not channel:
        await interaction.response.send_message("❌ Канал не найден. Настройте заново через `/setup`", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🎫 Система поддержки",
        description="Нажмите на кнопку «Создать тикет», чтобы открыть обращение в службу поддержки.",
        color=discord.Color.green()
    )
    await channel.send(embed=embed, view=TicketButton(bot))
    await interaction.response.send_message(f"✅ Панель создана в канале {channel.mention}", ephemeral=True)

# ---------- Событие готовности ----------
@bot.event
async def on_ready():
    logger.info(f"✅ Бот {bot.user} запущен на хостинге!")
    await bot.change_presence(activity=discord.Game(name="/setup - настройка тикетов"))
    print(f"Бот {bot.user} готов. Используйте /setup для настройки")

# ---------- Запуск ----------
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
