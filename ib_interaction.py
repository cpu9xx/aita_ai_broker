import math
import random
import socket
import subprocess
import time
from pathlib import Path

from ib_async import IB, OrderStatus, StartupFetch, Stock, LimitOrder, MarketOrder


class IBConnectionPool:
    def __init__(
        self,
        port=4002,
        host="127.0.0.1",
        delayed_data=True,
        max_clients=20,
        gateway_bat=None,
        gateway_wait_seconds=180,
        gateway_poll_seconds=5,
        connect_timeout=4,
        connect_attempts=30,
        client_id=None,
        launcher_env=None,
    ):
        self.host = host
        self.port = port
        self.delayed_data = delayed_data
        self.max_clients = max_clients
        self.gateway_bat = gateway_bat
        self.gateway_wait_seconds = gateway_wait_seconds
        self.gateway_poll_seconds = gateway_poll_seconds
        self.connect_timeout = connect_timeout
        self.connect_attempts = connect_attempts
        self.client_id = client_id
        self.launcher_env = launcher_env or {}
        self.used_client_ids = set()
        self.connected_ibs = []

    def release_idle_ib(self):
        for ib in list(self.connected_ibs):
            if not ib.isConnected():
                self.used_client_ids.discard(ib.client.clientId)
                self.connected_ibs.remove(ib)

    def get_client_id(self):
        if self.client_id is not None:
            if self.client_id in self.used_client_ids:
                raise ValueError(f"Configured clientId is already in use: {self.client_id}")
            self.used_client_ids.add(self.client_id)
            return self.client_id

        if len(self.used_client_ids) >= self.max_clients:
            self.release_idle_ib()
            if len(self.used_client_ids) >= self.max_clients:
                raise ValueError(f"All available clientIds are in use: {self.max_clients}")

        for _ in range(30):
            client_id = random.randint(1, 10_000_000)
            if client_id not in self.used_client_ids:
                self.used_client_ids.add(client_id)
                return client_id

        raise TimeoutError("Getting available clientId timed out")

    def get_ib(self):
        if self.gateway_bat is not None:
            ensure_gateway_online(
                host=self.host,
                port=self.port,
                gateway_bat=self.gateway_bat,
                wait_seconds=self.gateway_wait_seconds,
                poll_seconds=self.gateway_poll_seconds,
                launcher_env=self.launcher_env,
            )

        client_id = self.get_client_id()
        ib = IB()

        print(f"Connecting IB {self.host}:{self.port} clientId={client_id}", flush=True)
        for _ in range(self.connect_attempts):
            try:
                ib.connect(
                    self.host,
                    self.port,
                    clientId=client_id,
                    timeout=self.connect_timeout,
                    fetchFields=StartupFetch(0),
                )
                ib.sleep(2)
            except Exception as e:
                print(f"clientId {client_id} connect failed: {e}", flush=True)

            if ib.isConnected():
                self.connected_ibs.append(ib)
                if self.delayed_data:
                    ib.reqMarketDataType(3)
                print(f"IB connected clientId={client_id}", flush=True)
                return ib

            print("waiting IB connected...", flush=True)
            time.sleep(0.7 + random.uniform(0.5, 1))

        raise TimeoutError("Connecting to IB timed out")


class PositionPool:
    def __init__(self, ib, account, contract_filter=None):
        self.ib = ib
        self.account = account
        self.contract_filter = contract_filter
        self.positions = {}
        self.update()

    def update(self):
        positions = {}
        for position in self.ib.positions():
            if position.account != self.account:
                continue
            if self.contract_filter is not None and not self.contract_filter(position.contract):
                continue
            key = contract_key(position.contract)
            positions[key] = positions.get(key, 0) + position.position
        self.positions = positions
        return positions

    def get(self, contract_or_key):
        key = contract_or_key if isinstance(contract_or_key, str) else contract_key(contract_or_key)
        return self.positions.get(key, 0)


class OrderIdPool:
    def __init__(self, ib):
        self.ib = ib
        self.next_order_id = ib.client.getReqId()

    def get(self):
        self.next_order_id += 1
        return self.next_order_id


def contract_key(contract):
    sec_type = getattr(contract, "secType", "")
    symbol = getattr(contract, "symbol", "")
    exchange = getattr(contract, "exchange", "")
    currency = getattr(contract, "currency", "")
    con_id = getattr(contract, "conId", 0)
    return f"{sec_type}:{symbol}:{exchange}:{currency}:{con_id}"


def make_stock_contract(ib, symbol, exchange="SMART", currency="USD", qualify=True):
    contract = Stock(symbol, exchange, currency)
    if qualify:
        qualified = ib.qualifyContracts(contract)
        if len(qualified) != 1:
            raise ValueError(f"Expected exactly one qualified contract for {symbol}, got {len(qualified)}")
        contract = qualified[0]
    return contract


