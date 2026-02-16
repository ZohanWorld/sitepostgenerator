import requests
import json
import os
import re
import random
from datetime import datetime
import uuid
import urllib3

# ============================================================
# SITE CONFIGURATIONS
# ============================================================

SITE_CONFIGS = {
    'mfo': {
        'name': 'МФО Витрина',
        'titles_file': 'titles_mfo.txt',
        'env_supabase_url': 'SUPABASE_URL',
        'env_service_key': 'SUPABASE_SERVICE_ROLE_KEY',
        'env_site_url': 'SITE_URL',
        'env_revalidate_secret': 'REVALIDATE_SECRET',
        'default_author': 'Редакция МФО Витрина',
        'allowed_categories': [
            'Инструкции', 'Акции', 'Требования', 'Кредитная история',
            'Сравнение', 'Советы', 'Обзоры', 'Личный опыт', 'Юридические'
        ],
        'default_category': 'Советы',
        # Маппинг полей: ключ = поле в JSON от GPT, значение = поле в таблице Supabase
        'field_mapping': {
            'title': 'title',
            'slug': 'slug',
            'excerpt': 'excerpt',
            'content': 'content',
            'category': 'category',
            'tags': 'tags',
            'author': 'author',
            'read_time': 'read_time',
            'meta_title': 'meta_title',
            'meta_description': 'meta_description',
            'seo_keywords': 'seo_keywords',
        },
    },
    'hr': {
        'name': 'Rabotaify',
        'titles_file': 'titles_hr.txt',
        'env_supabase_url': 'HR_SUPABASE_URL',
        'env_service_key': 'HR_SUPABASE_SERVICE_ROLE_KEY',
        'env_site_url': 'HR_SITE_URL',
        'env_revalidate_secret': 'HR_REVALIDATE_SECRET',
        'default_author': None,  # Will be auto-selected from HR_AUTHORS
        'allowed_categories': [
            'IT и карьера', 'Зарплаты', 'Поиск работы', 'Собеседования',
            'Удалённая работа', 'Образование', 'Фриланс', 'Soft skills',
            'Программирование', 'Data Science', 'DevOps', 'Дизайн', 'Менеджмент'
        ],
        'default_category': 'IT и карьера',
        # Маппинг полей: Rabotaify использует другие названия колонок
        'field_mapping': {
            'title': 'title',
            'slug': 'slug',
            'excerpt': 'excerpt',
            'content': 'content',
            'category': 'category_name',       # → category_name
            'category_slug': 'category_slug',   # доп. поле
            'category_icon': 'category_icon',   # доп. поле
            'tags': 'tags',
            'author': 'author_name',            # → author_name
            'read_time': 'reading_time',        # → reading_time
            # Rabotaify не имеет meta_title/meta_description/seo_keywords
        },
    },
}

# Иконки категорий для Rabotaify
HR_CATEGORY_ICONS = {
    'IT и карьера': '💻',
    'Зарплаты': '💰',
    'Поиск работы': '📄',
    'Собеседования': '🎯',
    'Удалённая работа': '🏠',
    'Образование': '📚',
    'Фриланс': '💼',
    'Soft skills': '🤝',
    'Программирование': '⌨️',
    'Data Science': '📊',
    'DevOps': '⚙️',
    'Дизайн': '🎨',
    'Менеджмент': '📋',
}

# Вымышленные авторы для Rabotaify
HR_AUTHORS = [
    {
        'name': 'Иван Маслаков',
        'role': 'IT-рекрутер',
        'categories': ['Собеседования', 'Поиск работы'],
    },
    {
        'name': 'Анна Ковалёва',
        'role': 'Карьерный консультант',
        'categories': ['Зарплаты', 'Soft skills', 'Менеджмент', 'Удалённая работа', 'Фриланс'],
    },
    {
        'name': 'Дмитрий Соколов',
        'role': 'Разработчик',
        'categories': ['Программирование', 'Data Science', 'DevOps', 'Дизайн', 'Образование'],
    },
]

def select_hr_author(category=None):
    """Выбирает автора для HR статьи по категории (или случайно)"""
    if category:
        for author in HR_AUTHORS:
            if category in author['categories']:
                return author
    # IT и карьера или неизвестная категория — случайный автор
    return random.choice(HR_AUTHORS)

