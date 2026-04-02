# 🎭 Театральная Студия — Telegram Mini App

Полнофункциональное приложение для управления театральной студией через Telegram.

## 🚀 Возможности

- **📅 Календарь репетиций** — синхронизация с Google Calendar
- **🗳️ Опросы** — быстрые опросы о посещении занятий
- **🔔 Система уведомлений** — напоминания о платежах, занятиях, опросах
- **⚙️ Модульная архитектура** — легко добавлять новые функции

## 🏗️ Архитектура

### Backend (Python)
- **FastAPI** — REST API
- **SQLAlchemy** — ORM
- **aiogram** — Telegram Bot
- **SQLite** — БД для разработки

### Frontend (React)
- **Telegram Mini App** — встраивается в Telegram
- **React 18** — UI
- **Axios** — HTTP клиент

### Модули
```
backend/modules/
├── calendar/     # Google Calendar интеграция
├── polling/      # Система опросов
└── notifications/  # Уведомления и напоминания
```

Каждый модуль содержит:
- `models.py` — SQLAlchemy модели
- `services.py` — бизнес-логика
- `router.py` — FastAPI endpoints

## 📦 Установка

### Требования
- Python 3.9+
- Node.js 16+
- Docker (опционально)

### Локальная разработка

**1. Клонируйте репо и создайте окружение:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**2. Создайте `.env` файл:**
```bash
cp .env.example .env
```

**3. Заполните переменные:**
```env
BOT_TOKEN=YOUR_TOKEN_FROM_BOTFATHER
ADMIN_ID=YOUR_TELEGRAM_ID
API_PORT=8000
```

**4. Запустите backend:**
```bash
python main.py
```

**5. В новом терминале запустите frontend:**
```bash
cd frontend
npm install
npm start
```

### Docker

```bash
# Создайте .env в корне проекта
cp backend/.env.example .env

# Запустите
docker-compose up
```

Backend будет доступен на `http://localhost:8000`
Frontend на `http://localhost:3000`

## 📚 API Endpoints

### Календарь
- `GET /api/calendar/events?days=30` — получить события
- `GET /api/calendar/events/next` — следующее событие
- `POST /api/calendar/sync` — синхронизировать с Google Calendar

### Опросы
- `POST /api/polls/create` — создать опрос
- `GET /api/polls/{poll_id}` — результаты опроса
- `POST /api/polls/{poll_id}/vote` — проголосовать
- `GET /api/polls/` — активные опросы

### Уведомления
- `GET /api/notifications/settings?user_id=123` — настройки пользователя
- `POST /api/notifications/settings?user_id=123` — обновить настройки

## 🔌 Как добавить новый модуль

**1. Создайте папку в `backend/modules/`:**
```
backend/modules/my_feature/
├── __init__.py
├── models.py       # Модели БД
├── services.py     # Бизнес-логика
└── router.py       # API endpoints
```

**2. Напишите модели:**
```python
# models.py
from sqlalchemy import Column, String, Integer
from core.database import Base

class MyModel(Base):
    __tablename__ = "my_table"
    id = Column(Integer, primary_key=True)
    name = Column(String)
```

**3. Напишите сервис:**
```python
# services.py
class MyService:
    def __init__(self, db):
        self.db = db
    
    def get_something(self):
        return self.db.query(MyModel).all()
```

**4. Создайте API endpoints:**
```python
# router.py
from fastapi import APIRouter
from core.database import get_db

router = APIRouter(prefix="/api/my_feature", tags=["my_feature"])

@router.get("/")
async def get_data(db = Depends(get_db)):
    service = MyService(db)
    return {"data": service.get_something()}
```

**5. Зарегистрируйте маршрут в `backend/main.py`:**
```python
from modules.my_feature.router import router as my_feature_router
app.include_router(my_feature_router)
```

**6. Добавьте компонент в frontend:**
```javascript
// frontend/src/components/MyFeatureView.js
function MyFeatureView() {
  return <div>My Feature</div>;
}
```

## 🔐 Интеграция Google Calendar

1. Создайте Google Cloud Project
2. Включите Google Calendar API
3. Скачайте `credentials.json`
4. Поместите в `backend/credentials.json`
5. Реализуйте `CalendarService.sync_from_google()` через Google API client

## 🚢 Развертывание

### Railway
```bash
git push  # Railway auto-deploys при push
```

### Heroku (старая конфигурация)
```bash
heroku create your-app-name
git push heroku main
```

### VPS
```bash
# Установите supervisor для фонового запуска
sudo apt-get install supervisor

# Создайте конфиг supervisor
# /etc/supervisor/conf.d/theater-bot.conf
[program:theater-bot]
command=/path/to/venv/bin/python /path/to/main.py
autorestart=true
```

## 📝 Структура файлов

```
.
├── backend/
│   ├── main.py              # Entry point
│   ├── config.py            # Конфигурация
│   ├── requirements.txt      # Зависимости
│   ├── core/
│   │   ├── database.py      # SQLAlchemy
│   │   └── security.py      # JWT токены
│   └── modules/
│       ├── calendar/
│       ├── polling/
│       └── notifications/
├── frontend/
│   ├── package.json
│   ├── public/
│   └── src/
│       ├── App.js
│       ├── components/
│       │   ├── CalendarView.js
│       │   ├── PollingView.js
│       │   └── NotificationsView.js
│       └── api/
│           └── client.js
└── docker-compose.yml
```

## 🐛 Debugging

Backend logs:
```bash
python main.py  # logs выводятся в консоль
```

Frontend:
```bash
npm start  # открыть DevTools в браузере
```

## 📞 Помощь

Если что-то не работает:
1. Проверьте переменные в `.env`
2. Убедитесь что ports свободны (8000, 3000)
3. Очистите кэш: `npm cache clean --force` (frontend)
4. Удалите БД: `rm theater_bot.db` и перезапустите

## 📄 Лицензия

MIT
