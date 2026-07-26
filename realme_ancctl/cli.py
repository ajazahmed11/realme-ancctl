from __future__ import annotations

import argparse
import asyncio
import json
import re
import socket
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".config" / "realme-ancctl" / "config.json"
DEFAULT_CLASSIC_ADDRESS = ""
DEFAULT_NOTIFY_CHARACTERISTIC = "00000002-0000-1000-8000-00805f9b34fb"
DEFAULT_WRITE_CHARACTERISTIC = "00000003-0000-1000-8000-00805f9b34fb"
OPPO_COMMAND_ANC_CONFIG_SET = 0x0404
OPPO_COMMAND_BATTERY_REQ = 0x0106
OPPO_COMMAND_FIRMWARE_GET = 0x0105
OPPO_COMMAND_ANC_CONFIG_REQ = 0x010C
OPPO_COMMAND_SUBSCRIPTION_SET = 0x0205
OPPO_COMMAND_MISC_CONFIG_REQ = 0x010D
OPPO_COMMAND_TOUCH_CONFIG_REQ = 0x0108

ANC_MODE_CODES = {
    "off": 0x01,
    "normal": 0x01,
    "transparency": 0x02,
    "on": 0x08,
    "noise_cancellation": 0x08,
    "noise-cancellation": 0x08,
}

ANC_SUBMODE_CODES = {
    "smart": 0x00,
    "max": 0x01,
    "deep": 0x01,
    "moderate": 0x02,
    "mild": 0x03,
}

REQUEST_PAYLOADS = {
    "battery": (OPPO_COMMAND_BATTERY_REQ, b""),
    "firmware": (OPPO_COMMAND_FIRMWARE_GET, b""),
    "anc": (OPPO_COMMAND_ANC_CONFIG_REQ, bytes([0x01, 0x01])),
    "anc-cycle": (OPPO_COMMAND_ANC_CONFIG_REQ, bytes([0x02, 0x01])),
    "subscription": (OPPO_COMMAND_SUBSCRIPTION_SET, bytes([0x09, 0x01, 0x02, 0x03, 0x05])),
    "misc": (OPPO_COMMAND_MISC_CONFIG_REQ, bytes([0x00])),
    "touch": (OPPO_COMMAND_TOUCH_CONFIG_REQ, bytes([0x02, 0x03, 0x01])),
}


@dataclass
class WriteCommand:
    address: str
    characteristic: str = DEFAULT_WRITE_CHARACTERISTIC
    off: str | None = None
    normal: str | None = None
    transparency: str | None = None
    noise_cancellation: str | None = None
    response: bool = False


