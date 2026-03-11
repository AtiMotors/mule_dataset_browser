#!/usr/bin/env python3
"""
Mule Dataset Browser — standalone TUI for browsing Ati Motors robot datasets.

Usage:
  python mule_browser.py 192.168.x.x   # SSH mode (direct)
  python mule_browser.py               # startup menu: [L] Local  [R] Robot
"""

from __future__ import annotations

import argparse
import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)

# ─── Constants ───────────────────────────────────────────────────────────────

ROBOT_USER = "ati"
ROBOT_BASE_PATH = "/opt/ati/data"
LOCAL_DATA_PATH = Path.home() / "data"

DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_FULL = {
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
    "Sat": "Saturday",
    "Sun": "Sunday",
}

# Mode → color mapping (used in table and badges)
MODE_COLORS = {
    "fleet": "green",
    "manual": "yellow",
    "simulation": "blue",
    "off": "dim",
}

# ─── Data Models ─────────────────────────────────────────────────────────────


@dataclass
class DatasetMeta:
    folder_name: str
    date: datetime
    robot: str
    mode: str
    distance_m: float
    duration_mins: float
    ip: str
    software_tag: str
    commit_id: str
    transition_reason: str
    raw_info: str = field(default="", repr=False)


@dataclass
class ConfigDiff:
    lines: List[str]
    is_empty: bool


# ─── Parsers ─────────────────────────────────────────────────────────────────

_FOLDER_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})-(\d{2})-(\d{2})-(\d{2})-(.+)$"
)


