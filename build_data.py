#!/usr/bin/env python3
"""build_data.py — AI関連銘柄の多様体  日次データ取得バッチ
54銘柄の株価・前日比・時価総額をyfinanceで取得し data.json を出力する。
"""
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yfinance as yf

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

SCRIPT_DIR = Path(__file__).parent
DATA_PATH  = SCRIPT_DIR / "data.json"

JST            = timezone(timedelta(hours=9))
MAX_RETRIES    = 5
RETRY_INTERVAL = 10  # 秒

# 54銘柄（ユニーク）。yfinanceティッカーは末尾に .T を付ける
STOCK_CODES = [
    # 島1 AI
    "9432", "9433", "6702", "6701", "6758", "9984",
    # 島2 半導体
    "285A", "6723", "6526",
    # 島3 製造装置
    "8035", "6920", "6857", "6146", "7735", "6525", "6315", "6323", "6254", "7751", "7731",
    # 島4 材料
    "4063", "3436", "4004", "4062", "7741", "5384", "3110", "6855", "6890",
    # 島5 電子部品
    "6981", "6976", "6762", "6971", "6479", "6997", "6779", "5344", "6787",
    # 島6 電線
    "5803", "5801", "5802",
    # 島7 パワー半導体
    "6963", "6504", "6503",
    # 島8 フィジカルAI
    "6861", "6954", "6506", "6273", "6324", "6594", "6645",
    # 島9 データセンター
    "3778", "3905", "6501",
]


def now_jst():
    return datetime.now(JST)


def jst_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def load_prev():
    if DATA_PATH.exists():
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(data):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _mcap_trillion(t):
    """時価総額（兆円）。取得できなければ None。"""
    # fast_info (yfinance >= 0.2.x)
    try:
        mc = t.fast_info.market_cap
        if mc and mc > 0:
            return round(float(mc) / 1e12, 4)
    except Exception:
        pass
    # 旧 API / フォールバック
    try:
        mc = t.info.get("marketCap")
        if mc and mc > 0:
            return round(float(mc) / 1e12, 4)
    except Exception:
        pass
    return None


def fetch_one(code):
    """(price, change_pct, mcap_trillion, date_str) を返す。失敗時は (None, None, None, None)。"""
    ticker_str = f"{code}.T"
    for attempt in range(MAX_RETRIES):
        try:
            t    = yf.Ticker(ticker_str)
            hist = t.history(period="5d")
            if hist.empty:
                raise ValueError("empty history")
            closes = hist["Close"].dropna()
            if closes.empty:
                raise ValueError("all NaN")

            price    = round(float(closes.iloc[-1]), 2)
            date_str = str(closes.index[-1].date())

            chg_pct = None
            if len(closes) >= 2:
                prev = float(closes.iloc[-2])
                if prev:
                    chg_pct = round((price - prev) / abs(prev) * 100, 4)

            mcap = _mcap_trillion(t)
            return price, chg_pct, mcap, date_str

        except Exception as e:
            print(f"  {code} attempt {attempt+1}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_INTERVAL)

    return None, None, None, None


def main():
    generated_at = now_jst()
    prev         = load_prev()
    prev_stocks  = prev.get("stocks", {})

    stocks_out = {}
    any_fail = any_stale = False

    for code in STOCK_CODES:
        p0 = prev_stocks.get(code, {})
        price, chg, mcap, date = fetch_one(code)

        if price is not None:
            status = "ok"
            mcap_disp = f"{mcap}T" if mcap is not None else "—"
            print(f"  {code:5s}  {price:>10.1f}  {(chg or 0):+.2f}%  mcap={mcap_disp}  [{date}]")
        else:
            # 前回値でフォールバック
            price = p0.get("price")
            chg   = p0.get("change_pct")
            mcap  = p0.get("mcap_trillion")
            date  = p0.get("date")
            if price is not None:
                status     = "stale"
                any_stale  = True
                print(f"  {code:5s}  [STALE] {price}")
            else:
                status   = "failed"
                any_fail = True
                print(f"  {code:5s}  [FAILED]")

        stocks_out[code] = {
            "price":         price,
            "change_pct":    chg,
            "mcap_trillion": mcap,
            "date":          date,
            "status":        status,
        }

    overall = "partial" if (any_fail or any_stale) else "complete"
    output  = {
        "_meta": {
            "schema_version": "1.0",
            "generated_at":   jst_iso(generated_at),
            "overall_status": overall,
        },
        "stocks": stocks_out,
    }
    save(output)
    tag = "OK" if overall == "complete" else "WARN"
    print(f"[{tag}] data.json 書き出し完了  overall={overall}  {jst_iso(generated_at)}")


if __name__ == "__main__":
    main()