def is_mac_address(address: str) -> bool:
    return bool(re.match(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$", address))


def get_saved_address() -> str | None:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            return data.get("address")
        except Exception:
            pass
    return None


def save_last_address(address: str, characteristic: str = DEFAULT_WRITE_CHARACTERISTIC) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    existing["address"] = address
    if "characteristic" not in existing:
        existing["characteristic"] = characteristic
    CONFIG_PATH.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")


def parse_hex(value: str) -> bytes:
    cleaned = value.replace(":", " ").replace("-", " ").replace(",", " ")
    cleaned = " ".join(cleaned.split())
    try:
        if " " in cleaned:
            return bytes(int(part, 16) for part in cleaned.split())
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid hex payload: {value}") from exc


def encode_oppo_message(command: int, payload: bytes, seq: int = 0) -> bytes:
    total_len_after_preamble_and_len = 7 + len(payload)
    return bytes(
        [
            0xAA,
            total_len_after_preamble_and_len,
            0x00,
            0x00,
            command & 0xFF,
            (command >> 8) & 0xFF,
            seq & 0xFF,
            len(payload) & 0xFF,
            (len(payload) >> 8) & 0xFF,
        ]
    ) + payload


def encode_anc_mode(mode: str, submode: str | None = None, seq: int = 0) -> bytes:
    mode_code = ANC_MODE_CODES[mode]
    if submode and mode_code == 0x08 and submode in ANC_SUBMODE_CODES:
        payload = bytes([0x01, 0x01, mode_code, ANC_SUBMODE_CODES[submode]])
    else:
        payload = bytes([0x01, 0x01, mode_code])
    return encode_oppo_message(OPPO_COMMAND_ANC_CONFIG_SET, payload, seq=seq)


def format_props(props: list[str]) -> str:
    return ",".join(props) if props else "-"


def decode_packet(data: bytes) -> str | None:
    if len(data) >= 6 and data[:1] == b"\xaa":
        code = int.from_bytes(data[4:6], "little")
        known = {
            0x8106: "battery response",
            0x8205: "subscription ack",
            0x0204: "subscription update",
            0x8105: "firmware response",
            0x8404: "ANC config ack",
            0x810C: "ANC config response",
            0x810D: "misc config response",
            0x8108: "touch config response",
        }.get(code)
        if known:
            details = parse_packet_details(code, data)
            return f"{known} ({details})" if details else known

    if len(data) == 17 and data[:2] == b"\xaa\x0f" and data[4:6] == b"\x04\x02":
        return "status subscription update"
    if len(data) >= 12 and data[:2] == b"\xaa\x0a" and data[4:6] == b"\x04\x84":
        status = data[9]
        return f"ANC config ack: status=0x{status:02x}"
    if len(data) >= 12 and data[:2] == b"\xaa\x0a" and data[4:6] == b"\x0c\x81":
        return "ANC config response"
    if len(data) >= 8 and data[:2] == b"\xaa\x17" and data[4:6] == b"\x0e\x05":
        return "battery/status update"
    return None


def parse_packet_details(code: int, data: bytes) -> str | None:
    try:
        payload = data[9:]
        if code == 0x8106 and len(payload) >= 3:  # Battery response
            # Format often contains triples: [type (1=L,2=R,3=Case), level (0-100 or 0-10), charging]
            parts = []
            i = 0
            while i + 2 < len(payload):
                b_type, b_level, b_charge = payload[i], payload[i + 1], payload[i + 2]
                name = {1: "L", 2: "R", 3: "Case"}.get(b_type)
                if name:
                    pct = b_level if b_level <= 100 else (b_level * 10)
                    chg = "+" if b_charge else ""
                    parts.append(f"{name}:{pct}%{chg}")
                    i += 3
                else:
                    i += 1
            if parts:
                return ", ".join(parts)
        elif code == 0x810C and len(payload) >= 2:  # ANC config response
            anc_val = payload[-1] if len(payload) > 0 else 0
            anc_map = {1: "Off/Normal", 2: "Transparency", 8: "Noise Cancellation"}
            mode_str = anc_map.get(anc_val, f"0x{anc_val:02x}")
            return f"Mode: {mode_str}"
        elif code == 0x8105 and len(payload) > 0:  # Firmware
            return f"FW: {payload.hex()}"
    except Exception:
        pass
    return None


def require_bleak():
    try:
        from bleak import BleakClient, BleakScanner
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing dependency `bleak`. Install with `pip install -e .` from ~/realme-ancctl."
        ) from exc
    return BleakClient, BleakScanner


def connect_rfcomm(address: str, channel: int, timeout: float) -> socket.socket:
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    sock.settimeout(timeout)
    try:
        sock.connect((address, channel))
    except Exception:
        sock.close()
        raise
    return sock


async def resolve_device(target: str, timeout: float) -> Any:
    _, BleakScanner = require_bleak()
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    target_lower = target.lower()

    exact_matches = []
    name_matches = []
    realme_fallback_matches = []

    for address, (device, adv) in devices.items():
        name = device.name or adv.local_name or ""
        uuids = ",".join(adv.service_uuids).lower() if adv.service_uuids else ""

        if target_lower == address.lower():
            exact_matches.append(device)
        elif target_lower in name.lower() or target_lower in address.lower():
            name_matches.append((device, name, adv.rssi))
        elif "realme" in name.lower() or "0000fe2c" in uuids or "000008a4" in uuids:
            realme_fallback_matches.append((device, name, adv.rssi))

    if exact_matches:
        return exact_matches[0]
    if len(name_matches) == 1:
        return name_matches[0][0]
    if len(name_matches) > 1:
        return name_matches[0][0]
    if realme_fallback_matches:
        return realme_fallback_matches[0][0]

    raise SystemExit(
        f"Could not find `{target}` over BLE. Open the case, keep the earbuds nearby, "
        "disconnect them from your phone, then run `realme-ancctl scan`."
    )


@asynccontextmanager
async def connect_device(address: str | None, timeout: float, attempts: int = 1):
    BleakClient, _ = require_bleak()

    if not address or address.lower() == "realme":
        saved = get_saved_address()
        if saved:
            address = saved

    if not address:
        address = "realme"

    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        # First attempt fast direct MAC connection if address is MAC format
        if is_mac_address(address):
            try:
                async with BleakClient(address, timeout=timeout) as client:
                    if client.is_connected:
                        save_last_address(address)
                        yield client
                        return
            except Exception as exc:
                last_error = exc

        # Fallback to BLE scanner discovery
        try:
            device = await resolve_device(address, timeout)
            async with BleakClient(device, timeout=timeout) as client:
                if client.is_connected:
                    save_last_address(device.address)
                    yield client
                    return
        except (TimeoutError, asyncio.TimeoutError) as exc:
            last_error = exc
            if attempt < attempts:
                await asyncio.sleep(1)
                continue
            raise SystemExit(
                "Timed out connecting to the earbuds. Keep them nearby, disconnect from phone, "
                "open case once, then retry with `--timeout 15`."
            ) from exc
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                await asyncio.sleep(1)
                continue
            raise

    if last_error:
        raise last_error


async def scan(args: argparse.Namespace) -> int:
    _, BleakScanner = require_bleak()
    devices = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
    rows = []
    for address, (device, adv) in sorted(devices.items()):
        name = device.name or adv.local_name or "(no name)"
        uuids = ",".join(adv.service_uuids) if adv.service_uuids else "-"
        if (
            not args.all
            and args.match
            and args.match.lower() not in name.lower()
            and args.match.lower() not in address.lower()
            and args.match.lower() not in uuids.lower()
        ):
            continue
        rows.append((address, name, adv.rssi, uuids))

    if not rows:
        print("No matching BLE devices found.")
        return 1

    for address, name, rssi, uuids in rows:
        print(f"{address}\t{rssi:>4} dBm\t{name}\t{uuids}")
    return 0


async def dump(args: argparse.Namespace) -> int:
    async with connect_device(args.address, args.timeout, args.retries) as client:
        if not client.is_connected:
            print("Could not connect.", file=sys.stderr)
            return 1

        services = client.services
        for service in services:
            print(f"service {service.uuid} {service.description}")
            for char in service.characteristics:
                print(f"  char {char.uuid} props={format_props(char.properties)} {char.description}")
                if args.read and "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char.uuid)
                        print(f"    value {value.hex(' ')}")
                    except Exception as exc:
                        print(f"    read failed: {exc}")
    return 0


async def write(args: argparse.Namespace) -> int:
    payload = parse_hex(args.hex)
    async with connect_device(args.address, args.timeout, args.retries) as client:
        if not client.is_connected:
            print("Could not connect.", file=sys.stderr)
            return 1
        await client.write_gatt_char(args.characteristic, payload, response=args.response)
        print(f"Wrote payload ({len(payload)} bytes) to {args.characteristic}: {payload.hex(' ')}")
    return 0


def get_classic_mac_address() -> str:
    import subprocess
    try:
        res = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, check=False)
        for line in res.stdout.splitlines():
            if "realme" in line.lower() or "buds" in line.lower():
                parts = line.strip().split()
                if len(parts) >= 2 and is_mac_address(parts[1]):
                    return parts[1]
    except Exception:
        pass
    return DEFAULT_CLASSIC_ADDRESS


