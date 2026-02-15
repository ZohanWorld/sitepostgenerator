#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Пакетная генерация постов — мультисайт
"""

import time
import json
from simple_main import (
    load_env, load_titles_from_file, save_titles_to_file,
    select_random_title, remove_title_from_list, generate_blog_post,
    create_slug, save_to_file, show_remaining_titles,
    save_post_to_database, validate_post_data, test_database_connection,
    revalidate_blog_cache, select_site, SITE_CONFIGS
)

def batch_generate_posts(count, delay_between_requests=30, site_ids=None):
    """Генерирует несколько постов подряд для указанных сайтов"""
    env_vars = load_env()
    api_key = env_vars.get('GPT_API_KEY')
    model_name = env_vars.get('MODEL_NAME', 'gpt-5.2')

    if not api_key:
        print("❌ Ошибка: GPT_API_KEY не найден в файле .env")
        return

    if site_ids is None:
        site_ids = ['mfo']

    for site_id in site_ids:
        site_config = SITE_CONFIGS[site_id]
        titles_file = site_config['titles_file']

        print(f"\n{'='*70}")
        print(f"🌐 ПАКЕТНАЯ ГЕНЕРАЦИЯ ДЛЯ: {site_config['name']}")
        print(f"{'='*70}")

        # Проверяем подключение к БД
        db_available = test_database_connection(env_vars, site_config)

        # Загружаем темы
        titles = load_titles_from_file(titles_file)
        if not titles:
            print(f"❌ Нет доступных тем в {titles_file}")
            continue

        actual_count = min(count, len(titles))
        if actual_count < count:
            print(f"⚠️ Запрошено {count} постов, но доступно только {len(titles)} тем")

        print(f"🚀 Генерация {actual_count} постов для {site_config['name']}")
        print(f"⏱️ Задержка: {delay_between_requests} сек")
        print(f"📚 Доступно тем: {len(titles)}")
        print(f"🗄️ Supabase: {'✅ Доступен' if db_available else '❌ Недоступен'}")
        print("=" * 70)

        successful_posts = []
        failed_posts = []

        for i in range(actual_count):
            print(f"\n🔄 [{site_config['name']}] ГЕНЕРАЦИЯ ПОСТА {i+1}/{actual_count}")
            print("-" * 50)

            selected_title = select_random_title(titles)
            if not selected_title:
                print("❌ Не удалось выбрать тему")
                break

            print(f"🎯 Тема: '{selected_title}'")
            print(f"⏳ Генерируем пост...")

            post_data, error = generate_blog_post(api_key, selected_title, model_name, site_id)

            if post_data:
                is_valid, validation_errors, post_data = validate_post_data(post_data, site_config)

                if not is_valid:
                    print(f"❌ Пост {i+1} не прошёл валидацию:")
                    for err in validation_errors:
                        print(f"   - {err}")
                    failed_posts.append({
                        'number': i+1,
                        'title': selected_title,
                        'error': 'Не прошёл валидацию: ' + '; '.join(validation_errors)
                    })
                    if i < actual_count - 1:
                        time.sleep(delay_between_requests)
                    continue

                if not post_data.get('slug') or post_data.get('slug').strip() == '':
                    post_data['slug'] = create_slug(post_data['title'])

                file_saved = save_to_file(post_data, selected_title)

                db_saved = False
                if db_available:
                    db_saved = save_post_to_database(post_data, selected_title, env_vars, site_config)

                if file_saved or db_saved:
                    print(f"✅ Пост {i+1} создан (файл: {'✅' if file_saved else '❌'}, БД: {'✅' if db_saved else '❌'})")
                    print(f"📄 Заголовок: {post_data.get('title', 'Без заголовка')}")
                    print(f"📊 Слов: ~{len(post_data.get('content', '').split())}")

                    titles = remove_title_from_list(titles, selected_title)
                    successful_posts.append({
                        'number': i+1,
                        'title': selected_title,
                        'post_title': post_data.get('title'),
                        'word_count': len(post_data.get('content', '').split()),
                        'category': post_data.get('category'),
                        'db_saved': db_saved
                    })
                else:
                    print(f"❌ Ошибка при сохранении поста {i+1}")
                    failed_posts.append({
                        'number': i+1,
                        'title': selected_title,
                        'error': 'Ошибка сохранения'
                    })
            else:
                print(f"❌ Ошибка при генерации поста {i+1}: {error}")
                failed_posts.append({
                    'number': i+1,
                    'title': selected_title,
                    'error': error
                })

            if i < actual_count - 1:
                print(f"⏳ Ожидание {delay_between_requests} секунд...")
                time.sleep(delay_between_requests)

        # Сохраняем обновлённый список тем
        save_titles_to_file(titles, titles_file)

        # Ревалидируем кеш
        if successful_posts and db_available:
            print(f"\n🔄 [{site_config['name']}] Обновляем кеш блога...")
            revalidate_blog_cache(env_vars, site_config)

        # Итоги
        print(f"\n{'='*70}")
        print(f"📊 ИТОГИ [{site_config['name']}]")
        print(f"{'='*70}")
        print(f"✅ Успешно: {len(successful_posts)}")
        print(f"❌ Ошибок: {len(failed_posts)}")

        db_saved_count = sum(1 for p in successful_posts if p.get('db_saved'))
        print(f"🗄️ В Supabase: {db_saved_count}/{len(successful_posts)}")

        if successful_posts:
            print(f"\n📝 СОЗДАННЫЕ ПОСТЫ:")
            for post in successful_posts:
                db_icon = '🗄️' if post.get('db_saved') else '📁'
                print(f"  {db_icon} {post['number']}. {post['post_title']} ({post['word_count']} слов, {post['category']})")

        if failed_posts:
            print(f"\n⚠️ ОШИБКИ:")
            for post in failed_posts:
                print(f"  {post['number']}. {post['title']} — {post['error']}")

        show_remaining_titles(titles)

        # Сохраняем отчёт
        report = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'site': site_config['name'],
            'total_requested': actual_count,
            'successful': len(successful_posts),
            'failed': len(failed_posts),
            'successful_posts': successful_posts,
            'failed_posts': failed_posts,
            'remaining_titles': len(titles)
        }
        report_filename = f"batch_report_{site_id}_{time.strftime('%Y%m%d_%H%M%S')}.json"
        try:
            with open(report_filename, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"\n💾 Отчёт: {report_filename}")
        except Exception as e:
            print(f"⚠️ Не удалось сохранить отчёт: {e}")


def main():
    """Главная функция"""
    print("🔥 ПАКЕТНАЯ ГЕНЕРАЦИЯ ПОСТОВ (мультисайт)")
    print("=" * 70)

    # Выбираем сайт
    site_ids = select_site()

    # Проверяем доступность тем для каждого сайта
    for site_id in site_ids:
        titles_file = SITE_CONFIGS[site_id]['titles_file']
        titles = load_titles_from_file(titles_file)
        print(f"📚 [{SITE_CONFIGS[site_id]['name']}] Тем: {len(titles)}")

    try:
        count = int(input(f"\nСколько постов генерировать (на каждый сайт)? "))
        if count < 1:
            print("❌ Количество должно быть ≥ 1")
            return
    except ValueError:
        print("❌ Введите корректное число")
        return

    try:
        delay = int(input("Задержка между запросами (сек, рекомендуется 30): ") or "30")
        if delay < 1:
            delay = 30
    except ValueError:
        delay = 30

    estimated_time = (count * len(site_ids) * (delay + 60)) / 60
    print(f"\n⚠️ Будет сгенерировано {count} постов × {len(site_ids)} сайт(ов)")
    print(f"⏱️ Примерное время: {estimated_time:.1f} минут")

    confirm = input("\nПродолжить? (y/n): ")
    if confirm.lower() not in ['y', 'yes', 'да', 'д']:
        print("❌ Операция отменена")
        return

    batch_generate_posts(count, delay, site_ids)


if __name__ == "__main__":
    main()