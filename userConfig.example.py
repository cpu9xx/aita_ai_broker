from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


# Account
account = "DUxxxxxx"


# IB API
ib_host = "127.0.0.1"
ib_port = 4002
ib_client_id = 880022
delayed_data = True
ib_connect_timeout = 4
ib_connect_attempts = 3


# IBC external dependency
# Install/configure IBC yourself, then point this to your local IBC folder.
ibc_path = Path(r"C:\path\to\IBCWin")
ibc_config = ibc_path / "config.ini"
ibc_log_path = ibc_path / "Logs"
tws_path = r"C:\Jts"
tws_major_version = 1037
trading_mode = "paper"
gateway_bat = str(BASE_DIR / "StartGateway.bat")
gateway_wait_seconds = 180
gateway_poll_seconds = 5


# Rebalance behavior
enable_trading = True
stock_exchange = "SMART"
stock_currency = "USD"
order_type = "LOO"
limit_price_buffer = 0.005
outside_rth = False
cash_buffer_usd = 1000
min_trade_value_usd = 100
market_data_timeout_seconds = 20
cancel_existing_orders = True
cancel_wait_seconds = 120


# Reporting
report_currency = "USD"
usd_hkd_rate_fallback = 7.8
send_rebalance_report = False
feishu_sender_dir = ""
report_output_dir = str(BASE_DIR / "reports")