def send_rfcomm_anc(address: str, payload: bytes, timeout: float = 2.0) -> tuple[int, str] | None:
    for channel in [12, 15, 17, 1, 2, 4, 6]:
        try:
            with connect_rfcomm(address, channel, timeout) as sock:
                sock.sendall(payload)
                sock.settimeout(1.5)
                try:
                    data = sock.recv(1024)
                    decoded = decode_packet(data) or data.hex(" ")
                    return channel, decoded
                except TimeoutError:
                    return channel, "sent (no response)"
        except Exception:
            continue
    return None


async def anc(args: argparse.Namespace) -> int:
    payload = encode_anc_mode(args.mode, submode=getattr(args, "submode", None), seq=args.seq)
    submode_str = f" ({args.submode})" if getattr(args, "submode", None) else ""

    # Try Bluetooth Classic RFCOMM first (instant hardware response when connected for audio)
    classic_addr = get_classic_mac_address()
    rfcomm_result = send_rfcomm_anc(classic_addr, payload)
    if rfcomm_result is not None:
        channel, resp = rfcomm_result
        print(f"Set ANC {args.mode}{submode_str} via Bluetooth Classic (channel {channel}): {resp}")
        return 0

    # Fallback to BLE GATT write if RFCOMM is not connected
    async with connect_device(args.address, args.timeout, args.retries) as client:
        if not client.is_connected:
            print("Could not connect over Classic Bluetooth or BLE.", file=sys.stderr)
            return 1
        await client.write_gatt_char(args.characteristic, payload, response=args.response)
        print(f"Sent ANC {args.mode}{submode_str} via BLE: {payload.hex(' ')}")
    return 0


