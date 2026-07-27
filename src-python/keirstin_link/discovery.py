"""LAN discovery: UDP broadcast + optional mDNS."""

import json
import socket
import struct
import threading
import time
from datetime import datetime, timezone
from typing import Callable, List, Tuple

from .config import (
    HOST,
    INSTALL_ID,
    MDNS_SERVICE_NAME,
    MDNS_SERVICE_TYPE,
    PORT,
    UDP_BUFFER,
    UDP_DISCOVERY_PORT,
)
from .models import DeviceInfo
from .store import DeviceStore
from .settings_store import SettingsStore

BROADCAST_INTERVAL = 5.0


def _list_lan_interfaces() -> list[tuple[str, str, str | None]]:
    """Return list of (interface_name, ipv4_address, broadcast_address) for usable LAN interfaces."""
    results = []
    try:
        import psutil
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for iface, addr_list in addrs.items():
            s = stats.get(iface)
            if not s or not s.isup:
                continue
            lower = iface.lower()
            if any(v in lower for v in ("loopback", "virtual", "vmware", "wsl", "hyper-v", "tailscale", "vpn", "tap", "tun")):
                continue
            for a in addr_list:
                if a.family != socket.AF_INET:
                    continue
                ip = a.address
                if not ip or ip.startswith("127.") or ip.startswith("169.254."):
                    continue
                results.append((iface, ip, a.broadcast))
    except Exception:
        pass
    return results


def _detect_local_ip() -> str:
    """Return a routable LAN IP address for this machine.

    HOST is usually '0.0.0.0' so the HTTP backend listens on all interfaces,
    but discovery beacons must advertise a real address peers can connect to.
    We prefer interfaces that have a default gateway, since those are the
    LAN segments that can actually reach peers.
    """
    if HOST and HOST not in {"0.0.0.0", "127.0.0.1", "localhost", "::"}:
        return HOST

    interfaces = _list_lan_interfaces()
    if interfaces:
        # Prefer physical ethernet-like adapters, then others
        def _score(item):
            iface, ip, _ = item
            lower = iface.lower()
            is_ethernet = "ethernet" in lower or "realtek" in lower or "intel" in lower or "gbe" in lower or "marvell" in lower or "usb" in lower
            is_wifi = "wi-fi" in lower or "wifi" in lower or "wireless" in lower
            return (is_ethernet, is_wifi, iface)
        interfaces.sort(key=_score, reverse=True)
        return interfaces[0][1]

    # Fallback 1: UDP connect to a public address without sending data. The kernel picks
    # the best local route and we read the bound IP. Works even if the target
    # is unreachable because no packets are actually sent for a connect().
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.connect(("8.8.8.8", 80))
        addr = s.getsockname()[0]
        s.close()
        if addr and not addr.startswith("127.") and not addr.startswith("169.254."):
            return addr
    except Exception:
        pass

    # Fallback 2: try to find any non-loopback, non-link-local IPv4 interface address.
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addr = info[4][0]
            if addr and not addr.startswith("127.") and not addr.startswith("169.254."):
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
    def __init__(self, device_name: str | None = None, port: int = PORT):
        settings = SettingsStore.load()
        self.device_name = device_name or settings.device_name or MDNS_SERVICE_NAME
        self.port = port
        self._advertised_host = _detect_local_ip()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._mdns: object | None = None

    def restart(self) -> None:
        """Stop and restart discovery with current settings (name may have changed)."""
        self.stop()
        settings = SettingsStore.load()
        self.device_name = settings.device_name or MDNS_SERVICE_NAME
        self._advertised_host = _detect_local_ip()
        self.start()

    def _own_beacon(self) -> dict:
        return {
            "id": f"{self.device_name}-{INSTALL_ID}-{self.port}",
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
                # Send to the global broadcast address; routers/switches flood it
                # to every interface. Also send to each interface's subnet broadcast
                # address so broadcasts work even on multi-homed hosts where 255.255.255.255
                # may be bound to a wrong/default interface.
                targets = set()
                targets.add("255.255.255.255")
                for iface, ip, bcast in _list_lan_interfaces():
                    if bcast:
                        targets.add(bcast)
                for target in targets:
                    try:
                        sock.sendto(beacon, (target, UDP_DISCOVERY_PORT))
                    except OSError as exc:
                        print(f"[discovery] broadcast to {target} failed: {exc}")
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
