import json
import math
import time
from pathlib import Path

import userConfig
from ib_interaction import (
    IBConnectionPool,
    OrderIdPool,
    cancel_all_orders,
    make_stock_contract,
    place_limit_order,
    place_market_order,
    place_open_limit_order,
    place_open_market_order,
    require_managed_account,
)
from rebalance_report import format_rebalance_report, save_rebalance_report_image, send_rebalance_report


def load_latest_order_file():
    json_files = sorted(Path(".").glob("*.json"), key=lambda path: path.stat().st_mtime)
    if len(json_files) == 0:
        raise FileNotFoundError("No json files found in current directory")
    path = json_files[-1]
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "target_weight" not in data:
        raise KeyError(f"{path} must contain target_weight")
    return path, data


def get_market_price(ib, contract):
    ticker = ib.reqMktData(contract, snapshot=False)
    deadline = time.monotonic() + userConfig.market_data_timeout_seconds
    while time.monotonic() < deadline:
        bid = getattr(ticker, "bid", None)
        ask = getattr(ticker, "ask", None)
        midpoint = None
        if bid is not None and ask is not None and bid == bid and ask == ask and bid > 0 and ask > 0:
            midpoint = (bid + ask) / 2
        prices = [ticker.marketPrice(), getattr(ticker, "last", None), getattr(ticker, "close", None), midpoint]
        valid_prices = [price for price in prices if price is not None and price == price and price > 0]
        if valid_prices:
            ib.cancelMktData(contract)
            return float(valid_prices[0])
        ib.sleep(1)
    ib.cancelMktData(contract)
    raise TimeoutError(f"Market data timed out for {contract}")


def wait_order_accepted(ib, trade, timeout_seconds=60):
    deadline = time.monotonic() + timeout_seconds
    accepted_states = {"PreSubmitted", "Submitted", "Filled", "Cancelled", "Inactive", "ApiCancelled"}
    while time.monotonic() < deadline:
        if trade.orderStatus.status in accepted_states:
            return trade.orderStatus.status
        ib.sleep(1)
    return trade.orderStatus.status


def order_price(action, reference_price):
    if userConfig.order_type == "LOO":
        if action == "BUY":
            return round(reference_price * (1 + userConfig.limit_price_buffer), 2)
        return round(reference_price * (1 - userConfig.limit_price_buffer), 2)
    if userConfig.order_type == "LMT":
        return round(reference_price, 2)
    return None


def place_order(ib, contract, action, quantity, reference_price, account, order_id_pool):
    order_type = userConfig.order_type.upper()
    price = order_price(action, reference_price)
    if order_type == "MKT":
        trade = place_market_order(ib, contract, action, quantity, account, order_id_pool, outside_rth=userConfig.outside_rth)
    elif order_type == "LMT":
        trade = place_limit_order(ib, contract, action, quantity, price, account, order_id_pool, outside_rth=userConfig.outside_rth)
    elif order_type == "MOO":
        trade = place_open_market_order(ib, contract, action, quantity, account, order_id_pool)
    elif order_type == "LOO":
        trade = place_open_limit_order(ib, contract, action, quantity, price, account, order_id_pool)
    else:
        raise ValueError(f"Unsupported order_type: {userConfig.order_type}")
    return trade, price or order_type


