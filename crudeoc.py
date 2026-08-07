
import requests
import time
from datetime import datetime

TELEGRAM = True

def fetch_nt_total():
    url = "https://webapi.niftytrader.in/webapi/option/option-chain-data?symbol=crudeoil&expiryDate=&exchange=MCX&atmBelow=0&atmAbove=0"
    headers = {"User-Agent": "Mozilla/5.0", "accept": "application/json"}
    try:
        res = requests.get(url, headers=headers)
        return res.json()
    except Exception as e:
        print(f"❌ Fetch error: {e}")
        return None

def fmt_k(val):
    return f"{abs(val)/1_000:.1f}K"

def send_telegram_message(msg, imp=True):
    if not TELEGRAM:
        return
    BOT_TOKEN      = "8331147432:AAGSG4mI8d87sWEBsY0qtarAtwWbpa4viq0"
    CHANNEL_ID     = "-1003494200670"
    CHANNEL_ID_IMP = "-1003448158591"
    chat_id        = CHANNEL_ID_IMP if imp else CHANNEL_ID
    url            = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": chat_id, "text": msg}, timeout=15)
    except Exception as e:
        print("❌ Telegram error:", e)

def main():
    print("🔁 Refreshing every 60s. Ctrl+C to stop.\n")
    while True:
        data = fetch_nt_total()
        if data and data.get("result") == 1:
            totals = data["resultData"]["opTotals"]["total_calls_puts"]
            pe_coi = totals["total_puts_change_oi"]
            ce_coi = totals["total_calls_change_oi"]
            net = pe_coi - ce_coi
            now = datetime.now().strftime("%H:%M")
            if net >= 0:
                msg = f"🕒{now}  |  {fmt_k(net)}🟢"
            else:
                msg = f"🕒{now}  |  -{fmt_k(net)}🔴"
            print(msg)
            send_telegram_message(msg, False)
        else:
            print(f"⚠️  Bad response at {datetime.now().strftime('%H:%M')}")
        time.sleep(60)

if __name__ == "__main__":
    main()
