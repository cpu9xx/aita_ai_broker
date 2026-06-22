import json
from pathlib import Path

from ib_interaction import IBConnectionPool, require_managed_account
import userConfig


def load_latest_order_file():
    json_files = sorted(Path(".").glob("*.json"), key=lambda path: path.stat().st_mtime)
    if len(json_files) == 0:
        raise FileNotFoundError("No json files found in current directory")
    path = json_files[-1]
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return path, data


def account_values_by_tag(account_values, account):
    result = {}
    for item in account_values:
        if item.account != account:
            continue
        result[(item.tag, item.currency)] = item.value
    return result


def stock_positions_by_symbol(positions, account):
    result = {}
    for position in positions:
        if position.account != account:
            continue
        if position.contract.secType != "STK":
            continue
        symbol = position.contract.symbol
        result[symbol] = result.get(symbol, 0) + position.position
    return result


def portfolio_by_symbol(portfolio_items, account):
    result = {}
    for item in portfolio_items:
        if item.account != account:
            continue
        if item.contract.secType != "STK":
            continue
        result[item.contract.symbol] = item
    return result


def print_account_item(values, tag, currency="USD"):
    value = values.get((tag, currency), "")
    print(f"{tag} {currency}: {value}")


def read_float(values, tag, currency):
    value = values.get((tag, currency), "")
    if value == "":
        return None
    return float(value)


order_file, order_data = load_latest_order_file()
account = userConfig.account
target_weight = order_data["target_weight"]

ib = IBConnectionPool(
    host=userConfig.ib_host,
    port=userConfig.ib_port,
    delayed_data=userConfig.delayed_data,
    gateway_bat=userConfig.gateway_bat,
    gateway_wait_seconds=userConfig.gateway_wait_seconds,
    gateway_poll_seconds=userConfig.gateway_poll_seconds,
).get_ib()
ib.sleep(1)
managed_accounts = require_managed_account(ib, account)

account_values = account_values_by_tag(ib.accountValues(), account)
positions = stock_positions_by_symbol(ib.positions(), account)
portfolio = portfolio_by_symbol(ib.portfolio(), account)
usd_hkd_rate = read_float(account_values, "ExchangeRate", "USD")
net_liq_hkd = read_float(account_values, "NetLiquidation", "HKD")
net_liq_usd = net_liq_hkd / usd_hkd_rate

print(f"order_file: {order_file}")
print(f"managed_accounts: {managed_accounts}")
print(f"account: {account}")
print(f"trade_date: {order_data['trade_date']}")
print(f"trade_time: {order_data['trade_time']}")
print("")
print("account_state")
for currency in ("BASE", "USD", "HKD"):
    print_account_item(account_values, "NetLiquidation", currency)
    print_account_item(account_values, "TotalCashValue", currency)
    print_account_item(account_values, "AvailableFunds", currency)
    print_account_item(account_values, "BuyingPower", currency)
    print_account_item(account_values, "ExchangeRate", currency)
print(f"NetLiquidation USD converted: {net_liq_usd:.2f}")
print("")
print("current_stock_positions")
for symbol in sorted(portfolio):
    item = portfolio[symbol]
    cost_value = item.averageCost * item.position
    holding_return = item.unrealizedPNL / cost_value if cost_value != 0 else 0
    current_weight = item.marketValue / net_liq_usd * 100
    print(
        f"{symbol}: shares={item.position:g}, market_value_usd={item.marketValue:.2f}, "
        f"weight={current_weight:.2f}%, avg_cost={item.averageCost:.4f}, "
        f"unrealized_pnl={item.unrealizedPNL:.2f}, holding_return={holding_return:.2%}, "
        f"holding_days=N/A"
    )
print("")
print("rebalance_target")
for symbol in sorted(target_weight):
    item = portfolio.get(symbol)
    current_shares = positions.get(symbol, 0)
    current_value = item.marketValue if item is not None else 0
    current_weight = current_value / net_liq_usd * 100
    target_value = net_liq_usd * target_weight[symbol] / 100
    diff_value = target_value - current_value
    print(
        f"{symbol}: current_shares={current_shares:g}, current_weight={current_weight:.2f}%, "
        f"target_weight={target_weight[symbol]:.2f}%, target_value_usd={target_value:.2f}, "
        f"diff_value_usd={diff_value:.2f}"
    )

ib.disconnect()
