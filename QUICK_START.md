# ⚡ Быстрый Старт

## Локально (рекомендуется для разработки)

### 1️⃣ Подготовка

```bash
# Создайте .env файл
cp .env.example .env

# Отредактируйте .env и вставьте:
# - BOT_TOKEN (получить у @BotFather)
# - ADMIN_ID (узнать у @userinfobot)
```

### 2️⃣ Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Запустите (откройте этот терминал, не закрывайте)
python main.py
```

### 3️⃣ Frontend

```bash
# В новом терминале
cd frontend
npm install
npm start
```

✅ Backend: http://127.0.0.1:8000
✅ Frontend: http://127.0.0.1:3000

### 4️⃣ Тестирование

**В Telegram:**
1. Найдите вашего бота
2. Отправьте `/start`
3. Нажмите кнопку "Открыть приложение"

## Docker (вся система в одной команде)

```bash
# Убедитесь что Docker установлен и .env заполнен
docker-compose up

# Стоп
docker-compose down

# Пересобрать образы
docker-compose up --build
```

✅ Backend: http://localhost:8000
✅ Frontend: http://localhost:3000

## Что дальше?

### Добавить Google Calendar

1. Google Cloud Console → Создать проект
2. Enable Google Calendar API
3. Скачать credentials.json → поместить в `backend/`
4. Реализовать синхронизацию в `backend/modules/calendar/services.py`

### Добавить новый модуль

```python
# 1. Создайте backend/modules/my_feature/
# 2. Добавьте models.py, services.py, router.py
# 3. Зарегистрируйте router в backend/main.py
# 4. Создайте компонент в frontend/src/components/
```

### Развернуть в сеть

**Railway** (самый простой):
```bash
git push  # автоматическое развертывание
```

**VPS**:
```bash
# SSH на сервер
ssh user@your.server.com

# Клонируйте проект
git clone <repo>
cd theater-bot

# Запустите через supervisor
```

## Структура

```
backend/           — Python API и логика
├── main.py       — Entry point
├── modules/      — Календарь, опросы, уведомления
└── core/         — БД, безопасность

frontend/          — React приложение
├── src/
│   ├── App.js
│   └── components/  — Календарь, опросы, уведомления
└── public/         — Static файлы
```

## FAQ

**Q: Не работает бот**
- Проверьте BOT_TOKEN в .env
- Убедитесь что backend работает: curl http://127.0.0.1:8000

**Q: Не работает frontend**
- npm install прошла успешно? Есть node_modules/
- Port 3000 свободен? sudo lsof -i :3000

**Q: Как обновить зависимости**
```bash
# Backend
pip install --upgrade -r requirements.txt

# Frontend
npm update
```

**Q: Где логи?**
- Backend: консоль где запустили python main.py
- Frontend: DevTools браузера (F12)
- Docker: docker-compose logs -f backend
