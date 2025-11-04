import os
import sqlite3
import datetime
import csv
import io
import pytz
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

DB_PATH = 'budget_bot.db'
DEFAULT_CATEGORIES = [
    'еда', 'кафе', 'покупки', 'коммуналка', 'такси', 'спорт', 'медицина', 'другое'
]
TIMEZONE = 'Europe/Amsterdam'

# Создаем Flask app для открытия порта
app = Flask(__name__)

@app.route('/')
def home():
    return "Telegram Bot is running!"

@app.route('/health')
def health():
    return "OK"

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

# ---------- Database helpers ----------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            created_at TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            UNIQUE(user_id, name)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ts TEXT,
            amount REAL,
            category TEXT,
            note TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            month TEXT,
            category TEXT,
            budget_limit REAL
        )
    ''')
    conn.commit()
    conn.close()

def ensure_user(user_id, chat_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT 1 FROM users WHERE user_id=?', (user_id,))
    if not cur.fetchone():
        cur.execute('INSERT INTO users(user_id, chat_id, created_at) VALUES (?,?,?)', (user_id, chat_id, now_iso()))
        for cat in DEFAULT_CATEGORIES:
            cur.execute('INSERT OR IGNORE INTO categories(user_id, name) VALUES (?,?)', (user_id, cat))
        conn.commit()
    conn.close()

def now_iso():
    tz = pytz.timezone(TIMEZONE)
    return datetime.datetime.now(tz).isoformat()

# ---------- Commands ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, update.effective_chat.id)
    text = ("Привет! Я бот для учёта бюджета.\n"
            "Используйте /add <категория> <сумма> [примечание] чтобы добавить расход.\n"
            "Пример: /add еда 250 супермаркет\n"
            "Посмотреть баланс: /balance\n"
            "Список категорий: /categories\n"
            "Отчёт за месяц: /report 2025-11\n"
            "Экспорт CSV: /export 2025-11\n"
            "Установить лимит: /setbudget еда 10000\n")
    await update.message.reply_text(text)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def categories_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, update.effective_chat.id)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT name FROM categories WHERE user_id=?', (user.id,))
    rows = cur.fetchall()
    conn.close()
    text = 'Категории:\n' + '\n'.join('- ' + r[0] for r in rows)
    text += '\n\nДобавить новую категорию: /addcat название'
    await update.message.reply_text(text)

async def addcat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, update.effective_chat.id)
    args = context.args
    if not args:
        await update.message.reply_text('Укажите название категории. Пример: /addcat подарки')
        return
    name = ' '.join(args).lower()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO categories(user_id, name) VALUES (?,?)', (user.id, name))
        conn.commit()
        await update.message.reply_text(f'Категория "{name}" добавлена.')
    except sqlite3.IntegrityError:
        await update.message.reply_text('Такая категория уже есть.')
    finally:
        conn.close()

async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, update.effective_chat.id)
    args = context.args
    if len(args) < 2:
        await update.message.reply_text('Формат: /add <категория> <сумма> [примечание]')
        return
    category = args[0].lower()
    try:
        amount = float(args[1].replace(',', '.'))
    except ValueError:
        await update.message.reply_text('Неверная сумма. Используйте цифры. Пример: /add еда 250')
        return
    note = ' '.join(args[2:]) if len(args) > 2 else ''
    ts = now_iso()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('INSERT INTO transactions(user_id, ts, amount, category, note) VALUES (?,?,?,?,?)', 
                (user.id, ts, -abs(amount), category, note))
    conn.commit()
    conn.close()
    await update.message.reply_text(f'Добавлен расход: {category} {amount} ₽ {note}')

async def income_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, update.effective_chat.id)
    args = context.args
    if not args:
        await update.message.reply_text('Формат: /income <сумма> [примечание]')
        return
    try:
        amount = float(args[0].replace(',', '.'))
    except ValueError:
        await update.message.reply_text('Неверная сумма.')
        return
    note = ' '.join(args[1:]) if len(args) > 1 else ''
    ts = now_iso()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('INSERT INTO transactions(user_id, ts, amount, category, note) VALUES (?,?,?,?,?)', 
                (user.id, ts, amount, 'доход', note))
    conn.commit()
    conn.close()
    await update.message.reply_text(f'Добавлен доход: {amount} ₽ {note}')

async def setbudget_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, update.effective_chat.id)
    args = context.args
    if len(args) < 2:
        await update.message.reply_text('Формат: /setbudget <категория> <сумма>')
        return
    category = args[0].lower()
    try:
        limit = float(args[1].replace(',', '.'))
    except ValueError:
        await update.message.reply_text('Неверная сумма.')
        return
    month = datetime.datetime.now().strftime('%Y-%m')
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO budgets(user_id, month, category, budget_limit) VALUES (?,?,?,?)', 
                (user.id, month, category, limit))
    conn.commit()
    conn.close()
    await update.message.reply_text(f'Установлен лимит {limit} ₽ на {category} за {month}')

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, update.effective_chat.id)
    month = datetime.datetime.now().strftime('%Y-%m')
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT category, SUM(amount) FROM transactions WHERE user_id=? AND substr(ts,1,7)=? GROUP BY category", 
                (user.id, month))
    rows = cur.fetchall()
    cur.execute('SELECT category, budget_limit FROM budgets WHERE user_id=? AND month=?', (user.id, month))
    budgets = {r[0]: r[1] for r in cur.fetchall()}
    conn.close()
    
    total = sum(r[1] for r in rows) if rows else 0
    text_lines = [f'Баланс за {month}: {total:.2f} ₽', 'По категориям:']
    for cat, s in rows:
        limit = budgets.get(cat)
        if limit:
            text_lines.append(f'- {cat}: {s:.2f} ₽ (лимит {limit} ₽, остал.: {limit + s:.2f} ₽)')
        else:
            text_lines.append(f'- {cat}: {s:.2f} ₽')
    await update.message.reply_text('\n'.join(text_lines))

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, update.effective_chat.id)
    args = context.args
    if args:
        month = args[0]
    else:
        month = datetime.datetime.now().strftime('%Y-%m')
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT ts, amount, category, note FROM transactions WHERE user_id=? AND substr(ts,1,7)=? ORDER BY ts', 
                (user.id, month))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text('Нет транзакций за указанный месяц.')
        return
    lines = [f'Отчёт за {month}:']
    total = 0
    for ts, amt, cat, note in rows:
        dt = ts.replace('T', ' ')[:19]
        lines.append(f'{dt} | {cat} | {amt:.2f} ₽ | {note}')
        total += amt
    lines.append(f'Итого: {total:.2f} ₽')
    await update.message.reply_text('\n'.join(lines))

async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, update.effective_chat.id)
    args = context.args
    if args:
        month = args[0]
    else:
        month = datetime.datetime.now().strftime('%Y-%m')
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT ts, amount, category, note FROM transactions WHERE user_id=? AND substr(ts,1,7)=? ORDER BY ts', 
                (user.id, month))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text('Нет транзакций для экспорта.')
        return
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ts', 'amount', 'category', 'note'])
    for r in rows:
        writer.writerow(r)
    output.seek(0)
    await update.message.reply_document(
        document=io.BytesIO(output.getvalue().encode('utf-8')), 
        filename=f'transactions_{month}.csv'
    )

async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Я понимаю команды: /add, /income, /balance, /report, /categories, /setbudget, /export')

# ---------- Main ----------

def main():
    init_db()
    token = os.getenv('BOT_TOKEN')
    if not token:
        print('Error: set BOT_TOKEN environment variable')
        return
    
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Запускаем Telegram бота
    app_bot = Application.builder().token(token).build()

    app_bot.add_handler(CommandHandler('start', start))
    app_bot.add_handler(CommandHandler('help', help_cmd))
    app_bot.add_handler(CommandHandler('categories', categories_cmd))
    app_bot.add_handler(CommandHandler('addcat', addcat_cmd))
    app_bot.add_handler(CommandHandler('add', add_cmd))
    app_bot.add_handler(CommandHandler('income', income_cmd))
    app_bot.add_handler(CommandHandler('setbudget', setbudget_cmd))
    app_bot.add_handler(CommandHandler('balance', balance_cmd))
    app_bot.add_handler(CommandHandler('report', report_cmd))
    app_bot.add_handler(CommandHandler('export', export_cmd))

    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    print('Bot started with HTTP server...')
    app_bot.run_polling()

if __name__ == '__main__':
    main()
