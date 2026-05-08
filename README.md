# 📞 Lead Caller Bot — Setup Guide

A Telegram bot that auto-dials your business leads, plays a message,
and only connects you when they press 1. No more wasted time on cold calls.

---

## How It Works

1. You add leads via Telegram: `/addlead +1234567890 John Doe`
2. You trigger a call: `/call +1234567890` or `/callall` for all pending
3. Twilio dials the lead and plays your intro message
4. If they press **1** → you get a Telegram notification with a **"Join Call Now"** button
5. You tap the button → your phone rings and you're connected live
6. If they press **2** → they're opted out automatically

---

## Step-by-Step Setup

### 1. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **token** (looks like `123456:ABCdef...`)
4. Find your Telegram Chat ID: message **@userinfobot** — it will reply with your ID

### 2. Configure Twilio

1. Log in to [twilio.com/console](https://twilio.com/console)
2. Copy your **Account SID** and **Auth Token** from the dashboard
3. Go to **Phone Numbers → Manage → Active Numbers**
4. Copy your Twilio phone number (or buy one — ~$1/month)

### 3. Deploy to Railway (Free)

1. Push this folder to a **GitHub repo** (public or private)
   ```bash
   git init
   git add .
   git commit -m "initial"
   git remote add origin https://github.com/YOUR_USERNAME/lead-caller-bot.git
   git push -u origin main
   ```

2. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub**
3. Select your repo

4. Go to your project → **Variables** tab → add these one by one:

   | Variable | Value |
   |---|---|
   | `TELEGRAM_TOKEN` | Your BotFather token |
   | `TWILIO_ACCOUNT_SID` | From Twilio console |
   | `TWILIO_AUTH_TOKEN` | From Twilio console |
   | `TWILIO_PHONE_NUMBER` | e.g. `+14155551234` |
   | `YOUR_PHONE_NUMBER` | Your real phone number |
   | `YOUR_TELEGRAM_CHAT_ID` | Your Telegram user ID |
   | `PUBLIC_URL` | Leave blank for now — fill in after step 5 |

5. After deploy, go to **Settings → Networking → Generate Domain**
   Copy the URL (e.g. `https://lead-caller-bot.up.railway.app`)

6. Go back to **Variables** and set `PUBLIC_URL` to that URL (no trailing slash)

7. Railway will auto-redeploy. Your bot is live! ✅

### 4. Test It

1. Open Telegram, find your bot, send `/start`
2. Add a test lead: `/addlead +YOUR_OWN_NUMBER Test Lead`
3. Call it: `/call +YOUR_OWN_NUMBER`
4. Your phone will ring — press 1
5. You should get a Telegram notification with a "Join Call Now" button

---

## Bot Commands

| Command | Description |
|---|---|
| `/addlead +1234567890 John Doe` | Add a new lead |
| `/leads` | List all leads with status |
| `/call +1234567890` | Call a specific lead |
| `/callall` | Call all pending leads |
| `/removelead +1234567890` | Remove a lead |
| `/stats` | Summary statistics |

---

## Lead Statuses

| Status | Meaning |
|---|---|
| ⏳ pending | Not called yet |
| 📞 calling | Call in progress |
| 🔥 interested | Pressed 1 — wants to talk! |
| ❌ opted_out | Pressed 2 — remove from list |
| ✅ completed | Call completed normally |
| 📵 no-answer | No answer |
| 🔴 busy | Line was busy |
| ⚠️ failed | Call failed |

---

## Customizing the Call Message

Edit the `say()` text in `bot.py` around line 55:

```python
gather.say(
    "Hello {name}, this is a call from YOUR COMPANY NAME. "
    "If you're interested in our offer, press 1 to speak with us. "
    "Press 2 to be removed from our list.",
    voice="Polly.Joanna"   # change voice here
)
```

Available voices: `Polly.Joanna` (US female), `Polly.Matthew` (US male),
`Polly.Brian` (UK male), `Polly.Amy` (UK female)

---

## Cost Estimate

| Item | Cost |
|---|---|
| Railway hosting | Free ($5 credit/month) |
| Twilio phone number | ~$1/month |
| Twilio outbound calls | ~$0.013/min (US) |
| 100 calls × 30 sec avg | ~$0.65 |

---

## Bulk Import Leads (CSV)

You can import leads in bulk by running this locally:

```python
import csv, requests

leads_csv = "leads.csv"   # columns: phone, name
bot_token = "YOUR_TOKEN"
chat_id   = "YOUR_CHAT_ID"

with open(leads_csv) as f:
    for row in csv.DictReader(f):
        requests.get(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            params={
                "chat_id": chat_id,
                "text": f"/addlead {row['phone']} {row['name']}"
            }
        )
```
