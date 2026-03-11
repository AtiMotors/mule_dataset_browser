# Mule Dataset Browser

A terminal UI for browsing Ati Motors robot datasets — locally or over SSH.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Startup menu (choose Local or Robot)
python mule_browser.py

# SSH mode directly
python mule_browser.py 192.168.6.180

# Local mode directly
python mule_browser.py --local
```

## Keybindings

| Key | Action |
|-----|--------|
| `↑/↓` or `j/k` | Navigate |
| `Tab` / `←→` | Switch panels |
| `Enter` | Open dataset detail |
| `Esc` or `b` | Back |
| `/` | Search/filter |
| `l` | Jump to latest |
| `f` | Fetch dataset (SSH mode only) |
| `q` | Quit |

## Data layout

**Robot (SSH):** `/opt/ati/data/<Day>/` — Mon through Sun, each containing all datasets from past occurrences of that weekday.

**Local:** `~/data/` — flat folder of datasets, grouped by weekday derived from the date prefix in folder names.