async def status_info(args: argparse.Namespace) -> int:
    classic_addr = get_classic_mac_address()
    battery_req = encode_oppo_message(OPPO_COMMAND_BATTERY_REQ, b"")

    for channel in [12, 15, 17]:
        try:
            with connect_rfcomm(classic_addr, channel, 2.0) as sock:
                sock.sendall(battery_req)
                sock.settimeout(2.0)
                responses = []
                for _ in range(3):
                    try:
                        data = sock.recv(1024)
                        decoded = decode_packet(data)
                        if decoded:
                            responses.append(decoded)
                    except TimeoutError:
                        break
                if responses:
                    print("\n--- Realme Earbuds Status ---")
                    for resp in responses:
                        print(f"  • {resp}")
                    return 0
        except Exception:
            continue

    # Fallback to BLE status query
    received_responses: list[str] = []

    def on_notify(characteristic, data: bytearray) -> None:
        packet = bytes(data)
        decoded = decode_packet(packet)
        if decoded:
            received_responses.append(decoded)

    async with connect_device(args.address, args.timeout, args.retries) as client:
        if not client.is_connected:
            print("Could not connect.", file=sys.stderr)
            return 1

        print("Connected over BLE. Querying earbud status...")
        try:
            await client.start_notify(DEFAULT_NOTIFY_CHARACTERISTIC, on_notify)
        except Exception:
            pass

        sub_payload = encode_oppo_message(OPPO_COMMAND_SUBSCRIPTION_SET, bytes([0x09, 0x01, 0x02, 0x03, 0x05]))
        await client.write_gatt_char(DEFAULT_WRITE_CHARACTERISTIC, sub_payload, response=False)
        await asyncio.sleep(0.3)

        bat_payload = encode_oppo_message(OPPO_COMMAND_BATTERY_REQ, b"")
        await client.write_gatt_char(DEFAULT_WRITE_CHARACTERISTIC, bat_payload, response=False)
        await asyncio.sleep(0.3)

        try:
            await client.stop_notify(DEFAULT_NOTIFY_CHARACTERISTIC)
        except Exception:
            pass

    if received_responses:
        print("\n--- Realme Earbuds Status ---")
        for resp in received_responses:
            print(f"  • {resp}")
    else:
        print("Status request sent, but no notification responses decoded.")

    return 0


def classic_scan(args: argparse.Namespace) -> int:
    found = []
    for channel in range(args.start, args.end + 1):
        try:
            with connect_rfcomm(args.address, channel, args.timeout):
                print(f"channel {channel}: open")
                found.append(channel)
        except OSError as exc:
            if args.verbose:
                print(f"channel {channel}: {exc}", file=sys.stderr)
        except TimeoutError as exc:
            if args.verbose:
                print(f"channel {channel}: timeout: {exc}", file=sys.stderr)

    if not found:
        print("No open RFCOMM channels found.")
        return 1
    return 0


def classic_anc(args: argparse.Namespace) -> int:
    payload = encode_anc_mode(args.mode, seq=args.seq)
    try:
        with connect_rfcomm(args.address, args.channel, args.timeout) as sock:
            sock.sendall(payload)
            print(f"sent classic ANC {args.mode} on channel {args.channel}: {payload.hex(' ')}")
            if args.read:
                sock.settimeout(args.read_timeout)
                try:
                    data = sock.recv(1024)
                    decoded = decode_packet(data)
                    suffix = f" # {decoded}" if decoded else ""
                    print(f"recv {data.hex(' ')}{suffix}")
                except TimeoutError:
                    print("no response before read timeout")
    except PermissionError as exc:
        raise SystemExit(
            "Permission denied opening Bluetooth RFCOMM socket. Run this command from your normal "
            "terminal, or allow elevated Bluetooth access."
        ) from exc
    except OSError as exc:
        raise SystemExit(f"RFCOMM failed: {exc}") from exc
    return 0


