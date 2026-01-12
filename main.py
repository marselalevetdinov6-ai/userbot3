import asyncio
import json
import os
import re
import logging
from datetime import datetime
from typing import List, Optional, Set
from enum import Enum
from telethon import TelegramClient, events
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import (
    FloodWaitError, ChannelPrivateError, ChatAdminRequiredError,
    UserAlreadyParticipantError, UsernameNotOccupiedError,
    UsernameInvalidError, InviteHashExpiredError,
    InviteHashInvalidError, InviteRequestSentError
)
from telethon.tl.types import Channel, Chat, User
from dataclasses import dataclass, asdict
from dataclasses_json import dataclass_json

# ==================== КОНФИГУРАЦИЯ ====================
API_ID = 30320335  # Получите на my.telegram.org
API_HASH = 'c19aaafc21ca4cedbd72b89ec8a7c544'  # Получите на my.telegram.org
PHONE_NUMBER = '+19017175662'  # Ваш номер телефона

# Настройки бота
TARGET_BOT = 'gram_piarbot'  # Бот, сообщения которого будем обрабатывать
MESSAGE_INTERVAL = 5  # Интервал между отправкой сообщений в секундах
JOIN_DELAY = 5  # Задержка между вступлениями в секундах
MAX_JOIN_ATTEMPTS = 3  # Максимальное количество попыток вступления

# Настройки для ответов на личные сообщения
RESPONSE_ENABLED = True  # Включить ответы на личные сообщения
AUTO_JOIN_FROM_PM = True  # Автоматически вступать в каналы из личных сообщений
RESPONSE_MESSAGE = "✅ Спасибо за сообщение! Я автоматически обработаю все ссылки на каналы и чаты."

# Паттерны для поиска ссылок
LINK_PATTERNS = [
    r'https?://t.me/joinchat/([a-zA-Z0-9_-]+)',  # Приватные ссылки
    r'https?://t.me/+([a-zA-Z0-9_-]+)',  # Приватные ссылки с +
    r't.me/([a-zA-Z0-9_]+)',  # Публичные ссылки
    r'telegram.me/([a-zA-Z0-9_]+)',  # Альтернативные ссылки
    r'@([a-zA-Z0-9_]{5,32})'  # Username
]

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ==================== МОДЕЛИ ДАННЫХ ====================
class ChatStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    LEFT = "left"
    BANNED = "banned"


@dataclass_json
@dataclass
class ChatInfo:
    id: int
    title: str
    username: Optional[str]
    link: str
    status: ChatStatus
    joined_at: str
    last_activity: str
    is_group: bool = False
    is_channel: bool = False
    participants_count: int = 0


