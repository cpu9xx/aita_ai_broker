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
import math
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


def _return_stats(df, value_col):
    values = df[value_col].astype(float)
    daily_returns = values.pct_change().dropna()
    total_return = values.iloc[-1] / values.iloc[0] - 1
    elapsed_days = max((df["date"].iloc[-1] - df["date"].iloc[0]).days, 1)
    ann_return = (1 + total_return) ** (365.25 / elapsed_days) - 1
    ann_vol = daily_returns.std() * math.sqrt(252)
    drawdown = values / values.cummax() - 1
    mdd = drawdown.min()
    sharpe = ann_return / ann_vol if ann_vol and ann_vol == ann_vol else None
    return ann_return, ann_vol, mdd, sharpe


def _format_stats(label, stats):
    ann_return, ann_vol, mdd, sharpe = stats
    sharpe_text = "n/a" if sharpe is None else f"{sharpe:.2f}"
    return (
        f"{label:<10} AnnRet {ann_return:>7.2%} | "
        f"AnnVol {ann_vol:>6.2%} | "
        f"MDD {mdd:>7.2%} | "
        f"Sharpe {sharpe_text:>5}"
    )


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

    account_label = _format_stats(account, _return_stats(df, "net_liq_usd"))

    ax.plot(df["date"], df["return"], color="#0072B2", linewidth=1.8, label=account_label)
    if spx_df is not None and not spx_df.empty:
        spx_initial = spx_df["close"].iloc[0]
        spx_df["return"] = (spx_df["close"] / spx_initial - 1) * 100
        spx_label = _format_stats("SPX", _return_stats(spx_df, "close"))
        ax.plot(spx_df["date"], spx_df["return"], color="#E69F00", linewidth=1.8, label=spx_label)

    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.set_ylabel("Cumulative Return (%)")
    ax.set_title(f"{account} vs SPX")
    ax.legend(loc="upper left", prop={"family": "monospace", "size": 8})
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    fig.autofmt_xdate()
    plt.tight_layout()

    CHART_FILE.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(CHART_FILE), dpi=120)
    plt.close(fig)
    return str(CHART_FILE)
