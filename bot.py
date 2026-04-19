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
    """Проверка: есть ли у пользователя одна из разрешённых ролей ИЛИ права администратора"""
    if interaction.user.guild_permissions.administrator:
        return True
    for role_id in ROLE_IDS:
        role = interaction.user.get_role(role_id)
        if role:
            return True
    return False

def can_close_ticket(interaction: discord.Interaction, ticket_author_id: int) -> bool:
    """Кто может закрыть тикет:
    1. Администратор сервера
    2. Сотрудник с ролью из списка
    3. Автор тикета (только если статус не 'review')
    """
    if interaction.user.guild_permissions.administrator:
        return True
    for role_id in ROLE_IDS:
        role = interaction.user.get_role(role_id)
        if role:
            return True
    if interaction.user.id == ticket_author_id:
        return True
    return False

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
        
        try:
            if interaction.guild.id != WHITE_SERVER_ID:
                await interaction.followup.send("⛔ Бот работает только на официальном сервере!", ephemeral=True)
                return
            
            category = interaction.guild.get_channel(TICKET_CATEGORY_ID)
            if not category:
                category = await interaction.guild.create_category("Жалобы в Прокуратуру")
                await interaction.followup.send("ℹ️ Категория для жалоб создана автоматически.", ephemeral=True)
            
            channel_name = f"жалоба-{interaction.user.name.lower()}"
            existing = discord.utils.get(interaction.guild.text_channels, name=channel_name)
            if existing:
                await interaction.followup.send("❌ У вас уже есть открытая жалоба! Дождитесь рассмотрения.", ephemeral=True)
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
                "author_id": interaction.user.id,
                "channel_name": channel_name
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
            logger.info(f"Создана жалоба {channel_name} от {interaction.user}")
            
        except discord.Forbidden:
            await interaction.followup.send("❌ У бота нет прав для создания канала! Выдайте ему права `Manage Channels`.", ephemeral=True)
        except Exception as e:
            logger.error(f"Ошибка при создании тикета: {e}")
            await interaction.followup.send(f"❌ Произошла ошибка: {str(e)[:100]}\n\nПожалуйста, сообщите администратору.\n\nby Ilya Vetrov", ephemeral=True)

# ========== КНОПКИ УПРАВЛЕНИЯ ТИКЕТОМ ==========
class TicketControlButtons(View):
    def __init__(self, author_id, channel_id):
        super().__init__(timeout=None)
        self.author_id = author_id
        self.channel_id = channel_id

    @discord.ui.button(label="🔒 Закрыть жалобу", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        # ✅ ОБЯЗАТЕЛЬНОЕ ОТЛОЖЕНИЕ ОТВЕТА (чтобы избежать "Приложение не отвечает")
        await interaction.response.defer(ephemeral=True)
        
        if not can_close_ticket(interaction, self.author_id):
            await interaction.followup.send("❌ У вас нет прав для закрытия этой жалобы!\n\n*Закрыть могут: автор, администратор или сотрудник с ролью*", ephemeral=True)
            return
        
        if interaction.user.id == self.author_id:
            if self.channel_id in ticket_status and ticket_status[self.channel_id].get("status") == "review":
                await interaction.followup.send("❌ Жалоба уже на рассмотрении! Вы не можете её закрыть.\n\n*Дождитесь решения сотрудника*", ephemeral=True)
                return
        
        await interaction.followup.send("🔒 Жалоба будет закрыта через 3 секунды...\n\nby Ilya Vetrov", ephemeral=True)
        
        os.makedirs("complaint_logs", exist_ok=True)
        log_file = f"complaint_logs/{interaction.channel.name}.txt"
        
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"Лог жалобы: {interaction.channel.name}\n")
                f.write(f"Дата закрытия: {datetime.utcnow()}\n")
                f.write(f"Закрыл: {interaction.user} ({interaction.user.id})\n")
                f.write("by Ilya Vetrov\n")
                f.write("="*50 + "\n")
                async for msg in interaction.channel.history(limit=500, oldest_first=True):
                    f.write(f"{msg.author} [{msg.created_at}]: {msg.content}\n")
        except Exception as e:
            logger.error(f"Ошибка сохранения лога: {e}")
        
        await asyncio.sleep(3)
        
        try:
            if self.channel_id in ticket_status:
                del ticket_status[self.channel_id]
            await interaction.channel.delete()
        except Exception as e:
            logger.error(f"Ошибка удаления канала: {e}")

    @discord.ui.button(label="📋 На рассмотрении", style=discord.ButtonStyle.primary, custom_id="review_ticket")
    async def review_ticket(self, interaction: discord.Interaction, button: Button):
        # ✅ ОТЛОЖЕННЫЙ ОТВЕТ
        await interaction.response.defer(ephemeral=True)
        
        if not check_roles(interaction):
            await interaction.followup.send("❌ Только сотрудники или администраторы могут перевести жалобу в режим рассмотрения!\n\nby Ilya Vetrov", ephemeral=True)
            return
        
        if self.channel_id in ticket_status and ticket_status[self.channel_id].get("status") == "review":
            await interaction.followup.send("ℹ️ Эта жалоба уже на рассмотрении!\n\nby Ilya Vetrov", ephemeral=True)
            return
        
        ticket_status[self.channel_id] = {
            "status": "review",
            "author_id": self.author_id,
            "channel_name": interaction.channel.name
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
        
        await interaction.followup.send("✅ Жалоба переведена в статус «На рассмотрении»\n\nby Ilya Vetrov", ephemeral=True)
        await interaction.channel.send(embed=embed, view=StaffCloseButton(self.channel_id, self.author_id))
        
        try:
            await interaction.channel.purge(limit=1)
        except:
            pass

# ========== КНОПКА ЗАКРЫТИЯ ДЛЯ СОТРУДНИКОВ И АДМИНОВ ==========
class StaffCloseButton(View):
    def __init__(self, channel_id, author_id):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        self.author_id = author_id

    @discord.ui.button(label="🔒 Закрыть жалобу", style=discord.ButtonStyle.red, custom_id="staff_close")
    async def staff_close(self, interaction: discord.Interaction, button: Button):
        # ✅ ОТЛОЖЕННЫЙ ОТВЕТ
        await interaction.response.defer(ephemeral=True)
        
        if not check_roles(interaction):
            await interaction.followup.send("❌ Только администраторы или сотрудники могут закрыть жалобу!\n\nby Ilya Vetrov", ephemeral=True)
            return
        
        await interaction.followup.send("🔒 Жалоба будет закрыта через 3 секунды...\n\nby Ilya Vetrov", ephemeral=True)
        
        os.makedirs("complaint_logs", exist_ok=True)
        log_file = f"complaint_logs/{interaction.channel.name}.txt"
        
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"Лог жалобы: {interaction.channel.name}\n")
                f.write(f"Дата закрытия: {datetime.utcnow()}\n")
                f.write(f"Закрыл сотрудник/админ: {interaction.user} ({interaction.user.id})\n")
                f.write("by Ilya Vetrov\n")
                f.write("="*50 + "\n")
                async for msg in interaction.channel.history(limit=500, oldest_first=True):
                    f.write(f"{msg.author} [{msg.created_at}]: {msg.content}\n")
        except Exception as e:
            logger.error(f"Ошибка сохранения лога: {e}")
        
        await asyncio.sleep(3)
        
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
        await interaction.response.send_message(f"❌ Канал {PANEL_CHANNEL_ID} не найден!\n\nby Ilya Vetrov", ephemeral=True)
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