# ==================== ОСНОВНОЙ КЛАСС БОТА ====================
class TelegramAutoJoinBot:
    def __init__(self):
        self.client = None
        self.chats = {}  # id -> ChatInfo
        self.active_chats = set()  # id активных чатов
        self.data_file = 'chats_data.json'
        self.joined_channels_file = 'joined_channels.json'
        self.message_text = ""

        # Загружаем сохраненные данные
        self.load_data()

    def load_data(self):
        """Загружает сохраненные данные из файла"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for chat_id, chat_data in data.get('chats', {}).items():
                        chat_info = ChatInfo.from_dict(chat_data)
                        chat_info.status = ChatStatus(chat_data['status'])
                        self.chats[int(chat_id)] = chat_info
                        if chat_info.status == ChatStatus.ACTIVE:
                            self.active_chats.add(int(chat_id))
                logger.info(f"📂 Загружено {len(self.chats)} сохраненных чатов")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки данных: {e}")
            self.chats = {}
            self.active_chats = set()

    def save_data(self):
        """Сохраняет данные в файл"""
        try:
            data = {
                'chats': {str(chat_id): asdict(chat_info) for chat_id, chat_info in self.chats.items()}
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("💾 Данные сохранены")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения данных: {e}")

    def extract_links(self, text: str) -> List[str]:
        """Извлекает все ссылки на Telegram из текста"""
        links = []

        for pattern in LINK_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if pattern == r'https?://t.me/joinchat/([a-zA-Z0-9_-]+)':
                    links.append(f"https://t.me/joinchat/{match}")
                elif pattern == r'https?://t.me/+([a-zA-Z0-9_-]+)':
                    links.append(f"https://t.me/+{match}")
                elif pattern in [r't.me/([a-zA-Z0-9_]+)', r'telegram.me/([a-zA-Z0-9_]+)']:
                    links.append(f"t.me/{match}")
                elif pattern == r'@([a-zA-Z0-9_]{5,32})':
                    links.append(f"@{match}")

        return list(set(links))  # Убираем дубликаты

    async def join_channel(self, link: str) -> Optional[ChatInfo]:
        """Присоединяется к каналу/чату по ссылке и возвращает информацию"""
        try:
            logger.info(f"Попытка присоединиться к: {link}")

            # Проверяем, не присоединялись ли уже
            for chat in self.chats.values():
                if chat.link == link:
                    logger.info(f"Уже присоединен к: {link}")
                    chat.status = ChatStatus.ACTIVE
                    self.active_chats.add(chat.id)
                    return chat

            entity = None
            is_channel = False
            is_group = False

            # Обработка разных типов ссылок
            if link.startswith('https://t.me/joinchat/') or link.startswith('https://t.me/+'):
                # Приватная ссылка с инвайтом
                invite_hash = link.split('/')[-1]
                if invite_hash.startswith('+'):
                    invite_hash = invite_hash[1:]

                try:
                    result = await self.client(ImportChatInviteRequest(invite_hash))
                    entity = result.chats[0] if result.chats else None
                    is_group = True
                    logger.info(f"Успешно присоединился по приватной ссылке: {link}")
                except InviteHashExpiredError:
                    logger.error(f"Ссылка истекла: {link}")
                    return None
                except InviteHashInvalidError:
                    logger.error(f"Неверная ссылка: {link}")
                    return None
                except InviteRequestSentError:
                    logger.info(f"Запрос на присоединение отправлен: {link}")
                    # Создаем временную запись
                    chat_info = ChatInfo(
                        id=hash(link),  # Временный ID
                        title=link,
                        username=None,
                        link=link,
                        status=ChatStatus.PAUSED,
                        joined_at=datetime.now().isoformat(),
                        last_activity=datetime.now().isoformat(),
                        is_group=True
                    )
                    self.chats[chat_info.id] = chat_info
                    self.save_data()
                    return chat_info

            else:
                # Публичный канал/чат
                # Извлекаем username из ссылки
                if link.startswith('t.me/'):
                    username = link[5:]
                elif link.startswith('@'):
                    username = link[1:]
                else:
                    username = link

                # Убираем возможные параметры
                username = username.split('?')[0]

                try:
                    # Пытаемся получить сущность
                    entity = await self.client.get_entity(username)

                    if isinstance(entity, Channel):
                        is_channel = True
                        # Присоединяемся к каналу
                        await self.client(JoinChannelRequest(entity))
                        logger.info(f"Успешно присоединился к каналу: {link}")
                    elif isinstance(entity, Chat):
                        is_group = True
                        logger.info(f"Уже в чате: {link}")
                    else:
                        logger.error(f"Неизвестный тип сущности: {type(entity)}")
                        return None

                except (UsernameNotOccupiedError, UsernameInvalidError):
                    logger.error(f"Неверный username: {link}")
                    return None
                except UserAlreadyParticipantError:
                    logger.info(f"Уже участник: {link}")
                except ChannelPrivateError:
                    logger.error(f"Канал приватный: {link}")
                    return None
                except Exception as e:
                    logger.error(f"Ошибка при присоединении к {link}: {e}")
                    return None

            # Получаем информацию о чате
            if entity:
                try:
                    # Получаем полную информацию
                    full_chat = await self.client.get_entity(entity)

                    chat_info = ChatInfo(
                        id=full_chat.id,
                        title=getattr(full_chat, 'title', link),
                        username=getattr(full_chat, 'username', None),
                        link=link,
                        status=ChatStatus.ACTIVE,
                        joined_at=datetime.now().isoformat(),
                        last_activity=datetime.now().isoformat(),
                        is_group=is_group,
                        is_channel=is_channel,
                        participants_count=getattr(full_chat, 'participants_count', 0)
                    )

                    self.chats[chat_info.id] = chat_info
                    self.active_chats.add(chat_info.id)
                    self.save_data()

                    logger.info(f"✅ Успешно присоединился: {chat_info.title}")
                    return chat_info

                except Exception as e:
                    logger.error(f"Ошибка получения информации о чате {link}: {e}")
                    return None

        except FloodWaitError as e:
            wait_time = e.seconds
            logger.warning(f"⚠️ FloodWait: ждем {wait_time} секунд")
            await asyncio.sleep(wait_time)
            return await self.join_channel(link)  # Повторная попытка
        except Exception as e:
            logger.error(f"❌ Неизвестная ошибка при присоединении к {link}: {e}")
            return None

    async def process_message(self, text: str, source: str):
        """Обрабатывает сообщение и присоединяется ко всем найденным ссылкам"""
        logger.info(f"📨 Обработка сообщения от {source}")

        links = self.extract_links(text)
        if not links:
            logger.info("ℹ️ Ссылки не найдены")
            return

        logger.info(f"🔗 Найдено {len(links)} ссылок: {links}")

        results = []
        for i, link in enumerate(links):
            logger.info(f"🔄 Обработка ссылки {i + 1}/{len(links)}: {link}")

            # Задержка между обработкой ссылок
            if i > 0:
                await asyncio.sleep(JOIN_DELAY)

            chat_info = await self.join_channel(link)
            if chat_info:
                results.append(f"✅ {chat_info.title}: {link}")
            else:
                results.append(f"❌ Не удалось присоединиться: {link}")
        return

    async def run(self):
        """Основной метод запуска бота"""
        # Создаем клиент
        self.client = TelegramClient('session', API_ID, API_HASH)

        # Создаем папку session если ее нет
        if not os.path.exists('session'):
            os.makedirs('session')

        # Запускаем клиент с авторизацией
        logger.info("🔐 Подключение к Telegram...")
        await self.client.start(phone=PHONE_NUMBER)
        logger.info("✅ Успешно авторизован!")

        # Получаем информацию о себе
        me = await self.client.get_me()
        logger.info(f"👤 Авторизован как: {me.first_name} (@{me.username})")

        # ============ РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ СОБЫТИЙ ============

        @self.client.on(events.NewMessage())
        async def message_handler(event):
            """Обработчик всех сообщений"""

            # Проверяем, что сообщение от нужного бота
            sender = await event.get_sender()
            if sender and hasattr(sender, 'username') and sender.username == TARGET_BOT:
                logger.info(f"🤖 Сообщение от @{TARGET_BOT}")

                # Сохраняем текст сообщения
                self.message_text = event.message.text

                # Обрабатываем сообщение
                report = await self.process_message(event.message.text, f"@{TARGET_BOT}")

            # Обработка личных сообщений от пользователей
            elif event.is_private and RESPONSE_ENABLED:
                # Не обрабатываем сообщения от самого себя
                if sender and sender.id == me.id:
                    return

                logger.info(f"👤 Личное сообщение от {sender.first_name if sender else 'неизвестный'}")

                # Если включено автоприсоединение, обрабатываем ссылки
                if AUTO_JOIN_FROM_PM and event.message.text:
                    report = await self.process_message(event.message.text, f"Пользователь {sender.id}")
                    if report:
                        await event.respond(report, parse_mode='Markdown')


        # Обработчик команды /start
        @self.client.on(events.NewMessage(pattern='(?i)/start'))
        async def start_handler(event):
            """Обработчик команды /start"""
            await event.respond(
                "🤖 **Бот запущен и готов к работе!**\n\n"
                f"Я буду автоматически обрабатывать сообщения от @{TARGET_BOT}\n"
                "и отвечать на личные сообщения.\n\n"
                "📊 **Статистика:**\n"
                f"• Активных чатов: {len(self.active_chats)}\n"
                f"• Всего чатов в базе: {len(self.chats)}\n\n"
                "ℹ️ Используйте /help для списка команд",
                parse_mode='Markdown'
            )

        # Обработчик команды /help
        @self.client.on(events.NewMessage(pattern='(?i)/help'))
        async def help_handler(event):
            """Обработчик команды /help"""
            help_text = """
