from ib_async import IB, StartupFetch

import userConfig
from ib_interaction import is_gateway_online


print(f"tcp_port: {userConfig.ib_host}:{userConfig.ib_port} -> {is_gateway_online(userConfig.ib_host, userConfig.ib_port)}", flush=True)

ib = IB()
print("connecting minimal IB API session...", flush=True)
ib.connect(
    userConfig.ib_host,
    userConfig.ib_port,
    clientId=987654,
    timeout=userConfig.ib_connect_timeout,
    fetchFields=StartupFetch(0),
)
print(f"connected: {ib.isConnected()}", flush=True)

print("managed_accounts...", flush=True)
print(ib.managedAccounts(), flush=True)

print("positions...", flush=True)
print(ib.positions(), flush=True)

print("account_values sample...", flush=True)
values = ib.accountValues()
print(values[:20], flush=True)

ib.disconnect()
print("done", flush=True)
