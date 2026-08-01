#!/usr/bin/env python3
"""
CRUDEOILM (MCX) - live 5M SMA5/SMA200 state bot.

Strategy:
  - Timeframe : broker-native 5 minute candles
  - LONG      : SMA5 is above SMA200
  - SHORT     : SMA5 is below SMA200
  - Product   : Normal ('M'), so MCX positions can carry
  - Monitor   : keeps running during MCX market hours
"""

import time
from datetime import datetime, timedelta
from NorenWebApi import NorenWebApi, ProductType, PriceType, BuyorSell


# ------------------------- credentials -------------------------
userid = "FZ19246"
password = "##"
totp_secret = "35LY6332V5YJ36F5RATW36GJ7J446L43"
app_key = "9e5e9c7220b524ea19a7e6029f5140c423daea49318b23b3b36416549673bac2"

# userid = "FZ31096"
# password = "##"
# totp_secret = "V3B3T3AZ3U6236HO35BQRL6S4KP725O5"
# app_key = "271b7fc4385a31a3855553a29e31af8a1ee91232f3f980aa810197afe58c8ff9"


# ------------------------- instrument / config -------------------------
EXCHANGE = "MCX"
TRADINGSYMBOL = "CRUDEOILM19AUG26"
INTERVAL = "5"
DAYS_BACK = 10

PRODUCT_TYPE = ProductType.Normal
QTY = 1

MARKET_OPEN_H, MARKET_OPEN_M = 9, 15
MARKET_CLOSE_H, MARKET_CLOSE_M = 23, 30
CHECK_INTERVAL_SEC = 300

FAST_SMA = 5
SLOW_SMA = 200

strategy_side = None

api = NorenWebApi()


def login():
    return api.login(
        userid=userid,
        password=password,
        totp_secret=totp_secret,
        app_key=app_key,
    )


def get_token(exchange, tradingsymbol):
    res = api.searchscrip(exchange, tradingsymbol)
    if not res or "values" not in res:
        print(f"Could not resolve token for {tradingsymbol}")
        return None

    for item in res["values"]:
        if item.get("tsym") == tradingsymbol:
            return item.get("token")

    return res["values"][0].get("token")


def get_ohlcv_5m(days_back=DAYS_BACK):
    """Fetch broker-native 5-minute OHLCV candles in chronological order."""
    token = get_token(EXCHANGE, TRADINGSYMBOL)
    if token is None:
        return None

    starttime = (datetime.now() - timedelta(days=days_back)).timestamp()
    data = api.get_time_price_series(
        exchange=EXCHANGE,
        token=token,
        starttime=starttime,
        interval=INTERVAL,
    )

    if data is None:
        print("No OHLCV data returned")
        return None

    return list(reversed(data))


def sma(values, length):
    out = [None] * len(values)
    running_sum = 0.0

    for i, value in enumerate(values):
        running_sum += value
        if i >= length:
            running_sum -= values[i - length]
        if i >= length - 1:
            out[i] = running_sum / length

    return out


def compute_sma_state(candles):
    """
    Return the latest desired position from SMA state.
    This intentionally does not require a fresh crossover, so Monday can
    reconcile an old Friday position if SMA state has already flipped.
    """
    if len(candles) < SLOW_SMA + 1:
        print(f"Not enough candles: {len(candles)} / need {SLOW_SMA + 1}")
        return None

    closes = [float(c["intc"]) for c in candles]
    sma_fast = sma(closes, FAST_SMA)
    sma_slow = sma(closes, SLOW_SMA)

    i = len(candles) - 1

    if sma_fast[i] is None or sma_slow[i] is None:
        return None

    desired_side = None
    if sma_fast[i] > sma_slow[i]:
        desired_side = "LONG"
    elif sma_fast[i] < sma_slow[i]:
        desired_side = "SHORT"

    return {
        "time": candles[i]["time"],
        "close": closes[i],
        "sma_fast": sma_fast[i],
        "sma_slow": sma_slow[i],
        "desired_side": desired_side,
    }


def get_current_side():
    """Returns ('LONG'/'SHORT'/'FLAT', netqty) for the configured symbol."""
    positions = api.get_positions() or []
    if isinstance(positions, dict) or not positions:
        return "FLAT", 0

    for pos in positions:
        if pos.get("tsym") == TRADINGSYMBOL and pos.get("exch") == EXCHANGE:
            netqty = int(pos.get("netqty", 0))
            if netqty > 0:
                return "LONG", netqty
            if netqty < 0:
                return "SHORT", netqty

    return "FLAT", 0


