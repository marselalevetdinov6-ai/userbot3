#!/usr/bin/env python3
"""
Telegram User Bot без использования events - только базовые методы
"""

import asyncio
import logging
import json
import os
import sys
import getpass
import time
from datetime import datetime, timedelta
from telethon import TelegramClient, errors
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest


# ========== КОНФИГУРАЦИЯ ==========
class Config:
    # Получите на https://my.telegram.org
    API_ID = 30320335  # Получите на my.telegram.org
    API_HASH = 'c19aaafc21ca4cedbd72b89ec8a7c544'  # Получите на my.telegram.org

    # Файл сессии
    SESSION_FILE = 'user_bot.session'

    # Настройки автоотправки
    AUTO_SEND_ENABLED = True  # Включить автоотправку
    AUTO_SEND_INTERVAL = 180  # Интервал в секундах (3 минуты)
    AUTO_SEND_CHATS = []  # Список чатов для автоотправки (ID или username)
    AUTO_SEND_MESSAGES = []  # Список сообщений для ротации

    # Настройки
    LOG_LEVEL = logging.INFO


# ========== КЛАСС БОТА ==========
class TelegramUserBot:
    def __init__(self):
        self.client = None
        self.is_running = False
        self.auto_send_task = None
        self.message_check_task = None
        self.auto_send_enabled = Config.AUTO_SEND_ENABLED
        self.auto_send_interval = Config.AUTO_SEND_INTERVAL
        self.auto_send_chats = Config.AUTO_SEND_CHATS.copy()
        self.auto_send_messages = Config.AUTO_SEND_MESSAGES.copy()
        self.message_index = 0
        self.next_send_time = None
        self.last_message_id = {}  # Для отслеживания последних сообщений по чатам

    async def interactive_auth(self):
        """Интерактивная авторизация"""
        print("\n" + "=" * 50)
        print("🔐 АВТОРИЗАЦИЯ TELEGRAM USER BOT")
        print("=" * 50)

        # Запрашиваем данные у пользователя
        phone = input("\n📱 Введите номер телефона (например, +79123456789): ").strip()

        if not phone:
            print("❌ Номер телефона обязателен!")
            return False

        # Запускаем клиент
        self.client = TelegramClient(
            Config.SESSION_FILE,
            Config.API_ID,
            Config.API_HASH
        )

        try:
            # Подключаемся
            await self.client.connect()

            # Отправляем код
            sent_code = await self.client.send_code_request(phone)
            print(f"\n✅ Код отправлен на номер {phone}")

            # Запрашиваем код
            code = input("\n🔢 Введите код из Telegram: ").strip()

            if not code:
                print("❌ Код обязателен!")
                return False

            # Пытаемся войти
            try:
                await self.client.sign_in(phone, code)
                print("✅ Успешная авторизация!")
                return True

            except errors.SessionPasswordNeededError:
                # Нужен пароль 2FA
                print("\n🔐 Требуется пароль двухфакторной аутентификации")
                password = getpass.getpass("Введите пароль 2FA: ")
                await self.client.sign_in(password=password)
                print("✅ Успешная авторизация с 2FA!")
                return True

        except errors.PhoneNumberInvalidError:
            print("❌ Неверный номер телефона")
            return False
        except errors.PhoneCodeInvalidError:
            print("❌ Неверный код подтверждения")
            return False
        except errors.PhoneCodeExpiredError:
            print("❌ Срок действия кода истек")
            return False
        except Exception as e:
            print(f"❌ Ошибка авторизации: {e}")
            return False

    async def initialize(self):
        """Инициализация бота"""
        print("\n" + "=" * 50)
        print("🤖 TELEGRAM USER BOT v5.0 (без events)")
        print("=" * 50)

        # Проверяем API данные
        if Config.API_ID == 1234567 or Config.API_HASH == 'ваш_api_hash_здесь':
            print("\n❌ ОШИБКА: Не настроены API данные!")
            print("\nИнструкция по получению API:")
            print("1. Перейдите на https://my.telegram.org")
            print("2. Войдите в свой аккаунт Telegram")
            print("3. Создайте приложение в разделе 'API Development Tools'")
            print("4. Скопируйте API_ID и API_HASH")
            print("5. Вставьте их в файл main.py")
            return False

        # Проверяем существующую сессию
        if os.path.exists(Config.SESSION_FILE):
            print("\n📂 Найдена сохраненная сессия...")
            self.client = TelegramClient(
                Config.SESSION_FILE,
                Config.API_ID,
                Config.API_HASH
            )

            try:
                await self.client.connect()

                # Проверяем валидность сессии
                if not await self.client.is_user_authorized():
                    print("❌ Сессия устарела, требуется повторная авторизация")
                    if not await self.interactive_auth():
                        return False
                else:
                    print("✅ Используется сохраненная сессия")

            except Exception as e:
                print(f"❌ Ошибка подключения: {e}")
                if not await self.interactive_auth():
                    return False
        else:
            print("\n📂 Создание новой сессии...")
            if not await self.interactive_auth():
                return False

        # Получаем информацию о себе
        me = await self.client.get_me()
        print(f"\n✅ Успешный вход как: {me.first_name} (@{me.username})")
        print(f"🆔 ID пользователя: {me.id}")

        # Загружаем конфигурацию автоотправки
        await self.load_auto_send_config()

        return True

    async def check_new_messages(self):
        """Проверка новых сообщений (альтернатива events)"""
        print("\n📡 Начинаю проверку новых сообщений...")

        # Получаем все диалоги
        dialogs = await self.client.get_dialogs(limit=50)

        for dialog in dialogs:
            chat_id = dialog.id

            # Получаем последнее сообщение в диалоге
            messages = await self.client.get_messages(chat_id, limit=1)

            if messages:
                last_msg = messages[0]
                last_msg_id = last_msg.id

                # Проверяем, новое ли это сообщение
                if chat_id not in self.last_message_id:
                    self.last_message_id[chat_id] = last_msg_id
                    continue

                if last_msg_id != self.last_message_id[chat_id]:
                    # Новое сообщение!
                    self.last_message_id[chat_id] = last_msg_id

                    # Обрабатываем сообщение
                    await self.process_message(last_msg)

    async def process_message(self, message):
        """Обработка одного сообщения"""
        try:
            # Получаем информацию о сообщении
            sender = await message.get_sender()
            chat = await message.get_chat()
            message_text = message.message or ""

            # Пропускаем сообщения от самого себя
            me = await self.client.get_me()
            if sender.id == me.id:
                return

            print(f"\n📩 [{datetime.now().strftime('%H:%M:%S')}] Новое сообщение:")
            print(f"   👤 От: {sender.first_name} (@{sender.username})")
            print(f"   💬 Текст: {message_text[:100]}...")

            # Проверяем, является ли сообщение командой
            if message_text.startswith('/'):
                await self.process_command(message)
            elif message.is_private:
                # Автоответ на личные сообщения
                response = f"Привет. Го ВЗ: @roblox_ru_chat"
                await message.reply(response)
                print(f"   ✅ Автоответ отправлен")

        except Exception as e:
            print(f"❌ Ошибка обработки сообщения: {e}")

    async def process_command(self, message):
        """Обработка команд"""
        try:
            command = message.message.lower().strip()
            sender = await message.get_sender()

            # Получаем информацию о себе
            me = await self.client.get_me()

            print(f"\n⚡️ [{datetime.now().strftime('%H:%M:%S')}] Команда: {command}")
            print(f"   👤 От: {sender.first_name} (@{sender.username})")

            # Проверяем, что команда от владельца
            allowed_users = [
                me.id,  # Ваш ID
                8114855403  # ID пользователя @marss73 (замените на реальный)  # Можно добавить других пользователей
            ]

            if sender.id not in allowed_users:
                await message.reply("❌ У вас нет прав для использования команд")
                return

            print("   ✅ Владелец подтвержден")

            if command == '/start':
                await message.reply("🤖 Бот запущен и работает!")
                print("   ✅ Ответ: /start")

            elif command == '/help':
                help_text = """
🤖 **Доступные команды:**

**Основные команды:**
/start - Проверка работы бота
/help - Эта справка
/me - Информация о боте
/chats - Список диалогов
/send <id> <текст> - Отправить сообщение
/join <ссылка> - Вступить в канал/группу
/stop - Остановить бота

**Команды автоотправки:**
/autosend status - Статус автоотправки
/autosend start - Запустить автоотправку
/autosend stop - Остановить автоотправку
/autosend interval <секунды> - Изменить интервал
/autosend addchat <ID> - Добавить чат
/autosend removechat <ID> - Удалить чат
/autosend listchats - Список чатов
/autosend addmsg <текст> - Добавить сообщение
/autosend removemsg <номер> - Удалить сообщение
/autosend listmsgs - Список сообщений
/autosend now - Отправить сейчас
                """
                await message.reply(help_text)
                print("   ✅ Ответ: /help")

            elif command == '/me':
                me = await self.client.get_me()
                info = f"""
👤 **Информация о боте:**
Имя: {me.first_name}
Фамилия: {me.last_name or 'Не указана'}
Username: @{me.username or 'Не указан'}
ID: {me.id}
Телефон: {me.phone or 'Не указан'}
                """
                await message.reply(info)
                print("   ✅ Ответ: /me")

            elif command.startswith('/send '):
                parts = command.split(' ', 2)
                if len(parts) >= 3:
                    chat_id = parts[1]
                    text = parts[2]

                    try:
                        await self.client.send_message(chat_id, text)
                        await message.reply(f"✅ Сообщение отправлено в {chat_id}")
                        print(f"   ✅ Отправлено в {chat_id}")
                    except Exception as e:
                        await message.reply(f"❌ Ошибка: {e}")
                        print(f"   ❌ Ошибка: {e}")

            elif command.startswith('/join '):
                parts = command.split(' ', 1)
                if len(parts) >= 2:
                    link = parts[1].strip()

                    try:
                        # Обработка разных форматов ссылок
                        if 't.me/+' in link:
                            # Пригласительная ссылка на группу в формате t.me/+
                            if 'https://t.me/+' in link:
                                # Полный URL: https://t.me/+uIKykIHp9_A5ZDIy
                                invite_hash = link.replace('https://t.me/+', '')
                            elif 't.me/+' in link:
                                # Без https: t.me/+uIKykIHp9_A5ZDIy
                                invite_hash = link.split('t.me/+')[-1]
                            # Убираем возможные параметры после ? и /
                            invite_hash = invite_hash.split('?')[0].split('/')[0]
                            print(f"   🔍 Пытаюсь вступить с invite_hash: {invite_hash}")
                            # Пробуем вступить
                            await self.client(ImportChatInviteRequest(invite_hash))
                            await message.reply(f"✅ Успешно вступил в приватную группу")
                            print(f"   ✅ Вступил в приватную группу")

                        elif 't.me/joinchat/' in link:
                            # Старый формат: t.me/joinchat/...
                            if 'https://t.me/joinchat/' in link:
                                invite_hash = link.replace('https://t.me/joinchat/', '')
                            else:
                                invite_hash = link.split('t.me/joinchat/')[-1]
                            invite_hash = invite_hash.split('?')[0].split('/')[0]
                            print(f"   🔍 Пытаюсь вступить с invite_hash: {invite_hash}")
                            await self.client(ImportChatInviteRequest(invite_hash))
                            await message.reply(f"✅ Успешно вступил в приватную группу")
                            print(f"   ✅ Вступил в приватную группу")

                        else:
                            # Публичный канал/группа
                            # Убираем @ если есть
                            if link.startswith('@'):
                                link = link[1:]
                            # Убираем https:// если есть
                            if link.startswith('https://t.me/'):
                                link = link.replace('https://t.me/', '')
                            print(f"   🔍 Пытаюсь вступить в публичный чат: {link}")

                            # Получаем сущность чата
                            entity = await self.client.get_entity(link)
                            # Определяем тип чата для более информативного сообщения
                            chat_type = "канал" if getattr(entity, 'broadcast', False) else "группу"
                            chat_title = getattr(entity, 'title', link)
                            await self.client(JoinChannelRequest(entity))
                            await message.reply(f"✅ Успешно вступил в {chat_type}: {chat_title}")
                            print(f"   ✅ Вступил в {chat_type}: {chat_title}")

                    except errors.InviteHashExpiredError:
                        await message.reply("❌ Срок действия пригласительной ссылки истек")
                        print(f"   ❌ Ссылка устарела: {link}")

                    except errors.InviteHashInvalidError:
                        # Попробуем альтернативный метод для ссылок формата t.me/+
                        if 't.me/+' in link:
                            await message.reply("❌ Неверная пригласительная ссылка. Попробуйте:\n"

                                                "1. Проверить, что ссылка актуальна\n"

                                                f"2. Использовать только хэш: {invite_hash if 'invite_hash' in locals() else 'неизвестно'}")
                        else:
                            await message.reply("❌ Неверная пригласительная ссылка")
                        print(f"   ❌ Неверная ссылка: {link}")
                    except errors.UserAlreadyParticipantError:

                        await message.reply("ℹ️ Я уже состою в этом чате")

                        print(f"   ℹ️ Уже в чате: {link}")
                    except errors.ChannelPrivateError:
                        await message.reply("🔒 Этот чат приватный. Нужна пригласительная ссылка")
                        print(f"   🔒 Приватный чат: {link}")

                    except errors.UsernameNotOccupiedError:
                        await message.reply("❌ Такого чата/канала не существует")
                        print(f"   ❌ Несуществующий чат: {link}")

                    except errors.FloodWaitError as e:
                        await message.reply(f"⏳ Слишком много запросов. Подождите {e.seconds} секунд")
                        print(f"   ⏳ FloodWait: {e.seconds} сек")

                    except Exception as e:
                        error_msg = str(e)
                        print(f"   ❌ Ошибка при вступлении в {link}: {error_msg}")

                        if "Cannot find any entity corresponding to" in error_msg:
                            await message.reply("❌ Не удалось найти чат. Проверьте ссылку")
                        elif "The invite hash has expired" in error_msg:
                            await message.reply("❌ Срок действия пригласительной ссылки истек")
                        else:
                            await message.reply(f"❌ Ошибка: {error_msg}")

            elif command == '/chats':
                # Получаем диалоги
                dialogs = await self.client.get_dialogs(limit=20)

                response = "💬 **Последние диалоги:**\n\n"
                for dialog in dialogs[:10]:
                    name = dialog.name
                    if hasattr(dialog.entity, 'username') and dialog.entity.username:
                        name = f"@{dialog.entity.username}"

                    response += f"• {name} (ID: {dialog.id})\n"

                await message.reply(response)
                print("   ✅ Ответ: /chats")

            # ========== КОМАНДЫ АВТООТПРАВКИ ==========
            elif command == '/autosend status':
                status_text = f"""
📊 **Статус автоотправки:**

• Включено: {'✅ Да' if self.auto_send_enabled else '❌ Нет'}
• Интервал: {self.auto_send_interval} сек ({self.auto_send_interval // 60} мин)
• Чатов: {len(self.auto_send_chats)}
• Сообщений: {len(self.auto_send_messages)}
• Текущий индекс: {self.message_index}
                """

                if self.next_send_time:
                    status_text += f"• Следующая отправка: {self.next_send_time.strftime('%H:%M:%S')}\n"

                await message.reply(status_text)
                print("   ✅ Ответ: /autosend status")

            elif command == '/autosend start':
                self.auto_send_enabled = True
                await self.start_auto_send()
                await message.reply("✅ Автоотправка запущена")
                print("   ✅ Автоотправка запущена")

            elif command == '/autosend stop':
                self.auto_send_enabled = False
                if self.auto_send_task:
                    self.auto_send_task.cancel()
                await message.reply("🛑 Автоотправка остановлена")
                print("   ✅ Автоотправка остановлена")

            elif command.startswith('/autosend interval '):
                parts = command.split(' ', 2)
                if len(parts) >= 3:
                    try:
                        interval = int(parts[2])
                        if interval < 10:
                            await message.reply("❌ Интервал не может быть меньше 10 секунд")
                            print("   ❌ Интервал слишком мал")
                        else:
                            self.auto_send_interval = interval
                            await self.save_config()
                            await message.reply(f"✅ Интервал изменен на {interval} сек ({interval // 60} мин)")
                            print(f"   ✅ Интервал изменен на {interval} сек")
                    except ValueError:
                        await message.reply("❌ Неверный формат числа")
                        print("   ❌ Неверный формат числа")

            elif command.startswith('/autosend addchat '):
                parts = command.split(' ', 2)
                if len(parts) >= 3:
                    chat_id = parts[2]
                    if chat_id not in self.auto_send_chats:
                        self.auto_send_chats.append(chat_id)
                        await self.save_config()
                        await message.reply(f"✅ Чат {chat_id} добавлен")
                        print(f"   ✅ Чат {chat_id} добавлен")
                    else:
                        await message.reply(f"⚠️  Чат {chat_id} уже в списке")
                        print(f"   ⚠️  Чат уже в списке")
            elif command.startswith('/autosend removechat '):
                parts = command.split(' ', 2)
                if len(parts) >= 3:
                    chat_id = parts[2]
                    if chat_id in self.auto_send_chats:
                        self.auto_send_chats.remove(chat_id)
                        await self.save_config()
                        await message.reply(f"✅ Чат {chat_id} удален")
                        print(f"   ✅ Чат {chat_id} удален")
                    else:
                        await message.reply(f"❌ Чат {chat_id} не найден")
                        print(f"   ❌ Чат не найден")

            elif command == '/autosend listchats':
                if not self.auto_send_chats:
                    await message.reply("📋 Список чатов пуст")
                    print("   ✅ Список чатов пуст")
                else:
                    response = "📋 **Чаты для автоотправки:**\n\n"
                    for i, chat in enumerate(self.auto_send_chats, 1):
                        response += f"{i}. {chat}\n"
                    await message.reply(response)
                    print(f"   ✅ Список из {len(self.auto_send_chats)} чатов")

            elif command.startswith('/autosend addmsg '):
                parts = command.split(' ', 2)
                if len(parts) >= 3:
                    message_text = parts[2]
                    self.auto_send_messages.append(message_text)
                    await self.save_config()
                    await message.reply(f"✅ Сообщение добавлено (всего: {len(self.auto_send_messages)})")
                    print(f"   ✅ Сообщение добавлено")

            elif command.startswith('/autosend removemsg '):
                parts = command.split(' ', 2)
                if len(parts) >= 3:
                    try:
                        index = int(parts[2]) - 1
                        if 0 <= index < len(self.auto_send_messages):
                            removed = self.auto_send_messages.pop(index)
                            await self.save_config()
                            await message.reply(f"✅ Сообщение удалено: {removed[:50]}...")
                            print(f"   ✅ Сообщение удалено")
                        else:
                            await message.reply(f"❌ Неверный номер сообщения")
                            print(f"   ❌ Неверный номер")
                    except ValueError:
                        await message.reply("❌ Неверный формат номера")
                        print(f"   ❌ Неверный формат")

            elif command == '/autosend listmsgs':
                if not self.auto_send_messages:
                    await message.reply("📋 Список сообщений пуст")
                    print("   ✅ Список сообщений пуст")
                else:
                    response = "📋 **Сообщения для автоотправки:**\n\n"
                    for i, msg in enumerate(self.auto_send_messages, 1):
                        response += f"{i}. {msg[:50]}...\n"
                    await message.reply(response)
                    print(f"   ✅ Список из {len(self.auto_send_messages)} сообщений")

            elif command == '/autosend now':
                await message.reply("⏳ Отправляю сообщения сейчас...")
                print("   ⏳ Начинаю отправку...")
                await self.send_to_all_chats()
                await message.reply("✅ Сообщения отправлены")
                print("   ✅ Сообщения отправлены")

            elif command == '/stop':
                await message.reply("🛑 Остановка бота...")
                print("   🛑 Остановка бота...")
                await self.stop()

            else:
                await message.reply("❌ Неизвестная команда. Используйте /help")
                print("   ❌ Неизвестная команда")

        except Exception as e:
            print(f"❌ Ошибка обработки команды: {e}")
            try:
                await message.reply(f"❌ Ошибка: {str(e)}")
            except:
                pass

    async def load_auto_send_config(self):
        """Загрузка конфигурации автоотправки"""
        config_file = 'auto_send_config.json'

        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)

                self.auto_send_enabled = config.get('enabled', True)
                self.auto_send_interval = config.get('interval', 180)
                self.auto_send_chats = config.get('chats', [])
                self.auto_send_messages = config.get('messages', [])

                print(f"\n📋 Загружена конфигурация автоотправки:")
                print(f"   • Включено: {'Да' if self.auto_send_enabled else 'Нет'}")
                print(f"   • Интервал: {self.auto_send_interval} сек ({self.auto_send_interval // 60} мин)")
                print(f"   • Чатов: {len(self.auto_send_chats)}")
                print(f"   • Сообщений: {len(self.auto_send_messages)}")

            except Exception as e:
                print(f"❌ Ошибка загрузки конфигурации: {e}")
                # Создаем дефолтную конфигурацию
                await self.create_default_config()
        else:
            print("\n📋 Файл конфигурации не найден, создаем дефолтный...")
            await self.create_default_config()

    async def create_default_config(self):
        """Создание дефолтной конфигурации"""
        config = {
            'enabled': True,
            'interval': 180,  # 3 минуты
            'chats': [],  # Добавьте сюда ID чатов
            'messages': [
                "Привет всем! 👋",
                "Как дела? 🤔",
                "Отличный день для общения! ☀️",
                "Что нового? 📰"
            ]
        }

        try:
            with open('auto_send_config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print("✅ Создан файл конфигурации auto_send_config.json")
            print("⚠️  Отредактируйте его, добавив ID чатов!")
        except Exception as e:
            print(f"❌ Ошибка создания конфигурации: {e}")

    async def start_auto_send(self):
        """Запуск задачи автоотправки"""
        if not self.auto_send_enabled:
            print("⚠️  Автоотправка отключена в настройках")
            return

        if not self.auto_send_chats:
            print("⚠️  Не указаны чаты для автоотправки")
            print("   Используйте команду /autosend addchat <ID>")
            return

        if not self.auto_send_messages:
            print("⚠️  Не указаны сообщения для автоотправки")
            print("   Используйте команду /autosend addmsg <текст>")
            return

        print(f"\n🚀 Запуск автоотправки сообщений:")
        print(f"   • Чатов: {len(self.auto_send_chats)}")
        print(f"   • Сообщений: {len(self.auto_send_messages)}")
        print(f"   • Интервал: {self.auto_send_interval} сек")

        # Запускаем задачу
        self.auto_send_task = asyncio.create_task(self.auto_send_loop())

        # Устанавливаем время следующей отправки
        self.next_send_time = datetime.now() + timedelta(seconds=self.auto_send_interval)
        print(f"   • Следующая отправка: {self.next_send_time.strftime('%H:%M:%S')}")

    async def auto_send_loop(self):
        """Основной цикл автоотправки"""
        while self.is_running and self.auto_send_enabled:
            try:
                # Ждем указанный интервал
                await asyncio.sleep(self.auto_send_interval)

                # Отправляем сообщения
                await self.send_to_all_chats()

                # Обновляем время следующей отправки
                self.next_send_time = datetime.now() + timedelta(seconds=self.auto_send_interval)

            except asyncio.CancelledError:
                print("🛑 Задача автоотправки остановлена")
                break
            except Exception as e:
                print(f"❌ Ошибка в цикле автоотправки: {e}")
                await asyncio.sleep(60)  # Ждем минуту при ошибке

    async def send_to_all_chats(self):
        """Отправка сообщений во все чаты"""
        if not self.auto_send_chats or not self.auto_send_messages:
            return

        print(f"\n📤 [{datetime.now().strftime('%H:%M:%S')}] Начинаю отправку...")

        # Получаем следующее сообщение
        message = self.auto_send_messages[self.message_index]
        self.message_index = (self.message_index + 1) % len(self.auto_send_messages)

        success_count = 0
        fail_count = 0

        for chat in self.auto_send_chats:
            try:
                # Отправляем сообщение
                await self.client.send_message(chat, message)
                print(f"   ✅ Отправлено в {chat}")
                success_count += 1

                # Небольшая задержка между отправками
                await asyncio.sleep(1)

            except Exception as e:
                print(f"   ❌ Ошибка отправки в {chat}: {e}")
                fail_count += 1

        print(f"📊 Итог: {success_count} успешно, {fail_count} с ошибками")
        print(f"⏰ Следующая отправка: {self.next_send_time.strftime('%H:%M:%S')}")

    async def message_check_loop(self):
        """Цикл проверки новых сообщений"""
        print("🔍 Запуск цикла проверки сообщений...")

        while self.is_running:
            try:
                # Проверяем новые сообщения каждые 5 секунд
                await self.check_new_messages()
                await asyncio.sleep(2)

            except asyncio.CancelledError:
                print("🛑 Проверка сообщений остановлена")
                break
            except Exception as e:
                print(f"❌ Ошибка проверки сообщений: {e}")
                await asyncio.sleep(5)

    async def save_config(self):
        """Сохранение конфигурации"""
        config = {
            'enabled': self.auto_send_enabled,
            'interval': self.auto_send_interval,
            'chats': self.auto_send_chats,
            'messages': self.auto_send_messages
        }

        try:
            with open('auto_send_config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print("✅ Конфигурация сохранена")
        except Exception as e:
            print(f"❌ Ошибка сохранения конфигурации: {e}")

    async def start(self):
        """Запуск основного цикла бота"""
        if not self.client:
            print("❌ Клиент не инициализирован")
            return

        self.is_running = True

        # Запускаем автоотправку
        if self.auto_send_enabled:
            await self.start_auto_send()

        # Запускаем проверку сообщений
        self.message_check_task = asyncio.create_task(self.message_check_loop())

        print("\n" + "=" * 50)
        print("🚀 Бот успешно запущен и готов к работе!")
        print("=" * 50)
        print("\n💬 Отправьте /help для списка команд")
        print("📡 Бот теперь слушает все входящие сообщения!")
        print("⏸️  Нажмите Ctrl+C для остановки")

        # Бесконечный цикл
        try:
            while self.is_running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n\n🛑 Получен сигнал остановки...")
            await self.stop()

    async def stop(self):
        """Остановка бота"""
        self.is_running = False

        # Останавливаем задачи
        if self.auto_send_task:
            self.auto_send_task.cancel()

        if self.message_check_task:
            self.message_check_task.cancel()

        # Отключаем клиент
        if self.client:
            await self.client.disconnect()

        print("\n✅ Бот остановлен")
        sys.exit(0)


# ========== ГЛАВНАЯ ФУНКЦИЯ ==========
async def main():
    bot = TelegramUserBot()

    # Инициализируем бота
    if not await bot.initialize():
        print("❌ Не удалось инициализировать бота")
        return

    # Запускаем основной цикл
    await bot.start()


# ========== ТОЧКА ВХОДА ==========
if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        level=Config.LOG_LEVEL,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        # Запускаем асинхронный цикл
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 До свидания!")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