📋 **Доступные команды:**

/start - Запустить бота и показать статистику
/help - Показать это сообщение
/status - Подробный статус бота
/stats - Статистика по чатам
/list - Список всех чатов
/join [ссылка] - Вступить в канал/чат по ссылке
/leave [id] - Покинуть чат по ID

⚙️ **Настройки:**
- Автообработка сообщений от @gram_piarbot
- Ответы на личные сообщения
- Автовступление в каналы из ЛС
- Логирование всех действий
            """
            await event.respond(help_text, parse_mode='Markdown')

        # Обработчик команды /status
        @self.client.on(events.NewMessage(pattern='(?i)/status'))
        async def status_handler(event):
            """Обработчик команды /status"""
            status_text = f"""
📊 **Статус бота:**

✅ **Активен**
👤 **Пользователь:** {me.first_name} (@{me.username})
📅 **Активных чатов:** {len(self.active_chats)}
🗂️ **Всего в базе:** {len(self.chats)}
🕒 **Время работы:** {datetime.now().strftime('%H:%M:%S')}
📡 **Целевой бот:** @{TARGET_BOT}
⏱️ **Интервал отправки:** {MESSAGE_INTERVAL} сек
            """
            await event.respond(status_text, parse_mode='Markdown')

        # Обработчик команды /stats
        @self.client.on(events.NewMessage(pattern='(?i)/stats'))
        async def stats_handler(event):
            """Обработчик команды /stats"""
            # Считаем статистику по типам чатов
            channels = sum(1 for c in self.chats.values() if c.is_channel)
            groups = sum(1 for c in self.chats.values() if c.is_group)
            active = sum(1 for c in self.chats.values() if c.status == ChatStatus.ACTIVE)

            stats_text = f"""