def parse_folder_name(folder_name: str) -> Optional[Tuple[datetime, str, str]]:
    """Return (date, robot, mode) from a dataset folder name, or None if unparseable."""
    m = _FOLDER_RE.match(folder_name)
    if not m:
        return None
    date_str = m.group(1)
    h, mi, s = m.group(2), m.group(3), m.group(4)
    rest = m.group(5)  # robot-customer-location-site-mode[_tag]
    try:
        dt = datetime.strptime(f"{date_str} {h}:{mi}:{s}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    parts = rest.split("-")
    # mode is always the last hyphen-separated segment (may have _tag suffix)
    mode_raw = parts[-1] if parts else "unknown"
    mode = mode_raw.split("_")[0]  # strip _tag suffix if present

    # robot name is everything except the last 4 parts (customer/location/site/mode)
    # folder: robot-customer-location-site-mode  →  min 5 parts
    if len(parts) >= 5:
        robot = "-".join(parts[:-4])
    elif len(parts) >= 2:
        robot = parts[0]
    else:
        robot = rest

    return dt, robot, mode


def parse_info_txt(raw: str) -> Dict[str, str]:
    """
    Parse info.txt into a flat dict.

    The file has two sections:
    1. Header lines: "key: value" or "key:value"
    2. A final run summary line: "key: value, key: value, ..."
    """
    result: Dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # Detect the comma-separated run summary line by looking for multiple k:v pairs
        if ", " in line and "run_id:" in line:
            for pair in line.split(", "):
                if ":" in pair:
                    k, _, v = pair.partition(":")
                    result[k.strip()] = v.strip().rstrip(",")
        elif ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


def build_dataset_meta(folder_name: str, raw_info: str) -> DatasetMeta:
    """Construct DatasetMeta from folder name + raw info.txt content."""
    parsed = parse_folder_name(folder_name)
    info = parse_info_txt(raw_info)

    if parsed:
        dt, robot_from_name, mode_from_name = parsed
    else:
        dt = datetime.min
        robot_from_name = "unknown"
        mode_from_name = "unknown"

    # Prefer info.txt values over folder name parsing where available
    robot = info.get("sherpa", robot_from_name).split()[0] if "sherpa" in info else robot_from_name
    ip = info.get("sherpa", "").split()[-1] if "sherpa" in info and len(info.get("sherpa", "").split()) > 1 else ""
    mode = info.get("mode", mode_from_name)
    software_tag = info.get("software_tag", "")
    commit_id = info.get("commit_id", "")[:8]
    transition_reason = info.get("transition_reason", "")

    try:
        distance_m = float(info.get("distance_m", "0"))
    except ValueError:
        distance_m = 0.0

    try:
        duration_mins = float(info.get("total_time_mins", "0"))
    except ValueError:
        duration_mins = 0.0

    # Parse start time from info if available (more precise than folder name)
    start_str = info.get("start_time", "")
    if start_str:
        try:
            dt = datetime.strptime(start_str, "%Y-%m-%d-%H-%M-%S")
        except ValueError:
            pass

    return DatasetMeta(
        folder_name=folder_name,
        date=dt,
        robot=robot,
        mode=mode,
        distance_m=distance_m,
        duration_mins=duration_mins,
        ip=ip,
        software_tag=software_tag,
        commit_id=commit_id,
        transition_reason=transition_reason,
        raw_info=raw_info,
    )


def parse_config_diff(raw: str) -> ConfigDiff:
    """Parse config-changes.txt into a ConfigDiff."""
    lines = raw.splitlines()
    return ConfigDiff(lines=lines, is_empty=len(lines) == 0 or not raw.strip())


def weekday_from_date(dt: datetime) -> str:
    """Return 3-letter weekday name (Mon, Tue, ...) from datetime."""
    return dt.strftime("%a")


# ─── Data Sources ─────────────────────────────────────────────────────────────


@dataclass
class DayBucket:
    day: str          # "Mon", "Tue", etc.
    count: int


class DataSource(ABC):
    @abstractmethod
    def list_days(self) -> List[DayBucket]:
        """Return all 7 day buckets (Mon–Sun) with dataset counts."""

    @abstractmethod
    def list_datasets(self, day: str) -> List[DatasetMeta]:
        """Return DatasetMeta list for the given day, sorted newest-first."""

    @abstractmethod
    def read_file(self, dataset: DatasetMeta, filename: str) -> str:
        """Return raw file contents as string, or empty string if missing."""

    @property
    @abstractmethod
    def label(self) -> str:
        """Short label for the header (e.g., robot name + IP, or 'Local')."""

    @property
    @abstractmethod
    def is_ssh(self) -> bool:
        """Whether this source uses SSH (enables fetch feature)."""


class LocalSource(DataSource):
    """Reads datasets from ~/data/ (flat folder, grouped by weekday from date prefix)."""

    def __init__(self, data_path: Path = LOCAL_DATA_PATH):
        self._path = data_path
        self._cache: Dict[str, List[DatasetMeta]] = {}

    @property
    def label(self) -> str:
        return f"Local  {self._path}"

    @property
    def is_ssh(self) -> bool:
        return False

    def _load_all(self) -> Dict[str, List[DatasetMeta]]:
        if self._cache:
            return self._cache
        grouped: Dict[str, List[DatasetMeta]] = {d: [] for d in DAY_ORDER}
        if not self._path.exists():
            return grouped
        for entry in self._path.iterdir():
            if not entry.is_dir():
                continue
            parsed = parse_folder_name(entry.name)
            if parsed is None:
                continue
            dt, _, _ = parsed
            day = weekday_from_date(dt)
            if day not in grouped:
                continue
            try:
                raw_info = (entry / "info.txt").read_text(errors="replace")
            except FileNotFoundError:
                raw_info = ""
            meta = build_dataset_meta(entry.name, raw_info)
            grouped[day].append(meta)
        for day in grouped:
            grouped[day].sort(key=lambda m: m.date, reverse=True)
        self._cache = grouped
        return grouped

    def list_days(self) -> List[DayBucket]:
        grouped = self._load_all()
        return [DayBucket(day=d, count=len(grouped[d])) for d in DAY_ORDER]

    def list_datasets(self, day: str) -> List[DatasetMeta]:
        grouped = self._load_all()
        return grouped.get(day, [])

    def read_file(self, dataset: DatasetMeta, filename: str) -> str:
        p = self._path / dataset.folder_name / filename
        try:
            return p.read_text(errors="replace")
        except FileNotFoundError:
            return ""


class SSHSource(DataSource):
    """Reads datasets from a robot over SSH."""

    def __init__(self, ip: str):
        self._ip = ip
        self._robot_name: str = ""
        self._cache: Dict[str, List[DatasetMeta]] = {}

    @property
    def label(self) -> str:
        name = self._robot_name or self._ip
        return f"●  {name}  {self._ip}"

    @property
    def is_ssh(self) -> bool:
        return True

    def _ssh(self, cmd: str) -> str:
        """Run a command on the robot via SSH, return stdout."""
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", f"{ROBOT_USER}@{self._ip}", cmd],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        return result.stdout

    def connect(self) -> None:
        """Verify connectivity and grab robot hostname."""
        out = self._ssh("hostname")
        self._robot_name = out.strip()

    def list_days(self) -> List[DayBucket]:
        if self._cache:
            return [DayBucket(day=d, count=len(self._cache.get(d, []))) for d in DAY_ORDER]
        result = []
        for day in DAY_ORDER:
            try:
                out = self._ssh(f"ls {ROBOT_BASE_PATH}/{day}/ 2>/dev/null | wc -l")
                count = int(out.strip())
            except Exception:
                count = 0
            result.append(DayBucket(day=day, count=count))
        return result

    def list_datasets(self, day: str) -> List[DatasetMeta]:
        if day in self._cache:
            return self._cache[day]
        try:
            out = self._ssh(f"ls {ROBOT_BASE_PATH}/{day}/")
            folders = [f.strip() for f in out.splitlines() if f.strip()]
        except Exception:
            return []

        datasets = []
        for folder in folders:
            try:
                raw_info = self._ssh(
                    f"cat {ROBOT_BASE_PATH}/{day}/{folder}/info.txt 2>/dev/null || true"
                )
            except Exception:
                raw_info = ""
            meta = build_dataset_meta(folder, raw_info)
            # For SSH mode we know the IP
            if not meta.ip:
                meta.ip = self._ip
            datasets.append(meta)

        datasets.sort(key=lambda m: m.date, reverse=True)
        self._cache[day] = datasets
        return datasets

    def read_file(self, dataset: DatasetMeta, filename: str) -> str:
        # We need to find which day bucket this dataset belongs to
        day = weekday_from_date(dataset.date)
        path = f"{ROBOT_BASE_PATH}/{day}/{dataset.folder_name}/{filename}"
        try:
            return self._ssh(f"cat {path} 2>/dev/null || true")
        except Exception:
            return ""

    def fetch_dataset(self, dataset: DatasetMeta, dest: Path = LOCAL_DATA_PATH) -> subprocess.Popen:
        """Start an rsync subprocess to fetch the dataset. Returns the Popen handle."""
        day = weekday_from_date(dataset.date)
        remote_path = f"{ROBOT_BASE_PATH}/{day}/{dataset.folder_name}"
        dest.mkdir(parents=True, exist_ok=True)
        return subprocess.Popen(
            ["rsync", "-avzP", f"{ROBOT_USER}@{self._ip}:{remote_path}", str(dest)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


# ─── Textual CSS ─────────────────────────────────────────────────────────────

APP_CSS = """
/* ── Global ── */
Screen {
    background: #1a1b26;
    color: #c0caf5;
}

/* ── Header ── */
Header {
    background: #16213e;
    color: #c0caf5;
    height: 1;
    dock: top;
}

/* ── Footer ── */
Footer {
    background: #16213e;
    color: #565f89;
    height: 1;
    dock: bottom;
}

Footer > .footer--key {
    color: #7aa2f7;
    background: #16213e;
}

/* ── Startup Screen ── */
#startup-container {
    align: center middle;
    height: 100%;
}

#startup-box {
    width: 50;
    height: 14;
    border: round #7aa2f7;
    background: #1f2335;
    padding: 2 4;
}

#startup-title {
    text-align: center;
    color: #7dcfff;
    text-style: bold;
    margin-bottom: 1;
}

#startup-subtitle {
    text-align: center;
    color: #565f89;
    margin-bottom: 2;
}

.startup-option {
    height: 3;
    align: center middle;
    border: round #3b4261;
    background: #1a1b26;
    margin-bottom: 1;
}

.startup-option:focus {
    border: round #7aa2f7;
    background: #1f2335;
}

.startup-key {
    color: #7aa2f7;
    text-style: bold;
}

#ip-input-container {
    align: center middle;
    height: 100%;
}

#ip-input-box {
    width: 50;
    height: 9;
    border: round #7aa2f7;
    background: #1f2335;
    padding: 2 4;
}

#ip-prompt {
    text-align: center;
    color: #c0caf5;
    margin-bottom: 1;
}

/* ── Main Screen ── */
#main-layout {
    layout: horizontal;
    height: 100%;
}

#day-panel {
    width: 18;
    border-right: solid #3b4261;
    background: #1f2335;
    padding: 0 1;
}

#day-panel-title {
    color: #7dcfff;
    text-style: bold;
    padding: 1 0;
    border-bottom: solid #3b4261;
    margin-bottom: 1;
}

#day-list {
    height: 1fr;
    border: none;
    background: #1f2335;
}

#day-list > ListItem {
    background: #1f2335;
    color: #a9b1d6;
    padding: 0 0;
}

#day-list > ListItem.--highlight {
    background: #2d3f6e;
    color: #7dcfff;
}

#day-list > ListItem Label {
    color: inherit;
    width: 100%;
}

#dataset-panel {
    width: 1fr;
    padding: 0 1;
}

#dataset-panel-title {
    color: #c0caf5;
    text-style: bold;
    padding: 1 0;
    border-bottom: solid #3b4261;
    margin-bottom: 1;
}

#dataset-table {
    height: 1fr;
    border: none;
    background: #1a1b26;
}

DataTable > .datatable--header {
    background: #16213e;
    color: #7aa2f7;
    text-style: bold;
}

DataTable > .datatable--odd-row {
    background: #1a1b26;
}

DataTable > .datatable--even-row {
    background: #1f2335;
}

DataTable > .datatable--cursor {
    background: #2d3f6e;
    color: #c0caf5;
}

#search-bar {
    dock: bottom;
    display: none;
    height: 3;
    border: round #7aa2f7;
    background: #1f2335;
    margin: 0 1;
}

#search-bar.visible {
    display: block;
}

/* ── Detail Screen ── */
#detail-layout {
    layout: horizontal;
    height: 100%;
}

#info-panel {
    width: 40;
    border-right: solid #3b4261;
    background: #1f2335;
    padding: 1 2;
}

#info-panel-title {
    color: #7dcfff;
    text-style: bold;
    border-bottom: solid #3b4261;
    margin-bottom: 1;
    padding-bottom: 1;
}

.info-row {
    height: 1;
    layout: horizontal;
}

.info-label {
    width: 10;
    color: #565f89;
}

.info-value {
    color: #c0caf5;
    width: 1fr;
}

.info-value.mode-fleet { color: #9ece6a; }
.info-value.mode-manual { color: #e0af68; }
.info-value.mode-simulation { color: #7aa2f7; }

#diff-panel {
    width: 1fr;
    padding: 1 2;
}

#diff-panel-title {
    color: #7dcfff;
    text-style: bold;
    border-bottom: solid #3b4261;
    margin-bottom: 1;
    padding-bottom: 1;
}

#diff-content {
    height: 1fr;
    overflow-y: auto;
}

.diff-line-add {
    color: #9ece6a;
    background: #1a2e1a;
}

.diff-line-remove {
    color: #f7768e;
    background: #2e1a1a;
}

.diff-line-meta {
    color: #7dcfff;
}

.diff-line-normal {
    color: #565f89;
}

.diff-empty {
    color: #565f89;
    text-style: italic;
    margin-top: 2;
}

/* ── Fetch Modal ── */
FetchModal {
    align: center middle;
}

#fetch-box {
    width: 60;
    height: 14;
    border: round #7aa2f7;
    background: #1f2335;
    padding: 2 3;
}

#fetch-title {
    color: #7dcfff;
    text-style: bold;
    text-align: center;
    margin-bottom: 1;
}

#fetch-dataset-name {
    color: #a9b1d6;
    text-align: center;
    margin-bottom: 2;
}

#fetch-progress {
    color: #9ece6a;
    height: 3;
    overflow: hidden;
}

#fetch-actions {
    layout: horizontal;
    align: center middle;
    margin-top: 1;
}

.fetch-btn {
    width: 12;
    height: 3;
    border: round #3b4261;
    background: #1a1b26;
    margin: 0 1;
    align: center middle;
    text-align: center;
}

.fetch-btn:hover {
    border: round #7aa2f7;
    background: #1f2335;
}

/* ── Error Screen ── */
#error-container {
    align: center middle;
    height: 100%;
}

#error-box {
    width: 60;
    height: 14;
    border: round #f7768e;
    background: #1f2335;
    padding: 2 3;
}

#error-title {
    color: #f7768e;
    text-style: bold;
    text-align: center;
    margin-bottom: 1;
}

#error-message {
    color: #a9b1d6;
    margin-bottom: 2;
    text-align: center;
}
"""


# ─── Custom Widgets ───────────────────────────────────────────────────────────


class DiffLine(Static):
    """A single line of unified diff output with appropriate styling."""

    def __init__(self, line: str):
        css_class = "diff-line-normal"
        if line.startswith("+") and not line.startswith("+++"):
            css_class = "diff-line-add"
        elif line.startswith("-") and not line.startswith("---"):
            css_class = "diff-line-remove"
        elif line.startswith("@@") or line.startswith("---") or line.startswith("+++"):
            css_class = "diff-line-meta"
        super().__init__(line)
        self.add_class(css_class)


# ─── Screens ─────────────────────────────────────────────────────────────────


class ErrorScreen(Screen):
    """Full-screen error with Retry / Quit options."""

    BINDINGS = [
        Binding("r", "retry", "Retry"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, message: str, **kwargs):
        super().__init__(**kwargs)
        self._message = message

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="error-container"):
            with Vertical(id="error-box"):
                yield Static("Connection Error", id="error-title")
                yield Static(self._message, id="error-message")
                yield Static(
                    "  [r] Retry    [q] Quit  ",
                    markup=False,
                )
        yield Footer()

    def action_retry(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()


class FetchModal(ModalScreen):
    """Confirmation + progress modal for rsync fetch."""

    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
        Binding("y", "confirm", "Confirm"),
    ]

    def __init__(self, dataset: DatasetMeta, source: SSHSource, **kwargs):
        super().__init__(**kwargs)
        self._dataset = dataset
        self._source = source
        self._fetching = False

    def compose(self) -> ComposeResult:
        with Vertical(id="fetch-box"):
            yield Static("Fetch Dataset", id="fetch-title")
            yield Static(self._dataset.folder_name, id="fetch-dataset-name")
            yield Static(
                f"Destination: {LOCAL_DATA_PATH}/",
                classes="diff-line-normal",
            )
            yield Static("", id="fetch-progress")
            with Horizontal(id="fetch-actions"):
                yield Static("[y] Confirm", classes="fetch-btn", id="confirm-btn")
                yield Static("[Esc] Cancel", classes="fetch-btn", id="cancel-btn")

    def action_confirm(self) -> None:
        if not self._fetching:
            self._fetching = True
            self._do_fetch()

    @work(thread=True)
    def _do_fetch(self) -> None:
        progress = self.query_one("#fetch-progress", Static)
        self.app.call_from_thread(progress.update, "Starting rsync…")
        try:
            proc = self._source.fetch_dataset(self._dataset)
            lines = []
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.append(line.rstrip())
                # Show last 3 lines of rsync output
                display = "\n".join(lines[-3:])
                self.app.call_from_thread(progress.update, display)
            proc.wait()
            if proc.returncode == 0:
                self.app.call_from_thread(
                    self.app.notify,
                    f"Fetched {self._dataset.folder_name}",
                    title="Done",
                )
                self.app.call_from_thread(self.dismiss, True)
            else:
                stderr = proc.stderr.read() if proc.stderr else ""
                msg = f"rsync failed:\n{stderr}\n\nRe-run to resume."
                self.app.call_from_thread(progress.update, msg)
        except Exception as exc:
            self.app.call_from_thread(
                progress.update,
                f"Error: {exc}\n\nRe-run to resume.",
            )


class DetailScreen(Screen):
    """Shows Run Info + Config Diff for a single dataset."""

    BINDINGS = [
        Binding("escape,b", "back", "Back"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, dataset: DatasetMeta, source: DataSource, **kwargs):
        super().__init__(**kwargs)
        self._dataset = dataset
        self._source = source

    def compose(self) -> ComposeResult:
        ds = self._dataset
        yield Header(show_clock=False)
        with Horizontal(id="detail-layout"):
            # Left: Run Info
            with Vertical(id="info-panel"):
                yield Static("Run Info", id="info-panel-title")
                yield self._info_row("Robot", ds.robot)
                if ds.ip:
                    yield self._info_row("IP", ds.ip)
                yield self._info_row("Mode", ds.mode)
                yield self._info_row("Start", ds.date.strftime("%H:%M:%S"))
                yield self._info_row("Date", ds.date.strftime("%d %b %Y"))
                yield self._info_row("Time", f"{ds.duration_mins:.2f} min")
                yield self._info_row("Dist", f"{ds.distance_m:.1f} m")
                if ds.software_tag:
                    yield self._info_row("Tag", ds.software_tag)
                if ds.commit_id:
                    yield self._info_row("Commit", ds.commit_id)
                if ds.transition_reason:
                    yield self._info_row("Reason", ds.transition_reason)
                # Spacer + folder name at bottom
                yield Static("")
                yield Static(ds.folder_name, classes="diff-line-normal")

            # Right: Config diff
            with Vertical(id="diff-panel"):
                yield Static("Config Changes", id="diff-panel-title")
                with Vertical(id="diff-content"):
                    yield Static("Loading…", id="diff-loading")

        yield Footer()

    def _info_row(self, label: str, value: str) -> Static:
        return Static(f"{label:<8}  {value}", classes="diff-line-normal")

    def on_mount(self) -> None:
        self._load_diff()

    @work(thread=True)
    def _load_diff(self) -> None:
        raw = self._source.read_file(self._dataset, "config-changes.txt")
        diff = parse_config_diff(raw)
        container = self.query_one("#diff-content")
        self.app.call_from_thread(self._render_diff, container, diff)

    def _render_diff(self, container, diff: ConfigDiff) -> None:
        loading = self.query_one("#diff-loading", Static)
        loading.remove()
        if diff.is_empty:
            container.mount(Static("No config changes recorded.", classes="diff-empty"))
        else:
            for line in diff.lines:
                container.mount(DiffLine(line))

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()


class MainScreen(Screen):
    """Primary dataset browsing screen: Day panel (left) + Dataset table (right)."""

    BINDINGS = [
        Binding("enter", "open_detail", "Detail"),
        Binding("/", "search", "Search"),
        Binding("l", "jump_latest", "Latest"),
        Binding("f", "fetch", "Fetch"),
        Binding("q", "quit_app", "Quit"),
        Binding("escape", "close_search", "Close search", show=False),
    ]

    _search_filter: reactive[str] = reactive("")

    def __init__(self, source: DataSource, **kwargs):
        super().__init__(**kwargs)
        self._source = source
        self._days: List[DayBucket] = []
        self._current_datasets: List[DatasetMeta] = []
        self._search_active = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main-layout"):
            with Vertical(id="day-panel"):
                yield Static("  Day", id="day-panel-title")
                yield ListView(id="day-list")
            with Vertical(id="dataset-panel"):
                yield Static("", id="dataset-panel-title")
                yield DataTable(id="dataset-table", zebra_stripes=True, cursor_type="row")
                yield Input(placeholder="Filter datasets…", id="search-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#dataset-table", DataTable)
        table.add_columns("Date", "Day", "Robot", "Mode", "Dist", "Dur")
        self._load_days()

    @work(thread=True)
    def _load_days(self) -> None:
        try:
            days = self._source.list_days()
        except Exception as exc:
            self.app.call_from_thread(
                self.app.push_screen,
                ErrorScreen(str(exc)),
            )
            return
        self.app.call_from_thread(self._render_days, days)

    def _render_days(self, days: List[DayBucket]) -> None:
        self._days = days
        day_list = self.query_one("#day-list", ListView)
        day_list.clear()
        for bucket in days:
            label = f"  {DAY_FULL[bucket.day]:<11}  {bucket.count:>3}"
            day_list.append(ListItem(Label(label), name=bucket.day))
        # Focus day list first so user can immediately navigate
        day_list.focus()
        # Load first day
        if days:
            self._load_datasets(days[0].day)

    def _load_datasets(self, day: str) -> None:
        title = self.query_one("#dataset-panel-title", Static)
        title.update(f"  Loading {DAY_FULL[day]}…")
        self._do_load_datasets(day)

    @work(thread=True)
    def _do_load_datasets(self, day: str) -> None:
        try:
            datasets = self._source.list_datasets(day)
        except Exception as exc:
            self.app.call_from_thread(
                self.app.notify,
                str(exc),
                title="SSH Error",
                severity="error",
            )
            datasets = []
        self.app.call_from_thread(self._render_datasets, day, datasets)

    def _render_datasets(self, day: str, datasets: List[DatasetMeta]) -> None:
        self._current_datasets = datasets
        title = self.query_one("#dataset-panel-title", Static)
        total = len(datasets)
        title.update(f"  {DAY_FULL[day]} — {total} dataset{'s' if total != 1 else ''}")
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#dataset-table", DataTable)
        table.clear()
        filt = self._search_filter.lower()
        shown = [
            ds for ds in self._current_datasets
            if not filt or filt in ds.folder_name.lower() or filt in ds.robot.lower()
        ]
        for ds in shown:
            date_str = ds.date.strftime("%d %b %Y %H:%M")
            day_str = ds.date.strftime("%a")
            dist = f"{ds.distance_m:.1f}m"
            dur = f"{ds.duration_mins:.1f}m"
            mode_color = MODE_COLORS.get(ds.mode, "")
            mode_cell = f"[{mode_color}]{ds.mode}[/]" if mode_color else ds.mode
            table.add_row(date_str, day_str, ds.robot, mode_cell, dist, dur)

    def _get_selected_dataset(self) -> Optional[DatasetMeta]:
        """Return the dataset under the DataTable cursor, or None."""
        table = self.query_one("#dataset-table", DataTable)
        if table.cursor_row is None:
            return None
        filt = self._search_filter.lower()
        shown = [
            ds for ds in self._current_datasets
            if not filt or filt in ds.folder_name.lower() or filt in ds.robot.lower()
        ]
        if 0 <= table.cursor_row < len(shown):
            return shown[table.cursor_row]
        return None

    # ── ListView event: day changed ──

    @on(ListView.Highlighted, "#day-list")
    def on_day_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is not None and event.item.name:
            self._load_datasets(event.item.name)

    # ── Key actions ──

    def action_open_detail(self) -> None:
        focused = self.focused
        if focused and focused.id == "day-list":
            # Enter on day list → move focus to dataset table
            self.query_one("#dataset-table", DataTable).focus()
            return
        dataset = self._get_selected_dataset()
        if dataset:
            self.app.push_screen(DetailScreen(dataset, self._source))

    def action_search(self) -> None:
        search_bar = self.query_one("#search-bar", Input)
        self._search_active = True
        search_bar.add_class("visible")
        search_bar.focus()

    def action_close_search(self) -> None:
        if self._search_active:
            search_bar = self.query_one("#search-bar", Input)
            self._search_active = False
            search_bar.remove_class("visible")
            self._search_filter = ""
            search_bar.value = ""
            self._refresh_table()
            self.query_one("#dataset-table", DataTable).focus()

    def action_jump_latest(self) -> None:
        table = self.query_one("#dataset-table", DataTable)
        if self._current_datasets:
            table.move_cursor(row=0)
            table.focus()

    def action_fetch(self) -> None:
        if not self._source.is_ssh:
            self.app.notify("Fetch is only available in SSH mode.", severity="warning")
            return
        dataset = self._get_selected_dataset()
        if dataset:
            self.app.push_screen(FetchModal(dataset, self._source))  # type: ignore[arg-type]

    def action_quit_app(self) -> None:
        self.app.exit()

    @on(Input.Changed, "#search-bar")
    def on_search_changed(self, event: Input.Changed) -> None:
        self._search_filter = event.value
        self._refresh_table()

    @on(Input.Submitted, "#search-bar")
    def on_search_submitted(self) -> None:
        self.query_one("#dataset-table", DataTable).focus()


class StartupScreen(Screen):
    """Initial screen: choose Local or SSH mode."""

    BINDINGS = [
        Binding("l", "local", "Local"),
        Binding("r", "robot", "Robot (SSH)"),
        Binding("q", "quit_app", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="startup-container"):
            with Vertical(id="startup-box"):
                yield Static("Mule Dataset Browser", id="startup-title")
                yield Static("Choose a data source", id="startup-subtitle")
                yield Static(
                    "[bold cyan]L[/]  Browse local datasets  ~/data/",
                    classes="startup-option",
                    id="opt-local",
                )
                yield Static(
                    "[bold cyan]R[/]  Connect to robot  (SSH)",
                    classes="startup-option",
                    id="opt-robot",
                )
        yield Footer()

    def action_local(self) -> None:
        self.app.switch_source(LocalSource())

    def action_robot(self) -> None:
        self.app.push_screen(IPInputScreen())

    def action_quit_app(self) -> None:
        self.app.exit()


class IPInputScreen(Screen):
    """Prompt for robot IP address."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="ip-input-container"):
            with Vertical(id="ip-input-box"):
                yield Static("Enter robot IP address:", id="ip-prompt")
                yield Input(
                    placeholder="192.168.x.x",
                    id="ip-input",
                )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#ip-input", Input).focus()

    @on(Input.Submitted, "#ip-input")
    def on_ip_submitted(self, event: Input.Submitted) -> None:
        ip = event.value.strip()
        if ip:
            self.app.connect_ssh(ip)

    def action_back(self) -> None:
        self.app.pop_screen()


# ─── App ─────────────────────────────────────────────────────────────────────


class MuleBrowser(App):
    """Mule Dataset Browser TUI application."""

    CSS = APP_CSS
    TITLE = "Mule Dataset Browser"
    SUB_TITLE = ""

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, initial_ip: Optional[str] = None, start_local: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._initial_ip = initial_ip
        self._start_local = start_local

    def on_mount(self) -> None:
        if self._start_local:
            self.switch_source(LocalSource())
        elif self._initial_ip:
            self.connect_ssh(self._initial_ip)
        else:
            self.push_screen(StartupScreen())

    def switch_source(self, source: DataSource) -> None:
        self.SUB_TITLE = source.label
        # Clear the screen stack down to root, then push MainScreen
        while len(self._screen_stack) > 1:
            self.pop_screen()
        self.push_screen(MainScreen(source))

    @work(thread=True)
    def connect_ssh(self, ip: str) -> None:
        source = SSHSource(ip)
        try:
            source.connect()
        except Exception as exc:
            self.call_from_thread(
                self.push_screen,
                ErrorScreen(f"Cannot connect to {ip}:\n{exc}"),
            )
            return
        self.call_from_thread(self.switch_source, source)


# ─── Entry Point ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Browse Ati Motors robot datasets in a TUI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python mule_browser.py                 # startup menu
  python mule_browser.py 192.168.6.180  # SSH mode directly
  python mule_browser.py --local        # local mode directly
        """,
    )
    parser.add_argument(
        "ip",
        nargs="?",
        default=None,
        help="Robot IP address for SSH mode (optional)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Open local dataset browser directly (~/data/)",
    )
    args = parser.parse_args()

    app = MuleBrowser(initial_ip=args.ip, start_local=args.local)
    app.run()


if __name__ == "__main__":
    main()
