import os
import json
import logging
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters, CallbackQueryHandler
)
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
import threading
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config from environment ──────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TWILIO_SID       = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH      = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM      = os.environ["TWILIO_PHONE_NUMBER"]   # e.g. +14155551234
YOUR_PHONE       = os.environ["YOUR_PHONE_NUMBER"]      # your personal number
YOUR_CHAT_ID     = os.environ["YOUR_TELEGRAM_CHAT_ID"]  # your Telegram user ID
PUBLIC_URL       = os.environ["PUBLIC_URL"]             # Railway URL, no trailing slash

twilio_client = Client(TWILIO_SID, TWILIO_AUTH)

# ── In-memory lead store (persisted to leads.json) ───────────────────────────
LEADS_FILE = "leads.json"

def load_leads():
    if os.path.exists(LEADS_FILE):
        with open(LEADS_FILE) as f:
            return json.load(f)
    return {}

def save_leads(leads):
    with open(LEADS_FILE, "w") as f:
        json.dump(leads, f, indent=2)

leads = load_leads()   # { phone: {name, status, call_sid} }

# ── Flask app (Twilio webhooks) ───────────────────────────────────────────────
flask_app = Flask(__name__)

telegram_app = None   # set after build

def send_telegram_sync(chat_id, text, reply_markup=None):
    """Thread-safe fire-and-forget Telegram message."""
    async def _send():
        if reply_markup:
            await telegram_app.bot.send_message(chat_id=chat_id, text=text,
                                                 reply_markup=reply_markup)
        else:
            await telegram_app.bot.send_message(chat_id=chat_id, text=text)
    asyncio.run(_send())

@flask_app.route("/twilio/outbound", methods=["POST"])
def twilio_outbound():
    """Initial TwiML: play message and wait for keypress."""
    phone = request.form.get("To", "unknown")
    name  = leads.get(phone, {}).get("name", "there")

    resp    = VoiceResponse()
    gather  = Gather(num_digits=1, action=f"{PUBLIC_URL}/twilio/keypress",
                     method="POST", timeout=10)
    gather.say(
        f"Hello {name}, this is a call from our business. "
        "If you're interested in learning more about our offer, "
        "please press 1 now to speak with us directly. "
        "Press 2 to be removed from our list. "
        "Otherwise, have a great day.",
        voice="Polly.Joanna"
    )
    resp.append(gather)
    resp.say("We didn't receive a response. We'll try again later. Goodbye!")
    return str(resp), 200, {"Content-Type": "text/xml"}

@flask_app.route("/twilio/keypress", methods=["POST"])
def twilio_keypress():
    """Handle the digit pressed by the lead."""
    digit = request.form.get("Digits", "")
    phone = request.form.get("To", "unknown")
    call_sid = request.form.get("CallSid", "")
    name  = leads.get(phone, {}).get("name", "Unknown")

    resp = VoiceResponse()

    if digit == "1":
        # Update lead status
        if phone in leads:
            leads[phone]["status"] = "interested"
            save_leads(leads)

        # Notify you on Telegram
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📞 Join Call Now", callback_data=f"join_{call_sid}_{phone}")
        ]])
        threading.Thread(target=send_telegram_sync, args=(
            YOUR_CHAT_ID,
            f"🔥 *Lead pressed 1!*\n\n👤 Name: {name}\n📱 Phone: {phone}\n\nPress the button to join the call:",
            keyboard
        )).start()

        resp.say(
            "Great! Please hold for just a moment while we connect you. Thank you!",
            voice="Polly.Joanna"
        )
        resp.pause(length=20)   # hold music gap — extend if needed
        resp.say("We're sorry, no one is available right now. Please try again later.", voice="Polly.Joanna")

    elif digit == "2":
        if phone in leads:
            leads[phone]["status"] = "opted_out"
            save_leads(leads)
        threading.Thread(target=send_telegram_sync, args=(
            YOUR_CHAT_ID,
            f"❌ Lead opted out: {name} ({phone})"
        )).start()
        resp.say("You have been removed from our list. Goodbye!", voice="Polly.Joanna")

    else:
        resp.say("Invalid input. Goodbye!", voice="Polly.Joanna")

    return str(resp), 200, {"Content-Type": "text/xml"}

@flask_app.route("/twilio/status", methods=["POST"])
def twilio_status():
    """Receive call status updates from Twilio."""
    status   = request.form.get("CallStatus", "")
    phone    = request.form.get("To", "unknown")
    name     = leads.get(phone, {}).get("name", "Unknown")

    if status in ("completed", "busy", "no-answer", "failed", "canceled"):
        if phone in leads and leads[phone].get("status") == "calling":
            leads[phone]["status"] = status
            save_leads(leads)
        threading.Thread(target=send_telegram_sync, args=(
            YOUR_CHAT_ID,
            f"📋 Call ended — {name} ({phone}): *{status}*"
        )).start()

    return "", 204

