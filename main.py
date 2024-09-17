import asyncio
import aiohttp
import vk_api
from aiogram import Bot, Dispatcher, html, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import config
from datetime import datetime, timezone
import pytz

bot_token = config.token_telegram_bot
vk_token = config.vk_api
chat_gpt_token = config.chatgpt_api_key
admins = [786279129, 741936713]

dp = Dispatcher()

unread_messages = {}
active_dialogs = set()

@dp.message(CommandStart())
async def start(message: Message):
    if message.from_user.id in admins:
        start_message = (
            f"Здравствуйте, <b>{message.from_user.full_name}!</b>\n\n"
            "Добро пожаловать в бота для управления сообщениями из ВКонтакте. Вот команды, которые вы можете использовать:\n\n"
            "<b>/message</b> - Получить список непрочитанных сообщений.\n"
            "<b>/start</b> - Начать диалог с конкретным пользователем на основе непрочитанных сообщений.\n"
            "Вы можете взаимодействовать с сообщениями, используя предоставленные кнопки."
            )
        await message.answer(
            text=start_message,
            parse_mode=ParseMode.HTML
        )

@dp.message(Command('message'))
async def get_messages(message: Message):
    if message.from_user.id in admins:
        if unread_messages:
            response = "Непрочитанные сообщения:\n"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"Начать диалог с {peer_id}",
                        callback_data=f"start_dialog:{peer_id}"
                    )
                ] for peer_id in unread_messages.keys()
            ])

            await message.answer(response, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        else:
            await message.answer("Нет непрочитанных сообщений.")

async def get_recent_messages(vk_api_instance, peer_id):
    try:
        response = vk_api_instance.messages.getHistory(
            peer_id=peer_id,
            count=10
        )
        messages = response.get('items', [])
        timezone_utc_plus_3 = pytz.timezone('Europe/Moscow')
        result = []
        for msg in messages:
            sender_info = vk_api_instance.users.get(user_ids=msg['from_id'])
            
            if sender_info:
                sender_name = f"{sender_info[0]['first_name']} {sender_info[0]['last_name']}"
            else:
                sender_name = "OBLAKO"

            timestamp_utc = datetime.fromtimestamp(msg['date'], tz=pytz.utc)
            timestamp_local = timestamp_utc.astimezone(timezone_utc_plus_3)
            timestamp = timestamp_local.strftime("%d/%m/%Y %H:%M:%S")
            result.append({
                'text': msg['text'],
                'sender_name': sender_name,
                'timestamp': timestamp,
                'message_id': msg['id']
            })

            result.sort(key=lambda msg: msg['timestamp'], reverse=False)
        return result

    except vk_api.exceptions.VkApiError as e:
        print(f"Ошибка при получении истории сообщений: {e}")
        return []

@dp.callback_query(lambda c: c.data.startswith('start_dialog:'))
async def handle_start_dialog(callback_query: CallbackQuery):
    _, peer_id = callback_query.data.split(':')
    peer_id = int(peer_id)

    if peer_id in active_dialogs:
        await callback_query.answer("Диалог уже активен.")
        return

    active_dialogs.add(peer_id)
    await callback_query.answer("Начинаем диалог...")

    vk_session = vk_api.VkApi(token=vk_token)
    vk_api_instance = vk_session.get_api()
    messages = await get_recent_messages(vk_api_instance, peer_id)

    if messages:
        response = f"История диалога с {peer_id}:\n"
        for msg in messages:
            response += f"{msg['timestamp']} | От {msg['sender_name']}: {msg['text']}\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Прочитать сообщение", callback_data=f"read_message:{peer_id}"),
                InlineKeyboardButton(text="Отправить сообщение", callback_data=f"reply:{peer_id}")
            ],
            [
                # InlineKeyboardButton(text="Помощь ChatGPT", callback_data=f"help_chatgpt:{peer_id}"),
                InlineKeyboardButton(text="Закончить диалог", callback_data=f"end_dialog:{peer_id}")
            ]
        ])
        await callback_query.message.answer(response, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    else:
        await callback_query.message.answer("Нет сообщений для отображения.")


@dp.callback_query(lambda c: c.data.startswith('end_dialog:'))
async def handle_end_dialog(callback_query: CallbackQuery):
    _, peer_id = callback_query.data.split(':')
    peer_id = int(peer_id)

    if peer_id not in active_dialogs:
        await callback_query.answer("Диалог не активен.")
        return

    active_dialogs.remove(peer_id)
    await callback_query.answer("Диалог завершен.")
    await callback_query.message.answer("Диалог с пользователем завершен.")

@dp.callback_query(lambda c: c.data.startswith('reply:'))
async def handle_reply(callback_query: CallbackQuery):
    _, peer_id = callback_query.data.split(':')
    peer_id = int(peer_id)

    await callback_query.answer("Ожидаем ваш ответ...")
    await callback_query.message.answer("Введите ваш ответ:")

    @dp.message()
    async def get_reply(message: Message):
        reply_text = message.text

        vk_session = vk_api.VkApi(token=vk_token)
        vk_api_instance = vk_session.get_api()

        if await send_reply_to_vk(vk_api_instance, peer_id, reply_text):
            await message.answer("Ответ отправлен в ВКонтакте!")

            messages = await get_recent_messages(vk_api_instance, peer_id)
            if messages:
                response = f"История диалога с {peer_id}:\n"
                for msg in messages:
                    response += f"{msg['timestamp']} | От {msg['sender_name']}: {msg['text']}\n"

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Прочитать сообщение", callback_data=f"read_message:{peer_id}"),
                        InlineKeyboardButton(text="Отправить сообщение", callback_data=f"reply:{peer_id}")
                    ],
                    [
                        InlineKeyboardButton(text="Помощь ChatGPT", callback_data=f"help_chatgpt:{peer_id}"),
                        InlineKeyboardButton(text="Закончить диалог", callback_data=f"end_dialog:{peer_id}")
                    ]
                ])
                await callback_query.message.answer(response, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            else:
                await callback_query.message.answer("Нет сообщений для отображения.")
        else:
            await message.answer(f"Ошибка при отправке ответа пользователю с ID {peer_id}.")

async def send_reply_to_vk(vk_api_instance, peer_id, message_text):
    try:
        vk_api_instance.messages.send(
            peer_id=peer_id,
            message=message_text,
            random_id=0
        )
        return True
    except vk_api.exceptions.VkApiError as e:
        if e.code == 901:
            print(f"Ошибка при отправке: нет прав для отправки сообщений пользователю с peer_id {peer_id}")
        else:
            print(f"Ошибка при отправке сообщения: {e}")
        return False

@dp.callback_query(lambda c: c.data.startswith('read_message:'))
async def handle_read_message(callback_query: CallbackQuery):
    _, peer_id = callback_query.data.split(':')
    peer_id = int(peer_id)

    if peer_id not in unread_messages or not unread_messages[peer_id]:
        await callback_query.answer("Нет непрочитанных сообщений.")
        return

    message = unread_messages[peer_id].pop(0)
    if not unread_messages[peer_id]:
        del unread_messages[peer_id]

    response = f"Сообщение от {message['sender_name']}:\n{message['timestamp']} | {message['text']}"

    await callback_query.message.answer(response)
    await callback_query.answer("Сообщение прочитано.")

async def long_poll_listener(bot: Bot, vk_api_instance):
    server, key, ts = get_long_poll_server(vk_api_instance)

    if not server or not key:
        print("Не удалось получить данные Long Poll сервера.")
        return

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                url = f"https://{server}?act=a_check&key={key}&ts={ts}&wait=1"
                async with session.get(url) as response:
                    data = await response.json()
                
                if 'failed' in data:
                    if data['failed'] == 1:
                        ts = data['ts']
                    elif data['failed'] in [2, 3]:
                        server, key, ts = get_long_poll_server(vk_api_instance)
                    continue

                ts = data['ts']
                updates = data.get('updates', [])

                for update in updates:
                    if update[0] == 4:
                        message_text = update[6]
                        peer_id = update[3]

                        sender_info = vk_api_instance.users.get(user_ids=peer_id)
                        sender_name = f"{sender_info[0]['first_name']} {sender_info[0]['last_name']}"
                        timestamp = update[4]
                        timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%d/%m/%Y %H:%M:%S")

                        if peer_id not in unread_messages:
                            unread_messages[peer_id] = []
                        unread_messages[peer_id].append({
                            'text': message_text,
                            'sender_name': sender_name,
                            'timestamp': timestamp,
                            'message_id': update[1]
                        })

                        if peer_id not in active_dialogs:
                            message_to_send = f"Сообщение из VK от {html.quote(sender_name)}: {html.quote(message_text)}"
                            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                                [
                                    InlineKeyboardButton(text="Начать диалог", callback_data=f"start_dialog:{peer_id}")
                                ]
                            ])
                            await bot.send_message(chat_id=admins[0], text=message_to_send, reply_markup=keyboard, parse_mode=ParseMode.HTML)

            except Exception as e:
                print(f"Ошибка при обработке Long Poll: {e}")

            await asyncio.sleep(1)

def get_long_poll_server(vk_api_instance):
    try:
        response = vk_api_instance.messages.getLongPollServer()
        return response['server'], response['key'], response['ts']
    except Exception as e:
        print(f"Ошибка при получении Long Poll сервера: {e}")
        return None, None, None

async def main():
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    vk_session = vk_api.VkApi(token=vk_token)
    vk_api_instance = vk_session.get_api()

    print("Bot Start")
    
    await asyncio.gather(
        dp.start_polling(bot),
        long_poll_listener(bot, vk_api_instance)
    )

if __name__ == "__main__":
    asyncio.run(main())
