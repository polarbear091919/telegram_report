# Telegram Report Collector

PDF research-report collector for Korean securities. Listens to a single Telegram channel and downloads new PDF attachments to local disk + Supabase metadata.

See [design spec](docs/superpowers/specs/2026-05-05-telegram-report-collector-design.md) for full design rationale.

## Setup (one-time)

1. **Clone / download** this repo.

2. **Create venv and install dependencies:**

   ```bash
   python -m venv .venv
   .venv\Scripts\activate            # Windows
   # source .venv/bin/activate       # Mac/Linux
   pip install -r requirements.txt
   ```

3. **Create Supabase tables.** Open your Supabase project → SQL Editor → paste the contents of `migrations/001_init.sql` → Run.

4. **Configure environment.** Copy the template and fill in your secrets:

   ```bash
   copy .env.example .env             # Windows
   # cp .env.example .env             # Mac/Linux
   ```

   Then edit `.env`:
   - `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`: from https://my.telegram.org
   - `TELEGRAM_CHANNEL`: channel username (default `sunstudy1004`)
   - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`: from Supabase dashboard → Settings → API → `service_role` key (⚠️ secret — never commit)

5. **First run** (will prompt for SMS verification once):

   ```bash
   python main.py
   ```

## Usage

| Command | Effect |
|---|---|
| `python main.py` | Normal run: collect new PDFs since last run |
| `python main.py --dry-run` | List what would be downloaded; write nothing |
| `python main.py --cutoff-days 7` | Override INITIAL_CUTOFF_DAYS for this run |
| `python main.py -v` | Verbose (DEBUG level) logging |

### Exit codes

- `0` Complete success
- `1` Total failure (config / auth / network)
- `2` Partial failure — some messages added to `failed_attempts` table; will be auto-retried next run

## Development

Run tests:

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Troubleshooting

- **"Missing required env var: X"** — Add the key to `.env`.
- **SMS code prompt every run** — The `sessions/samstudy.session` file is missing or got deleted. Telethon re-authenticates each time.
- **Persistent failures in `failed_attempts`** — Check the `error_message` and `attempt_count` columns. If `attempt_count > 10` for a row, the message is likely permanently broken; manually inspect or DELETE the row to stop retrying.

## Security

- `.env` and `*.session` files contain credentials and account access. They are in `.gitignore` — keep it that way.
- `SUPABASE_SERVICE_KEY` bypasses Row-Level Security. Treat it as a master password.
