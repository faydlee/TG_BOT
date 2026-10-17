import asyncio
import html
import os
import re
import sqlite3

import feedparser
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN в файле .env")

if not ADMIN_ID:
    raise ValueError("Не найден ADMIN_ID в файле .env")

if not CHANNEL_ID:
    raise ValueError("Не найден CHANNEL_ID в файле .env")

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    raise ValueError("ADMIN_ID должен быть числовым Telegram ID")

if CHANNEL_ID.lstrip("-").isdigit():
    CHANNEL_ID = int(CHANNEL_ID)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

RSS_SOURCES = {
    "StopGame": "https://rss.stopgame.ru/rss_news.xml",
    "3DNews": "https://3dnews.ru/news/rss/",
    "PC Gamer": "https://www.pcgamer.com/feeds.xml",
    "IGN": "https://www.ign.com/rss/v2/articles/feed",
}

CHECK_INTERVAL = 30 * 60
MAX_NEWS_PER_CHECK = 5
DB_NAME = "playwire.db"

GAME_KEYWORDS = [
    # Русские игровые термины
    "игра", "игры", "игру", "игре", "игров",
    "гейм", "геймплей", "видеоигр", "игрок", "игроки",
    "игровой мир", "игровая студия", "игровой процесс",
    "трейлер", "анонс", "релиз", "выход игры", "дата выхода",
    "дополнение", "обновление игры", "патч", "бета-тест",
    "ранний доступ", "киберспорт", "турнир",

    # Англоязычные игровые термины
    "video game", "video games", "gameplay", "game studio",
    "game developer", "game developers", "game update",
    "game release", "new game", "gamescom", "summer game fest",
    "the game awards", "early access", "patch notes",
    "expansion", "game pass", "playstation plus",
    "xbox game pass", "epic games store", "game mod",
    "pc port", "ported to pc", "survival game",
    "political sim", "motion blur", "gaming mouse",
    "humble choice", "humble games", "free games",
    "games lineup", "game subscription", "game demo",
    "gaming news", "cheating",

    # Игровые платформы
    "steam", "playstation", "xbox", "nintendo",
    "pc gamer", "steam deck", "playstation 5",
    "xbox series", "nintendo switch", "dlc",

    # Известные игры и серии
    "valorant", "fortnite", "minecraft",
    "counter-strike", "counter strike", "apex legends",
    "call of duty", "grand theft auto", "gta 5", "gta 6",
    "elden ring", "baldur's gate", "resident evil",
    "final fantasy", "assassin's creed", "league of legends",
    "dota 2", "overwatch", "world of warcraft", "wow:",
    "phantom blade zero", "tanks blitz",
    "warhammer 40,000", "dawn of war", "rainbow six",
    "gears of war", "cities: skylines", "silent hill",
    "doom", "arc raiders", "nivalis", "wardogs",
    "system shock", "black & white", "spiritfarer",
    "at fate's end", "like a dragon", "pirate yakuza",
    "battlefield", "dead space", "militsioner",
    "star wars zero company",     "cat and paste", "crimson desert", 
    "tropico", "ace combat","machinarium", "dragon's dogma", "ea sports fc", 
    "2xko", "marvel's wolverine", "ghost of tsushima", "cyberpunk 2077", 
    "skate", "deadlock", "street fighter", "pokemon", "leisure suit larry", 
    "the witcher", "forza horizon", "marvel cosmic invasion" ,"stronghold", 
    "valor mortis", "clair obscur", "a plague tale",
]

EXCLUDE_KEYWORDS = [
    "смартфон", "смартфоны", "смартфонов",
    "smartphone",
    "процессор", "процессоры", "processor",
    "материнск",
    "оперативная память",
    "ноутбук", "ноутбуки", "laptop",
    "монитор",
    "мобильный интернет",
    "умного дома",
    "macbook", "iphone",
    "выручка openai",
    "поставки пк",
    "глобальный рынок смартфонов",
    "motherboard",
    "дата-центр", "data center",
]

# Игровое железо
HARDWARE_KEYWORDS = [
    "gaming pc", "gaming laptop", "gaming monitor",
    "gaming mouse", "gaming keyboard", "gaming headset",
    "игровой пк", "игровой ноутбук", "игровой монитор",
    "игровая мышь", "игровая клавиатура",
    "видеокарта", "graphics card", "gpu",
    "rtx", "geforce", "radeon",
    "игровой процессор", "gaming cpu",
    "oled gaming", "steam deck",
]

