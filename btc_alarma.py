TELEGRAM_TOKEN = "8803309738:AAEJOzKpWJSQM_OJSAPUcwmSatWxKrHgqQI"
TELEGRAM_CHAT_ID = "8728510954"

import requests, time, json
from datetime import datetime, timezone

# ─── PARÁMETROS DEL PATRÓN (ajustables) ───────────────────────────
DROP_MIN_PCT      = 3.0   # Caída mínima total (%)
DROP_DUR_MIN_H    = 2.0   # Duración mínima de caída continua (horas)
TOLERANCE_PCT     = 0.8   # Máx rebote permitido dentro de la caída (%)
RECOV_MIN_PCT     = 2.0   # Recuperación mínima esperada (%)
CHECK_INTERVAL_S  = 60    # Chequea cada 60 segundos
# ──────────────────────────────────────────────────────────────────

DROP_DUR_MIN_BARS = max(1, int(DROP_DUR_MIN_H * 4))
SYMBOL = "BTCUSDT"
INTERVAL = "15m"
last_alert_ts = 0
COOLDOWN_S = 4 * 3600  # No repetir alerta por 4 horas

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"})

def get_candles(limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={INTERVAL}&limit={limit}"
    r = requests.get(url, timeout=10)
    return r.json()

def detect_sustained_drop(candles):
    """
    Recorre las últimas velas buscando si HAY UNA caída continua activa AHORA.
    Retorna (True, info_dict) si detecta el patrón, (False, None) si no.
    """
    closes = [float(c[4]) for c in candles]
    lows   = [float(c[3]) for c in candles]
    times  = [c[0] for c in candles]

    # Buscar desde la vela más reciente hacia atrás
    i = len(closes) - 1
    drop_end_idx = i
    current_low = min(closes[i], lows[i])

    while i > 0:
        prev_close = closes[i - 1]
        curr_low   = min(closes[i], lows[i])

        # ¿Sigue bajando (con tolerancia)?
        if curr_low > current_low * (1 + TOLERANCE_PCT / 100):
            break

        if curr_low < current_low:
            current_low = curr_low
        i -= 1

    drop_start_idx = i
    drop_bars = drop_end_idx - drop_start_idx

    if drop_bars < DROP_DUR_MIN_BARS:
        return False, None

    start_price = closes[drop_start_idx - 1] if drop_start_idx > 0 else closes[drop_start_idx]
    drop_pct = ((start_price - current_low) / start_price) * 100

    if drop_pct < DROP_MIN_PCT:
        return False, None

    drop_dur_h = drop_bars * 0.25

    return True, {
        "drop_pct":    round(drop_pct, 2),
        "drop_dur_h":  round(drop_dur_h, 2),
        "start_price": round(start_price, 1),
        "current_low": round(current_low, 1),
        "current_price": round(closes[-1], 1),
        "drop_bars":   drop_bars,
        "start_time":  datetime.fromtimestamp(times[drop_start_idx]/1000, tz=timezone.utc).strftime('%H:%M UTC'),
    }

def fmt_alert(info):
    bars = info['drop_bars']
    recov_est_min = round(info['drop_pct'] * 0.4, 1)
    recov_est_max = round(info['drop_pct'] * 0.6, 1)
    return (
        f"🚨 <b>ALERTA BTC — Caída sostenida detectada</b>\n\n"
        f"📉 Caída: <b>-{info['drop_pct']}%</b> en <b>{info['drop_dur_h']}h continuas</b>\n"
        f"🕐 Inicio caída: {info['start_time']}\n"
        f"💰 Precio inicio: <b>${info['start_price']:,}</b>\n"
        f"📍 Precio mínimo: <b>${info['current_low']:,}</b>\n"
        f"📊 Precio actual: <b>${info['current_price']:,}</b>\n"
        f"🕯 Velas consecutivas bajando: <b>{bars}</b>\n\n"
        f"⚡ Rebote histórico estimado: <b>+{recov_est_min}% a +{recov_est_max}%</b>\n"
        f"⚠️ Esto no es asesoramiento financiero. Evaluá antes de operar."
    )

def log(msg):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

# ─── MAIN LOOP ────────────────────────────────────────────────────
log("🤖 Bot de alarma BTC iniciado")
send_telegram("✅ <b>Bot BTC iniciado</b>\nMonitoreando caídas sostenidas en BTC/USDT 15m...")

while True:
    try:
        candles = get_candles(limit=80)
        detected, info = detect_sustained_drop(candles)

        now_ts = time.time()
        if detected:
            log(f"⚠ Patrón detectado — caída {info['drop_pct']}% en {info['drop_dur_h']}h")
            if now_ts - last_alert_ts > COOLDOWN_S:
                send_telegram(fmt_alert(info))
                last_alert_ts = now_ts
                log("✅ Alerta enviada a Telegram")
            else:
                log("⏳ En cooldown, no se reenvía alerta")
        else:
            log(f"OK — sin patrón. Precio actual: ${float(candles[-1][4]):,.0f}")

    except Exception as e:
        log(f"❌ Error: {e}")

    time.sleep(CHECK_INTERVAL_S)