# ── Telegram command handlers ─────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Lead Caller Bot*\n\n"
        "Commands:\n"
        "• /addlead +1234567890 John Doe — add a lead\n"
        "• /leads — list all leads\n"
        "• /call +1234567890 — call a lead\n"
        "• /callall — call all pending leads\n"
        "• /removelead +1234567890 — remove a lead\n"
        "• /stats — summary stats",
        parse_mode="Markdown"
    )

async def cmd_addlead(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 1:
        await update.message.reply_text("Usage: /addlead +1234567890 John Doe")
        return
    phone = args[0]
    name  = " ".join(args[1:]) if len(args) > 1 else "Unknown"
    leads[phone] = {"name": name, "status": "pending", "call_sid": None}
    save_leads(leads)
    await update.message.reply_text(f"✅ Added: {name} ({phone})")

async def cmd_leads(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not leads:
        await update.message.reply_text("No leads yet. Use /addlead to add some.")
        return
    status_emoji = {
        "pending": "⏳", "calling": "📞", "interested": "🔥",
        "opted_out": "❌", "completed": "✅", "no-answer": "📵",
        "busy": "🔴", "failed": "⚠️"
    }
    lines = []
    for phone, data in leads.items():
        e = status_emoji.get(data["status"], "❓")
        lines.append(f"{e} {data['name']} — {phone} — _{data['status']}_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_call(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /call +1234567890")
        return
    phone = ctx.args[0]
    if phone not in leads:
        await update.message.reply_text(f"Lead {phone} not found. Add with /addlead first.")
        return
    await _place_call(phone, update)

async def _place_call(phone, update_or_none=None):
    name = leads[phone]["name"]
    try:
        call = twilio_client.calls.create(
            to=phone,
            from_=TWILIO_FROM,
            url=f"{PUBLIC_URL}/twilio/outbound",
            status_callback=f"{PUBLIC_URL}/twilio/status",
            status_callback_method="POST"
        )
        leads[phone]["status"]   = "calling"
        leads[phone]["call_sid"] = call.sid
        save_leads(leads)
        msg = f"📞 Calling {name} ({phone})..."
    except Exception as e:
        msg = f"❌ Failed to call {phone}: {e}"

    if update_or_none:
        await update_or_none.message.reply_text(msg)
    else:
        send_telegram_sync(YOUR_CHAT_ID, msg)

async def cmd_callall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pending = [(p, d) for p, d in leads.items() if d["status"] == "pending"]
    if not pending:
        await update.message.reply_text("No pending leads to call.")
        return
    await update.message.reply_text(f"🚀 Starting calls to {len(pending)} leads...")
    for phone, _ in pending:
        await _place_call(phone)

async def cmd_removelead(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /removelead +1234567890")
        return
    phone = ctx.args[0]
    if phone in leads:
        name = leads.pop(phone)["name"]
        save_leads(leads)
        await update.message.reply_text(f"🗑️ Removed {name} ({phone})")
    else:
        await update.message.reply_text("Lead not found.")

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from collections import Counter
    counts = Counter(d["status"] for d in leads.values())
    total  = len(leads)
    lines  = [f"📊 *Stats — {total} total leads*\n"]
    for status, n in counts.most_common():
        lines.append(f"• {status}: {n}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def callback_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """When you tap 'Join Call Now' in Telegram."""
    query = update.callback_query
    await query.answer()
    parts    = query.data.split("_", 2)   # join_<sid>_<phone>
    call_sid = parts[1]
    phone    = parts[2]

    try:
        # Use Twilio's Calls API to redirect the held lead to a new TwiML
        # that dials YOUR number
        twilio_client.calls(call_sid).update(
            twiml=f"<Response><Dial>{YOUR_PHONE}</Dial></Response>"
        )
        await query.edit_message_text(
            f"✅ Connecting you now! Your phone ({YOUR_PHONE}) will ring."
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Could not join: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

def main():
    global telegram_app
    telegram_app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    telegram_app.add_handler(CommandHandler("start",       cmd_start))
    telegram_app.add_handler(CommandHandler("addlead",     cmd_addlead))
    telegram_app.add_handler(CommandHandler("leads",       cmd_leads))
    telegram_app.add_handler(CommandHandler("call",        cmd_call))
    telegram_app.add_handler(CommandHandler("callall",     cmd_callall))
    telegram_app.add_handler(CommandHandler("removelead",  cmd_removelead))
    telegram_app.add_handler(CommandHandler("stats",       cmd_stats))
    telegram_app.add_handler(CallbackQueryHandler(callback_join, pattern="^join_"))

    # Run Flask in background thread, Telegram bot in main thread
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

    logger.info("Bot started!")
    telegram_app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
