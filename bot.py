import os
import json
import base64
import requests
import threading
from datetime import date
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= WEB SERVER (FOR RENDER) =================
# Render requires a web server to bind to port 10000 for health checks
server = Flask(__name__)

@server.route('/')
def health_check():
    return "Bot is Running!", 200

def run_flask():
    server.run(host='0.0.0.0', port=10000)

# ================= CONFIG & ENV =================
BOT_TOKEN = "8503894365:AAFl7sv9WFrPGSF2EC5jR6rr_gXOOntX_II"
OWNER_ID = 7645689440

# GitHub Environment Variables
GH_TOKEN = os.getenv("GITHUB_TOKEN")
GH_REPO = os.getenv("GITHUB_REPO")
GH_PATH = os.getenv("GITHUB_PATH", "limits.json")
GH_URL = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_PATH}"

DAILY_LIMIT = 25

# ================= GITHUB SYNC SYSTEM =================
def load_limits():
    """Fetches data from GitHub repository."""
    if not GH_TOKEN or not GH_REPO:
        print("⚠️ GitHub credentials missing! Using local mode.")
        return {}
    
    headers = {"Authorization": f"token {GH_TOKEN}"}
    try:
        response = requests.get(GH_URL, headers=headers)
        if response.status_code == 200:
            content = response.json()
            file_data = base64.b64decode(content['content']).decode('utf-8')
            return json.loads(file_data)
        return {}
    except Exception as e:
        print(f"❌ Load Error: {e}")
        return {}

def save_limits(data):
    """Pushes data to GitHub repository."""
    if not GH_TOKEN or not GH_REPO:
        return
    
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Get SHA of existing file to update it
    get_res = requests.get(GH_URL, headers=headers)
    sha = get_res.json().get('sha') if get_res.status_code == 200 else None

    string_data = json.dumps(data, indent=4)
    encoded_data = base64.b64encode(string_data.encode('utf-8')).decode('utf-8')
    
    payload = {
        "message": f"Sync Limits: {date.today().isoformat()}",
        "content": encoded_data,
        "sha": sha
    }

    requests.put(GH_URL, headers=headers, json=payload)

def check_limit(user_id):
    if user_id == OWNER_ID:
        return True

    data = load_limits()
    today = date.today().isoformat()
    uid = str(user_id)

    if uid not in data or data[uid]["date"] != today:
        data[uid] = {"count": 0, "date": today}

    if data[uid]["count"] >= DAILY_LIMIT:
        return False

    data[uid]["count"] += 1
    save_limits(data)
    return True

def get_usage(user_id):
    if user_id == OWNER_ID:
        return None
    data = load_limits()
    today = date.today().isoformat()
    uid = str(user_id)
    used = data.get(uid, {}).get("count", 0)
    return used, DAILY_LIMIT - used

# ================= KEYBOARD =================
menu_buttons = ReplyKeyboardMarkup(
    [
        [{"text": "👤 User Info", "request_users": {"request_id": 1, "user_is_bot": False, "max_quantity": 1}}],
        [{"text": "👥 Group", "request_chat": {"request_id": 3, "chat_is_channel": False}}],
        [{"text": "📢 Channel", "request_chat": {"request_id": 2, "chat_is_channel": True}}],
        [{"text": "🤖 Bot", "request_users": {"request_id": 4, "user_is_bot": True, "max_quantity": 1}}],
        ["📊 Check Limit"]
    ],
    resize_keyboard=True
)

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    name = user.full_name
    username = f"@{user.username}" if user.username else "No username"

    status_tag = "👑 <b>Owner verified</b>" if uid == OWNER_ID else "✅ <b>Access granted</b>"
    
    text = (
        f"{status_tag}\n\n"
        "🆔 <b>Account Details:</b>\n"
        f"User ID: <code>{uid}</code>\n"
        f"Name: <code>{name}</code>\n"
        f"Username: <code>{username}</code>"
    )

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=menu_buttons)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "📊 Check Limit":
        await limit_cmd(update, context)

async def limit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid == OWNER_ID:
        await update.message.reply_text("♾️ Unlimited access (Owner)")
        return

    used, left = get_usage(uid)
    await update.message.reply_text(
        f"📊 <b>Daily Usage</b>\n\n"
        f"Used: <code>{used}</code>\n"
        f"Left: <code>{left}/{DAILY_LIMIT}</code>\n\n"
        f"🕛 Reset at 12:00 AM",
        parse_mode="HTML"
    )
    
async def users_shared(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    for u in update.message.users_shared.users:
        if not check_limit(user_id):
            await update.message.reply_text("❌ Daily limit reached!")
            return

        text = (
            f"🆔 <b>User ID:</b> <code>{u.user_id}</code>\n"
            f"👤 <b>Name:</b> <code>{u.first_name} {u.last_name or ''}</code>\n"
            f"🔗 <b>Username:</b> @{u.username if u.username else 'None'}"
        )
        await update.message.reply_text(text, parse_mode="HTML")

async def chat_shared(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not check_limit(uid):
        await update.message.reply_text("❌ Daily limit reached!")
        return
    await update.message.reply_text(f"🎯 <b>Chat ID:</b> <code>{update.message.chat_shared.chat_id}</code>", parse_mode="HTML")

# ================= MAIN =================
def main():
    # Start the Flask web server in a background thread
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("limit", limit_cmd))
    app.add_handler(MessageHandler(filters.StatusUpdate.USERS_SHARED, users_shared))
    app.add_handler(MessageHandler(filters.StatusUpdate.CHAT_SHARED, chat_shared))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🚀 Bot is live and Web Server is listening on port 10000")
    app.run_polling()
    
if __name__ == "__main__":
    main()
