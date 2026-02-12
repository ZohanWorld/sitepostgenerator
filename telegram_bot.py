#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram-бот для управления генерацией блог-постов.
Полное управление постером через Telegram.
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from telegram.constants import ParseMode

# Импортируем функции из основного генератора
from simple_main import (
    load_env, load_titles_from_file, save_titles_to_file,
    select_random_title, remove_title_from_list, generate_blog_post,
    create_slug, save_to_file, show_remaining_titles,
    save_post_to_database, validate_post_data, test_database_connection,
    revalidate_blog_cache
)

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные переменные
env_vars = load_env()
TELEGRAM_BOT_TOKEN = env_vars.get('TELEGRAM_BOT_TOKEN', '')
ADMIN_CHAT_ID = env_vars.get('ADMIN_CHAT_ID', '')

# Состояние бота
bot_state = {
    'is_generating': False,
    'posts_generated_today': 0,
    'total_posts_generated': 0,
    'last_generation_time': None,
    'scheduler_active': False,
    'scheduler_posts_per_day': 3,
    'scheduler_interval_hours': 8,
}


def is_admin(update: Update) -> bool:
    """Проверяет, является ли пользователь админом"""
    if not ADMIN_CHAT_ID:
        return True  # Если ADMIN_CHAT_ID не задан, доступ открыт
    return str(update.effective_chat.id) == str(ADMIN_CHAT_ID)


def escape_md(text: str) -> str:
    """Экранирует специальные символы для MarkdownV2"""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start — главное меню"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    chat_id = update.effective_chat.id
    keyboard = [
        [
            InlineKeyboardButton("📝 Генерировать 1 пост", callback_data="gen_1"),
            InlineKeyboardButton("📦 Пакет (5)", callback_data="gen_5"),
        ],
        [
            InlineKeyboardButton("📦 Пакет (10)", callback_data="gen_10"),
            InlineKeyboardButton("📦 Пакет (20)", callback_data="gen_20"),
        ],
        [
            InlineKeyboardButton("📋 Список тем", callback_data="titles"),
            InlineKeyboardButton("📊 Статистика", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("⏰ Автопостинг", callback_data="scheduler"),
            InlineKeyboardButton("ℹ️ Статус бота", callback_data="status"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🤖 *Бот\\-постер МФО Витрина*\n\n"
        "Выберите действие или используйте команды:\n\n"
        "`/generate` — генерация 1 поста\n"
        "`/batch N` — пакетная генерация\n"
        "`/titles` — список тем\n"
        "`/addtitle Тема` — добавить тему\n"
        "`/stats` — статистика\n"
        "`/schedule` — автопостинг\n"
        "`/status` — статус бота\n\n"
        f"Ваш Chat ID: `{chat_id}`",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /generate — генерация одного поста"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return
    await do_generate(update.effective_chat.id, context, count=1)


async def batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /batch N — пакетная генерация"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    try:
        count = int(context.args[0]) if context.args else 5
        count = max(1, min(count, 30))  # Лимит 1-30
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Укажите количество: `/batch 5`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    await do_generate(update.effective_chat.id, context, count=count)


async def do_generate(chat_id: int, context: ContextTypes.DEFAULT_TYPE, count: int = 1):
    """Выполняет генерацию постов"""
    if bot_state['is_generating']:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏳ Генерация уже идёт. Дождитесь завершения."
        )
        return

    bot_state['is_generating'] = True

    try:
        api_key = env_vars.get('GPT_API_KEY')
        model_name = env_vars.get('MODEL_NAME', 'gpt-5.2')

        if not api_key:
            await context.bot.send_message(chat_id=chat_id, text="❌ GPT_API_KEY не найден в .env")
            return

        # Проверяем БД
        db_available = test_database_connection()
        titles = load_titles_from_file()

        if not titles:
            await context.bot.send_message(chat_id=chat_id, text="❌ Нет доступных тем в titles.txt")
            return

        actual_count = min(count, len(titles))
        if actual_count < count:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Запрошено {count}, но доступно только {len(titles)} тем. Генерируем {actual_count}."
            )

        est_minutes = actual_count * 1.5
        status_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"🚀 Запуск генерации {actual_count} пост(ов)\n"
                 f"⏱ Примерное время: {est_minutes:.0f} мин\n"
                 f"📚 Тем осталось: {len(titles)}\n"
                 f"🗄️ Supabase: {'✅' if db_available else '❌'}"
        )

        successful = []
        failed = []

        for i in range(actual_count):
            selected_title = select_random_title(titles)
            if not selected_title:
                break

            # Обновляем статус
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_msg.message_id,
                    text=f"🔄 Генерация {i+1}/{actual_count}\n"
                         f"📝 Тема: {selected_title}\n"
                         f"✅ Готово: {len(successful)} | ❌ Ошиблось: {len(failed)}"
                )
            except Exception:
                pass

            # Генерируем пост (в отдельном потоке чтобы не блокировать бота)
            post_data, error = await asyncio.get_event_loop().run_in_executor(
                None, lambda t=selected_title: generate_blog_post(api_key, t, model_name)
            )

            if post_data:
                # Валидация
                is_valid, validation_errors, post_data = validate_post_data(post_data)

                if not is_valid:
                    failed.append({'title': selected_title, 'error': '; '.join(validation_errors)})
                    continue

                # Slug
                if not post_data.get('slug') or post_data.get('slug').strip() == '':
                    post_data['slug'] = create_slug(post_data['title'])

                # Сохранение
                file_saved = save_to_file(post_data, selected_title)
                db_saved = False
                if db_available:
                    db_saved = save_post_to_database(post_data, selected_title, env_vars)

                if file_saved or db_saved:
                    titles = remove_title_from_list(titles, selected_title)
                    word_count = len(post_data.get('content', '').split())
                    successful.append({
                        'title': post_data.get('title', selected_title),
                        'words': word_count,
                        'category': post_data.get('category', '?'),
                        'db_saved': db_saved
                    })
                    bot_state['posts_generated_today'] += 1
                    bot_state['total_posts_generated'] += 1
                else:
                    failed.append({'title': selected_title, 'error': 'Ошибка сохранения'})
            else:
                failed.append({'title': selected_title, 'error': str(error)[:100]})

            # Пауза между генерациями
            if i < actual_count - 1:
                await asyncio.sleep(15)

        # Сохраняем обновлённый список тем
        save_titles_to_file(titles)

        # Ревалидация кеша
        if successful and db_available:
            revalidate_blog_cache(env_vars)

        bot_state['last_generation_time'] = datetime.now().strftime('%H:%M:%S %d.%m.%Y')

        # Финальный отчёт
        report = f"📊 *Генерация завершена*\n\n"
        report += f"✅ Успешно: {len(successful)}\n"
        report += f"❌ Ошибок: {len(failed)}\n"
        report += f"📚 Осталось тем: {len(titles)}\n\n"

        if successful:
            report += "*Созданные посты:*\n"
            for j, post in enumerate(successful, 1):
                db_icon = '🗄️' if post['db_saved'] else '📁'
                report += f"{j}\\. {db_icon} {escape_md(post['title'][:50])}\n"
                report += f"   _{escape_md(post['category'])}_ • {post['words']} слов\n"

        if failed:
            report += f"\n*Ошибки:*\n"
            for post in failed:
                report += f"❌ {escape_md(post['title'][:50])}\n"
                report += f"   _{escape_md(post['error'][:80])}_\n"

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_msg.message_id,
                text=report,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=report,
                parse_mode=ParseMode.MARKDOWN_V2
            )

    except Exception as e:
        logger.error(f"Generation error: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Критическая ошибка: {str(e)[:200]}"
        )
    finally:
        bot_state['is_generating'] = False


