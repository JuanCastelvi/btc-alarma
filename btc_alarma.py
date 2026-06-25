TELEGRAM_TOKEN = "8803309738:AAEJOzKpWJSQM_OJSAPUcwmSatWxKrHgqQI"
TELEGRAM_CHAT_ID = "8728510954"

import requests, time
from datetime import datetime, timezone

# ─── PARÁMETROS MODO A: Caída sostenida ───────────────────────────
A_DROP_MIN_PCT    = 3.0   # Caída total mínima (%)
A_DROP_DUR_MIN_H  = 2.0   # Duración mínima continua (horas)
A_TOLERANCE_PCT   = 0.8   # Tolerancia rebote interno (%)

# ─── PARÁMETROS MODO B: Caída rápida ──────────────────────────────
B_DROP_MIN_PCT    = 5.0   # Caída mínima (%) en pocas velas
B_WINDOW_BARS     = 8     # Ventana máxima de velas (8 x 15m = 2 horas)

# ─── GENERAL ──────────────────────────────────────────────────────
CHECK_INTERVAL_S  = 60
COOLDOWN_S        = 4 * 3600
# ──────────────────────────────────────────────────────────────────

A_DROP_DUR_MIN_BARS = max(1, int(A_DROP_DUR_MIN_H * 4))
last_alert_ts = 0

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        print(f"Error Telegram: {e}")

def get_candles():
    try:
        url = "https://api.kucoin.com/api/v1/market/candles?type=15min&symbol=BTC-USDT&limit=80"
        r = requests.get(url, timeout=15)
        data = r.json()
        if data.get("code") == "200000":
            raw = data["data"]
            raw.reverse()
            candles = [[int(c[0])*1000, c[1], c[3], c[4], c[2], c[5]] for c in raw]
            return candles
    except Exception as e:
        print(f"Error KuCoin: {e}")

    try:
        url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=15"
        r = requests.get(url, timeout=15)
        data = r.json()
        if not data.get("error"):
            raw = data["result"]["XXBTZUSD"]
            candles = [[c[0]*1000, c[1], c[2], c[3], c[4], c[6]] for c in raw[-80:]]
            return candles
    except Exception as e:
        print(f"Error Kraken: {e}")

    return None

def detect_sustained_drop(candles):
    """Modo A: caída continua durante varias horas"""
    if not candles or len(candles) < 10:
        return False, None
    try:
        closes = [float(c[4]) for c in candles]
        lows   = [float(c[3]) for c in candles]
        times  = [c[0] for c in candles]

        i = len(closes) - 1
        drop_end_idx = i
        current_low = min(closes[i], lows[i])

        while i > 0:
            curr_low = min(closes[i], lows[i])
            if curr_low > current_low * (1 + A_TOLERANCE_PCT / 100):
                break
            if curr_low < current_low:
                current_low = curr_low
            i -= 1

        drop_start_idx = i
        drop_bars = drop_end_idx - drop_start_idx

        if drop_bars < A_DROP_DUR_MIN_BARS:
            return False, None

        start_price = closes[drop_start_idx - 1] if drop_start_idx > 0 else closes[drop_start_idx]
        drop_pct = ((start_price - current_low) / start_price) * 100

        if drop_pct < A_DROP_MIN_PCT:
            return False, None

        return True, {
            "modo": "A",
            "modo_label": "Caída sostenida",
            "drop_pct":      round(drop_pct, 2),
            "drop_dur_h":    round(drop_bars * 0.25, 2),
            "start_price":   round(start_price, 1),
            "current_low":   round(current_low, 1),
            "current_price": round(closes[-1], 1),
            "drop_bars":     drop_bars,
            "start_time":    datetime.fromtimestamp(times[drop_start_idx]/1000, tz=timezone.utc).strftime('%H:%M UTC'),
        }
    except Exception as e:
        print(f"Error detección A: {e}")
        return False, None

