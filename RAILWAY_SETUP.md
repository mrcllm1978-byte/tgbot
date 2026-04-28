# Railway Deployment Setup

## Issues Fixed

1. **Procfile**: Changed from `bot.py` → `tgbot.py` (matching actual filename)
2. **Dependencies**: Updated `pyTelegramBotAPI` → `python-telegram-bot[all]` (correct async library)
3. **Missing ADMINS**: Added empty set - **you must add admin user IDs**
4. **Async main()**: Updated to properly handle async/await for Railway

## Configuration Steps

### 1. Set Environment Variables on Railway
- `BOT_TOKEN`: Your Telegram bot token from @BotFather

### 2. Add Admin User IDs
Edit `tgbot.py` and add your admin Telegram user ID:
```python
ADMINS = {123456789, 987654321}  # Replace with your user IDs
```

### 3. Database Note
The SQLite database (`bot.db`) will be lost when Railway restarts the app. For persistence, consider:
- **PostgreSQL**: Railway offers free PostgreSQL databases
- **MongoDB**: Cloud-based option
- **For now**: Accept data loss on app restart (good for testing)

### 4. Deploy to Railway
```bash
git push origin main  # Or your branch name
```

## If Bot Still Doesn't Work

Check the Railway logs for:
1. **Missing BOT_TOKEN**: Set the environment variable
2. **Polling timeout**: Railway may have networking restrictions
3. **Database errors**: Check SQLite file permissions

## Next Steps (Optional Improvements)
- Use webhooks instead of polling for better Railway compatibility
- Switch to PostgreSQL for persistent storage
- Add startup logging to diagnose issues
