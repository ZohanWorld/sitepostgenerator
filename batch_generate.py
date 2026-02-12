#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Пакетная генерация постов о микрофинансах
"""

import time
import json
from simple_main import (
    load_env, load_titles_from_file, save_titles_to_file,
    select_random_title, remove_title_from_list, generate_blog_post,
    create_slug, save_to_file, show_remaining_titles,
    save_post_to_database, validate_post_data, test_database_connection,
    revalidate_blog_cache
)

def batch_generate_posts(count, delay_between_requests=30):
    """
    Генерирует несколько постов подряд с задержкой между запросами
    """
    # Загружаем настройки
    env_vars = load_env()
    api_key = env_vars.get('GPT_API_KEY')
    model_name = env_vars.get('MODEL_NAME', 'gpt-5.2')
    
    if not api_key:
        print("❌ Ошибка: GPT_API_KEY не найден в файле .env")
        return
    
    # Проверяем подключение к БД
    db_available = test_database_connection()
    
    # Загружаем темы
    titles = load_titles_from_file()
    if not titles:
        print("❌ Нет доступных тем для генерации постов")
        return
    
    if count > len(titles):
        print(f"⚠️ Запрошено {count} постов, но доступно только {len(titles)} тем")
        count = len(titles)
    
    print(f"🚀 Пакетная генерация {count} постов")
    print(f"⏱️ Задержка между запросами: {delay_between_requests} секунд")
    print(f"📚 Доступно тем: {len(titles)}")
    print(f"🗄️ Supabase: {'✅ Доступен' if db_available else '❌ Недоступен'}")
    print("=" * 70)
    
    successful_posts = []
    failed_posts = []
    
    for i in range(count):
        print(f"\n🔄 ГЕНЕРАЦИЯ ПОСТА {i+1}/{count}")
        print("-" * 50)
        
        # Выбираем случайную тему
        selected_title = select_random_title(titles)
        if not selected_title:
            print("❌ Не удалось выбрать тему")
            break
        
        print(f"🎯 Тема: '{selected_title}'")
        print(f"⏳ Генерируем пост...")
        
        # Генерируем пост
        post_data, error = generate_blog_post(api_key, selected_title, model_name)
        
        if post_data:
            # Валидируем данные от GPT
            is_valid, validation_errors, post_data = validate_post_data(post_data)
            
            if not is_valid:
                print(f"❌ Пост {i+1} не прошёл валидацию:")
                for err in validation_errors:
                    print(f"   - {err}")
                failed_posts.append({
                    'number': i+1,
                    'title': selected_title,
                    'error': 'Не прошёл валидацию: ' + '; '.join(validation_errors)
                })
                if i < count - 1:
                    time.sleep(delay_between_requests)
                continue
            
            # Автоматически создаем slug, если его нет
            if not post_data.get('slug') or post_data.get('slug').strip() == '':
                post_data['slug'] = create_slug(post_data['title'])
            
            # Сохраняем пост в файл
            file_saved = save_to_file(post_data, selected_title)
            
            # Сохраняем пост в БД
            db_saved = False
            if db_available:
                db_saved = save_post_to_database(post_data, selected_title, env_vars)
            
            if file_saved or db_saved:
                print(f"✅ Пост {i+1} создан (файл: {'✅' if file_saved else '❌'}, БД: {'✅' if db_saved else '❌'})")
                print(f"📄 Заголовок: {post_data.get('title', 'Без заголовка')}")
                print(f"📊 Слов: ~{len(post_data.get('content', '').split())}")
                
                # Удаляем использованную тему
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
        
        # Задержка между запросами (кроме последнего)
        if i < count - 1:
            print(f"⏳ Ожидание {delay_between_requests} секунд до следующего запроса...")
            time.sleep(delay_between_requests)
    
    # Сохраняем обновленный список тем
    save_titles_to_file(titles)
    
    # Ревалидируем кеш один раз после всей пакетной генерации
    if successful_posts and db_available:
        print("\n🔄 Обновляем кеш блога...")
        revalidate_blog_cache(env_vars)
    
    # Выводим итоги
    print("\n" + "=" * 70)
    print("📊 ИТОГИ ПАКЕТНОЙ ГЕНЕРАЦИИ")
    print("=" * 70)
    print(f"✅ Успешно создано постов: {len(successful_posts)}")
    print(f"❌ Ошибок: {len(failed_posts)}")
    
    db_saved_count = sum(1 for p in successful_posts if p.get('db_saved'))
    print(f"🗄️ Сохранено в Supabase: {db_saved_count}/{len(successful_posts)}")
    
    if successful_posts:
        print(f"\n📝 УСПЕШНО СОЗДАННЫЕ ПОСТЫ:")
        for post in successful_posts:
            db_icon = '🗄️' if post.get('db_saved') else '📁'
            print(f"  {db_icon} {post['number']}. {post['post_title']} ({post['word_count']} слов, {post['category']})")
    
    if failed_posts:
        print(f"\n⚠️ ПОСТЫ С ОШИБКАМИ:")
        for post in failed_posts:
            print(f"  {post['number']}. {post['title']} - {post['error']}")
    
    show_remaining_titles(titles)
    
    # Сохраняем отчет
    report = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'total_requested': count,
        'successful': len(successful_posts),
        'failed': len(failed_posts),
        'successful_posts': successful_posts,
        'failed_posts': failed_posts,
        'remaining_titles': len(titles)
    }
    
    report_filename = f"batch_report_{time.strftime('%Y%m%d_%H%M%S')}.json"
    try:
        with open(report_filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Отчет сохранен в файл: {report_filename}")
    except Exception as e:
        print(f"⚠️ Не удалось сохранить отчет: {e}")

def main():
    """
    Главная функция
    """
    print("🔥 ПАКЕТНАЯ ГЕНЕРАЦИЯ ПОСТОВ О МИКРОФИНАНСАХ")
    print("=" * 70)
    
    # Загружаем темы для проверки
    titles = load_titles_from_file()
    if not titles:
        print("❌ Нет доступных тем для генерации")
        return
    
    print(f"📚 Доступно тем: {len(titles)}")
    
    try:
        count = int(input(f"Сколько постов генерировать? (1-{len(titles)}): "))
        if count < 1 or count > len(titles):
            print(f"❌ Количество должно быть от 1 до {len(titles)}")
            return
    except ValueError:
        print("❌ Введите корректное число")
        return
    
    try:
        delay = int(input("Задержка между запросами в секундах (рекомендуется 30): ") or "30")
        if delay < 1:
            delay = 30
    except ValueError:
        delay = 30
    
    # Предупреждение
    estimated_time = (count * (delay + 60)) / 60  # примерно 60 секунд на генерацию + задержка
    print(f"\n⚠️ ВНИМАНИЕ:")
    print(f"Будет сгенерировано {count} постов")
    print(f"Примерное время выполнения: {estimated_time:.1f} минут")
    print(f"Использованные темы будут удалены из файла titles.txt")
    
    confirm = input("\nПродолжить? (y/n): ")
    if confirm.lower() not in ['y', 'yes', 'да', 'д']:
        print("❌ Операция отменена")
        return
    
    # Запускаем пакетную генерацию
    batch_generate_posts(count, delay)

if __name__ == "__main__":
    main() 