📈 **Статистика чатов:**

🔹 **Всего чатов:** {len(self.chats)}
🔹 **Активных:** {active}
🔹 **Каналов:** {channels}
🔹 **Групп:** {groups}
🔹 **Приостановлено:** {len(self.chats) - active}

📊 **По статусам:**
• ✅ Активных: {sum(1 for c in self.chats.values() if c.status == ChatStatus.ACTIVE)}
• ⏸️ Приостановлено: {sum(1 for c in self.chats.values() if c.status == ChatStatus.PAUSED)}
• 🚪 Покинуто: {sum(1 for c in self.chats.values() if c.status == ChatStatus.LEFT)}
• 🚫 Заблокировано: {sum(1 for c in self.chats.values() if c.status == ChatStatus.BANNED)}
            """
            await event.respond(stats_text, parse_mode='Markdown')

        # Обработчик команды /list
        @self.client.on(events.NewMessage(pattern='(?i)/list'))
        async def list_handler(event):
            """Обработчик команды /list"""
            if not self.chats:
                await event.respond("📭 Список чатов пуст")
                return

            response = "📋 **Список чатов:**\n\n"
            for i, (chat_id, chat) in enumerate(list(self.chats.items())[:20], 1):  # Ограничиваем 20 чатами
                status_emoji = {
                    ChatStatus.ACTIVE: "✅",
                    ChatStatus.PAUSED: "⏸️",
                    ChatStatus.LEFT: "🚪",
                    ChatStatus.BANNED: "🚫"
                }.get(chat.status, "❓")

                response += f"{i}. {status_emoji} **{chat.title}**\n"
                response += f"   ID: {chat_id}\n"
                if chat.username:
                    response += f"   @{chat.username}\n"
                response += f"   Тип: {'Канал' if chat.is_channel else 'Группа' if chat.is_group else 'Неизвестно'}\n"
                response += f"   Участников: {chat.participants_count}\n"
                response += f"   Добавлен: {chat.joined_at[:10]}\n\n"

            if len(self.chats) > 20:
                response += f"\n... и еще {len(self.chats) - 20} чатов"

            await event.respond(response, parse_mode='Markdown')

        # Обработчик команды /join
        @self.client.on(events.NewMessage(pattern='(?i)/join'))
        async def join_handler(event):
            """Обработчик команды /join"""
            args = event.message.text.split()
            if len(args) < 2:
                await event.respond("❌ Использование: /join [ссылка]")
                return

            link = args[1]
            await event.respond(f"🔄 Пытаюсь присоединиться к: {link}")

            chat_info = await self.join_channel(link)
            if chat_info:
                await event.respond(
                    f"✅ Успешно присоединился!\n\n"
                    f"**Название:** {chat_info.title}\n"
                    f"**ID:** {chat_info.id}\n"
                    f"**Тип:** {'Канал' if chat_info.is_channel else 'Группа'}\n"
                    f"**Статус:** {chat_info.status.value}",
                    parse_mode='Markdown'
                )
            else:
                await event.respond(f"❌ Не удалось присоединиться к: {link}")

        logger.info(f"✅ Бот запущен и готов к работе!")
        logger.info(f"📱 Ожидание сообщений от @{TARGET_BOT}...")

        if self.message_text:
            logger.info(f"📝 Текст сообщения: {self.message_text[:50]}...")
        logger.info(f"⏱️ Интервал отправки: {MESSAGE_INTERVAL} секунд")

        # Сохраняем данные перед запуском
        self.save_data()

        # Запускаем бесконечный цикл
        await self.client.run_until_disconnected()


# ==================== ЗАПУСК БОТА ====================
async def main():
    bot = TelegramAutoJoinBot()
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("\n🛑 Бот остановлен пользователем")
        bot.save_data()
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        bot.save_data()


if __name__ == '__main__':
    # Устанавливаем кодировку для Windows
    if os.name == 'nt':
        import sys

        sys.stdout.reconfigure(encoding='utf-8')

    # Запускаем бота
    asyncio.run(main())