def classic_request(args: argparse.Namespace) -> int:
    command, request_payload = REQUEST_PAYLOADS[args.request]
    payload = encode_oppo_message(command, request_payload, seq=args.seq)
    try:
        with connect_rfcomm(args.address, args.channel, args.timeout) as sock:
            sock.sendall(payload)
            print(f"sent {args.request} on channel {args.channel}: {payload.hex(' ')}")
            sock.settimeout(args.read_timeout)
            for _ in range(args.reads):
                try:
                    data = sock.recv(1024)
                except TimeoutError:
                    print("no more responses before read timeout")
                    break
                if not data:
                    print("socket closed")
                    break
                decoded = decode_packet(data)
                suffix = f" # {decoded}" if decoded else ""
                print(f"recv {data.hex(' ')}{suffix}")
    except PermissionError as exc:
        raise SystemExit(
            "Permission denied opening Bluetooth RFCOMM socket. Run this command from your normal "
            "terminal, or allow elevated Bluetooth access."
        ) from exc
    except OSError as exc:
        raise SystemExit(f"RFCOMM failed: {exc}") from exc
    return 0


async def monitor(args: argparse.Namespace) -> int:
    def on_notify(characteristic, data: bytearray) -> None:
        packet = bytes(data)
        decoded = decode_packet(packet)
        suffix = f"\t# {decoded}" if decoded else ""
        print(f"{characteristic.uuid}\t{packet.hex(' ')}{suffix}")

    async with connect_device(args.address, args.timeout, args.retries) as client:
        if not client.is_connected:
            print("Could not connect.", file=sys.stderr)
            return 1

        await client.start_notify(args.characteristic, on_notify)
        print(f"Monitoring {args.characteristic} for {args.seconds:g}s...")
        try:
            await asyncio.sleep(args.seconds)
        finally:
            try:
                await client.stop_notify(args.characteristic)
            except Exception as exc:
                pass
    return 0


def load_config() -> WriteCommand:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"No config found at {CONFIG_PATH}. Run `realme-ancctl configure ...` first.")
    return WriteCommand(**json.loads(CONFIG_PATH.read_text()))


def save_config(command: WriteCommand) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(command), indent=2, sort_keys=True) + "\n")


async def set_mode(args: argparse.Namespace) -> int:
    config = load_config()
    payload_hex = getattr(config, args.mode)
    if not payload_hex:
        print(f"No payload configured for mode `{args.mode}`.", file=sys.stderr)
        return 1

    payload = parse_hex(payload_hex)
    async with connect_device(config.address, args.timeout, args.retries) as client:
        if not client.is_connected:
            print("Could not connect.", file=sys.stderr)
            return 1
        await client.write_gatt_char(config.characteristic, payload, response=config.response)
        print(f"Set {args.mode} using {payload.hex(' ')}")
    return 0


