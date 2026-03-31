# Mule Dataset Browser

A terminal UI for browsing Ati Motors robot datasets — locally or over SSH.

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/AtiMotors/mule_dataset_browser/main/install.sh | bash
```

## Usage

```bash
# Startup menu (choose Local or Robot)
browse_data

# SSH mode directly
browse_data 192.168.6.180

# Local mode directly
browse_data --local
```

## Keybindings

| Key | Action |
|-----|--------|
| `↑/↓` | Navigate |
| `Tab` / `←→` | Switch panels |
| `Enter` | Open dataset detail |
| `Esc` or `b` | Back |
| `/` | Search/filter |
| `l` | Jump to latest |
| `f` | Fetch dataset (SSH mode only) |
| `y` | Copy dataset path to clipboard |
| `q` | Quit |

## Data layout

**Robot (SSH):** `/opt/ati/data/<Day>/` — Mon through Sun, each containing all datasets from past occurrences of that weekday.

**Local:** `~/data/` — flat folder of datasets, grouped by weekday derived from the date prefix in folder names.