def main():
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
        connect_timeout=userConfig.ib_connect_timeout,
        connect_attempts=userConfig.ib_connect_attempts,
        client_id=userConfig.ib_client_id,
        launcher_env={
            "IBC_PATH": str(userConfig.ibc_path),
            "IBC_CONFIG": str(userConfig.ibc_config),
            "TWS_PATH": userConfig.tws_path,
            "IBC_LOG_PATH": str(userConfig.ibc_log_path),
            "TWS_MAJOR_VRSN": str(userConfig.tws_major_version),
            "TRADING_MODE": userConfig.trading_mode,
        },
    ).get_ib()
    ib.sleep(1)
    require_managed_account(ib, account)

    if userConfig.cancel_existing_orders:
        ib.reqOpenOrders()
        ib.sleep(1)
        open_orders = [
            order for order in ib.openOrders()
            if order.account == account and order.clientId == ib.client.clientId
        ]
        if open_orders:
            print(f"existing_orders: canceling current client orders {len(open_orders)}", flush=True)
            cancel_all_orders(ib)
            deadline = time.monotonic() + userConfig.cancel_wait_seconds
            while time.monotonic() < deadline:
                ib.reqOpenOrders()
                ib.sleep(1)
                open_orders = [
                    order for order in ib.openOrders()
                    if order.account == account and order.clientId == ib.client.clientId
                ]
                if not open_orders:
                    break
                ib.sleep(1)
            if open_orders:
                active = [
                    f"orderId={order.orderId} {order.action} {order.totalQuantity:g} {order.orderType} {getattr(order, 'tif', '')}"
                    for order in open_orders
                ]
                raise TimeoutError(f"Current-client orders not cancelled within {userConfig.cancel_wait_seconds}s: {active}")
        else:
            print("existing_orders: none", flush=True)

    account_values = {}
    account_values_source = "accountSummary"
    for item in ib.accountSummary():
        if item.account == account:
            account_values[(item.tag, item.currency)] = item.value
    if not account_values:
        account_values_source = "accountValues"
        for item in ib.accountValues():
            if item.account == account:
                account_values[(item.tag, item.currency)] = item.value
    if not account_values:
        raise KeyError(f"No account values returned for {account}; managed_accounts={ib.managedAccounts()}")

    net_liq_usd = None
    net_liq_hkd = None
    usd_hkd_rate = None
    if ("NetLiquidation", "USD") in account_values:
        net_liq_usd = float(account_values[("NetLiquidation", "USD")])
    elif ("NetLiquidation", "HKD") in account_values:
        net_liq_hkd = float(account_values[("NetLiquidation", "HKD")])
        if ("ExchangeRate", "USD") in account_values:
            usd_hkd_rate = float(account_values[("ExchangeRate", "USD")])
        else:
            usd_hkd_rate = userConfig.usd_hkd_rate_fallback
        net_liq_usd = net_liq_hkd / usd_hkd_rate
    elif ("NetLiquidationByCurrency", "BASE") in account_values and account_values.get(("BaseCurrency", "")) == "USD":
        net_liq_usd = float(account_values[("NetLiquidationByCurrency", "BASE")])
    else:
        available = [
            f"{tag} {currency}={value}"
            for (tag, currency), value in sorted(account_values.items())
            if tag in ("BaseCurrency", "NetLiquidation", "NetLiquidationByCurrency", "ExchangeRate")
        ]
        raise KeyError("Cannot derive USD NetLiquidation from account values: " + "; ".join(available))

    positions = {}
    for position in ib.positions():
        if position.account == account and position.contract.secType == "STK":
            positions[position.contract.symbol] = positions.get(position.contract.symbol, 0) + position.position

    portfolio = {}
    for item in ib.portfolio():
        if item.account == account and item.contract.secType == "STK":
            portfolio[item.contract.symbol] = item

    print(f"order_file: {order_file}", flush=True)
    print(f"account: {account}", flush=True)
    print(f"account_values_source: {account_values_source}", flush=True)
    print(f"net_liq_usd: {net_liq_usd:.2f}", flush=True)
    print(f"enable_trading: {userConfig.enable_trading}", flush=True)
    print(f"order_type: {userConfig.order_type}", flush=True)

    order_id_pool = OrderIdPool(ib)
    trades = []
    position_rows = []

    for symbol in sorted(target_weight):
        contract = make_stock_contract(ib, symbol, exchange=userConfig.stock_exchange, currency=userConfig.stock_currency)
        current_qty = positions.get(symbol, 0)
        price = portfolio[symbol].marketPrice if symbol in portfolio else get_market_price(ib, contract)
        target_value = max(net_liq_usd - userConfig.cash_buffer_usd, 0) * target_weight[symbol] / 100
        target_qty = math.floor(target_value / price)
        diff_qty = target_qty - current_qty
        current_value = current_qty * price
        current_weight = current_value / net_liq_usd * 100 if net_liq_usd else 0
        order_value = abs(diff_qty * price)

        position_rows.append(
            {
                "symbol": symbol,
                "price": price,
                "current_qty": current_qty,
                "market_value_usd": current_value,
                "current_weight": current_weight,
                "target_weight": target_weight[symbol],
                "target_value_usd": target_value,
                "target_qty": target_qty,
                "diff_qty": diff_qty,
            }
        )

        print(
            f"{symbol}: price={price:.2f}, current={current_qty:g}, "
            f"target_weight={target_weight[symbol]:.2f}%, target_shares={target_qty:g}, "
            f"diff={diff_qty:g}, diff_value={order_value:.2f}",
            flush=True,
        )

        if diff_qty == 0 or order_value < userConfig.min_trade_value_usd:
            continue

        action = "BUY" if diff_qty > 0 else "SELL"
        quantity = abs(int(diff_qty))
        trade_record = {
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": order_price(action, price) or userConfig.order_type,
            "order_value_usd": order_value,
            "status": "DRY_RUN",
        }

        if userConfig.enable_trading:
            trade, submitted_price = place_order(ib, contract, action, quantity, price, account, order_id_pool)
            trade_record["price"] = submitted_price
            trade_record["status"] = wait_order_accepted(ib, trade)
            print(f"{symbol}: {action} {quantity} status={trade_record['status']}", flush=True)
        else:
            print(f"{symbol}: DRY_RUN {action} {quantity}", flush=True)

        trades.append(trade_record)

    account_state = {"NetLiquidation USD": f"{net_liq_usd:.2f}"}
    if net_liq_hkd is not None:
        account_state["NetLiquidation HKD"] = f"{net_liq_hkd:.2f}"
    if usd_hkd_rate is not None:
        account_state["USDHKD"] = f"{usd_hkd_rate:.7f}"

    report_text = format_rebalance_report(
        order_file=order_file,
        account=account,
        trade_date=order_data["trade_date"],
        trade_time=order_data["trade_time"],
        account_state=account_state,
        position_rows=position_rows,
        trades=trades,
    )
    report_image = save_rebalance_report_image(
        order_file=order_file,
        account=account,
        trade_date=order_data["trade_date"],
        trade_time=order_data["trade_time"],
        account_state=account_state,
        position_rows=position_rows,
        trades=trades,
    )
    print(f"report_image: {report_image}", flush=True)

    if userConfig.send_rebalance_report:
        send_rebalance_report(report_text, report_image)

    ib.disconnect()


if __name__ == "__main__":
    main()
