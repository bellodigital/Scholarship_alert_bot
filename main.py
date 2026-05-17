
# ============================================
# NIGERIA SCHOLARSHIP ALERT BOT
# Telegram + WhatsApp | Paystack Payments
# ============================================

import os
import json
import time
import logging
import requests
import hashlib
import hmac
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
from pymongo import MongoClient
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -- CONFIG --
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
GREEN_API_ID       = os.getenv("GREEN_API_ID")
GREEN_API_TOKEN    = os.getenv("GREEN_API_TOKEN")
PAYSTACK_SECRET    = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_PUBLIC    = os.getenv("PAYSTACK_PUBLIC_KEY")
MONGODB_URI        = os.getenv("MONGODB_URI")
SUB_PRICE          = int(os.getenv("SUBSCRIPTION_PRICE", "150000"))
PORT               = int(os.getenv("PORT", "8080"))

GREEN_API_URL = f"https://api.green-api.com/waInstance{GREEN_API_ID}"

# -- DATABASE --
client = MongoClient(MONGODB_URI)
db = client["scholarshipbot"]
subscribers_col  = db["subscribers"]
scholarships_col = db["scholarships"]
payments_col     = db["payments"]

# -- HELPERS --
def send_telegram_message(chat_id, text, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Telegram error: {e}")

def send_whatsapp_message(phone, message):
    try:
        if phone.startswith("0"):
            phone = "234" + phone[1:]
        elif not phone.startswith("234"):
            phone = "234" + phone
        url = f"{GREEN_API_URL}/sendMessage/{GREEN_API_TOKEN}"
        payload = {"chatId": f"{phone}@c.us", "message": message}
        resp = requests.post(url, json=payload, timeout=30)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"WhatsApp error: {e}")
        return False

def admin_alert(message):
    send_telegram_message(TELEGRAM_CHAT_ID, message)

def is_subscribed(identifier):
    sub = subscribers_col.find_one({"identifier": identifier})
    if not sub:
        return False
    expiry = sub.get("expiry")
    if not expiry:
        return False
    return datetime.utcnow() < expiry

def get_subscriber(identifier):
    return subscribers_col.find_one({"identifier": identifier})

