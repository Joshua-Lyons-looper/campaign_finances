<<<<<<< HEAD
# Campaign Spending API

Minimal FastAPI project with a SQLite connector. Requires Python 3.10+.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --env-file .env
```

Open API docs at http://127.0.0.1:8000/docs or check database connectivity
at http://127.0.0.1:8000/health.

## Database

SQLite is included with Python. The database is created on the first connection
at `data/app.sqlite3`. Set `DATABASE_PATH` to change its location; relative paths
are resolved from the project root. The Uvicorn command above loads `.env`.

Use `Depends(get_db)` from `app.database` in synchronous route functions to
receive a SQLite connection. Each request has its own connection, with foreign
keys enabled, automatic commit on success, rollback on error, and cleanup.
Use SQL placeholders for values, for example `db.execute("SELECT ?", (value,))`.
Add your tables and routes as needed.
=======
# campaign_finances
>>>>>>> 063b4ec2a264fabf04ff0a7d946e57bf1fe378d6