# Скидки и игровые подписки
DEAL_KEYWORDS = [
    "humble choice", "humble games",
    "free games", "free game",
    "free to play", "games lineup",
    "game subscription", "game pass",
    "playstation plus", "epic games store",
    "free game giveaway", "game giveaway",
    "скидка на игру", "скидки на игры",
    "бесплатная игра", "бесплатные игры",
    "раздача игр", "игровая подписка",
    "бесплатная раздача",
]

# Общие слова, которые сами по себе не подтверждают,
# что новость посвящена видеоиграм.
GENERIC_GAME_KEYWORDS = [
    "игра", "игры", "игру", "игре", "игров",
    "трейлер", "анонс", "релиз",
    "выход игры", "дата выхода",
    "дополнение", "expansion",
]


def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_news (
                link TEXT PRIMARY KEY,
                title TEXT,
                source TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT UNIQUE,
                title TEXT,
                source TEXT,
                status TEXT DEFAULT 'new'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drafts (
                action_id INTEGER PRIMARY KEY,
                draft_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def is_new_news(link):
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute(
            "SELECT 1 FROM sent_news WHERE link = ?",
            (link,),
        ).fetchone()
    return row is None


def mark_news_sent(link, title, source):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO sent_news (link, title, source)
            VALUES (?, ?, ?)
            """,
            (link, title, source),
        )


def save_news_action(link, title, source):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO news_actions (link, title, source)
            VALUES (?, ?, ?)
            """,
            (link, title, source),
        )
        row = conn.execute(
            "SELECT id FROM news_actions WHERE link = ?",
            (link,),
        ).fetchone()
    return row[0]


def add_paragraph_breaks(text, entities):
    if "\n" in text or "\r" in text:
        return text, entities

    edits = []
    paragraph_start = 0
    paragraph_separators = re.finditer(
        r"\n[ \t]*\n(?:[ \t]*\n)*",
        text,
    )

    def collect_edits(start, end):
        paragraph = text[start:end]
        sentence_count = 0
        sentence_ends = re.finditer(
            r'(?<=[.!?…])(?:["»”’)\]]*)[ \t\r\n]+',
            paragraph,
        )
        for sentence_end in sentence_ends:
            if not paragraph[sentence_end.end():].strip():
                continue
            sentence_count += 1
            if sentence_count % 3 == 0:
                edits.append(
                    (start + sentence_end.start(), start + sentence_end.end())
                )

    for separator in paragraph_separators:
        collect_edits(paragraph_start, separator.start())
        paragraph_start = separator.end()
    collect_edits(paragraph_start, len(text))

    if not edits:
        return text, entities

    formatted_parts = []
    previous_end = 0
    edit_offsets = []
    for start, end in edits:
        formatted_parts.extend((text[previous_end:start], "\n\n"))
        edit_start = len(text[:start].encode("utf-16-le")) // 2
        edit_end = len(text[:end].encode("utf-16-le")) // 2
        delta = 2 - (edit_end - edit_start)
        edit_offsets.append((edit_end, delta))
        previous_end = end
    formatted_parts.append(text[previous_end:])
    formatted_text = "".join(formatted_parts)

    if entities is None:
        return formatted_text, None

    formatted_entities = []
    for entity in entities:
        entity_start = entity.offset
        entity_end = entity.offset + entity.length
        start_shift = sum(
            delta for edit_end, delta in edit_offsets if edit_end <= entity_start
        )
        end_shift = sum(
            delta for edit_end, delta in edit_offsets if edit_end <= entity_end
        )
        formatted_entities.append(
            entity.model_copy(
                update={
                    "offset": entity_start + start_shift,
                    "length": entity.length + end_shift - start_shift,
                }
            )
        )

    return formatted_text, formatted_entities


# Новость, которую пользователь сейчас переписывает.
pending_rewrite = {}


@dp.callback_query(
    lambda callback: callback.data and callback.data.startswith("work:")
)
async def work_news(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    action_id = int(callback.data.split(":", 1)[1])

    with sqlite3.connect(DB_NAME) as conn:
        news = conn.execute(
            "SELECT title, source, link FROM news_actions WHERE id = ?",
            (action_id,),
        ).fetchone()
        if news is not None:
            conn.execute(
                "UPDATE news_actions SET status = 'in_progress' WHERE id = ?",
                (action_id,),
            )

    if news is None:
        await callback.answer(
            "Не удалось найти эту новость. Попробуй выбрать её снова.",
            show_alert=True,
        )
        return

    pending_rewrite[callback.from_user.id] = action_id
    title, source, link = news
    await callback.answer("Новость взята в работу.")

    if callback.message:
        await callback.message.answer(
            "📝 <b>Новость взята в работу</b>\n\n"
            f"🎮 <b>{html.escape(title)}</b>\n"
            f"Источник: {html.escape(source)}\n"
            f'<a href="{html.escape(link, quote=True)}">Открыть оригинал</a>\n\n'
            "Открой оригинал, перепиши новость своими словами "
            "и отправь готовый текст сюда одним сообщением.",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@dp.callback_query(
    lambda callback: callback.data and callback.data.startswith("skip:")
)
async def skip_news(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    action_id = int(callback.data.split(":", 1)[1])

    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "UPDATE news_actions SET status = 'skipped' WHERE id = ?",
            (action_id,),
        )

    await callback.answer("Новость пропущена.")

    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("⏭ Новость пропущена.")


@dp.message(
    lambda message: bool(
        (message.text and not message.text.startswith("/"))
        or (message.photo and message.caption)
    )
)
async def receive_rewritten_news(message: Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    action_id = pending_rewrite.get(message.from_user.id)

    draft = message.caption if message.photo else message.text
    if not draft or not draft.strip():
        await message.answer("Отправь непустой текст или фото с подписью.")
        return

    draft, entities = add_paragraph_breaks(
        draft,
        message.caption_entities if message.photo else message.entities,
    )

    if action_id is not None:
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute(
                "UPDATE news_actions SET status = 'drafted' WHERE id = ?",
                (action_id,),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO drafts (action_id, draft_text)
                VALUES (?, ?)
                """,
                (action_id, draft),
            )

    try:
        if message.photo:
            caption_length = len(draft.encode("utf-16-le")) // 2
            if caption_length <= 1024:
                await bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=message.photo[-1].file_id,
                    caption=draft,
                    caption_entities=entities,
                )
            else:
                await bot.send_photo(
                    chat_id=CHANNEL_ID,
                    photo=message.photo[-1].file_id,
                )
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=draft,
                    entities=entities,
                )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=draft,
                entities=entities,
            )
    except TelegramAPIError as error:
        print(f"Ошибка публикации в канал: {error}")
        if action_id is not None:
            await message.answer(
                "Черновик сохранён, но Telegram отклонил публикацию:\n"
                f"{error}\n\n"
                "Проверь детали ошибки и права бота в канале."
            )
        else:
            await message.answer(
                "Telegram отклонил публикацию:\n"
                f"{error}\n\n"
                "Проверь детали ошибки и права бота в канале."
            )
        return

    if action_id is not None:
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute(
                "UPDATE news_actions SET status = 'published' WHERE id = ?",
                (action_id,),
            )
        del pending_rewrite[message.from_user.id]

    await message.answer("✅ Пост опубликован в канале.")


collect_lock = asyncio.Lock()


async def collect_news():
    """Не допускает одновременного выполнения проверок."""
    if collect_lock.locked():
        print("Проверка уже выполняется. Повторный запуск пропущен.")
        return False

    async with collect_lock:
        await _collect_news()
    return True


async def _collect_news():
    sent_count = 0
    stats = {
        "получено из RSS": 0,
        "исключено фильтром": 0,
        "не подошло по ключевым словам": 0,
        "уже обработано": 0,
        "отправлено": 0,
    }

    for site, url in RSS_SOURCES.items():
        if sent_count >= MAX_NEWS_PER_CHECK:
            break

        try:
            feed = await asyncio.to_thread(feedparser.parse, url)
            stats["получено из RSS"] += len(feed.entries)

            if feed.bozo and not feed.entries:
                print(f"Не удалось прочитать RSS: {site}")
                print(f"Подробности ошибки: {feed.bozo_exception}")
                continue

            # Обрабатываем записи RSS от новых к старым.
            for article in feed.entries:
                if sent_count >= MAX_NEWS_PER_CHECK:
                    break

                title = str(article.get("title", "Без заголовка")).strip()
                link = str(article.get("link", "")).strip()
                if not link:
                    continue

                # Получаем описание новости из RSS.
                summary = str(article.get("summary", ""))
                if not summary:
                    contents = article.get("content", [])
                    if isinstance(contents, list) and contents:
                        summary = str(contents[0].get("value", ""))

                # Удаляем HTML-теги и декодируем HTML-сущности.
                summary_text = html.unescape(
                    re.sub(r"<[^>]+>", " ", summary)
                )
                summary_text = re.sub(r"\s+", " ", summary_text).strip()
                
                searchable_text = f"{title} {summary_text}".lower()
                title_lower = title.lower()

                # Общие слова вроде «анонс» и «релиз» сами по себе
                # не подтверждают, что новость посвящена видеоигре.
                game_matches = [
                    word for word in GAME_KEYWORDS
                    if word.lower() in searchable_text
                    and word.lower() not in GENERIC_GAME_KEYWORDS
                ]
                hardware_matches = [
                    word for word in HARDWARE_KEYWORDS
                    if word.lower() in searchable_text
                ]
                deal_matches = [
                    word for word in DEAL_KEYWORDS
                    if word.lower() in searchable_text
                ]
                has_game_context = bool(
                    game_matches or hardware_matches or deal_matches
                )

                # Исключаем обычные технологические новости, оставляя
                # материалы с явными игровыми, железными или deal-признаками.
                if any(word.lower() in title_lower for word in EXCLUDE_KEYWORDS):
                    if not has_game_context:
                        stats["исключено фильтром"] += 1
                        print(f"Исключено фильтром: {title}")
                        continue

                if not has_game_context:
                    stats["не подошло по ключевым словам"] += 1
                    print(f"Новость не подходит по ключевым словам: {title}")
                    continue

                matched_keywords = (
                    game_matches + hardware_matches + deal_matches
                )
                print(f"Совпадения: {', '.join(matched_keywords[:5])} | {title}")

                if not is_new_news(link):
                    stats["уже обработано"] += 1
                    continue

                # Аргументы: ссылка, заголовок, источник.
                action_id = save_news_action(link, title, site)

                safe_title = html.escape(title)
                safe_link = html.escape(link, quote=True)
                safe_source = html.escape(site)

                text = (
                    f"🎮 <b>{safe_title}</b>\n\n"
                    f"Источник: {safe_source}\n"
                    f'<a href="{safe_link}">Открыть оригинал</a>'
                )

                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="📝 В работу",
                                callback_data=f"work:{action_id}",
                            ),
                            InlineKeyboardButton(
                                text="⏭ Пропустить",
                                callback_data=f"skip:{action_id}",
                            ),
                        ]
                    ]
                )

                try:
                    await bot.send_message(
                        chat_id=ADMIN_ID,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=keyboard,
                    )
                    mark_news_sent(link, title, site)
                    sent_count += 1
                    stats["отправлено"] += 1
                    print(f"Новость отправлена: {title}")
                except Exception as error:
                    print(f"Ошибка отправки новости ({site}): {error}")

        except Exception as error:
            print(f"Ошибка источника {site}: {error}")

    print("--- Статистика проверки ---")
    for name, count in stats.items():
        print(f"  {name}: {count}")
    print(f"Проверка завершена. Отправлено новостей: {sent_count}")


async def auto_check_news():
    while True:
        print("Проверяю RSS...")
        await collect_news()
        print("Следующая проверка через 30 минут.")
        await asyncio.sleep(CHECK_INTERVAL)


@dp.message(CommandStart())
async def start_command(message: Message):
    await message.answer(
        "🎮 PLAYWIRE News работает!\n\n"
        "/news — проверить новости сейчас\n"
        "/status — состояние бота"
    )


@dp.message(Command("news"))
async def news_command(message: Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        await message.answer("Команда доступна только администратору.")
        return

    started = await collect_news()
    if started:
        await message.answer("✅ Проверка завершена.")
    else:
        await message.answer("⏳ Проверка уже выполняется. Подожди её завершения.")


@dp.message(Command("status"))
async def status_command(message: Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "✅ PLAYWIRE работает.\n"
        "Автоматическая проверка: каждые 30 минут.\n"
        "База повторов: SQLite."
    )


async def main():
    init_db()
    print("PLAYWIRE BOT запускается...")
    await asyncio.gather(
        dp.start_polling(bot),
        auto_check_news(),
    )


if __name__ == "__main__":
    asyncio.run(main())
