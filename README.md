# realme-ancctl

A lightweight Linux CLI utility for controlling Active Noise Cancellation (ANC), Transparency mode, and checking battery status on **Realme Buds Air 5** (and compatible OPPO / Realme Bluetooth earbuds).

---

## Why `realme-ancctl`?

The official *realme Link* app is only available on Android and iOS. Linux Bluetooth desktop environments (PipeWire / PulseAudio) allow audio streaming but cannot control vendor-specific features like ANC modes or read individual earbud/case battery levels.

`realme-ancctl` implements the OPPO/Realme Bluetooth protocol over **Bluetooth Classic (RFCOMM)** and **Bluetooth Low Energy (BLE)** to give you native command-line control on Linux.

---

## Features

- 🎧 **ANC Mode Control**: Switch instantly between **Noise Cancellation** (`noise_cancellation`), **Transparency** (`transparency`), and **Off** (`off` / `normal`).
- 🎚️ **ANC Submode Levels**: Fine-tune noise cancellation intensity (`max`, `deep`, `smart`, `moderate`, `mild`).
- 🔋 **Battery & Device Status**: Query battery percentages for **Left Earbud**, **Right Earbud**, and **Charging Case**.
- ⚡ **Instant RFCOMM Transport**: Sends direct hardware commands over Bluetooth Classic RFCOMM channel 12 when connected for audio—zero delay.
- 🧠 **Auto-Discovery & Memory**: Auto-detects paired Realme earbuds via `bluetoothctl` and remembers your device address for zero-config commands.
- 🔬 **Protocol Inspector**: Built-in BLE GATT dump, packet monitor, and raw hex payload tools for developers.

---

## Requirements

- **OS**: Linux (Fedora, Ubuntu, Arch, Debian, etc.)
- **Stack**: BlueZ (`bluetoothctl`) & Python >= 3.10
- **Dependencies**: `bleak`

---

## Installation

Clone the repository and install it in a Python virtual environment:

```bash
git clone https://github.com/ajazahmed11/realme-ancctl.git
cd realme-ancctl

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Quick Start & Usage

Commands are designed to be fast, intuitive, and easy to type from your terminal using `realme` (or `realme-ancctl`):

### 1. Control ANC Modes (Quick & Easy)

Once paired with your computer, control ANC directly without typing long argument strings:

```bash
# Switch to Transparency mode
realme trans

# Turn ANC Off (Normal mode)
realme off

# Turn on Noise Cancellation (default / last used level)
realme nc

# Noise Cancellation with specific intensity levels
realme nc-smart       # Smart adaptive level (or: realme smart)
realme nc-max         # Maximum noise cancellation (or: realme max)
realme nc-moderate    # Moderate level
realme nc-mild        # Mild level
```

You can also use the `anc` prefix if you prefer:
```bash
realme anc off
realme anc trans
realme anc nc
realme anc nc-smart   # or: realme anc smart
realme anc nc-max     # or: realme anc max
```

---

### 2. Check Earbud Battery & Status

Query battery levels (Left %, Right %, Case %) and connection info:

```bash
realme battery        # or simply: realme bat (or realme status)
```

**Example Output:**
```text
--- Realme Earbuds Status ---
  • battery response (Case: charging, Left: 80%, Right: 80%)
  • subscription update
```

---

### 3. Scan & Discover BLE Devices

Scan for nearby Bluetooth Low Energy devices if needed:

```bash
realme-ancctl scan
```

---

### 4. Advanced Debugging & Protocol Testing

```bash
# Monitor live vendor notification packets for 30 seconds
realme-ancctl monitor --seconds 30

# Dump GATT services and characteristics
realme-ancctl dump

# Send custom raw hex payload
realme-ancctl write AA:BB:CC:DD:EE:FF 00000003-0000-1000-8000-00805f9b34fb "aa 0a 00 00 04 04 00 03 00 01 01 01"
```

---

## Tested & Compatible Devices

- **Realme Buds Air 5** *(Tested & Verified)*
- Compatible with related Realme Buds Air series, OPPO Enco series, and OnePlus earbuds using the HeyMelody protocol.

---

## Configuration File

Device preferences and last known MAC address are stored locally in:
`~/.config/realme-ancctl/config.json`

---

## License

Distributed under the [MIT License](LICENSE).
