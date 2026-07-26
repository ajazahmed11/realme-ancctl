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

### 1. Control ANC Modes

Once paired with your computer, run commands directly without needing to pass MAC addresses:

```bash
# Switch to Transparency mode
realme-ancctl anc transparency

# Switch to Noise Cancellation mode
realme-ancctl anc noise_cancellation

# Set Noise Cancellation with a specific submode level (max, smart, moderate, mild)
realme-ancctl anc noise_cancellation --submode max

# Turn ANC Off (Normal mode)
realme-ancctl anc off
```

---

### 2. Check Earbud Battery & Status

Query battery levels (Left %, Right %, Case %) and connection info:

```bash
realme-ancctl status
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