def create_paystack_payment(email, identifier, name):
    try:
        url = "https://api.paystack.co/transaction/initialize"
        headers = {"Authorization": f"Bearer {PAYSTACK_SECRET}"}
        payload = {
            "email": email,
            "amount": SUB_PRICE,
            "metadata": {
                "identifier": identifier,
                "name": name,
            },
            "callback_url": "https://t.me/ngscholarship_bot",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        data = resp.json()
        if data.get("status"):
            return data["data"]["authorization_url"]
        return None
    except Exception as e:
        logger.error(f"Paystack error: {e}")
        return None
# -- SCHOLARSHIP SCRAPER --
def scrape_scholars4dev():
    scholarships = []
    try:
        url = "https://www.scholars4dev.com/category/scholarships-by-country/scholarships-for-africans/"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        articles = soup.find_all("article", limit=10)
        for article in articles:
            title_tag = article.find("h2")
            link_tag = article.find("a")
            desc_tag = article.find("p")
            if title_tag and link_tag:
                scholarships.append({
                    "title": title_tag.get_text(strip=True),
                    "link": link_tag.get("href", ""),
                    "description": desc_tag.get_text(strip=True)[:200] if desc_tag else "",
                    "source": "scholars4dev",
                    "date_found": datetime.utcnow(),
                })
    except Exception as e:
        logger.error(f"scholars4dev error: {e}")
    return scholarships

def scrape_opportunitydesk():
    scholarships = []
    try:
        url = "https://opportunitydesk.org/category/scholarships/"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        articles = soup.find_all("article", limit=10)
        for article in articles:
            title_tag = article.find("h2") or article.find("h3")
            link_tag = article.find("a")
            desc_tag = article.find("p")
            if title_tag and link_tag:
                scholarships.append({
                    "title": title_tag.get_text(strip=True),
                    "link": link_tag.get("href", ""),
                    "description": desc_tag.get_text(strip=True)[:200] if desc_tag else "",
                    "source": "opportunitydesk",
                    "date_found": datetime.utcnow(),
                })
    except Exception as e:
        logger.error(f"opportunitydesk error: {e}")
    return scholarships

def scrape_afterschoolafrica():
    scholarships = []
    try:
        url = "https://www.afterschoolafrica.com/category/scholarships/"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        articles = soup.find_all("article", limit=10)
        for article in articles:
            title_tag = article.find("h2") or article.find("h3")
            link_tag = article.find("a")
            desc_tag = article.find("p")
            if title_tag and link_tag:
                scholarships.append({
                    "title": title_tag.get_text(strip=True),
                    "link": link_tag.get("href", ""),
                    "description": desc_tag.get_text(strip=True)[:200] if desc_tag else "",
                    "source": "afterschoolafrica",
                    "date_found": datetime.utcnow(),
                })
    except Exception as e:
        logger.error(f"afterschoolafrica error: {e}")
    return scholarships

def check_and_send_scholarships():
    logger.info("Checking for new scholarships...")
    all_scholarships = []
    all_scholarships.extend(scrape_scholars4dev())
    all_scholarships.extend(scrape_opportunitydesk())
    all_scholarships.extend(scrape_afterschoolafrica())
    new_count = 0
    for sch in all_scholarships:
        existing = scholarships_col.find_one({"title": sch["title"]})
        if not existing:
            scholarships_col.insert_one(sch)
            new_count += 1
            broadcast_scholarship(sch)
            time.sleep(2)
    logger.info(f"Found {new_count} new scholarships")
    if new_count > 0:
        admin_alert(f"Found {new_count} new scholarships and sent to subscribers!")

def broadcast_scholarship(scholarship):
    message = (
        f"NEW SCHOLARSHIP ALERT\n\n"
        f"Title: {scholarship['title']}\n\n"
        f"Description: {scholarship['description']}\n\n"
        f"Link: {scholarship['link']}\n\n"
        f"Source: {scholarship['source']}\n"
        f"Found: {scholarship['date_found'].strftime('%d %b %Y')}"
    )
    all_subs = subscribers_col.find({"expiry": {"$gt": datetime.utcnow()}})
    sent = 0
    for sub in all_subs:
        identifier = sub.get("identifier", "")
        platform = sub.get("platform", "telegram")
        if platform == "telegram":
            send_telegram_message(identifier, message)
        elif platform == "whatsapp":
            send_whatsapp_message(identifier, message)
        sent += 1
        time.sleep(1)
    logger.info(f"Broadcast to {sent} subscribers")

# -- TELEGRAM BOT --
async def start(update, context):
    user = update.effective_user
    identifier = str(update.effective_chat.id)
    keyboard = {
        "inline_keyboard": [
            [{"text": "Subscribe N1,500/month", "callback_data": "subscribe"}],
            [{"text": "View Scholarships", "callback_data": "view"}],
            [{"text": "My Subscription", "callback_data": "mysub"}],
            [{"text": "Help", "callback_data": "help"}],
        ]
    }
    await update.message.reply_text(
        f"Welcome {user.first_name} to Nigeria Scholarship Alert Bot!\n\n"
        f"Get instant alerts for new scholarships\n"
        f"For all levels - JAMB, Undergraduate, Masters, PhD\n\n"
        f"Subscribe for just N1,500/month\n"
        f"and never miss a scholarship again!\n\n"
        f"Choose an option below:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Subscribe N1,500/month", callback_data="subscribe")],
            [InlineKeyboardButton("View Latest Scholarships", callback_data="view")],
            [InlineKeyboardButton("My Subscription", callback_data="mysub")],
            [InlineKeyboardButton("Help", callback_data="help")],
        ])
    )

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    identifier = str(query.message.chat_id)
    user = query.from_user
    if query.data == "subscribe":
        await query.message.reply_text(
            "To subscribe send your email address\n"
            "Example: yourname@gmail.com"
        )
        context.user_data["step"] = "waiting_email"
    elif query.data == "view":
        recent = list(scholarships_col.find().sort("date_found", -1).limit(5))
        if not recent:
            await query.message.reply_text("No scholarships found yet. Check back soon!")
            return
        text = "Latest 5 Scholarships:\n\n"
        for i, sch in enumerate(recent, 1):
            text += f"{i}. {sch['title']}\n{sch['link']}\n\n"
        await query.message.reply_text(text)
    elif query.data == "mysub":
        if is_subscribed(identifier):
            sub = get_subscriber(identifier)
            expiry = sub["expiry"].strftime("%d %b %Y")
            await query.message.reply_text(
                f"Your subscription is ACTIVE\n"
                f"Expires: {expiry}\n\n"
                f"You will receive all scholarship alerts automatically!"
            )
        else:
            await query.message.reply_text(
                "You are not subscribed yet.\n"
                "Tap Subscribe to get started!"
            )
    elif query.data == "help":
        await query.message.reply_text(
            "How it works:\n\n"
            "1. Subscribe for N1,500/month\n"
            "2. Get instant alerts for new scholarships\n"
            "3. Never miss a deadline again\n\n"
            "We check 8 websites every 6 hours\n"
            "for new scholarships and send you alerts immediately!\n\n"
            "Contact admin: @yourusername"
        )

async def handle_message(update, context):
    text = update.message.text
    identifier = str(update.effective_chat.id)
    user = update.effective_user
    step = context.user_data.get("step")
    if step == "waiting_email":
        if "@" not in text or "." not in text:
            await update.message.reply_text(
                "Invalid email. Please send a valid email address:"
            )
            return
        email = text.strip()
        payment_link = create_paystack_payment(
            email, identifier, user.first_name
        )
        if payment_link:
            await update.message.reply_text(
                f"Click the link below to pay N1,500:\n\n"
                f"{payment_link}\n\n"
                f"After payment your subscription activates automatically!"
            )
            context.user_data["step"] = None
            admin_alert(
                f"New payment initiated!\n"
                f"Name: {user.first_name}\n"
                f"Email: {email}\n"
                f"Amount: N1,500"
            )
        else:
            await update.message.reply_text(
                "Payment link error. Please try again later."
            )
    else:
        await update.message.reply_text(
            "Use the menu buttons or send /start"
        )