@bot.tree.command(name="force_close", description="⚠️ ПРИНУДИТЕЛЬНО закрыть любой тикет (админ/сотрудник)")
@app_commands.describe(channel_id="ID канала с жалобой (например, 123456789012345678)")
async def force_close(interaction: discord.Interaction, channel_id: str = None):
    await interaction.response.defer(ephemeral=True)  # ✅ defer для команд тоже полезен
    
    if not check_roles(interaction):
        await interaction.followup.send("❌ У вас нет прав для использования этой команды!\n\nby Ilya Vetrov", ephemeral=True)
        return
    
    if not channel_id:
        active_tickets = []
        for cid, data in ticket_status.items():
            channel = interaction.guild.get_channel(cid)
            if channel:
                active_tickets.append(f"📄 `{cid}` - {channel.name} (автор: <@{data.get('author_id')}>)")
        
        if not active_tickets:
            await interaction.followup.send("📭 Нет активных тикетов.\n\nby Ilya Vetrov", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="⚠️ Принудительное закрытие тикета",
            description="Используйте: `/force_close ID_канала`\n\n**Активные тикеты:**\n" + "\n".join(active_tickets),
            color=discord.Color.orange()
        )
        embed.set_footer(text="by Ilya Vetrov")
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    
    try:
        channel_id_int = int(channel_id)
        channel = interaction.guild.get_channel(channel_id_int)
        
        if not channel:
            await interaction.followup.send(f"❌ Канал с ID `{channel_id}` не найден!\n\nby Ilya Vetrov", ephemeral=True)
            return
        
        if not channel.name.startswith("жалоба-"):
            await interaction.followup.send(f"❌ Канал `{channel.name}` не является каналом жалобы!\n\nby Ilya Vetrov", ephemeral=True)
            return
        
        await interaction.followup.send(f"⚠️ Принудительное закрытие канала `{channel.name}` через 3 секунды...\n\nby Ilya Vetrov", ephemeral=True)
        
        os.makedirs("complaint_logs", exist_ok=True)
        log_file = f"complaint_logs/{channel.name}.txt"
        
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"Лог жалобы: {channel.name}\n")
                f.write(f"Дата принудительного закрытия: {datetime.utcnow()}\n")
                f.write(f"Принудительно закрыл: {interaction.user} ({interaction.user.id})\n")
                f.write("by Ilya Vetrov\n")
                f.write("="*50 + "\n")
                async for msg in channel.history(limit=500, oldest_first=True):
                    f.write(f"{msg.author} [{msg.created_at}]: {msg.content}\n")
        except Exception as e:
            logger.error(f"Ошибка сохранения лога: {e}")
        
        await asyncio.sleep(3)
        
        if channel.id in ticket_status:
            del ticket_status[channel.id]
        await channel.delete()
        
    except ValueError:
        await interaction.followup.send(f"❌ Неверный формат ID. Введите числовой ID канала.\n\nby Ilya Vetrov", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка при закрытии: {str(e)[:100]}\n\nby Ilya Vetrov", ephemeral=True)

@bot.tree.command(name="complaint_log", description="📄 Получить лог закрытой жалобы")
@app_commands.describe(channel_name="Название канала жалобы (например, жалоба-иван)")
async def complaint_log(interaction: discord.Interaction, channel_name: str = None):
    await interaction.response.defer(ephemeral=True)  # ✅ defer для безопасности
    
    if not check_roles(interaction):
        await interaction.followup.send("❌ Нет прав!\n\nby Ilya Vetrov", ephemeral=True)
        return
    
    if not channel_name:
        await interaction.followup.send("❌ Укажите название канала\n\nby Ilya Vetrov", ephemeral=True)
        return
    
    log_path = f"complaint_logs/{channel_name}.txt"
    if not os.path.exists(log_path):
        await interaction.followup.send(f"❌ Лог для `{channel_name}` не найден.\n\nby Ilya Vetrov", ephemeral=True)
        return
    
    await interaction.followup.send(file=discord.File(log_path))

@bot.tree.command(name="closed_list", description="📋 Список всех закрытых жалоб")
async def closed_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)  # ✅ defer для безопасности
    
    if not check_roles(interaction):
        await interaction.followup.send("❌ Нет прав!\n\nby Ilya Vetrov", ephemeral=True)
        return
    
    os.makedirs("complaint_logs", exist_ok=True)
    files = [f.replace(".txt", "") for f in os.listdir("complaint_logs") if f.endswith(".txt")]
    
    if not files:
        await interaction.followup.send("📭 Нет закрытых жалоб.\n\nby Ilya Vetrov", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📋 Список закрытых жалоб",
        description="\n".join([f"📄 `{f}`" for f in files]),
        color=discord.Color.blue()
    )
    embed.set_footer(text="by Ilya Vetrov")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="active_list", description="📋 Список активных (открытых) жалоб")