def detect_fast_drop(candles):
    """Modo B: caída brusca en pocas velas"""
    if not candles or len(candles) < B_WINDOW_BARS + 2:
        return False, None
    try:
        closes = [float(c[4]) for c in candles]
        highs  = [float(c[2]) for c in candles]
        lows   = [float(c[3]) for c in candles]
        times  = [c[0] for c in candles]

        # Miramos las últimas B_WINDOW_BARS velas
        window_start = len(candles) - B_WINDOW_BARS
        window_high = max(highs[window_start:])
        window_low  = min(lows[window_start:])
        current_price = closes[-1]

        # El high tiene que ser reciente (dentro de la ventana)
        high_idx = highs.index(window_high, window_start)
        low_idx  = lows.index(window_low, window_start)

        # El máximo tiene que venir ANTES que el mínimo
        if high_idx >= low_idx:
            return False, None

        drop_pct = ((window_high - window_low) / window_high) * 100

        if drop_pct < B_DROP_MIN_PCT:
            return False, None

        # La caída tiene que ser reciente: el mínimo en las últimas 3 velas
        if low_idx < len(candles) - 3:
            return False, None

        drop_bars = low_idx - high_idx
        drop_dur_h = round(drop_bars * 0.25, 2)

        return True, {
            "modo": "B",
            "modo_label": "Caída rápida",
            "drop_pct":      round(drop_pct, 2),
            "drop_dur_h":    drop_dur_h,
            "start_price":   round(window_high, 1),
            "current_low":   round(window_low, 1),
            "current_price": round(current_price, 1),
            "drop_bars":     drop_bars,
            "start_time":    datetime.fromtimestamp(times[high_idx]/1000, tz=timezone.utc).strftime('%H:%M UTC'),
        }
    except Exception as e:
        print(f"Error detección B: {e}")
        return False, None

def fmt_alert(info):
    recov_min = round(info['drop_pct'] * 0.4, 1)
    recov_max = round(info['drop_pct'] * 0.6, 1)
    emoji = "⚡" if info['modo'] == "B" else "📉"
    return (
        f"🚨 <b>ALERTA BTC — {info['modo_label']}</b>\n\n"
        f"{emoji} Caída: <b>-{info['drop_pct']}%</b> en <b>{info['drop_dur_h']}h</b>\n"
        f"🕐 Inicio: {info['start_time']}\n"
        f"💰 Precio inicio: <b>${info['start_price']:,}</b>\n"
        f"📍 Precio mínimo: <b>${info['current_low']:,}</b>\n"
        f"📊 Precio actual: <b>${info['current_price']:,}</b>\n"
        f"🕯 Velas: <b>{info['drop_bars']}</b>\n\n"
        f"⚡ Rebote estimado: <b>+{recov_min}% a +{recov_max}%</b>\n"
        f"⚠️ No es asesoramiento financiero."
    )

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

# ─── MAIN ─────────────────────────────────────────────────────────
log("🤖 Bot BTC iniciado v4 — Modo A (sostenida) + Modo B (rápida)")
send_telegram("✅ <b>Bot BTC v4 iniciado</b>\n🔍 Modo A: caída sostenida\n⚡ Modo B: caída rápida ≥5% en pocas velas")

while True:
    try:
        candles = get_candles()
        if candles is None:
            log("⚠ Sin datos, reintentando...")
            time.sleep(CHECK_INTERVAL_S)
            continue

        now_ts = time.time()
        alerted = False

        # Modo B primero (más urgente — caída rápida)
        det_b, info_b = detect_fast_drop(candles)
        if det_b and now_ts - last_alert_ts > COOLDOWN_S:
            log(f"⚡ MODO B — caída rápida {info_b['drop_pct']}% en {info_b['drop_bars']} velas")
            send_telegram(fmt_alert(info_b))
            last_alert_ts = now_ts
            alerted = True

        # Modo A (caída sostenida)
        if not alerted:
            det_a, info_a = detect_sustained_drop(candles)
            if det_a and now_ts - last_alert_ts > COOLDOWN_S:
                log(f"📉 MODO A — caída sostenida {info_a['drop_pct']}% en {info_a['drop_dur_h']}h")
                send_telegram(fmt_alert(info_a))
                last_alert_ts = now_ts
                alerted = True

        if not alerted:
            log(f"OK — sin patrón. Precio: ${float(candles[-1][4]):,.0f}")

    except Exception as e:
        log(f"❌ Error: {e}")

    time.sleep(CHECK_INTERVAL_S)
