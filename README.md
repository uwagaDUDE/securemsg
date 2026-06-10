# SecureMsg

Защищённый мессенджер с end-to-end шифрованием. Telegram-like UI, AES-256-GCM + RSA-2048, real-time через Socket.IO.

## Стек

| Слой | Технологии |
|---|---|
| **Backend** | Python 3.12 · FastAPI · Socket.IO · SQLAlchemy (async) · SQLite · Alembic |
| **Frontend** | React 19 · Vite · Zustand · i18next (EN/RU) · Web Crypto API |
| **Инфраструктура** | Docker · nginx (SSL-терминация) · Redis (rate limiting) |

## Быстрый старт

### Docker (рекомендуется)

```bash
# Первый запуск — собрать все образы
docker compose build

# Запустить
docker compose up
```

- **HTTPS**: https://localhost:8443
- **HTTP** → редирект на HTTPS: http://localhost:8080

При изменении фронтенда нужна пересборка nginx:

```bash
docker compose build nginx && docker compose up
```

### Без Docker

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
# или: source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt

# Сборка фронтенда
cd frontend && npm install && npm run build && cd ..

python run.py
```

## Архитектура

```
                  ┌─────────────────────────────┐
  HTTPS :8443 ───►│           nginx             │
  HTTP  :8080 ───►│  (SSL-терминация, статика)  │
                  └────────────┬────────────────┘
                               │ proxy_pass
                  ┌────────────▼────────────────┐
                  │        backend :8111         │
                  │  FastAPI + Socket.IO (ASGI)  │
                  └──────┬───────────┬───────────┘
                         │           │
              ┌──────────▼──┐  ┌─────▼──────┐
              │   SQLite    │  │   Redis    │
              │  (данные)   │  │ (rate limit│
              └─────────────┘  └────────────┘
```

### Структура репозитория

```
securemsg/
├── backend/
│   ├── app/
│   │   ├── main.py           — FastAPI + lifespan
│   │   ├── models.py         — SQLAlchemy модели
│   │   ├── schemas.py        — Pydantic схемы
│   │   ├── auth.py           — JWT, bcrypt
│   │   ├── database.py       — async engine, Alembic runner
│   │   ├── ratelimit.py      — Redis/in-memory rate limiter
│   │   ├── socketio.py       — Socket.IO события
│   │   ├── logging_config.py — structlog
│   │   ├── metrics.py        — Prometheus
│   │   └── routers/          — auth, messages, users, groups,
│   │                           channels, attachments, push, blocks,
│   │                           permissions, key_verification
│   └── alembic/              — миграции БД
├── frontend/
│   └── src/
│       ├── components/       — React компоненты (страницы, layout, чат, модалки)
│       ├── context/          — Auth, Socket, Chat, QueryProvider
│       ├── utils/            — crypto.js, api.js, helpers.js, ...
│       └── locale/           — en.json, ru.json
├── nginx/
│   ├── Dockerfile            — multi-stage: Node → nginx
│   └── default.conf          — proxy_pass + WebSocket + SSL
├── docker-compose.yml
├── requirements.txt          — Python зависимости
└── .env                      — авто-генерируемые секреты
```

## Шифрование

| Что | Алгоритм |
|---|---|
| Сообщения | AES-256-GCM (IV 12 байт, prepended) |
| Обмен ключами | RSA-2048 OAEP + SHA-256 |
| Приватный ключ на сервере | PBKDF2-SHA256 (600k итераций) + AES-256-GCM |
| Верификация ключей | SAS (6-значный код SHA-256 от публичных ключей обоих) |

Шифрование и дешифрование происходит **только на клиенте** через Web Crypto API. Сервер хранит только зашифрованные блобы.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:////data/messenger.db` | Путь к БД |
| `REDIS_URL` | `redis://redis:6379/0` | Redis для rate limiting |
| `ALLOWED_ORIGINS` | `https://localhost:8443` | CORS origins |
| `JWT_SECRET` | авто-генерация | Секрет подписи токенов |
| `VAPID_PRIVATE_KEY` | авто-генерация | Приватный ключ Web Push |
| `VAPID_PUBLIC_KEY` | авто-генерация | Публичный ключ Web Push |

Секреты сохраняются в `.env` при первом запуске и сохраняются через Docker volume.

## Тесты

```bash
pytest -v
pytest tests/test_api.py -v
pytest tests/test_socket.py -v
```

## Фичи

- Личные зашифрованные чаты
- Групповые чаты (E2E с shared key per member)
- Публичные каналы
- Реакции, редактирование (10 мин), удаление сообщений
- Прикрепление файлов (зашифрованные блобы)
- Read receipts (✓✓)
- Статус онлайн / last seen
- Уведомления (Web Push)
- Rate limiting (Redis + in-memory fallback)
- Метрики (Prometheus `/metrics`)
- i18n: English / Русский