def close_position():
    side, netqty = get_current_side()
    if side == "FLAT" or netqty == 0:
        return True

    trantype = BuyorSell.Sell if netqty > 0 else BuyorSell.Buy
    resp = api.place_order(
        buy_or_sell=trantype,
        product_type=PRODUCT_TYPE,
        exchange=EXCHANGE,
        tradingsymbol=TRADINGSYMBOL,
        quantity=abs(netqty),
        price_type=PriceType.Market,
        price=0.0,
        retention="DAY",
    )

    if resp is None or resp.get("stat") != "Ok":
        print(f"Failed to close {side}: {resp}")
        return False

    print(f"Closed {side} position ({abs(netqty)} qty) | order={resp.get('norenordno')}")
    return True


def enter_long(qty=QTY):
    resp = api.place_order(
        buy_or_sell=BuyorSell.Buy,
        product_type=PRODUCT_TYPE,
        exchange=EXCHANGE,
        tradingsymbol=TRADINGSYMBOL,
        quantity=qty,
        price_type=PriceType.Market,
        price=0.0,
        retention="DAY",
    )

    if resp is None or resp.get("stat") != "Ok":
        print(f"Failed to enter LONG: {resp}")
        return None

    print(f"Entered LONG {qty} | order={resp.get('norenordno')}")
    return resp


def enter_short(qty=QTY):
    resp = api.place_order(
        buy_or_sell=BuyorSell.Sell,
        product_type=PRODUCT_TYPE,
        exchange=EXCHANGE,
        tradingsymbol=TRADINGSYMBOL,
        quantity=qty,
        price_type=PriceType.Market,
        price=0.0,
        retention="DAY",
    )

    if resp is None or resp.get("stat") != "Ok":
        print(f"Failed to enter SHORT: {resp}")
        return None

    print(f"Entered SHORT {qty} | order={resp.get('norenordno')}")
    return resp


def sync_position_to_sma(desired_side):
    side, netqty = get_current_side()

    if desired_side == "LONG":
        if side == "SHORT":
            print("SMA state LONG - closing SHORT, entering LONG")
            if close_position():
                enter_long(QTY)
        elif side == "FLAT":
            print("SMA state LONG - entering LONG")
            enter_long(QTY)
        else:
            print("SMA state LONG - already LONG, holding")

    elif desired_side == "SHORT":
        if side == "LONG":
            print("SMA state SHORT - closing LONG, entering SHORT")
            if close_position():
                enter_short(QTY)
        elif side == "FLAT":
            print("SMA state SHORT - entering SHORT")
            enter_short(QTY)
        else:
            print("SMA state SHORT - already SHORT, holding")


def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:
        return False

    open_t = now.replace(hour=MARKET_OPEN_H, minute=MARKET_OPEN_M, second=0, microsecond=0)
    close_t = now.replace(hour=MARKET_CLOSE_H, minute=MARKET_CLOSE_M, second=0, microsecond=0)
    return open_t <= now <= close_t


def monitor_once():
    global strategy_side

    candles = get_ohlcv_5m(DAYS_BACK)
    if not candles:
        print("Skipping - no candle data")
        return

    state = compute_sma_state(candles)
    if state is None:
        return

    side, netqty = get_current_side()
    desired_text = state["desired_side"] if state["desired_side"] else "NEUTRAL"
    print(
        f"{state['time']} | close={state['close']:.2f} | "
        f"SMA{FAST_SMA}={state['sma_fast']:.2f} | SMA{SLOW_SMA}={state['sma_slow']:.2f} | "
        f"desired={desired_text} | pos={side}({netqty})"
    )

    if state["desired_side"] is None:
        return

    if strategy_side is None:
        strategy_side = state["desired_side"]
        print(f"Initial code state set to {strategy_side} - no trade until next flip")
        return

    if state["desired_side"] == strategy_side:
        print(f"Code state still {strategy_side} - no trade")
        return

    old_side = strategy_side
    strategy_side = state["desired_side"]
    print(f"Code state flipped {old_side} -> {strategy_side}")
    sync_position_to_sma(strategy_side)


def monitor_loop():
    print("Monitor started - 5M SMA5/SMA200 variable-state flips, Mon-Fri 09:15-23:30 IST")
    while True:
        try:
            if not is_market_open():
                print(f"[{datetime.now().strftime('%a %H:%M:%S')}] Market closed - sleeping 60s")
                time.sleep(60)
                continue

            monitor_once()
            time.sleep(CHECK_INTERVAL_SEC)

        except KeyboardInterrupt:
            print("Stopped by user.")
            break
        except Exception as e:
            print(f"Error in monitor loop: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(30)


if __name__ == "__main__":
    login()
    monitor_loop()
