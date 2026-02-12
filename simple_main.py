import requests
import json
import os
import re
import random
from datetime import datetime
import uuid
import urllib3

# Допустимые категории (должны совпадать с тем, что ожидает веб-приложение)
ALLOWED_CATEGORIES = [
    'Инструкции', 'Акции', 'Требования', 'Кредитная история',
    'Сравнение', 'Советы', 'Обзоры', 'Личный опыт', 'Юридические'
]

def load_env():
    """
    Простая загрузка переменных из .env файла
    """
    env_vars = {}
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Убираем кавычки из значений
                    value = value.strip('"').strip("'")
                    env_vars[key] = value
    except FileNotFoundError:
        print("❌ Файл .env не найден!")
    return env_vars

def get_supabase_headers(env_vars):
    """
    Возвращает заголовки для Supabase REST API
    """
    service_key = env_vars.get('SUPABASE_SERVICE_ROLE_KEY', '')
    return {
        'apikey': service_key,
        'Authorization': f'Bearer {service_key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }

def get_supabase_url(env_vars):
    """
    Возвращает базовый URL для Supabase REST API
    """
    url = env_vars.get('SUPABASE_URL', env_vars.get('NEXT_PUBLIC_SUPABASE_URL', ''))
    url = url.strip('"').strip("'")
    return f"{url}/rest/v1"

def check_slug_exists(env_vars, slug):
    """
    Проверяет, существует ли пост с таким slug в БД
    """
    base_url = get_supabase_url(env_vars)
    headers = get_supabase_headers(env_vars)
    
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

def make_unique_slug(env_vars, slug):
    """
    Гарантирует уникальность slug, добавляя суффикс -2, -3 и т.д. при необходимости
    """
    if not check_slug_exists(env_vars, slug):
        return slug
    
    counter = 2
    while True:
        new_slug = f"{slug}-{counter}"
        if not check_slug_exists(env_vars, new_slug):
            print(f"⚠️ Slug '{slug}' уже существует, используем '{new_slug}'")
            return new_slug
        counter += 1
        if counter > 100:
            # Крайний случай — добавляем случайный суффикс
            new_slug = f"{slug}-{uuid.uuid4().hex[:6]}"
            return new_slug

def save_post_to_database(post_data, selected_title, env_vars=None):
    """
    Сохраняет пост в таблицу blog_posts через Supabase REST API
    """
    if env_vars is None:
        env_vars = load_env()
    
    base_url = get_supabase_url(env_vars)
    headers = get_supabase_headers(env_vars)
    
    if not base_url or base_url.endswith('/rest/v1'):
        supabase_url = env_vars.get('SUPABASE_URL', env_vars.get('NEXT_PUBLIC_SUPABASE_URL', ''))
        if not supabase_url:
            print("❌ SUPABASE_URL не найден в .env")
            return False
    
    # Генерируем уникальный UUID
    post_id = str(uuid.uuid4())
    
    # Текущее время в ISO формате
    now = datetime.now().isoformat()
    
    # Гарантируем уникальность slug
    slug = post_data.get('slug', '')
    slug = make_unique_slug(env_vars, slug)
    
    # Подготавливаем данные для вставки
    payload = {
        "id": post_id,
        "title": post_data.get('title', ''),
        "slug": slug,
        "excerpt": post_data.get('excerpt', ''),
        "content": post_data.get('content', ''),
        "category": post_data.get('category', ''),
        "tags": post_data.get('tags', []),
        "author": post_data.get('author', 'Редакция МФО Витрина'),
        "published_at": now,
        "updated_at": now,
        "is_published": True,
        "read_time": post_data.get('read_time', 5),
        "meta_title": post_data.get('meta_title', ''),
        "meta_description": post_data.get('meta_description', ''),
        "seo_keywords": post_data.get('seo_keywords', []),
        "created_at": now
    }
    
    try:
        response = requests.post(
            f"{base_url}/blog_posts",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            print(f"✅ Пост добавлен в базу данных с ID: {post_id}")
            return True
        else:
            print(f"❌ Ошибка при сохранении в БД: {response.status_code} — {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка при сохранении в базу данных: {e}")
        return False

def revalidate_blog_cache(env_vars):
    """
    Вызывает ревалидацию кеша Next.js для страниц блога
    """
    revalidate_secret = env_vars.get('REVALIDATE_SECRET', '')
    site_url = env_vars.get('SITE_URL', 'http://localhost:3000')
    
    if not revalidate_secret:
        print("⚠️ REVALIDATE_SECRET не задан — кеш обновится автоматически через 30 минут")
        return
    
    try:
        response = requests.post(
            f"{site_url}/api/revalidate",
            json={"secret": revalidate_secret, "path": "/blog"},
            timeout=10
        )
        if response.status_code == 200:
            print("🔄 Кеш блога обновлён")
        else:
            print(f"⚠️ Ревалидация не удалась: {response.status_code}")
    except Exception:
        print("⚠️ Не удалось обновить кеш (сайт недоступен?)")

def test_database_connection():
    """
    Проверяет подключение к Supabase
    """
    print("🔍 Проверяем подключение к Supabase...")
    env_vars = load_env()
    base_url = get_supabase_url(env_vars)
    headers = get_supabase_headers(env_vars)
    
    try:
        response = requests.get(
            f"{base_url}/blog_posts?select=id&limit=1",
            headers=headers,
            timeout=10
        )
        if response.status_code == 200:
            print("✅ Подключение к Supabase успешно")
            return True
        else:
            print(f"❌ Ошибка подключения: {response.status_code} — {response.text}")
            return False
    except Exception as e:
        print(f"❌ Ошибка при проверке подключения: {e}")
        return False

def load_titles_from_file(filename="titles.txt"):
    """
    Загружает список тем из файла
    """
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
    """
    Сохраняет обновленный список тем в файл
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            for title in titles:
                f.write(title + '\n')
        return True
    except Exception as e:
        print(f"❌ Ошибка при сохранении файла {filename}: {e}")
        return False

def select_random_title(titles):
    """
    Выбирает случайную тему из списка
    """
    if not titles:
        return None
    return random.choice(titles)

def remove_title_from_list(titles, title_to_remove):
    """
    Удаляет использованную тему из списка
    """
    try:
        titles.remove(title_to_remove)
        return titles
    except ValueError:
        print(f"⚠️ Тема '{title_to_remove}' не найдена в списке")
        return titles

def validate_post_data(post_data):
    """
    Валидирует данные поста от GPT. Возвращает (is_valid, errors, fixed_data).
    Автоматически исправляет мелкие проблемы.
    """
    errors = []
    fixed = dict(post_data)  # копия для исправлений
    
    # Проверяем обязательные поля
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
    if category not in ALLOWED_CATEGORIES:
        # Пытаемся найти ближайшую
        best_match = None
        for allowed in ALLOWED_CATEGORIES:
            if allowed.lower() in category.lower() or category.lower() in allowed.lower():
                best_match = allowed
                break
        if best_match:
            fixed['category'] = best_match
            print(f"⚠️ Категория '{category}' заменена на '{best_match}'")
        else:
            fixed['category'] = 'Советы'  # дефолтная категория
            print(f"⚠️ Неизвестная категория '{category}', установлена 'Советы'")
    
    # Проверяем tags — должен быть список строк
    tags = fixed.get('tags', [])
    if isinstance(tags, str):
        fixed['tags'] = [t.strip() for t in tags.split(',') if t.strip()]
    elif not isinstance(tags, list):
        fixed['tags'] = []
    
    # Проверяем seo_keywords — должен быть список строк
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
    
    # Проверяем длину контента (предупреждение)
    word_count = len(fixed.get('content', '').split())
    if word_count < 500:
        print(f"⚠️ Контент слишком короткий: {word_count} слов (ожидается 2000+)")
    
    return True, errors, fixed

def generate_blog_post(api_key, selected_title, model_name="gpt-5.2"):
    """
    Генерирует пост для блога о микрофинансах на конкретную тему через ChatGPT API
    """
    
    current_year = 2026
    
    # Улучшенный промпт
    prompt = f"""
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
  "category": "СТРОГО одна из: Инструкции | Советы | Сравнение | Обзоры | Кредитная история | Юридические | Личный опыт",
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

    # Подготавливаем данные для запроса
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    data = {
        "model": model_name,
        "messages": [
            {
                "role": "system", 
                "content": f"Ты — опытный финансовый журналист и SEO-копирайтер, специализирующийся на микрофинансовом рынке России. Ты пишешь глубокие, экспертные статьи для блога 'МФО Витрина'. Твои тексты читаются как статьи в РБК или Банки.ру — с конкретикой, цифрами и практической пользой. Текущий год: {current_year}. Всегда отвечай ТОЛЬКО валидным JSON без обёрток и комментариев."
            },
            {
                "role": "user", 
                "content": prompt
            }
        ],
        "max_completion_tokens": 16000,
        "temperature": 0.7
    }
    
    try:
        # Отключаем предупреждения SSL
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Создаем сессию с настройками SSL
        session = requests.Session()
        session.verify = True
        
        # Настройки ретраев
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.packages.urllib3.util.retry.Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[500, 502, 503, 504]
            )
        )
        session.mount('https://', adapter)
        
        print("🔄 Отправляем запрос к OpenAI API...")
        
        # Отправляем запрос к OpenAI API
        response = session.post(
            'https://api.openai.com/v1/chat/completions',
            headers=headers,
            json=data,
            timeout=300  # 5 минут для длинных постов
        )
        
        if response.status_code == 200:
            response_data = response.json()
            content = response_data['choices'][0]['message']['content'].strip()
            
            # Пытаемся парсить JSON
            try:
                post_data = json.loads(content)
                return post_data, None
            except json.JSONDecodeError:
                # Если JSON некорректен, пытаемся его починить
                print("⚠️ Ошибка парсинга JSON, пытаемся починить...")
                try:
                    # Удаляем возможные префиксы/суффиксы (```json ... ```)
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
                
        except Exception as fallback_error:
            return None, f"SSL ошибка и fallback не сработал: {e} -> {fallback_error}"
            
    except requests.exceptions.RequestException as e:
        return None, f"Ошибка запроса: {e}"
    except Exception as e:
        return None, f"Неожиданная ошибка: {e}"