def create_category_slug(category_name):
    """Создаёт slug категории из её названия"""
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    slug = category_name.lower()
    for cyrillic, latin in translit_map.items():
        slug = slug.replace(cyrillic, latin)
    slug = re.sub(r'[^a-zA-Z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug


def load_env():
    """Простая загрузка переменных из .env файла"""
    env_vars = {}
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    value = value.strip('"').strip("'")
                    env_vars[key] = value
    except FileNotFoundError:
        print("❌ Файл .env не найден!")
    return env_vars


def get_supabase_headers(env_vars, site_config):
    """Возвращает заголовки для Supabase REST API для конкретного сайта"""
    service_key = env_vars.get(site_config['env_service_key'], '')
    return {
        'apikey': service_key,
        'Authorization': f'Bearer {service_key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }


def get_supabase_url(env_vars, site_config):
    """Возвращает базовый URL для Supabase REST API для конкретного сайта"""
    url = env_vars.get(site_config['env_supabase_url'], '')
    url = url.strip('"').strip("'")
    return f"{url}/rest/v1"


def check_slug_exists(env_vars, slug, site_config):
    """Проверяет, существует ли пост с таким slug в БД"""
    base_url = get_supabase_url(env_vars, site_config)
    headers = get_supabase_headers(env_vars, site_config)
    try:
        response = requests.get(
            f"{base_url}/blog_posts?slug=eq.{slug}&select=slug",
            headers=headers,
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            return len(data) > 0
    except Exception as e:
        print(f"⚠️ Не удалось проверить slug: {e}")
    return False


def make_unique_slug(env_vars, slug, site_config):
    """Гарантирует уникальность slug"""
    if not check_slug_exists(env_vars, slug, site_config):
        return slug
    counter = 2
    while True:
        new_slug = f"{slug}-{counter}"
        if not check_slug_exists(env_vars, new_slug, site_config):
            print(f"⚠️ Slug '{slug}' уже существует, используем '{new_slug}'")
            return new_slug
        counter += 1
        if counter > 100:
            new_slug = f"{slug}-{uuid.uuid4().hex[:6]}"
            return new_slug


def save_post_to_database(post_data, selected_title, env_vars=None, site_config=None):
    """Сохраняет пост в таблицу blog_posts через Supabase REST API с маппингом полей"""
    if env_vars is None:
        env_vars = load_env()
    if site_config is None:
        site_config = SITE_CONFIGS['mfo']

    site_id = 'mfo' if site_config == SITE_CONFIGS['mfo'] else 'hr'
    base_url = get_supabase_url(env_vars, site_config)
    headers = get_supabase_headers(env_vars, site_config)

    supabase_url = env_vars.get(site_config['env_supabase_url'], '')
    if not supabase_url:
        print(f"❌ {site_config['env_supabase_url']} не найден в .env")
        return False

    post_id = str(uuid.uuid4())
    now = datetime.now().isoformat()

    # Гарантируем уникальность slug
    slug = post_data.get('slug', '')
    slug = make_unique_slug(env_vars, slug, site_config)

    mapping = site_config['field_mapping']

    # Базовые поля через маппинг
    payload = {
        "id": post_id,
        mapping.get('title', 'title'): post_data.get('title', ''),
        mapping.get('slug', 'slug'): slug,
        mapping.get('excerpt', 'excerpt'): post_data.get('excerpt', ''),
        mapping.get('content', 'content'): post_data.get('content', ''),
        mapping.get('category', 'category'): post_data.get('category', ''),
        mapping.get('tags', 'tags'): post_data.get('tags', []),
        mapping.get('author', 'author'): post_data.get('author', site_config['default_author']) or random.choice(HR_AUTHORS)['name'],
        "published_at": now,
        "updated_at": now,
        "is_published": True,
        mapping.get('read_time', 'read_time'): post_data.get('read_time', 5),
        "created_at": now
    }

    # Дополнительные поля для MFO
    if site_id == 'mfo':
        payload['meta_title'] = post_data.get('meta_title', '')
        payload['meta_description'] = post_data.get('meta_description', '')
        payload['seo_keywords'] = post_data.get('seo_keywords', [])

    # Дополнительные поля для HR (Rabotaify)
    if site_id == 'hr':
        category = post_data.get('category', '')
        payload['category_slug'] = post_data.get('category_slug', create_category_slug(category))
        payload['category_icon'] = post_data.get('category_icon', HR_CATEGORY_ICONS.get(category, '📝'))

    try:
        response = requests.post(
            f"{base_url}/blog_posts",
            headers=headers,
            json=payload,
            timeout=30
        )
        if response.status_code in [200, 201]:
            print(f"✅ [{site_config['name']}] Пост добавлен в базу данных с ID: {post_id}")
            return True
        else:
            print(f"❌ [{site_config['name']}] Ошибка при сохранении в БД: {response.status_code} — {response.text}")
            return False
    except Exception as e:
        print(f"❌ [{site_config['name']}] Ошибка при сохранении: {e}")
        return False


def revalidate_blog_cache(env_vars, site_config=None):
    """Вызывает ревалидацию кеша Next.js"""
    if site_config is None:
        site_config = SITE_CONFIGS['mfo']

    revalidate_secret = env_vars.get(site_config['env_revalidate_secret'], '')
    site_url = env_vars.get(site_config['env_site_url'], 'http://localhost:3000')

    if not revalidate_secret:
        print(f"⚠️ [{site_config['name']}] REVALIDATE_SECRET не задан — кеш обновится автоматически")
        return

    try:
        response = requests.post(
            f"{site_url}/api/revalidate",
            json={"secret": revalidate_secret, "path": "/blog"},
            timeout=10
        )
        if response.status_code == 200:
            print(f"🔄 [{site_config['name']}] Кеш блога обновлён")
        else:
            print(f"⚠️ [{site_config['name']}] Ревалидация не удалась: {response.status_code}")
    except Exception:
        print(f"⚠️ [{site_config['name']}] Не удалось обновить кеш (сайт недоступен?)")


def test_database_connection(env_vars=None, site_config=None):
    """Проверяет подключение к Supabase для указанного сайта"""
    if env_vars is None:
        env_vars = load_env()
    if site_config is None:
        site_config = SITE_CONFIGS['mfo']

    print(f"🔍 [{site_config['name']}] Проверяем подключение к Supabase...")
    base_url = get_supabase_url(env_vars, site_config)
    headers = get_supabase_headers(env_vars, site_config)

    try:
        response = requests.get(
            f"{base_url}/blog_posts?select=id&limit=1",
            headers=headers,
            timeout=10
        )
        if response.status_code == 200:
            print(f"✅ [{site_config['name']}] Подключение к Supabase успешно")
            return True
        else:
            print(f"❌ [{site_config['name']}] Ошибка подключения: {response.status_code} — {response.text}")
            return False
    except Exception as e:
        print(f"❌ [{site_config['name']}] Ошибка проверки: {e}")
        return False


def load_titles_from_file(filename="titles.txt"):
    """Загружает список тем из файла"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            titles = [line.strip() for line in f if line.strip()]
        return titles
    except FileNotFoundError:
        print(f"❌ Файл {filename} не найден!")
        return []
    except Exception as e:
        print(f"❌ Ошибка при чтении файла {filename}: {e}")
        return []


def save_titles_to_file(titles, filename="titles.txt"):
    """Сохраняет обновленный список тем в файл"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            for title in titles:
                f.write(title + '\n')
        return True
    except Exception as e:
        print(f"❌ Ошибка при сохранении файла {filename}: {e}")
        return False


def select_random_title(titles):
    """Выбирает случайную тему из списка"""
    if not titles:
        return None
    return random.choice(titles)


def remove_title_from_list(titles, title_to_remove):
    """Удаляет использованную тему из списка"""
    try:
        titles.remove(title_to_remove)
        return titles
    except ValueError:
        print(f"⚠️ Тема '{title_to_remove}' не найдена в списке")
        return titles


def validate_post_data(post_data, site_config=None):
    """Валидирует данные поста от GPT. Возвращает (is_valid, errors, fixed_data)."""
    if site_config is None:
        site_config = SITE_CONFIGS['mfo']

    errors = []
    fixed = dict(post_data)

    required_fields = ['title', 'content', 'excerpt']
    for field in required_fields:
        if not fixed.get(field) or not str(fixed[field]).strip():
            errors.append(f"Отсутствует обязательное поле: {field}")

    if errors:
        return False, errors, fixed

    # Обрезаем title если слишком длинный
    if len(fixed.get('title', '')) > 70:
        fixed['title'] = fixed['title'][:67] + '...'
        print(f"⚠️ Title обрезан до 70 символов")

    # Обрезаем excerpt если слишком длинный
    if len(fixed.get('excerpt', '')) > 200:
        fixed['excerpt'] = fixed['excerpt'][:197] + '...'
        print(f"⚠️ Excerpt обрезан до 200 символов")

    # Обрезаем meta_title
    if len(fixed.get('meta_title', '')) > 70:
        fixed['meta_title'] = fixed['meta_title'][:67] + '...'

    # Обрезаем meta_description
    if len(fixed.get('meta_description', '')) > 200:
        fixed['meta_description'] = fixed['meta_description'][:197] + '...'

    # Проверяем категорию
    category = fixed.get('category', '')
    allowed = site_config['allowed_categories']
    if category not in allowed:
        best_match = None
        for a in allowed:
            if a.lower() in category.lower() or category.lower() in a.lower():
                best_match = a
                break
        if best_match:
            fixed['category'] = best_match
            print(f"⚠️ Категория '{category}' заменена на '{best_match}'")
        else:
            fixed['category'] = site_config['default_category']
            print(f"⚠️ Неизвестная категория '{category}', установлена '{site_config['default_category']}'")

    # Проверяем tags
    tags = fixed.get('tags', [])
    if isinstance(tags, str):
        fixed['tags'] = [t.strip() for t in tags.split(',') if t.strip()]
    elif not isinstance(tags, list):
        fixed['tags'] = []

    # Проверяем seo_keywords
    keywords = fixed.get('seo_keywords', [])
    if isinstance(keywords, str):
        fixed['seo_keywords'] = [k.strip() for k in keywords.split(',') if k.strip()]
    elif not isinstance(keywords, list):
        fixed['seo_keywords'] = []

    # Проверяем read_time
    read_time = fixed.get('read_time', 5)
    if not isinstance(read_time, (int, float)):
        try:
            fixed['read_time'] = int(read_time)
        except (ValueError, TypeError):
            fixed['read_time'] = 5

    # Проверяем длину контента
    word_count = len(fixed.get('content', '').split())
    if word_count < 500:
        print(f"⚠️ Контент слишком короткий: {word_count} слов (ожидается 2000+)")

    return True, errors, fixed


# ============================================================
# GPT PROMPTS PER SITE
# ============================================================

def get_gpt_prompt_mfo(selected_title):
    """GPT промпт для МФО Витрина"""
    current_year = 2026
    categories_str = ' | '.join(SITE_CONFIGS['mfo']['allowed_categories'])
    return f"""
Напиши экспертную статью для блога "МФО Витрина" на тему:

"{selected_title}"

Целевая аудитория: люди, которые ищут информацию о микрозаймах в России в {current_year} году. Они хотят конкретные ответы, а не общие рассуждения.

## Формат ответа

Верни результат СТРОГО как JSON-объект (без ```json обёртки, без текста до/после):
{{
  "title": "Заголовок поста (50-60 символов, включи год {current_year} если уместно)",
  "slug": "slug-na-latinitse-cherez-defis",
  "excerpt": "Краткое описание (150-160 символов). Должно интриговать и содержать ключевое слово.",
  "content": "ПОЛНЫЙ текст статьи в формате Markdown (минимум 2500 слов, см. требования ниже)",
  "category": "СТРОГО одна из: {categories_str}",
  "tags": ["тег1", "тег2", "тег3", "тег4", "тег5"],
  "author": "Редакция МФО Витрина",
  "meta_title": "SEO-заголовок для Google (50-60 символов с ключевым словом)",
  "meta_description": "SEO-описание с CTA (150-160 символов)",
  "seo_keywords": ["основной запрос", "LSI-запрос 1", "LSI-запрос 2", "длиннохвостый запрос"],
  "read_time": число_минут_чтения
}}

## Требования к content (КРИТИЧЕСКИ ВАЖНО)

### Структура статьи:
1. Вводный абзац (2-3 предложения, сразу по делу — зачем читать эту статью)
2. Основной блок — 3-4 секции с заголовками ## (H2). Внутри каждой секции — подзаголовки ### (H3) если нужно
3. Секция "## Часто задаваемые вопросы" — 3-5 вопросов с ответами (если подходит к теме)
4. Заключительный абзац с выводом

### Форматирование:
- НИКОГДА не используй заголовок # (H1) — он уже есть на странице
- Используй только ## (H2) и ### (H3)
- **ЗАПРЕЩЕНО** использовать маркированные или нумерованные списки. Вместо списка пиши связный текст. Например, вместо:
  "- Паспорт\\n- СНИЛС\\n- Справка о доходах"
  пиши: "Для оформления потребуется паспорт гражданина РФ, СНИЛС и, в некоторых компаниях, справка о доходах."
- Единственное исключение для списков — секция FAQ, где допустимы нумерованные вопросы

### Стиль текста:
- Пиши как финансовый журналист, НЕ как маркетолог
- Избегай водянистых фраз: "в современном мире", "важно понимать что", "как известно", "не секрет что", "давайте разберёмся"
- Каждый абзац должен содержать КОНКРЕТНУЮ информацию: цифры, сроки, суммы, проценты, примеры
- Упоминай реальные названия МФО (Займер, Webbankir, Lime, МигКредит, MoneyMan и др.)
- Все данные и цифры должны быть актуальны на {current_year} год
- Минимальная длина: 2500 слов. Каждая из 3-4 основных секций — минимум 500 слов

### SEO:
- Естественно встраивай ключевые слова в текст (плотность ~1-2%)
- Используй синонимы и LSI-фразы: "микрозайм", "займ онлайн", "кредит в МФО", "деньги на карту"
- В первом абзаце обязательно должно быть основное ключевое слово

### Экранирование:
- В поле "content" все кавычки внутри текста должны быть экранированы (\\")
- Переносы строк в content: используй \\n
- Убедись, что JSON валиден
"""


def get_gpt_prompt_hr(selected_title, author_name='Иван Маслаков'):
    """GPT промпт для Rabotaify (HR, IT, карьера)"""
    current_year = 2026
    categories_str = ' | '.join(SITE_CONFIGS['hr']['allowed_categories'])
    return f"""
Напиши экспертную статью для блога "Rabotaify" — платформы поиска работы в IT и HR на тему:

"{selected_title}"

Целевая аудитория: IT-специалисты, начинающие разработчики, менеджеры и все, кто ищет работу или развивает карьеру в IT в России в {current_year} году.

## Формат ответа

Верни результат СТРОГО как JSON-объект (без ```json обёртки, без текста до/после):
{{
  "title": "Заголовок поста (50-60 символов, включи год {current_year} если уместно)",
  "slug": "slug-na-latinitse-cherez-defis",
  "excerpt": "Краткое описание (150-160 символов). Должно интриговать и содержать ключевое слово.",
  "content": "ПОЛНЫЙ текст статьи в формате Markdown (минимум 2500 слов, см. требования ниже)",
  "category": "СТРОГО одна из: {categories_str}",
  "tags": ["тег1", "тег2", "тег3", "тег4", "тег5"],
  "author": "{author_name}",
  "read_time": число_минут_чтения
}}

## Требования к content (КРИТИЧЕСКИ ВАЖНО)

### Структура статьи:
1. Вводный абзац (2-3 предложения, сразу по делу — зачем читать эту статью)
2. Основной блок — 3-5 секций с заголовками ## (H2). Внутри секций — подзаголовки ### (H3) если нужно
3. Секция "## Часто задаваемые вопросы" — 3-5 вопросов с ответами (если подходит к теме)
4. Заключительный абзац с выводом и призывом к действию

### Форматирование:
- НИКОГДА не используй заголовок # (H1) — он уже есть на странице
- Используй только ## (H2) и ### (H3)
- **ЗАПРЕЩЕНО** использовать маркированные или нумерованные списки. Вместо списка пиши связный текст. Например, вместо:
  "- React\\n- Vue\\n- Angular"
  пиши: "Среди популярных фреймворков выделяются React, Vue и Angular — каждый со своими преимуществами."
- Единственное исключение для списков — секция FAQ, где допустимы нумерованные вопросы

### Стиль текста:
- Пиши как опытный IT-рекрутер и карьерный консультант
- Избегай водянистых фраз: "в современном мире", "важно понимать что", "как известно", "не секрет что", "давайте разберёмся"
- Каждый абзац должен содержать КОНКРЕТНУЮ информацию: цифры зарплат, названия компаний, ссылки на ресурсы, реальные примеры
- Упоминай реальные компании (Яндекс, Сбер, Тинькофф, VK, Ozon, Авито и др.)
- Упоминай реальные платформы (HeadHunter, Habr Career, GitHub, LeetCode, Rabotaify)
- Все данные должны быть актуальны на {current_year} год
- Минимальная длина: 2500 слов. Каждая из 3-5 основных секций — минимум 400 слов

### SEO:
- Естественно встраивай ключевые слова (плотность ~1-2%)
- Используй синонимы и LSI-фразы для IT-тематики
- В первом абзаце обязательно должно быть основное ключевое слово

### Внутренние ссылки (ОБЯЗАТЕЛЬНО):
- В тексте статьи ОБЯЗАТЕЛЬНО вставь 2-3 ссылки на другие разделы rabotaify.ru
- Используй markdown-формат: [текст ссылки](URL)
- Доступные страницы для ссылок:
  - [вакансии в IT](https://rabotaify.ru/jobs) — каталог вакансий
  - [IT-компании](https://rabotaify.ru/companies) — каталог компаний-работодателей
  - [блог о карьере](https://rabotaify.ru/blog) — все статьи блога
- Ссылки должны быть вписаны ЕСТЕСТВЕННО в текст, например:
  "Актуальные предложения можно найти в [каталоге вакансий](https://rabotaify.ru/jobs) на нашей платформе."
  "Ознакомьтесь с ведущими [IT-компаниями](https://rabotaify.ru/companies), которые сейчас нанимают."
- НЕ делай отдельную секцию с ссылками — они должны быть органичной частью текста

### Экранирование:
- В поле "content" все кавычки внутри текста должны быть экранированы (\\")
- Переносы строк в content: используй \\n
- Убедись, что JSON валиден
"""


def get_system_prompt(site_id):
    """Возвращает system prompt для GPT в зависимости от сайта"""
    current_year = 2026
    if site_id == 'mfo':
        return f"Ты — опытный финансовый журналист и SEO-копирайтер, специализирующийся на микрофинансовом рынке России. Ты пишешь глубокие, экспертные статьи для блога 'МФО Витрина'. Твои тексты читаются как статьи в РБК или Банки.ру — с конкретикой, цифрами и практической пользой. Текущий год: {current_year}. Всегда отвечай ТОЛЬКО валидным JSON без обёрток и комментариев."
    else:
        return f"Ты — опытный IT-рекрутер, карьерный консультант и SEO-копирайтер. Ты пишешь экспертные статьи для блога 'Rabotaify' — платформы поиска работы в IT. Твои тексты полезны, конкретны и написаны как статьи на Хабре или vc.ru — с реальными цифрами, примерами и практическими советами. Текущий год: {current_year}. Всегда отвечай ТОЛЬКО валидным JSON без обёрток и комментариев."


def generate_blog_post(api_key, selected_title, model_name="gpt-5.2", site_id='mfo'):
    """Генерирует пост через ChatGPT API для указанного сайта"""

    # Выбираем промпт в зависимости от сайта
    if site_id == 'mfo':
        prompt = get_gpt_prompt_mfo(selected_title)
    else:
        # Выбираем случайного автора для HR
        author = select_hr_author()
        print(f"✍️ Выбран автор: {author['name']} ({author['role']})")
        prompt = get_gpt_prompt_hr(selected_title, author['name'])

    system_prompt = get_system_prompt(site_id)

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    data = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "max_completion_tokens": 16000,
        "temperature": 0.7
    }

    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session = requests.Session()
        session.verify = True

        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.packages.urllib3.util.retry.Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[500, 502, 503, 504]
            )
        )
        session.mount('https://', adapter)

        print("🔄 Отправляем запрос к OpenAI API...")

        response = session.post(
            'https://api.openai.com/v1/chat/completions',
            headers=headers,
            json=data,
            timeout=300
        )

        if response.status_code == 200:
            response_data = response.json()
            content = response_data['choices'][0]['message']['content'].strip()
            try:
                post_data = json.loads(content)
                return post_data, None
            except json.JSONDecodeError:
                print("⚠️ Ошибка парсинга JSON, пытаемся починить...")
                try:
                    content = re.sub(r'^```json\s*', '', content)
                    content = re.sub(r'\s*```$', '', content)
                    content = re.sub(r'^.*?(\{.*\}).*?$', r'\1', content, flags=re.DOTALL)
                    post_data = json.loads(content)
                    return post_data, None
                except json.JSONDecodeError as e:
                    return None, f"Не удалось парсить JSON: {e}\nОтвет: {content[:500]}..."
        else:
            return None, f"Ошибка API: {response.status_code} - {response.text}"

    except requests.exceptions.SSLError as e:
        print("⚠️ Ошибка SSL, пробуем без проверки сертификата...")
        try:
            session = requests.Session()
            session.verify = False
            response = session.post(
                'https://api.openai.com/v1/chat/completions',
                headers=headers,
                json=data,
                timeout=300
            )
            if response.status_code == 200:
                response_data = response.json()
                content = response_data['choices'][0]['message']['content'].strip()
                try:
                    post_data = json.loads(content)
                    return post_data, None
                except json.JSONDecodeError:
                    try:
                        content = re.sub(r'^```json\s*', '', content)
                        content = re.sub(r'\s*```$', '', content)
                        content = re.sub(r'^.*?(\{.*\}).*?$', r'\1', content, flags=re.DOTALL)
                        post_data = json.loads(content)
                        return post_data, None
                    except json.JSONDecodeError as e2:
                        return None, f"Не удалось парсить JSON: {e2}\nОтвет: {content[:500]}..."
            else:
                return None, f"Ошибка API: {response.status_code} - {response.text}"
        except Exception as fallback_error:
            return None, f"SSL ошибка и fallback не сработал: {e} -> {fallback_error}"

    except requests.exceptions.RequestException as e:
        return None, f"Ошибка запроса: {e}"
    except Exception as e:
        return None, f"Неожиданная ошибка: {e}"


