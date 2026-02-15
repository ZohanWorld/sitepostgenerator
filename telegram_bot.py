#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram-бот для управления генерацией блог-постов.
Полное управление постером через Telegram.
Поддержка нескольких сайтов: МФО Витрина и Rabotaify.
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
    revalidate_blog_cache, SITE_CONFIGS
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
    'selected_site': None,  # Текущий выбранный сайт для генерации
    'scheduler_site': 'both',  # Сайт для автопостинга: 'mfo', 'hr', 'both'
}

# Иконки сайтов
SITE_ICONS = {
    'mfo': '💰',
    'hr': '👨‍💻',
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


def get_site_selection_keyboard(action_prefix: str):
    """Генерирует клавиатуру выбора сайта"""
    keyboard = [
        [
            InlineKeyboardButton("💰 МФО Витрина", callback_data=f"{action_prefix}_mfo"),
            InlineKeyboardButton("👨‍💻 Rabotaify", callback_data=f"{action_prefix}_hr"),
        ],
        [
            InlineKeyboardButton("🌐 Оба сайта", callback_data=f"{action_prefix}_both"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start — главное меню"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    chat_id = update.effective_chat.id
    keyboard = [
        [
            InlineKeyboardButton("📝 Генерировать 1 пост", callback_data="site_gen_1"),
            InlineKeyboardButton("📦 Пакет (5)", callback_data="site_gen_5"),
        ],
        [
            InlineKeyboardButton("📦 Пакет (10)", callback_data="site_gen_10"),
            InlineKeyboardButton("📦 Пакет (20)", callback_data="site_gen_20"),
        ],
        [
            InlineKeyboardButton("📋 Список тем", callback_data="site_titles"),
            InlineKeyboardButton("📊 Статистика", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("⏰ Автопостинг", callback_data="scheduler"),
            InlineKeyboardButton("ℹ️ Статус бота", callback_data="status"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🤖 *Бот\\-постер \\(МФО \\+ Rabotaify\\)*\n\n"
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
    """Команда /generate — выбор сайта перед генерацией"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return
    await update.message.reply_text(
        "🌐 *Выберите сайт для генерации:*",
        reply_markup=get_site_selection_keyboard("gen1"),
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /batch N — выбор сайта перед пакетной генерацией"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    try:
        count = int(context.args[0]) if context.args else 5
        count = max(1, min(count, 30))  # Лимит 1-30
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Укажите количество: `/batch 5`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Сохраняем кол-во в user_data для использования после выбора сайта
    context.user_data['batch_count'] = count
    await update.message.reply_text(
        f"🌐 *Пакет из {count} постов\\. Выберите сайт:*",
        reply_markup=get_site_selection_keyboard("batch"),
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def do_generate(chat_id: int, context: ContextTypes.DEFAULT_TYPE, count: int = 1, site_ids=None):
    """Выполняет генерацию постов для указанных сайтов"""
    if bot_state['is_generating']:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏳ Генерация уже идёт. Дождитесь завершения."
        )
        return

    if site_ids is None:
        site_ids = ['mfo']

    bot_state['is_generating'] = True

    try:
        api_key = env_vars.get('GPT_API_KEY')
        model_name = env_vars.get('MODEL_NAME', 'gpt-5.2')

        if not api_key:
            await context.bot.send_message(chat_id=chat_id, text="❌ GPT_API_KEY не найден в .env")
            return

        all_successful = []
        all_failed = []

        for site_id in site_ids:
            site_config = SITE_CONFIGS[site_id]
            site_name = site_config['name']
            site_icon = SITE_ICONS.get(site_id, '🌐')
            titles_file = site_config['titles_file']

            # Проверяем БД для этого сайта
            db_available = test_database_connection(env_vars, site_config)
            titles = load_titles_from_file(titles_file)

            if not titles:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ {site_icon} [{site_name}] Нет доступных тем в {titles_file}"
                )
                continue

            actual_count = min(count, len(titles))
            if actual_count < count:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ {site_icon} [{site_name}] Запрошено {count}, доступно {len(titles)}. Генерируем {actual_count}."
                )

            est_minutes = actual_count * 1.5
            status_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"🚀 {site_icon} [{site_name}] Запуск генерации {actual_count} пост(ов)\n"
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
                        text=f"🔄 {site_icon} [{site_name}] Генерация {i+1}/{actual_count}\n"
                             f"📝 Тема: {selected_title}\n"
                             f"✅ Готово: {len(successful)} | ❌ Ошибок: {len(failed)}"
                    )
                except Exception:
                    pass

                # Генерируем пост (в отдельном потоке чтобы не блокировать бота)
                post_data, error = await asyncio.get_event_loop().run_in_executor(
                    None, lambda t=selected_title, sid=site_id: generate_blog_post(api_key, t, model_name, sid)
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
                        db_saved = save_post_to_database(post_data, selected_title, env_vars, site_config)

                    if file_saved or db_saved:
                        titles = remove_title_from_list(titles, selected_title)
                        word_count = len(post_data.get('content', '').split())
                        successful.append({
                            'title': post_data.get('title', selected_title),
                            'words': word_count,
                            'category': post_data.get('category', '?'),
                            'db_saved': db_saved,
                            'site': site_name,
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
            save_titles_to_file(titles, titles_file)

            # Ревалидация кеша
            if successful and db_available:
                revalidate_blog_cache(env_vars, site_config)

            all_successful.extend(successful)
            all_failed.extend(failed)

            # Отчёт по сайту
            report = f"📊 {site_icon} *{escape_md(site_name)} — готово*\n\n"
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

        bot_state['last_generation_time'] = datetime.now().strftime('%H:%M:%S %d.%m.%Y')

        # Итоговый отчёт если оба сайта
        if len(site_ids) > 1:
            summary = (
                f"🏁 *Итого по всем сайтам:*\n\n"
                f"✅ Успешно: {len(all_successful)}\n"
                f"❌ Ошибок: {len(all_failed)}\n"
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=summary,
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
    """Команда /titles — выбор сайта для просмотра тем"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return
    await update.message.reply_text(
        "🌐 *Список тем для какого сайта?*",
        reply_markup=get_site_selection_keyboard("titles"),
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def show_titles_for_site(chat_id, context, site_id, message_id=None):
    """Показывает темы для конкретного сайта"""
    site_config = SITE_CONFIGS[site_id]
    site_icon = SITE_ICONS.get(site_id, '🌐')
    titles = load_titles_from_file(site_config['titles_file'])

    if not titles:
        text = f"📋 {site_icon} [{site_config['name']}] Список тем пуст\\!"
    else:
        text = f"📋 {site_icon} *{escape_md(site_config['name'])} — темы \\({len(titles)}\\):*\n\n"
        for i, title in enumerate(titles[:30], 1):
            text += f"{i}\\. {escape_md(title)}\n"
        if len(titles) > 30:
            text += f"\n_\\.\\.\\.и ещё {len(titles) - 30} тем_"

    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=text, parse_mode=ParseMode.MARKDOWN_V2
            )
            return
        except Exception:
            pass
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN_V2)


async def addtitle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /addtitle — добавить тему (спрашивает сайт)"""
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

    context.user_data['pending_title'] = new_title
    await update.message.reply_text(
        f"🌐 *Добавить тему на какой сайт?*\n\nТема: _{escape_md(new_title)}_",
        reply_markup=get_site_selection_keyboard("addtitle"),
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats — статистика"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    text = f"📊 *Статистика бота*\n\n"

    for site_id, site_config in SITE_CONFIGS.items():
        site_icon = SITE_ICONS.get(site_id, '🌐')
        titles = load_titles_from_file(site_config['titles_file'])
        db_available = test_database_connection(env_vars, site_config)

        # Считаем посты в Supabase
        posts_count = 0
        if db_available:
            try:
                import requests as req
                base_url = env_vars.get(site_config['env_supabase_url'], '')
                service_key = env_vars.get(site_config['env_service_key'], '')
                headers = {
                    'apikey': service_key,
                    'Authorization': f"Bearer {service_key}",
                    'Content-Type': 'application/json',
                    'Prefer': 'count=exact'
                }
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

        text += (
            f"{site_icon} *{escape_md(site_config['name'])}*\n"
            f"   📋 Тем в очереди: {len(titles)}\n"
            f"   📝 Постов в Supabase: {posts_count}\n"
            f"   🗄️ Supabase: {'✅' if db_available else '❌'}\n\n"
        )

    text += (
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
    sched_site = {'mfo': '💰 МФО', 'hr': '👨‍💻 Rabotaify', 'both': '🌐 Оба'}

    text = (
        f"ℹ️ *Статус бота*\n\n"
        f"Состояние: {status}\n"
        f"Автопостинг: {scheduler}\n"
        f"Сайт автопостинга: {sched_site.get(bot_state['scheduler_site'], '?')}\n"
        f"Модель: {escape_md(env_vars.get('MODEL_NAME', 'не задана'))}\n"
        f"Время сервера: {escape_md(datetime.now().strftime('%H:%M:%S %d.%m.%Y'))}\n"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /schedule — управление автопостингом"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Доступ запрещён")
        return

    sched_site = {'mfo': '💰 МФО', 'hr': '👨‍💻 Rabotaify', 'both': '🌐 Оба'}

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Включить" if not bot_state['scheduler_active']
                else "❌ Выключить",
                callback_data="sched_toggle"
            ),
        ],
        [
            InlineKeyboardButton("1/день", callback_data="sched_1"),
            InlineKeyboardButton("3/день", callback_data="sched_3"),
            InlineKeyboardButton("5/день", callback_data="sched_5"),
        ],
        [
            InlineKeyboardButton("💰 МФО", callback_data="sched_site_mfo"),
            InlineKeyboardButton("👨‍💻 Rabotaify", callback_data="sched_site_hr"),
            InlineKeyboardButton("🌐 Оба", callback_data="sched_site_both"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    status = "✅ Активен" if bot_state['scheduler_active'] else "❌ Выключен"
    await update.message.reply_text(
        f"⏰ *Автопостинг*\n\n"
        f"Статус: {status}\n"
        f"Сайт: {sched_site.get(bot_state['scheduler_site'], '?')}\n"
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

    # Определяем сайты для автопостинга
    sched_site = bot_state.get('scheduler_site', 'both')
    if sched_site == 'both':
        site_ids = ['mfo', 'hr']
    else:
        site_ids = [sched_site]

    # Проверяем наличие тем
    has_titles = False
    for sid in site_ids:
        titles = load_titles_from_file(SITE_CONFIGS[sid]['titles_file'])
        if titles:
            has_titles = True
            break

    if not has_titles:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ Автопостинг: темы закончились! Добавьте новые через /addtitle"
        )
        bot_state['scheduler_active'] = False
        return

    site_names = ', '.join([SITE_CONFIGS[s]['name'] for s in site_ids])
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏰ Автопостинг: запускаю генерацию для {site_names}..."
    )
    await do_generate(chat_id, context, count=1, site_ids=site_ids)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на inline-кнопки"""
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        await query.edit_message_text("⛔ Доступ запрещён")
        return

    data = query.data

    # === Выбор сайта перед генерацией (из главного меню) ===
    if data.startswith("site_gen_"):
        count = int(data.split("_")[-1])
        context.user_data['gen_count'] = count
        await query.edit_message_text(
            f"🌐 *Генерация {count} пост\\(ов\\)\\. Выберите сайт:*",
            reply_markup=get_site_selection_keyboard(f"dogen_{count}"),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    # === Запуск генерации после выбора сайта (из кнопок меню) ===
    elif data.startswith("dogen_"):
        parts = data.split("_")
        # dogen_COUNT_SITE
        count = int(parts[1])
        site = parts[2]
        site_ids = ['mfo', 'hr'] if site == 'both' else [site]
        site_names = ', '.join([SITE_CONFIGS[s]['name'] for s in site_ids])
        await query.edit_message_text(f"🚀 Запускаю генерацию {count} пост(ов) для {site_names}...")
        await do_generate(query.message.chat_id, context, count=count, site_ids=site_ids)

    # === Генерация 1 поста из /generate ===
    elif data.startswith("gen1_"):
        site = data.split("_")[1]
        site_ids = ['mfo', 'hr'] if site == 'both' else [site]
        site_names = ', '.join([SITE_CONFIGS[s]['name'] for s in site_ids])
        await query.edit_message_text(f"🚀 Запускаю генерацию 1 поста для {site_names}...")
        await do_generate(query.message.chat_id, context, count=1, site_ids=site_ids)

    # === Пакетная генерация из /batch ===
    elif data.startswith("batch_"):
        site = data.split("_")[1]
        count = context.user_data.get('batch_count', 5)
        site_ids = ['mfo', 'hr'] if site == 'both' else [site]
        site_names = ', '.join([SITE_CONFIGS[s]['name'] for s in site_ids])
        await query.edit_message_text(f"🚀 Запускаю генерацию {count} пост(ов) для {site_names}...")
        await do_generate(query.message.chat_id, context, count=count, site_ids=site_ids)

    # === Темы — выбор сайта ===
    elif data == "site_titles":
        await query.edit_message_text(
            "🌐 *Список тем для какого сайта?*",
            reply_markup=get_site_selection_keyboard("titles"),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    elif data.startswith("titles_"):
        site = data.split("_")[1]
        if site == 'both':
            # Показываем для обоих
            for sid in ['mfo', 'hr']:
                await show_titles_for_site(query.message.chat_id, context, sid)
            try:
                await query.delete_message()
            except Exception:
                pass
        else:
            await show_titles_for_site(
                query.message.chat_id, context, site,
                message_id=query.message.message_id
            )

    # === Добавить тему ===
    elif data.startswith("addtitle_"):
        site = data.split("_")[1]
        new_title = context.user_data.get('pending_title', '')
        if not new_title:
            await query.edit_message_text("❌ Тема не найдена. Попробуйте /addtitle снова.")
            return

        if site == 'both':
            sites_to_add = ['mfo', 'hr']
        else:
            sites_to_add = [site]

        for sid in sites_to_add:
            sc = SITE_CONFIGS[sid]
            titles = load_titles_from_file(sc['titles_file'])
            titles.append(new_title)
            save_titles_to_file(titles, sc['titles_file'])

        site_names = ', '.join([SITE_CONFIGS[s]['name'] for s in sites_to_add])
        await query.edit_message_text(
            f"✅ Тема добавлена на {site_names}:\n*{escape_md(new_title)}*",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        context.user_data.pop('pending_title', None)

    # === Статистика ===
    elif data == "stats":
        text = f"📊 *Статистика*\n\n"
        for site_id, site_config in SITE_CONFIGS.items():
            site_icon = SITE_ICONS.get(site_id, '🌐')
            titles = load_titles_from_file(site_config['titles_file'])
            text += (
                f"{site_icon} *{escape_md(site_config['name'])}*\n"
                f"   📋 Тем: {len(titles)}\n\n"
            )
        text += (
            f"✏️ Сегодня: {bot_state['posts_generated_today']}\n"
            f"📈 За сессию: {bot_state['total_posts_generated']}\n"
            f"⏰ Последняя: {bot_state['last_generation_time'] or 'нет'}\n"
            f"⏰ Автопостинг: {'✅' if bot_state['scheduler_active'] else '❌'}\n"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    # === Статус ===
    elif data == "status":
        status = "🔄 Генерация" if bot_state['is_generating'] else "💤 Ожидание"
        text = (
            f"ℹ️ *Статус*\n\n"
            f"Состояние: {status}\n"
            f"Модель: {escape_md(env_vars.get('MODEL_NAME', '?'))}\n"
            f"Время: {escape_md(datetime.now().strftime('%H:%M:%S'))}\n"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    # === Автопостинг ===
    elif data == "scheduler":
        sched_site_labels = {'mfo': '💰 МФО', 'hr': '👨‍💻 Rabotaify', 'both': '🌐 Оба'}
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
            [
                InlineKeyboardButton("💰 МФО", callback_data="sched_site_mfo"),
                InlineKeyboardButton("👨‍💻 HR", callback_data="sched_site_hr"),
                InlineKeyboardButton("🌐 Оба", callback_data="sched_site_both"),
            ],
        ]
        await query.edit_message_text(
            f"⏰ *Автопостинг*\n\nСтатус: {status}\n"
            f"Сайт: {sched_site_labels.get(bot_state['scheduler_site'], '?')}\n"
            f"Постов/день: {bot_state['scheduler_posts_per_day']}\n"
            f"Интервал: {bot_state['scheduler_interval_hours']}ч",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    elif data == "sched_toggle":
        bot_state['scheduler_active'] = not bot_state['scheduler_active']

        if bot_state['scheduler_active']:
            interval_seconds = bot_state['scheduler_interval_hours'] * 3600
            context.job_queue.run_repeating(
                scheduled_generation,
                interval=interval_seconds,
                first=60,
                name="auto_post",
                chat_id=query.message.chat_id
            )
            sched_site_labels = {'mfo': '💰 МФО', 'hr': '👨‍💻 Rabotaify', 'both': '🌐 Оба'}
            await query.edit_message_text(
                f"✅ Автопостинг включён!\n\n"
                f"Сайт: {sched_site_labels.get(bot_state['scheduler_site'], '?')}\n"
                f"По 1 посту каждые {bot_state['scheduler_interval_hours']}ч\n"
                f"({bot_state['scheduler_posts_per_day']} постов в день)"
            )
        else:
            jobs = context.job_queue.get_jobs_by_name("auto_post")
            for job in jobs:
                job.schedule_removal()
            await query.edit_message_text("❌ Автопостинг выключен")

    elif data.startswith("sched_site_"):
        site = data.replace("sched_site_", "")
        bot_state['scheduler_site'] = site
        sched_site_labels = {'mfo': '💰 МФО', 'hr': '👨‍💻 Rabotaify', 'both': '🌐 Оба'}
        await query.edit_message_text(
            f"✅ Сайт автопостинга: {sched_site_labels.get(site, '?')}\n"
            f"Автопостинг: {'✅ активен' if bot_state['scheduler_active'] else '❌ выключен'}"
        )

    elif data.startswith("sched_"):
        count_per_day = int(data.split("_")[1])
        bot_state['scheduler_posts_per_day'] = count_per_day
        bot_state['scheduler_interval_hours'] = max(1, 24 // count_per_day)

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
        "`/stats` — статистика по обоим сайтам\n"
        "`/schedule` — автопостинг \\(выбор сайта\\)\n"
        "`/status` — статус бота\n"
        "`/help` — эта справка\n\n"
        "💡 При генерации бот спросит, на какой сайт постить:\n"
        "💰 МФО Витрина | 👨‍💻 Rabotaify | 🌐 Оба\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


def main():
    """Запуск бота"""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN не найден в .env!")
        print("Добавьте: TELEGRAM_BOT_TOKEN=ваш_токен")
        sys.exit(1)

    print("🤖 Запуск Telegram-бота (МФО + Rabotaify)...")
    for site_id, sc in SITE_CONFIGS.items():
        titles = load_titles_from_file(sc['titles_file'])
        icon = SITE_ICONS.get(site_id, '🌐')
        print(f"   {icon} {sc['name']}: {len(titles)} тем")
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