def req_mkt_data(ib, contract, snapshot=False, generic_tick_list=""):
    for _ in range(20):
        try:
            tick = ib.reqMktData(contract, genericTickList=generic_tick_list, snapshot=snapshot)
            if not snapshot:
                return tick

            ib.sleep(1)
            if not _is_nan(tick.bid) and not _is_nan(tick.ask):
                return tick
            raise TimeoutError("empty tick")
        except Exception as e:
            print(f"IB get tick failed: {e}, retrying...")
            time.sleep(1)

    raise TimeoutError(f"IB get tick timed out: {contract}")


def place_limit_order(ib, contract, action, quantity, price, account, order_id_pool, outside_rth=True):
    order = LimitOrder(
        action=action,
        totalQuantity=quantity,
        lmtPrice=price,
        orderId=order_id_pool.get(),
        outsideRth=outside_rth,
        account=account,
    )
    return ib.placeOrder(contract, order)


def place_market_order(ib, contract, action, quantity, account, order_id_pool, outside_rth=False):
    order = MarketOrder(
        action=action,
        totalQuantity=quantity,
        orderId=order_id_pool.get(),
        outsideRth=outside_rth,
        account=account,
    )
    return ib.placeOrder(contract, order)


def place_open_market_order(ib, contract, action, quantity, account, order_id_pool):
    order = MarketOrder(
        action=action,
        totalQuantity=quantity,
        orderId=order_id_pool.get(),
        outsideRth=False,
        account=account,
    )
    order.tif = "OPG"
    return ib.placeOrder(contract, order)


def place_open_limit_order(ib, contract, action, quantity, price, account, order_id_pool):
    order = LimitOrder(
        action=action,
        totalQuantity=quantity,
        lmtPrice=price,
        orderId=order_id_pool.get(),
        outsideRth=False,
        account=account,
    )
    order.tif = "OPG"
    return ib.placeOrder(contract, order)


def wait_order_submitted(ib, trade, price):
    start = time.time()
    done_states = {"Cancelled", "Filled", "Inactive", "ApiCancelled"}

    while trade.orderStatus.status != "Submitted" or not math.isclose(trade.order.lmtPrice, price):
        if trade.orderStatus.status in done_states:
            return trade.orderStatus.status, time.time() - start
        ib.sleep(0.01)

    return trade.orderStatus.status, time.time() - start


def cancel_trade(ib, trade, cancel_all_on_error=True):
    if trade is None:
        return "NonExist"

    order = trade.order
    print(f"Cancel trade, orderId {order.orderId}, price {order.lmtPrice}, status {trade.orderStatus.status}")

    for _ in range(10):
        try:
            if trade.orderStatus.status not in OrderStatus.DoneStates:
                ib.cancelOrder(order)
                ib.sleep(1)
            else:
                return trade.orderStatus.status
        except Exception as e:
            print(f"Cancel trade error: {e}")
            if cancel_all_on_error:
                cancel_all_orders(ib)

    if cancel_all_on_error:
        cancel_all_orders(ib)
    raise TimeoutError(f"Cancel trade timed out: orderId {order.orderId}")


def cancel_all_orders(ib):
    print("Canceling all orders")
    for order in ib.openOrders():
        print(f"Canceling order {order.orderId} with clientId {ib.client.clientId}")
        if ib.client.clientId == order.clientId:
            ib.cancelOrder(order)
            ib.sleep(0.2)


def _is_nan(value):
    return value is None or value != value


def require_managed_account(ib, account):
    accounts = ib.managedAccounts()
    if account not in accounts:
        raise ValueError(f"Account {account} is not managed by current IB session: {accounts}")
    return accounts


def is_gateway_online(host="127.0.0.1", port=4002):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex((host, port))
    sock.close()
    return result == 0


def wait_gateway_online(host="127.0.0.1", port=4002, wait_seconds=180, poll_seconds=5):
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if is_gateway_online(host, port):
            print(f"IB Gateway API is reachable at {host}:{port}", flush=True)
            return
        time.sleep(poll_seconds)
    raise TimeoutError(f"IB Gateway API did not become reachable within {wait_seconds} seconds")


def ensure_gateway_online(host, port, gateway_bat, wait_seconds=180, poll_seconds=5, launcher_env=None):
    if is_gateway_online(host, port):
        print(f"IB Gateway API is already reachable at {host}:{port}", flush=True)
        return

    gateway_bat = Path(gateway_bat)
    if not gateway_bat.exists():
        raise FileNotFoundError(f"Gateway launcher not found: {gateway_bat}")

    print(f"IB Gateway API is not reachable; starting {gateway_bat}", flush=True)
    env = None
    if launcher_env:
        import os
        env = os.environ.copy()
        env.update(launcher_env)
    subprocess.Popen(
        [str(gateway_bat)],
        cwd=str(gateway_bat.parent),
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        env=env,
    )
    wait_gateway_online(host, port, wait_seconds, poll_seconds)