def configure(args: argparse.Namespace) -> int:
    command = WriteCommand(
        address=args.address,
        characteristic=args.characteristic,
        off=args.off,
        normal=args.normal,
        transparency=args.transparency,
        noise_cancellation=args.noise_cancellation,
        response=args.response,
    )
    save_config(command)
    print(f"Saved configuration to {CONFIG_PATH}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="realme-ancctl",
        description="Realme earbuds ANC control helper for Linux.",
    )
    parser.add_argument("--timeout", type=float, default=6.0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="scan for BLE devices")
    scan_parser.add_argument("--match", default="realme", help="filter by name or address")
    scan_parser.add_argument("--all", action="store_true", help="show all BLE advertisements")
    scan_parser.set_defaults(func=scan)

    dump_parser = subparsers.add_parser("dump", help="dump GATT services and characteristics")
    dump_parser.add_argument("address", nargs="?", default="realme")
    dump_parser.add_argument("--read", action="store_true", help="try reading readable characteristics")
    dump_parser.add_argument("--retries", type=int, default=1)
    dump_parser.set_defaults(func=dump)

    write_parser = subparsers.add_parser("write", help="write a raw hex payload to a characteristic")
    write_parser.add_argument("address", nargs="?", default="realme")
    write_parser.add_argument("characteristic", nargs="?", default=DEFAULT_WRITE_CHARACTERISTIC)
    write_parser.add_argument("hex")
    write_parser.add_argument("--response", action="store_true")
    write_parser.add_argument("--retries", type=int, default=1)
    write_parser.set_defaults(func=write)

    monitor_parser = subparsers.add_parser("monitor", help="print notifications from a characteristic")
    monitor_parser.add_argument("address", nargs="?", default="realme")
    monitor_parser.add_argument("characteristic", nargs="?", default=DEFAULT_NOTIFY_CHARACTERISTIC)
    monitor_parser.add_argument("--seconds", type=float, default=30.0)
    monitor_parser.add_argument("--retries", type=int, default=1)
    monitor_parser.set_defaults(func=monitor)

    anc_parser = subparsers.add_parser("anc", help="set ANC/noise-control mode using the OPPO/Realme protocol")
    anc_parser.add_argument("mode", choices=sorted(ANC_MODE_CODES))
    anc_parser.add_argument("address", nargs="?", default="realme")
    anc_parser.add_argument("--submode", choices=sorted(ANC_SUBMODE_CODES), help="ANC submode (smart, max/deep, moderate, mild)")
    anc_parser.add_argument("--characteristic", default=DEFAULT_WRITE_CHARACTERISTIC)
    anc_parser.add_argument("--seq", type=int, default=0)
    anc_parser.add_argument("--response", action="store_true")
    anc_parser.add_argument("--retries", type=int, default=2)
    anc_parser.set_defaults(func=anc)

    status_parser = subparsers.add_parser("status", help="get earbud status (battery, ANC mode, etc.)")
    status_parser.add_argument("address", nargs="?", default="realme")
    status_parser.add_argument("--retries", type=int, default=2)
    status_parser.set_defaults(func=status_info)

    info_parser = subparsers.add_parser("info", help="alias for status")
    info_parser.add_argument("address", nargs="?", default="realme")
    info_parser.add_argument("--retries", type=int, default=2)
    info_parser.set_defaults(func=status_info)

    classic_scan_parser = subparsers.add_parser("classic-scan", help="find open RFCOMM channels")
    classic_scan_parser.add_argument("address", nargs="?", default=DEFAULT_CLASSIC_ADDRESS)
    classic_scan_parser.add_argument("--start", type=int, default=1)
    classic_scan_parser.add_argument("--end", type=int, default=30)
    classic_scan_parser.add_argument("--verbose", action="store_true")
    classic_scan_parser.set_defaults(func=classic_scan)

    classic_anc_parser = subparsers.add_parser("classic-anc", help="set ANC over classic Bluetooth RFCOMM")
    classic_anc_parser.add_argument("mode", choices=sorted(ANC_MODE_CODES))
    classic_anc_parser.add_argument("address", nargs="?", default=DEFAULT_CLASSIC_ADDRESS)
    classic_anc_parser.add_argument("--channel", type=int, required=True)
    classic_anc_parser.add_argument("--seq", type=int, default=0)
    classic_anc_parser.add_argument("--read", action="store_true")
    classic_anc_parser.add_argument("--read-timeout", type=float, default=2.0)
    classic_anc_parser.set_defaults(func=classic_anc)

    classic_request_parser = subparsers.add_parser("classic-request", help="send a safe OPPO/Realme read/init request")
    classic_request_parser.add_argument("request", choices=sorted(REQUEST_PAYLOADS))
    classic_request_parser.add_argument("address", nargs="?", default=DEFAULT_CLASSIC_ADDRESS)
    classic_request_parser.add_argument("--channel", type=int, required=True)
    classic_request_parser.add_argument("--seq", type=int, default=0)
    classic_request_parser.add_argument("--read-timeout", type=float, default=2.0)
    classic_request_parser.add_argument("--reads", type=int, default=3)
    classic_request_parser.set_defaults(func=classic_request)

    configure_parser = subparsers.add_parser("configure", help="save known command payloads")
    configure_parser.add_argument("address")
    configure_parser.add_argument("characteristic")
    configure_parser.add_argument("--off")
    configure_parser.add_argument("--normal")
    configure_parser.add_argument("--transparency")
    configure_parser.add_argument("--noise-cancellation")
    configure_parser.add_argument("--response", action="store_true")
    configure_parser.set_defaults(func=configure)

    mode_parser = subparsers.add_parser("set", help="send a configured mode command")
    mode_parser.add_argument(
        "mode",
        choices=["off", "normal", "transparency", "noise_cancellation"],
    )
    mode_parser.add_argument("--retries", type=int, default=2)
    mode_parser.set_defaults(func=set_mode)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    if asyncio.iscoroutine(result):
        return asyncio.run(result)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
