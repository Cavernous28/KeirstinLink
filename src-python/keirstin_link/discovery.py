"""LAN discovery: UDP broadcast + optional mDNS."""

import json
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from .config import HOST, MDNS_SERVICE_NAME, MDNS_SERVICE_TYPE, PORT, UDP_DISCOVERY_PORT
from .models import DeviceInfo
from .store import DeviceStore

BROADCAST_INTERVAL = 5.0
UDP_BUFFER = 4096


def _detect_local_ip() -> str:
    """Return a routable LAN IP address for this machine.

    HOST is usually '0.0.0.0' so the HTTP backend listens on all interfaces,
    but discovery beacons must advertise a real address peers can connect to.
    """
    if HOST and HOST not in {"0.0.0.0", "127.0.0.1", "localhost", "::"}:
        return HOST
    try:
        # UDP connect to a public address without sending data. The kernel picks
        # the best local route and we read the bound IP. Works even if the target
        # is unreachable because no packets are actually sent for a connect().
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.connect(("8.8.8.8", 80))
        addr = s.getsockname()[0]
        s.close()
        if addr and not addr.startswith("127."):
            return addr
    except Exception:
        pass
    # Fallback: try to find any non-loopback IPv4 interface address.
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addr = info[4][0]
            if addr and not addr.startswith("127."):
                return addr
    except Exception:
        pass
    return "127.0.0.1"


# Peers seen on the LAN but not yet added to the user's device list.
_discovered_peers: dict[str, dict] = {}
_discovery_lock = threading.Lock()


def get_discovered_peers() -> list[dict]:
    """Return recently discovered peers, newest first."""
    cutoff = datetime.now(timezone.utc).timestamp() - 60  # 1 minute stale
    with _discovery_lock:
        fresh = [
            {**info, "last_seen": info["last_seen"].isoformat()}
            for info in _discovered_peers.values()
            if info["last_seen"].timestamp() > cutoff
        ]
    return sorted(fresh, key=lambda d: d["last_seen"], reverse=True)


class DiscoveryService:
    def __init__(self, device_name: str = MDNS_SERVICE_NAME, port: int = PORT):
        self.device_name = device_name
        self.port = port
        self._advertised_host = _detect_local_ip()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._mdns: object | None = None

    def _own_beacon(self) -> dict:
        return {
            "id": f"{self.device_name}-{self.port}",
            "name": self.device_name,
            "host": self._advertised_host,
            "port": self.port,
            "capabilities": ["files", "sync", "propose"],
        }

    def start(self) -> None:
        self._stop.clear()
        t_udp_rx = threading.Thread(target=self._udp_listen, daemon=True)
        t_udp_tx = threading.Thread(target=self._udp_broadcast, daemon=True)
        t_udp_rx.start()
        t_udp_tx.start()
        self._threads.extend([t_udp_rx, t_udp_tx])
        self._start_mdns()

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1.0)
        self._stop_mdns()

    def _udp_listen(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", UDP_DISCOVERY_PORT))
        except OSError as exc:
            print(f"[discovery] UDP bind failed: {exc}")
            return

        sock.settimeout(1.0)
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(UDP_BUFFER)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                payload = json.loads(data.decode("utf-8"))
                if payload.get("id") == self._own_beacon()["id"]:
                    continue
                peer = {
                    "id": payload["id"],
                    "name": payload.get("name", "unknown"),
                    "host": addr[0],
                    "port": int(payload.get("port", self.port)),
                    "last_seen": datetime.now(timezone.utc),
                    "capabilities": payload.get("capabilities", []),
                }
                with _discovery_lock:
                    _discovered_peers[peer["id"]] = peer
            except Exception as exc:
                print(f"[discovery] bad beacon from {addr}: {exc}")
        sock.close()

    def _udp_broadcast(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        beacon = json.dumps(self._own_beacon()).encode("utf-8")
        while not self._stop.is_set():
            try:
                sock.sendto(beacon, ("255.255.255.255", UDP_DISCOVERY_PORT))
            except OSError as exc:
                print(f"[discovery] broadcast failed: {exc}")
            if self._stop.wait(BROADCAST_INTERVAL):
                break
        sock.close()

    def _start_mdns(self) -> None:
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            print("[discovery] zeroconf not installed; skipping mDNS")
            return
        try:
            host = self._advertised_host
            info = ServiceInfo(
                type_=MDNS_SERVICE_TYPE,
                name=f"{self.device_name}.{MDNS_SERVICE_TYPE}",
                addresses=[socket.inet_aton(host)] if host not in {"0.0.0.0", "127.0.0.1", "localhost"} else [],
                port=self.port,
                properties={"path": "/", "version": "0.1.1"},
            )
            self._mdns = Zeroconf()
            self._mdns.register_service(info)
        except Exception as exc:
            print(f"[discovery] mDNS registration failed: {exc}")

    def _stop_mdns(self) -> None:
        if self._mdns is not None:
            try:
                self._mdns.unregister_all_services()
                self._mdns.close()
            except Exception as exc:
                print(f"[discovery] mDNS shutdown failed: {exc}")
            finally:
                self._mdns = None