async def titles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /titles — список доступных тем"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    titles = load_titles_from_file()

    if not titles:
        await update.message.reply_text("📋 Список тем пуст!")
        return

    text = f"📋 *Доступные темы \\({len(titles)}\\):*\n\n"
    for i, title in enumerate(titles[:30], 1):  # Показываем до 30
        text += f"{i}\\. {escape_md(title)}\n"

    if len(titles) > 30:
        text += f"\n_\\.\\.\\.и ещё {len(titles) - 30} тем_"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def addtitle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /addtitle — добавить новую тему"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    new_title = ' '.join(context.args) if context.args else ''

    if not new_title:
        await update.message.reply_text(
            "❌ Укажите тему: `/addtitle Как выбрать МФО в 2026`",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    titles = load_titles_from_file()
    titles.append(new_title)
    save_titles_to_file(titles)

    await update.message.reply_text(
        f"✅ Тема добавлена: *{escape_md(new_title)}*\n"
        f"📚 Всего тем: {len(titles)}",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats — статистика"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    titles = load_titles_from_file()
    db_available = test_database_connection()

    # Считаем посты в Supabase
    posts_count = 0
    if db_available:
        try:
            import requests as req
            headers = {
                'apikey': env_vars.get('NEXT_PUBLIC_SUPABASE_ANON_KEY', ''),
                'Authorization': f"Bearer {env_vars.get('NEXT_PUBLIC_SUPABASE_ANON_KEY', '')}",
                'Content-Type': 'application/json',
                'Prefer': 'count=exact'
            }
            base_url = env_vars.get('SUPABASE_URL', env_vars.get('NEXT_PUBLIC_SUPABASE_URL', ''))
            resp = req.get(
                f"{base_url}/rest/v1/blog_posts?select=id",
                headers=headers,
                timeout=10
            )
            content_range = resp.headers.get('content-range', '')
            if '/' in content_range:
                posts_count = int(content_range.split('/')[1])
            else:
                posts_count = len(resp.json()) if resp.ok else 0
        except Exception:
            pass

    text = (
        f"📊 *Статистика бота*\n\n"
        f"📋 Тем в очереди: {len(titles)}\n"
        f"📝 Постов в Supabase: {posts_count}\n"
        f"🗄️ Supabase: {'✅ Доступен' if db_available else '❌ Недоступен'}\n\n"
        f"*Текущая сессия:*\n"
        f"✏️ Сгенерировано сегодня: {bot_state['posts_generated_today']}\n"
        f"📈 Всего за сессию: {bot_state['total_posts_generated']}\n"
        f"⏰ Последняя генерация: {bot_state['last_generation_time'] or 'нет'}\n"
        f"⏰ Автопостинг: {'✅ Вкл' if bot_state['scheduler_active'] else '❌ Выкл'}\n"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status — статус бота"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    status = "🔄 Генерация идёт..." if bot_state['is_generating'] else "💤 Ожидание"
    scheduler = "✅ Активен" if bot_state['scheduler_active'] else "❌ Неактивен"

    text = (
        f"ℹ️ *Статус бота*\n\n"
        f"Состояние: {status}\n"
        f"Автопостинг: {scheduler}\n"
        f"Модель: {escape_md(env_vars.get('MODEL_NAME', 'не задана'))}\n"
        f"Время сервера: {escape_md(datetime.now().strftime('%H:%M:%S %d.%m.%Y'))}\n"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /schedule — управление автопостингом"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Включить (3 поста/день)" if not bot_state['scheduler_active']
                else "❌ Выключить автопостинг",
                callback_data="sched_toggle"
            ),
        ],
        [
            InlineKeyboardButton("1 пост/день", callback_data="sched_1"),
            InlineKeyboardButton("3 поста/день", callback_data="sched_3"),
            InlineKeyboardButton("5 постов/день", callback_data="sched_5"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    status = "✅ Активен" if bot_state['scheduler_active'] else "❌ Выключен"
    await update.message.reply_text(
        f"⏰ *Автопостинг*\n\n"
        f"Статус: {status}\n"
        f"Постов в день: {bot_state['scheduler_posts_per_day']}\n"
        f"Интервал: каждые {bot_state['scheduler_interval_hours']}ч\n\n"
        f"Выберите действие:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def scheduled_generation(context: ContextTypes.DEFAULT_TYPE):
    """Автоматическая генерация по расписанию"""
    if not bot_state['scheduler_active'] or bot_state['is_generating']:
        return

    chat_id = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else None
    if not chat_id:
        return

    titles = load_titles_from_file()
    if not titles:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ Автопостинг: темы закончились! Добавьте новые через /addtitle"
        )
        bot_state['scheduler_active'] = False
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏰ Автопостинг: запускаю генерацию 1 поста..."
    )
    await do_generate(chat_id, context, count=1)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на inline-кнопки"""
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        await query.edit_message_text("⛔ Доступ запрещён")
        return

    data = query.data

    # Генерация
    if data.startswith("gen_"):
        count = int(data.split("_")[1])
        await query.edit_message_text(f"🚀 Запускаю генерацию {count} пост(ов)...")
        await do_generate(query.message.chat_id, context, count=count)

    # Темы
    elif data == "titles":
        titles = load_titles_from_file()
        if not titles:
            await query.edit_message_text("📋 Список тем пуст!")
            return

        text = f"📋 *Доступные темы \\({len(titles)}\\):*\n\n"
        for i, title in enumerate(titles[:30], 1):
            text += f"{i}\\. {escape_md(title)}\n"
        if len(titles) > 30:
            text += f"\n_\\.\\.\\.и ещё {len(titles) - 30} тем_"
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    # Статистика
    elif data == "stats":
        titles = load_titles_from_file()
        text = (
            f"📊 *Статистика*\n\n"
            f"📋 Тем в очереди: {len(titles)}\n"
            f"✏️ Сгенерировано сегодня: {bot_state['posts_generated_today']}\n"
            f"📈 Всего за сессию: {bot_state['total_posts_generated']}\n"
            f"⏰ Последняя: {bot_state['last_generation_time'] or 'нет'}\n"
            f"⏰ Автопостинг: {'✅' if bot_state['scheduler_active'] else '❌'}\n"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    # Статус
    elif data == "status":
        status = "🔄 Генерация" if bot_state['is_generating'] else "💤 Ожидание"
        text = (
            f"ℹ️ *Статус*\n\n"
            f"Состояние: {status}\n"
            f"Модель: {escape_md(env_vars.get('MODEL_NAME', '?'))}\n"
            f"Время: {escape_md(datetime.now().strftime('%H:%M:%S'))}\n"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    # Автопостинг
    elif data == "scheduler":
        status = "✅ Активен" if bot_state['scheduler_active'] else "❌ Выключен"
        keyboard = [
            [InlineKeyboardButton(
                "❌ Выключить" if bot_state['scheduler_active'] else "✅ Включить",
                callback_data="sched_toggle"
            )],
            [
                InlineKeyboardButton("1/день", callback_data="sched_1"),
                InlineKeyboardButton("3/день", callback_data="sched_3"),
                InlineKeyboardButton("5/день", callback_data="sched_5"),
            ],
        ]
        await query.edit_message_text(
            f"⏰ *Автопостинг*\n\nСтатус: {status}\n"
            f"Постов/день: {bot_state['scheduler_posts_per_day']}\n"
            f"Интервал: {bot_state['scheduler_interval_hours']}ч",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    elif data == "sched_toggle":
        bot_state['scheduler_active'] = not bot_state['scheduler_active']

        if bot_state['scheduler_active']:
            # Запускаем job
            interval_seconds = bot_state['scheduler_interval_hours'] * 3600
            context.job_queue.run_repeating(
                scheduled_generation,
                interval=interval_seconds,
                first=60,  # Первый пост через 1 минуту
                name="auto_post",
                chat_id=query.message.chat_id
            )
            await query.edit_message_text(
                f"✅ Автопостинг включён!\n\n"
                f"Буду генерировать по 1 посту каждые {bot_state['scheduler_interval_hours']}ч\n"
                f"({bot_state['scheduler_posts_per_day']} постов в день)"
            )
        else:
            # Удаляем job
            jobs = context.job_queue.get_jobs_by_name("auto_post")
            for job in jobs:
                job.schedule_removal()
            await query.edit_message_text("❌ Автопостинг выключен")

    elif data.startswith("sched_"):
        count_per_day = int(data.split("_")[1])
        bot_state['scheduler_posts_per_day'] = count_per_day
        bot_state['scheduler_interval_hours'] = max(1, 24 // count_per_day)

        # Перезапускаем job если активен
        if bot_state['scheduler_active']:
            jobs = context.job_queue.get_jobs_by_name("auto_post")
            for job in jobs:
                job.schedule_removal()

            interval_seconds = bot_state['scheduler_interval_hours'] * 3600
            context.job_queue.run_repeating(
                scheduled_generation,
                interval=interval_seconds,
                first=60,
                name="auto_post",
                chat_id=query.message.chat_id
            )

        await query.edit_message_text(
            f"✅ Установлено: {count_per_day} постов/день\n"
            f"Интервал: каждые {bot_state['scheduler_interval_hours']}ч\n"
            f"Автопостинг: {'✅ активен' if bot_state['scheduler_active'] else '❌ выключен'}"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    text = (
        "📖 *Справка по командам*\n\n"
        "`/start` — главное меню с кнопками\n"
        "`/generate` — генерация 1 поста\n"
        "`/batch 5` — пакетная генерация \\(1\\-30\\)\n"
        "`/titles` — список доступных тем\n"
        "`/addtitle Тема` — добавить тему\n"
        "`/stats` — статистика\n"
        "`/schedule` — автопостинг\n"
        "`/status` — статус бота\n"
        "`/help` — эта справка\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


def main():
    """Запуск бота"""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN не найден в .env!")
        print("Добавьте: TELEGRAM_BOT_TOKEN=ваш_токен")
        sys.exit(1)

    print("🤖 Запуск Telegram-бота МФО Витрина...")
    print(f"📋 Тем в очереди: {len(load_titles_from_file())}")
    print(f"🔑 Admin Chat ID: {ADMIN_CHAT_ID or 'не задан (доступ для всех)'}")
    print(f"🧠 Модель: {env_vars.get('MODEL_NAME', 'gpt-5.2')}")

    # Создаём приложение
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("generate", generate_command))
    app.add_handler(CommandHandler("batch", batch_command))
    app.add_handler(CommandHandler("titles", titles_command))
    app.add_handler(CommandHandler("addtitle", addtitle_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(CommandHandler("help", help_command))

    # Inline-кнопки
    app.add_handler(CallbackQueryHandler(button_callback))

    print("✅ Бот запущен! Нажмите Ctrl+C для остановки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