def create_slug(title):
    """Создает URL-friendly slug из заголовка"""
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    slug = title.lower()
    for cyrillic, latin in translit_map.items():
        slug = slug.replace(cyrillic, latin)
    slug = re.sub(r'[^a-zA-Z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug


def save_to_file(post_data, selected_title, filename_prefix="generated_post"):
    """Сохраняет сгенерированный пост в файл"""
    try:
        safe_title = re.sub(r'[^\w\s-]', '', selected_title.replace('?', '').replace(':', ''))
        safe_title = re.sub(r'\s+', '_', safe_title)[:50]
        filename = f"{filename_prefix}_{safe_title}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(post_data, f, ensure_ascii=False, indent=2)
        print(f"✅ Пост сохранен в файл: {filename}")
        return True
    except Exception as e:
        print(f"❌ Ошибка при сохранении в файл: {e}")
        return False


def show_remaining_titles(titles):
    """Показывает статистику оставшихся тем"""
    print(f"\n📊 СТАТИСТИКА ТЕМ:")
    print(f"Осталось тем: {len(titles)}")
    if titles:
        print("Ближайшие темы:")
        for i, title in enumerate(titles[:5], 1):
            print(f"  {i}. {title}")
        if len(titles) > 5:
            print(f"  ... и еще {len(titles) - 5} тем")
    else:
        print("🎉 Все темы использованы!")


def select_site():
    """Меню выбора сайта"""
    print("\n🌐 ВЫБЕРИТЕ САЙТ:")
    print("  1. МФО Витрина (микрозаймы)")
    print("  2. Rabotaify (IT, HR, карьера)")
    print("  3. Оба сайта")

    while True:
        choice = input("\nВаш выбор (1/2/3): ").strip()
        if choice == '1':
            return ['mfo']
        elif choice == '2':
            return ['hr']
        elif choice == '3':
            return ['mfo', 'hr']
        else:
            print("❌ Введите 1, 2 или 3")


def main():
    """Основная функция"""
    print("🚀 Генератор постов v4.0 (мультисайт)")
    print("=" * 60)

    # Загружаем переменные окружения
    env_vars = load_env()

    api_key = env_vars.get('GPT_API_KEY')
    model_name = env_vars.get('MODEL_NAME', 'gpt-5.2')

    if not api_key:
        print("❌ Ошибка: GPT_API_KEY не найден в файле .env")
        return

    # Выбираем сайты
    site_ids = select_site()

    for site_id in site_ids:
        site_config = SITE_CONFIGS[site_id]
        titles_file = site_config['titles_file']

        print(f"\n{'='*60}")
        print(f"🌐 САЙТ: {site_config['name']}")
        print(f"{'='*60}")

        # Проверяем подключение к Supabase
        db_available = test_database_connection(env_vars, site_config)

        # Загружаем список тем
        titles = load_titles_from_file(titles_file)
        if not titles:
            print(f"❌ Нет доступных тем в {titles_file}")
            continue

        print(f"📚 Загружено тем: {len(titles)}")

        # Выбираем случайную тему
        selected_title = select_random_title(titles)
        print(f"🎯 Выбранная тема: '{selected_title}'")
        print(f"🔑 Используем модель: {model_name}")
        print("🔄 Генерируем пост...")
        print("=" * 60)

        # Генерируем пост
        post_data, error = generate_blog_post(api_key, selected_title, model_name, site_id)

        if post_data:
            # Валидируем
            is_valid, validation_errors, post_data = validate_post_data(post_data, site_config)

            if not is_valid:
                print(f"❌ Данные от GPT не прошли валидацию:")
                for err in validation_errors:
                    print(f"   - {err}")
                print(f"🔄 Тема '{selected_title}' осталась в списке для повторной попытки")
                continue

            # Автоматически создаем slug
            if not post_data.get('slug') or post_data.get('slug').strip() == '':
                post_data['slug'] = create_slug(post_data['title'])

            print(f"\n✅ Пост успешно сгенерирован!")
            print(f"📖 На тему: '{selected_title}'")
            print("\n📝 РЕЗУЛЬТАТ:")
            print("=" * 60)
            print(json.dumps(post_data, ensure_ascii=False, indent=2))
            print("=" * 60)

            print(f"\n📊 СТАТИСТИКА ПОСТА:")
            print(f"Заголовок: {len(post_data.get('title', ''))} символов")
            print(f"Описание: {len(post_data.get('excerpt', ''))} символов")
            print(f"Контент: ~{len(post_data.get('content', '').split())} слов")
            print(f"Время чтения: {post_data.get('read_time', 'не указано')} мин")
            print(f"Категория: {post_data.get('category', 'не указана')}")
            print(f"Теги: {len(post_data.get('tags', []))} шт.")

            # Сохраняем пост в файл
            file_saved = save_to_file(post_data, selected_title)

            # Сохраняем пост в базу данных
            db_saved = False
            if db_available:
                print(f"💾 Сохраняем пост в Supabase [{site_config['name']}]...")
                db_saved = save_post_to_database(post_data, selected_title, env_vars, site_config)
                if db_saved:
                    revalidate_blog_cache(env_vars, site_config)
            else:
                print(f"⚠️ [{site_config['name']}] Supabase недоступен, пост сохранен только в файл")

            # Удаляем использованную тему
            if file_saved:
                updated_titles = remove_title_from_list(titles, selected_title)
                if save_titles_to_file(updated_titles, titles_file):
                    print(f"✅ Тема '{selected_title}' удалена из {titles_file}")
                    show_remaining_titles(updated_titles)
                else:
                    print("❌ Не удалось обновить файл с темами")

            print(f"\n🎯 ИТОГИ [{site_config['name']}]:")
            print(f"📁 Файл: {'✅ Сохранен' if file_saved else '❌ Ошибка'}")
            print(f"🗄️ Supabase: {'✅ Сохранен' if db_saved else '❌ Недоступна' if not db_available else '❌ Ошибка'}")
        else:
            print(f"❌ Ошибка при генерации поста:")
            print(f"📄 Детали: {error}")
            print(f"🔄 Тема '{selected_title}' осталась в списке для повторной попытки")


if __name__ == "__main__":
    main()