# -- FLASK APP --
flask_app = Flask(__name__)

@flask_app.route("/health")
def health():
    return "OK", 200

@flask_app.route("/")
def home():
    total_subs = subscribers_col.count_documents(
        {"expiry": {"$gt": datetime.utcnow()}}
    )
    total_scholarships = scholarships_col.count_documents({})
    return jsonify({
        "status": "running",
        "active_subscribers": total_subs,
        "total_scholarships": total_scholarships,
    })

@flask_app.route("/paystack/webhook", methods=["POST"])
def paystack_webhook():
    try:
        payload = request.get_data()
        signature = request.headers.get("x-paystack-signature")
        expected = hmac.new(
            PAYSTACK_SECRET.encode(),
            payload,
            hashlib.sha512
        ).hexdigest()
        if signature != expected:
            return jsonify({"status": "invalid"}), 400
        data = json.loads(payload)
        event = data.get("event")
        if event == "charge.success":
            charge_data = data["data"]
            metadata = charge_data.get("metadata", {})
            identifier = metadata.get("identifier")
            name = metadata.get("name", "Subscriber")
            email = charge_data.get("customer", {}).get("email")
            amount = charge_data.get("amount", 0)
            expiry = datetime.utcnow() + timedelta(days=30)
            subscribers_col.update_one(
                {"identifier": identifier},
                {"$set": {
                    "identifier": identifier,
                    "name": name,
                    "email": email,
                    "platform": "telegram",
                    "expiry": expiry,
                    "amount_paid": amount,
                    "last_payment": datetime.utcnow(),
                }},
                upsert=True
            )
            payments_col.insert_one({
                "identifier": identifier,
                "amount": amount,
                "date": datetime.utcnow(),
                "reference": charge_data.get("reference"),
            })
            send_telegram_message(
                identifier,
                f"Payment confirmed! Thank you {name}!\n\n"
                f"Your subscription is now ACTIVE\n"
                f"Expires: {expiry.strftime('%d %b %Y')}\n\n"
                f"You will now receive instant scholarship alerts!"
            )
            admin_alert(
                f"NEW SUBSCRIBER PAID!\n"
                f"Name: {name}\n"
                f"Email: {email}\n"
                f"Amount: N{amount/100:.0f}\n"
                f"Expiry: {expiry.strftime('%d %b %Y')}"
            )
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

@flask_app.route("/admin/stats", methods=["GET"])
def admin_stats():
    total_active = subscribers_col.count_documents(
        {"expiry": {"$gt": datetime.utcnow()}}
    )
    total_all = subscribers_col.count_documents({})
    total_revenue = sum(
        p["amount"] for p in payments_col.find()
    ) / 100
    total_scholarships = scholarships_col.count_documents({})
    return jsonify({
        "active_subscribers": total_active,
        "total_subscribers": total_all,
        "total_revenue_naira": total_revenue,
        "total_scholarships_found": total_scholarships,
    })

@flask_app.route("/admin/broadcast", methods=["POST"])
def admin_broadcast():
    data = request.json
    message = data.get("message")
    if not message:
        return jsonify({"error": "No message"}), 400
    all_subs = subscribers_col.find(
        {"expiry": {"$gt": datetime.utcnow()}}
    )
    sent = 0
    for sub in all_subs:
        identifier = sub.get("identifier")
        platform = sub.get("platform", "telegram")
        if platform == "telegram":
            send_telegram_message(identifier, message)
        elif platform == "whatsapp":
            send_whatsapp_message(identifier, message)
        sent += 1
        time.sleep(1)
    return jsonify({"sent": sent})

# -- MAIN --
if __name__ == "__main__":
    import asyncio

    logger.info("Starting Scholarship Alert Bot...")

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        check_and_send_scholarships,
        "interval",
        hours=6,
        id="scholarship_check"
    )
    scheduler.start()

    threading.Thread(
        target=check_and_send_scholarships,
        daemon=True
    ).start()

    threading.Thread(
        target=lambda: flask_app.run(
            host="0.0.0.0",
            port=PORT,
            debug=False,
            use_reloader=False
        ),
        daemon=True
    ).start()

    async def run_bot():
        telegram_app = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .build()
        )
        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CallbackQueryHandler(button_handler))
        telegram_app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                handle_message
            )
        )
        admin_alert("Scholarship Alert Bot is online!")
        await telegram_app.run_polling(
            drop_pending_updates=True
        )

    asyncio.run(run_bot())