async def active_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)  # ✅ defer для безопасности
    
    if not check_roles(interaction):
        await interaction.followup.send("❌ Нет прав!\n\nby Ilya Vetrov", ephemeral=True)
        return
    
    active_tickets = []
    for cid, data in ticket_status.items():
        channel = interaction.guild.get_channel(cid)
        if channel:
            status_text = "🟢 ОЖИДАЕТ" if data.get("status") == "waiting" else "🟡 НА РАССМОТРЕНИИ"
            active_tickets.append(f"📄 `{channel.name}` - {status_text} (автор: <@{data.get('author_id')}>)")
    
    if not active_tickets:
        await interaction.followup.send("📭 Нет активных жалоб.\n\nby Ilya Vetrov", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="📋 Список активных жалоб",
        description="\n".join(active_tickets),
        color=discord.Color.green()
    )
    embed.set_footer(text="by Ilya Vetrov")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="info", description="ℹ️ Информация о боте")
async def info(interaction: discord.Interaction):
    embed = discord.Embed(
        title="ℹ️ О боте",
        description=(
            "**Система подачи жалоб в Прокуратуру Нижегородской области**\n\n"
            "👨‍💻 **Разработчик:** Ilya Vetrov\n"
            "🛡️ **Версия:** 2.3 (исправлен таймаут)\n\n"
            "**Команды:**\n"
            "• `/setup` - Настройка панели (админ)\n"
            "• `/force_close` - Принудительно закрыть тикет\n"
            "• `/active_list` - Список активных тикетов\n"
            "• `/closed_list` - Список закрытых тикетов\n"
            "• `/complaint_log` - Лог закрытого тикета\n"
            "• `/check_roles` - Проверка ролей\n"
            "• `/info` - Эта информация\n\n"
            "**Кто может закрыть тикет:**\n"
            "• Автор жалобы (до рассмотрения)\n"
            "• Администратор сервера\n"
            "• Сотрудник с ролью"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="by Ilya Vetrov")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="check_roles", description="👥 Проверить какие роли видят тикеты")
async def check_roles_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)  # ✅ defer для безопасности
    
    if not check_roles(interaction):
        await interaction.followup.send("❌ Нет прав!\n\nby Ilya Vetrov", ephemeral=True)
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
        description="\n".join(roles_list) + "\n\n✅ Администраторы сервера также имеют полный доступ",
        color=discord.Color.blue()
    )
    embed.set_footer(text="by Ilya Vetrov")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.event
async def on_ready():
    logger.info(f"✅ Бот {bot.user} запущен!")
    await bot.change_presence(activity=discord.Game(name="by Ilya Vetrov"))
    print(f"✅ Бот {bot.user} готов!")
    print(f"👨‍💻 by Ilya Vetrov")
    print(f"🔧 Доступные команды: /setup, /force_close, /active_list, /closed_list, /complaint_log, /check_roles, /info")

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")