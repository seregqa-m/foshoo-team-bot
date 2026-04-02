# 🔧 Настройка Google Calendar

Интеграция использует Service Account для безопасного доступа к вашему Google Calendar. Это значит, что боту не требуется интерактивная авторизация пользователя.

## Пошаговая инструкция

### 1️⃣ Создание Google Cloud Project

1. Откройте [Google Cloud Console](https://console.cloud.google.com/)
2. В левом верхнем углу нажмите на выпадающее меню (рядом с "Google Cloud")
3. Нажмите **"Создать проект"**
4. Введите название: `Theater Studio Bot`
5. Нажмите **"Создать"**
6. Подождите, пока проект создастся (может занять минуту)

### 2️⃣ Включение Google Calendar API

1. В левой панели найдите **"APIs & Services"** → **"Library"**
2. В поле поиска введите `Google Calendar API`
3. Нажмите на **Google Calendar API**
4. Нажмите кнопку **"Enable"** (Включить)
5. Подождите несколько секунд

### 3️⃣ Создание Service Account

1. В левой панели выберите **"APIs & Services"** → **"Credentials"**
2. Нажмите кнопку **"+ Create Credentials"** (Создать учётные данные)
3. Выберите **"Service Account"**
4. Заполните форму:
   - **Service account name**: `Theater Bot`
   - **Service account ID**: `theater-bot` (будет заполнено автоматически)
   - Нажмите **"Create and Continue"**
5. На странице "Grant this service account access to project":
   - Нажмите **"Continue"** (пропустить)
6. На финальной странице нажмите **"Done"**

### 4️⃣ Скачивание JSON ключа

1. В левой панели выберите **"APIs & Services"** → **"Credentials"**
2. В разделе "Service Accounts" нажмите на только что созданный сервисный аккаунт
3. В верхней панели перейдите на вкладку **"Keys"** (Ключи)
4. Нажмите **"Add Key"** → **"Create new key"**
5. Выберите **"JSON"**
6. Нажмите **"Create"**
7. JSON файл автоматически скачается на ваш компьютер

### 5️⃣ Добавление JSON файла в проект

1. Переименуйте скачанный файл в `credentials.json`
2. Поместите его в папку `backend/` вашего проекта:
   ```
   theater-bot/
   ├── backend/
   │   ├── credentials.json  ← положить сюда
   │   ├── main.py
   │   └── ...
   ```

### 6️⃣ Получение Calendar ID

1. Откройте [Google Calendar](https://calendar.google.com/)
2. В левой панели найдите ваш календарь (или создайте новый)
3. Нажмите на три точки рядом с названием календаря
4. Выберите **"Settings"** (Настройки)
5. Скопируйте **Calendar ID** (обычно похож на `abc123xyz@group.calendar.google.com`)

### 7️⃣ Дать доступ сервисному аккаунту

1. В Google Calendar нажмите на три точки рядом с календарём
2. Выберите **"Settings"** (Настройки)
3. Нажмите на вкладку **"Share with specific people"** (Поделиться с конкретными людьми)
4. Нажмите **"Share"** (Поделиться)
5. В поле электронной почты вставьте email сервисного аккаунта
   - Этот email можно найти в `credentials.json` - поле `client_email`
6. Дайте права **"Editor"** (Редактор)
7. Нажмите **"Share"** (Поделиться)

### 8️⃣ Обновление .env

1. Откройте файл `.env` в корне проекта
2. Найдите строки:
   ```
   GOOGLE_CALENDAR_JSON=backend/credentials.json
   GOOGLE_CALENDAR_ID=your_calendar_id@group.calendar.google.com
   SYNC_INTERVAL_MINUTES=15
   ```
3. Обновите `GOOGLE_CALENDAR_ID` на ID вашего календаря (скопировали на шаге 6)
4. Остальные значения обычно не нужно менять

## Проверка

После настройки:

```bash
# Запустите backend
cd backend
python main.py
```

В логах должно появиться:
```
✅ Google Calendar client initialized
✅ Calendar sync completed: N events
```

Если вы видите ошибки — проверьте:
1. Файл `backend/credentials.json` существует
2. `GOOGLE_CALENDAR_ID` заполнен правильно
3. Сервисный аккаунт имеет доступ к календарю

## Безопасность

⚠️ **Важно:**
- `credentials.json` содержит приватные ключи — **не коммитьте его в git!**
- Файл уже в `.gitignore`, но проверьте
- Если случайно выложили ключ — удалите его в Google Cloud Console и создайте новый

## Для продакшена

На production сервере:
1. Создайте отдельный Google Project
2. Скачайте новый credentials.json
3. Поместите его на сервер способом, безопасным для вашей инфраструктуры (например, через env переменные в Docker)

## Проблемы и решения

**Q: События не синхронизируются**
- Проверьте в консоли Google Cloud что Calendar API включен
- Убедитесь что сервисный аккаунт имеет доступ к календарю

**Q: "Permission denied" ошибка**
- Перейдите в настройки календаря и заново поделитесь доступом с сервисным аккаунтом

**Q: Как часто синхронизируется календарь?**
- По умолчанию каждые 15 минут
- Можно изменить в `.env`: `SYNC_INTERVAL_MINUTES=5`

**Q: Можно ли вручную синхронизировать?**
- Да! В приложении есть кнопка 🔄 "Синхронизировать"
- Или через API: `curl -X POST http://127.0.0.1:8000/api/calendar/sync`
