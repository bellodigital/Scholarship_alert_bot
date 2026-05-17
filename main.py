
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
