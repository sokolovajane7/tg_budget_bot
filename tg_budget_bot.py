from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
cur.execute('SELECT ts, amount, category, note FROM transactions WHERE user_id=? AND substr(ts,1,7)=? ORDER BY ts', (user.id, month))
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
await update.message.reply_document(document=io.BytesIO(output.getvalue().encode('utf-8')), filename=f'transactions_{month}.csv')


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text('Я понимаю команды: /add, /income, /balance, /report, /categories, /setbudget, /export')


# ---------- Main ----------


def main():
init_db()
token = os.getenv('BOT_TOKEN')
if not token:
print('Error: set BOT_TOKEN environment variable')
return
app = ApplicationBuilder().token(token).build()


app.add_handler(CommandHandler('start', start))
app.add_handler(CommandHandler('help', help_cmd))
app.add_handler(CommandHandler('categories', categories_cmd))
app.add_handler(CommandHandler('addcat', addcat_cmd))
app.add_handler(CommandHandler('add', add_cmd))
app.add_handler(CommandHandler('income', income_cmd))
app.add_handler(CommandHandler('setbudget', setbudget_cmd))
app.add_handler(CommandHandler('balance', balance_cmd))
app.add_handler(CommandHandler('report', report_cmd))
app.add_handler(CommandHandler('export', export_cmd))


app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))


print('Bot started...')
app.run_polling()


if __name__ == '__main__':
main()