def create_slug(title):
    """
    Создает URL-friendly slug из заголовка
    """
    # Транслитерация
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
    
    # Удаляем специальные символы и заменяем пробелы на дефисы
    slug = re.sub(r'[^a-zA-Z0-9\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    
    return slug

def save_to_file(post_data, selected_title, filename_prefix="generated_post"):
    """
    Сохраняет сгенерированный пост в файл с уникальным именем
    """
    try:
        # Создаем безопасное имя файла
        safe_title = re.sub(r'[^\w\s-]', '', selected_title.replace('?', '').replace(':', ''))
        safe_title = re.sub(r'\s+', '_', safe_title)[:50]  # Ограничиваем длину
        
        filename = f"{filename_prefix}_{safe_title}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(post_data, f, ensure_ascii=False, indent=2)
        print(f"✅ Пост сохранен в файл: {filename}")
        return True
    except Exception as e:
        print(f"❌ Ошибка при сохранении в файл: {e}")
        return False

def show_remaining_titles(titles):
    """
    Показывает статистику оставшихся тем
    """
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

def main():
    """
    Основная функция
    """
    print("🚀 Генератор постов о микрофинансах v3.0")
    print("=" * 60)
    
    # Загружаем переменные окружения
    env_vars = load_env()
    
    # Проверяем подключение к Supabase
    db_available = test_database_connection()
    
    api_key = env_vars.get('GPT_API_KEY')
    model_name = env_vars.get('MODEL_NAME', 'gpt-5.2')
    
    if not api_key:
        print("❌ Ошибка: GPT_API_KEY не найден в файле .env")
        return
    
    # Загружаем список тем
    titles = load_titles_from_file()
    if not titles:
        print("❌ Нет доступных тем для генерации постов")
        return
    
    print(f"📚 Загружено тем: {len(titles)}")
    
    # Выбираем случайную тему
    selected_title = select_random_title(titles)
    print(f"🎯 Выбранная тема: '{selected_title}'")
    print(f"🔑 Используем модель: {model_name}")
    print("🔄 Генерируем пост...")
    print("=" * 60)
    
    # Генерируем пост на выбранную тему
    post_data, error = generate_blog_post(api_key, selected_title, model_name)
    
    if post_data:
        # Валидируем данные от GPT
        is_valid, validation_errors, post_data = validate_post_data(post_data)
        
        if not is_valid:
            print(f"❌ Данные от GPT не прошли валидацию:")
            for err in validation_errors:
                print(f"   - {err}")
            print(f"🔄 Тема '{selected_title}' осталась в списке для повторной попытки")
            return
        
        # Автоматически создаем slug, если его нет или он пустой
        if not post_data.get('slug') or post_data.get('slug').strip() == '':
            post_data['slug'] = create_slug(post_data['title'])
        
        # Выводим результат в консоль
        print("\n✅ Пост успешно сгенерирован и провалидирован!")
        print(f"📖 На тему: '{selected_title}'")
        print("\n📝 РЕЗУЛЬТАТ:")
        print("=" * 60)
        print(json.dumps(post_data, ensure_ascii=False, indent=2))
        print("=" * 60)
        
        # Дополнительная информация
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
            print("💾 Сохраняем пост в Supabase...")
            db_saved = save_post_to_database(post_data, selected_title, env_vars)
            
            # Ревалидируем кеш если пост сохранён
            if db_saved:
                revalidate_blog_cache(env_vars)
        else:
            print("⚠️ Supabase недоступен, пост сохранен только в файл")
        
        # Удаляем использованную тему из списка только если все прошло успешно
        if file_saved:
            updated_titles = remove_title_from_list(titles, selected_title)
            
            if save_titles_to_file(updated_titles):
                print(f"✅ Тема '{selected_title}' удалена из списка")
                show_remaining_titles(updated_titles)
            else:
                print("❌ Не удалось обновить файл с темами")
        
        # Итоговый статус
        print(f"\n🎯 ИТОГИ СОХРАНЕНИЯ:")
        print(f"📁 Файл: {'✅ Сохранен' if file_saved else '❌ Ошибка'}")
        print(f"🗄️ Supabase: {'✅ Сохранен' if db_saved else '❌ Недоступна' if not db_available else '❌ Ошибка'}")
        
    else:
        print(f"❌ Ошибка при генерации поста:")
        print(f"📄 Детали: {error}")
        print(f"🔄 Тема '{selected_title}' осталась в списке для повторной попытки")

if __name__ == "__main__":
    main()