# Mule Dataset Browser - Code Summary

## Overview
A Textual TUI application for browsing Ati Motors robot datasets stored locally or on robots via SSH.

## Usage
```bash
python mule_browser.py              # Interactive mode selection
python mule_browser.py 192.168.x.x # Direct SSH mode
```

## Architecture

### Data Sources
- **`DataSource`** (abstract base class)
  - **`LocalSource`**: Reads from `~/data/` directory
  - **`SSHSource`**: Connects via SSH to robot IP, fetches via rsync

### Data Model
```python
@dataclass
class DatasetMeta:
    folder_name: str
    date: datetime
    robot: str
    mode: str              # fleet | manual | simulation
    distance_m: float
    duration_mins: float
    ip: str
    software_tag: str
    commit_id: str
    transition_reason: str
    user: str = ""
    size_bytes: int = 0    # On-disk folder size
    raw_info: str = ""
```

### Folder Naming Convention
```
YYYY-MM-DD-HH-MM-SS-robotname-mode
```
- Parsed by `parse_folder_name()` to extract date, robot, mode

### Info Files
`info.txt` contains comma-separated key:value pairs parsed by `parse_info_txt()`

## UI Screens

| Screen | Purpose |
|--------|---------|
| **StartupScreen** | Source selection (Local/Robot SSH) |
| **MainScreen** | Dataset browser with day list + DataTable |
| **DetailScreen** | Single dataset view (config, stoppages, trip log) |
| **FetchModal** | Rsync progress for fetching datasets |
| **IPInputScreen** | SSH IP address input |

## MainScreen Components
- Left panel: Day list (Mon-Sun) with dataset counts
- Right panel: DataTable with columns (Date, Robot, Mode, Dist, Dur, Size, Folder)
- Filter bar for searching datasets

## Key Functions
- `parse_folder_name()`: Extract datetime/robot/mode from folder name
- `parse_info_txt()`: Parse info.txt key:value pairs
- `build_dataset_meta()`: Create DatasetMeta from folder + info
- `format_size()`: Convert bytes to human-readable (B/KB/MB/GB/TB)
- `weekday_from_date()`: Map datetime to day abbreviation

## Column Colors (Rich markup in cells)
- Date: #66ddff (light blue)
- Time: #ffcc44 (yellow)
- Robot: #ff88cc (pink)
- Mode: fleet=#00ffcc, manual=#ffcc00, simulation=#4488ff
- Dist: #88ff88 (green)
- Dur: #ffbb66 (orange)
- Size: #bb99ff (purple)
- Folder: #dddddd (gray)

## Keyboard Shortcuts
- `/` or `s`: Search/filter datasets
- `Escape`: Close search
- `j/l`: Navigate datasets (vim-style)
- `k/h`: Navigate datasets (vim-style)
- `g`: Jump to latest
- `q`: Quit
- `Enter`: Open dataset detail
- `Tab`: Toggle focus between panels
