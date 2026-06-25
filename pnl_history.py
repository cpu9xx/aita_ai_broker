"""Account PnL history recording and return-chart generation.

Records are stored in pnl/pnl_history.json in the account's base currency:
{
    "DUK115534": {
        "_currency": "HKD",
        "2026-06-20": 780000.00,
        "2026-06-23": 785000.00
    }
}

Today-PnL and chart are always displayed in USD.
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

PERSIST_DIR = Path(__file__).resolve().parent
HISTORY_FILE = PERSIST_DIR / "pnl" / "pnl_history.json"
CHART_FILE = PERSIST_DIR / "pnl" / "return_chart.png"

USDHKD_FALLBACK = 7.8


def load_history(account):
    if not HISTORY_FILE.exists():
        return {}
    with HISTORY_FILE.open("r") as f:
        data = json.load(f)
    return data.get(account, {})


def save_history(account, records):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if HISTORY_FILE.exists():
        with HISTORY_FILE.open("r") as f:
            data = json.load(f)
    data[account] = records
    with HISTORY_FILE.open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    print(f"pnl_history: saved {len(records) - 1} records for {account}", flush=True)


def record_today(account, raw_liq, currency):
    import pandas_market_calendars as mcal

    nyse = mcal.get_calendar("NYSE")
    today = pd.Timestamp.now().normalize()
    yesterday = today - pd.Timedelta(days=1)
    schedule = nyse.schedule(start_date=yesterday - pd.Timedelta(days=7), end_date=yesterday)
    last_trading_day = schedule.index[-1].strftime("%Y-%m-%d")

    records = load_history(account)
    records["_currency"] = currency
    records[last_trading_day] = raw_liq
    save_history(account, records)
    return records


def _previous_net_liq(records):
    dates = sorted(d for d in records if d != "_currency")
    if len(dates) < 2:
        return None, None
    return dates[-2], records[dates[-2]]


def today_pnl(account, net_liq_usd):
    records = load_history(account)
    prev_date, prev_raw = _previous_net_liq(records)
    if prev_date is None:
        return None, None
    abs_pnl = net_liq_usd - _to_usd(prev_raw, records.get("_currency", "USD"))
    pct_return = (net_liq_usd / _to_usd(prev_raw, records.get("_currency", "USD")) - 1) * 100
    return abs_pnl, pct_return


def _to_usd(raw_value, currency):
    if currency == "USD":
        return raw_value
    return raw_value / USDHKD_FALLBACK


def fetch_spx_benchmark(ib, start_date_str):
    from ib_async import Index
    contract = Index("SPX", "CBOE", "USD")
    ib.qualifyContracts(contract)
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",
        durationStr="2 Y",
        barSizeSetting="1 day",
        whatToShow="TRADES",
        useRTH=True,
        formatDate=1,
    )
    if not bars:
        return None
    rows = [{"date": b.date, "close": b.close} for b in bars]
    df = pd.DataFrame(rows).dropna()
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= pd.to_datetime(start_date_str)]
    return df


def generate_benchmark_chart(account, net_liq_usd, ib):
    records = load_history(account)
    currency = records.get("_currency", "USD")
    dates = sorted(d for d in records if d != "_currency")
    if len(dates) < 2:
        return None

    rows = [{"date": d, "net_liq_usd": _to_usd(records[d], currency)} for d in dates]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    initial = df["net_liq_usd"].iloc[0]
    df["return"] = (df["net_liq_usd"] / initial - 1) * 100

    spx_df = fetch_spx_benchmark(ib, df["date"].iloc[0].strftime("%Y-%m-%d"))
    fig, ax = plt.subplots(figsize=(10, 5))

    ax.plot(df["date"], df["return"], color="#1f77b4", linewidth=1.8, label=account)
    if spx_df is not None and not spx_df.empty:
        spx_initial = spx_df["close"].iloc[0]
        spx_df["return"] = (spx_df["close"] / spx_initial - 1) * 100
        ax.plot(spx_df["date"], spx_df["return"], color="#d62728", linewidth=1.8, label="SPX")

    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_ylabel("Cumulative Return (%)")
    ax.set_title(f"{account} vs SPX")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.autofmt_xdate()
    plt.tight_layout()

    CHART_FILE.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(CHART_FILE), dpi=120)
    plt.close(fig)
    return str(CHART_FILE)
