# LOCALREADLOG_GITHUB_READY_20260612
# NO_SERIES_ALL_FIXED_20260612
import csv
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote, unquote


# =========================
# 기본 설정
# =========================

APP_DISPLAY_NAME = "LocalReadLog"

HOST = "0.0.0.0"
DEFAULT_PORT = 8787

try:
    PORT = int(os.environ.get("LOCALREADLOG_MANAGER_PORT", os.environ.get("BLACKTOON_MANAGER_PORT", str(DEFAULT_PORT))))
except Exception:
    PORT = DEFAULT_PORT

PORT_CANDIDATES = []
for _port in [PORT, DEFAULT_PORT, 8877, 18787, 28787]:
    if _port not in PORT_CANDIDATES:
        PORT_CANDIDATES.append(_port)

CURRENT_SERVER_PORT = PORT

SITE_SPECS = {
    "blacktoon": {"label": "블랙툰", "prefix": "blacktoon"},
    "wfwf": {"label": "늑대", "prefix": "wfwf"},
    "tkor": {"label": "툰코", "prefix": "tkor"},
}

DEFAULT_SITE_PRIORITY = ["blacktoon", "wfwf", "tkor"]
SITE_NAME_ALIASES = {
    "blacktoon": "blacktoon",
    "블랙툰": "blacktoon",
    "wfwf": "wfwf",
    "늑대": "wfwf",
    "늑대닷컴": "wfwf",
    "tkor": "tkor",
    "툰코": "tkor",
}

DEFAULT_BROWSER_ENABLED = {
    "whale": True,
    "edge": True,
    "chrome": True,
    "firefox": True,
}
BROWSER_LABELS = {
    "whale": "Whale",
    "edge": "Edge",
    "chrome": "Chrome",
    "firefox": "Firefox",
}

SCRIPT_DIR = Path(__file__).resolve().parent
APP_ROOT_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.name.lower() == "core" else SCRIPT_DIR
BACKUP_SCRIPT = SCRIPT_DIR / "localreadlog_backup.py"
CONFIG_JSON = APP_ROOT_DIR / "localreadlog_config.json"

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def find_onedrive_dir():
    for env_name in ["OneDriveConsumer", "OneDrive", "OneDriveCommercial"]:
        path = os.environ.get(env_name)
        if path:
            p = Path(path)
            if p.exists():
                return p

    for p in Path.home().glob("OneDrive*"):
        if p.is_dir():
            return p

    return None


def load_app_config():
    if not CONFIG_JSON.exists():
        return {}

    try:
        with CONFIG_JSON.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        try:
            print(f"설정 파일 읽기 실패: {CONFIG_JSON} / {e}")
        except Exception:
            pass
        return {}


def expand_config_path(value):
    value = str(value or "").strip().strip('"')
    if not value:
        return None

    expanded = os.path.expanduser(os.path.expandvars(value))
    path = Path(expanded)

    if not path.is_absolute():
        path = APP_ROOT_DIR / path

    return path


# 공개판 기본값: 프로그램 파일이 있는 폴더에 DB/CSV/HTML/로그를 저장한다.
# 파일 위치를 한눈에 확인하기 쉽고, 백업/이동도 폴더째로 하면 된다.
ONEDRIVE_DIR = None
DATA_DIR = APP_ROOT_DIR / "data"
DEFAULT_BACKUP_DIR = DATA_DIR
DOCUMENTS_BACKUP_DIR = Path.home() / "Documents" / "reading_backup"  # 예전 수동 백업을 찾을 때만 참고
BACKUP_DIR = DEFAULT_BACKUP_DIR

LATEST_CSV = BACKUP_DIR / "localreadlog_latest.csv"
IGNORE_TXT = BACKUP_DIR / "localreadlog_ignore.txt"
PURGED_TXT = BACKUP_DIR / "localreadlog_purged.txt"

DB_JSON = BACKUP_DIR / "localreadlog_db.json"
LOG_TXT = BACKUP_DIR / "localreadlog_manager_log.txt"
PID_TXT = BACKUP_DIR / "localreadlog_server.pid"
PORT_TXT = BACKUP_DIR / "localreadlog_server_port.txt"



def is_same_path(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except Exception:
        return str(a) == str(b)


def migrate_first_existing_file_if_needed(new_path, old_paths):
    try:
        if new_path.exists():
            return None
        for old_path in old_paths:
            old_path = Path(old_path)
            if is_same_path(new_path, old_path):
                continue
            if not old_path.exists():
                continue
            new_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(old_path, new_path)
            return old_path
    except Exception as e:
        try:
            print(f"기존 파일 이전 실패: {new_path} / {e}")
        except Exception:
            pass
    return None


def migrate_legacy_file_if_needed(new_path, old_path):
    return migrate_first_existing_file_if_needed(new_path, [old_path]) is not None

SCAN_DIRS = [
    BACKUP_DIR,
    BACKUP_DIR / "archive",
]


# =========================
# 텍스트/정렬/로그
# =========================

def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_title(title):
    title = str(title or "").strip()
    title = re.sub(r"\s+", " ", title)

    remove_patterns = [
        r"\s*BlackToon\s*블랙툰\s*-\s*무료웹툰\s*웹툰미리보기\s*$",
        r"\s*BlackToon\s*블랙툰.*$",
        r"\s*-\s*BlackToon\s*블랙툰.*$",
        r"\s*\|\s*BlackToon\s*블랙툰.*$",
        r"\s*-\s*무료웹툰\s*웹툰미리보기\s*$",

        r"\s*-\s*늑대닷컴.*$",
        r"\s*\|\s*늑대닷컴.*$",
        r"\s*WFWF.*$",

        r"\s*-\s*툰코.*$",
        r"\s*\|\s*툰코.*$",
        r"\s*Toonkor.*$",
        r"\s*Tkor.*$",
    ]

    for pattern in remove_patterns:
        title = re.sub(pattern, "", title, flags=re.I)

    return title.strip()


def title_key(title):
    title = clean_title(title).lower()
    return re.sub(r"\s+", " ", title).strip()


def episode_sort_value(value):
    try:
        return float(str(value or "").strip())
    except Exception:
        return 0.0


def episode_key(value):
    n = episode_sort_value(value)

    if n <= 0:
        return ""

    if n.is_integer():
        return str(int(n))

    return str(n)


def append_log(message):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{now_text()}] {message}"

    try:
        with LOG_TXT.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

    print(line)


def read_log_lines(limit=300):
    if not LOG_TXT.exists():
        return []

    try:
        lines = LOG_TXT.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-limit:]
    except Exception as e:
        return [f"로그 읽기 실패: {e}"]


def choose_better(old, new):
    old_ep = episode_sort_value(old.get("latest_episode", ""))
    new_ep = episode_sort_value(new.get("latest_episode", ""))

    if new_ep > old_ep:
        return new

    if new_ep < old_ep:
        return old

    if str(new.get("last_seen", "")) > str(old.get("last_seen", "")):
        return new

    return old


def get___removed_link__(url):
    """
    회차 URL을 작품 메인 URL로 변환.
    현재 정확히 보장되는 건 블랙툰 구조.
    늑대/툰코는 URL 구조가 사이트마다 달라서 확실한 경우에만 빈값이 아닌 값을 반환.
    """
    url = str(url or "").strip()

    if not url:
        return ""

    episode_match = re.match(
        r"^(https?://(?:www\.)?blacktoon\d+\.com)/webtoons/(\d+)/\d+\.html(?:[?#].*)?$",
        url,
        flags=re.I,
    )

    if episode_match:
        return f"{episode_match.group(1)}/webtoon/{episode_match.group(2)}.html"

    series_match = re.match(
        r"^(https?://(?:www\.)?blacktoon\d+\.com/webtoon/\d+\.html)(?:[?#].*)?$",
        url,
        flags=re.I,
    )

    if series_match:
        return series_match.group(1)

    return ""


def site_label(site_key):
    return SITE_SPECS.get(site_key, {}).get("label", site_key or "")


def extract_tracked_host_info(url):
    url = str(url or "")

    for site_key, spec in SITE_SPECS.items():
        prefix = spec["prefix"]
        match = re.search(
            rf"https?://(?:www\.)?{re.escape(prefix)}(\d+)\.com",
            url,
            re.I,
        )

        if not match:
            continue

        try:
            return site_key, int(match.group(1))
        except Exception:
            return None

    return None


def extract_blacktoon_host_number(url):
    info = extract_tracked_host_info(url)

    if not info:
        return None

    return info[1]


def normalize_blacktoon_url(url, latest_hosts):
    url = str(url or "").strip()

    if not url or not latest_hosts:
        return url

    if isinstance(latest_hosts, str):
        return re.sub(
            r"^https?://(?:www\.)?blacktoon\d+\.com",
            latest_hosts,
            url,
            flags=re.I,
        )

    info = extract_tracked_host_info(url)

    if not info:
        return url

    site_key, _ = info
    latest_host = latest_hosts.get(site_key)

    if not latest_host:
        return url

    prefix = SITE_SPECS[site_key]["prefix"]

    return re.sub(
        rf"^https?://(?:www\.)?{re.escape(prefix)}\d+\.com",
        latest_host,
        url,
        flags=re.I,
    )


def collect_db_urls(db):
    urls = []

    for item in db.get("items", {}).values():
        if not isinstance(item, dict):
            continue

        if item.get("url"):
            urls.append(str(item.get("url", "")))

        for record in (item.get("episode_history", {}) or {}).values():
            if isinstance(record, dict) and record.get("url"):
                urls.append(str(record.get("url", "")))

    return urls


def get_latest_blacktoon_host_from_db(db):
    max_nums = {}

    for url in collect_db_urls(db):
        info = extract_tracked_host_info(url)

        if not info:
            continue

        site_key, number = info

        if site_key not in max_nums or number > max_nums[site_key]:
            max_nums[site_key] = number

    latest = {}

    for site_key, number in max_nums.items():
        prefix = SITE_SPECS[site_key]["prefix"]
        latest[site_key] = f"https://{prefix}{number}.com"

    return latest


def normalize_db_urls_to_latest(db):
    latest_hosts = get_latest_blacktoon_host_from_db(db)

    if not latest_hosts:
        return db

    for item in db.get("items", {}).values():
        if not isinstance(item, dict):
            continue

        item["url"] = normalize_blacktoon_url(item.get("url", ""), latest_hosts)

        history = item.get("episode_history", {}) or {}
        for record in history.values():
            if isinstance(record, dict):
                record["url"] = normalize_blacktoon_url(record.get("url", ""), latest_hosts)

    return db


# =========================
# CSV / TXT
# =========================

def read_csv_rows(csv_path):
    rows = []

    if not csv_path.exists():
        return rows

    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                title = clean_title(row.get("title", ""))

                if not title:
                    continue

                rows.append({
                    "title": title,
                    "latest_episode": str(row.get("latest_episode", "") or "").strip(),
                    "last_seen": str(row.get("last_seen", "") or "").strip(),
                    "url": str(row.get("url", "") or "").strip(),
                    "__removed_link__": str(row.get("__removed_link__", "") or "").strip(),
                })

    except Exception as e:
        append_log(f"CSV 읽기 실패: {csv_path} / {e}")

    return rows


def get_existing_csv_paths():
    paths = []

    for scan_dir in SCAN_DIRS:
        if not scan_dir.exists():
            continue

        for name in ["localreadlog_latest.csv"]:
            p = scan_dir / name
            if p.exists():
                paths.append(p)

        for pattern in ["localreadlog_latest_*.csv"]:
            for p in scan_dir.glob(pattern):
                if p.exists():
                    paths.append(p)

    unique = []
    seen = set()

    for p in paths:
        try:
            key = str(p.resolve())
        except Exception:
            key = str(p)

        if key in seen:
            continue

        seen.add(key)
        unique.append(p)

    return unique


def get_text_file_paths(filename):
    candidates = [
        BACKUP_DIR / filename,
    ]

    unique = []
    seen = set()

    for p in candidates:
        try:
            key = str(p.resolve())
        except Exception:
            key = str(p)

        if key in seen:
            continue

        seen.add(key)
        unique.append(p)

    return unique


def load_title_list_from_txt(filename):
    titles = {}

    for path in get_text_file_paths(filename):
        if not path.exists():
            continue

        try:
            with path.open("r", encoding="utf-8-sig") as f:
                for line in f:
                    raw = line.strip()

                    if not raw or raw.startswith("#"):
                        continue

                    title = clean_title(raw)
                    key = title_key(title)

                    if key:
                        titles[key] = title

        except Exception as e:
            append_log(f"{filename} 읽기 실패: {path} / {e}")

    return titles


def write_title_list_to_txt(path, titles):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="\n") as f:
        for title in sorted(set(clean_title(x) for x in titles if clean_title(x))):
            f.write(title + "\n")


# =========================
# DB
# =========================

def default_db():
    return {
        "version": 1,
        "created_at": now_text(),
        "updated_at": now_text(),
        "settings": {
            "site_priority": list(DEFAULT_SITE_PRIORITY),
            "hide_site_duplicates": True,
            "browser_enabled": dict(DEFAULT_BROWSER_ENABLED),
        },
        "items": {},
    }


def normalize_site_priority(value):
    if isinstance(value, str):
        raw_parts = re.split(r"[>,/,\s]+", value.strip())
    elif isinstance(value, list):
        raw_parts = value
    else:
        raw_parts = []

    result = []
    seen = set()

    for raw in raw_parts:
        token = str(raw or "").strip().lower()
        if not token:
            continue

        site_key = SITE_NAME_ALIASES.get(token, token)

        if site_key not in SITE_SPECS or site_key in seen:
            continue

        seen.add(site_key)
        result.append(site_key)

    for site_key in DEFAULT_SITE_PRIORITY:
        if site_key not in seen:
            result.append(site_key)

    return result


def normalize_settings(db):
    db.setdefault("settings", {})
    settings = db["settings"]

    if not isinstance(settings, dict):
        settings = {}
        db["settings"] = settings

    settings["site_priority"] = normalize_site_priority(
        settings.get("site_priority", DEFAULT_SITE_PRIORITY)
    )
    raw_hide = settings.get("hide_site_duplicates", True)
    if isinstance(raw_hide, str):
        settings["hide_site_duplicates"] = raw_hide.strip().lower() not in ["0", "false", "off", "no", "아니오", "끔"]
    else:
        settings["hide_site_duplicates"] = bool(raw_hide)

    raw_browser_enabled = settings.get("browser_enabled", DEFAULT_BROWSER_ENABLED)
    if not isinstance(raw_browser_enabled, dict):
        raw_browser_enabled = {}

    browser_enabled = {}
    for key, default in DEFAULT_BROWSER_ENABLED.items():
        value = raw_browser_enabled.get(key, default)
        if isinstance(value, str):
            browser_enabled[key] = value.strip().lower() not in ["0", "false", "off", "no", "아니오", "끔"]
        else:
            browser_enabled[key] = bool(value)

    settings["browser_enabled"] = browser_enabled

    return db


def get_site_key_from_url(url):
    info = extract_tracked_host_info(url)
    return info[0] if info else ""


def get_site_key_from_title(title):
    title = str(title or "").strip()

    match = re.match(r"^\[(블랙툰|늑대|툰코)\]\s*", title)
    if not match:
        return ""

    return SITE_NAME_ALIASES.get(match.group(1), "")


def item_site_key(item):
    if not isinstance(item, dict):
        return ""

    site_key = get_site_key_from_url(item.get("url", ""))
    if site_key:
        return site_key

    site_key = get_site_key_from_title(item.get("title", ""))
    if site_key:
        return site_key

    for record in (item.get("episode_history", {}) or {}).values():
        if isinstance(record, dict):
            site_key = get_site_key_from_url(record.get("url", ""))
            if site_key:
                return site_key

    return "blacktoon"


def canonical_title_for_duplicate(title):
    title = clean_title(title)

    labels = {"블랙툰", "늑대", "툰코"}

    try:
        for spec in (SITE_SPECS or {}).values():
            label = str(spec.get("label", "") or "").strip()
            if label:
                labels.add(label)
    except Exception:
        pass

    changed = True
    while changed:
        changed = False
        for label in sorted(labels, key=len, reverse=True):
            if not label:
                continue
            new_title = re.sub(rf"^\[{re.escape(label)}\]\s*", "", title, flags=re.I).strip()
            if new_title != title:
                title = new_title
                changed = True

    title = re.sub(r"\s+", " ", title)
    return title.lower()


def duplicate_group_key(row):
    title = canonical_title_for_duplicate(row.get("title", ""))

    if not title:
        return ""

    return f"title:{title}"


def priority_index(site_key, settings):
    priority = settings.get("site_priority", DEFAULT_SITE_PRIORITY)

    try:
        return priority.index(site_key)
    except ValueError:
        return len(priority) + 10


def choose_duplicate_display(old, new, settings):
    old_site = old.get("site", "") or get_site_key_from_url(old.get("url", "")) or get_site_key_from_title(old.get("title", ""))
    new_site = new.get("site", "") or get_site_key_from_url(new.get("url", "")) or get_site_key_from_title(new.get("title", ""))

    def enabled(site_key):
        try:
            return settings.get("sites", {}).get(site_key, {}).get("enabled", True) is not False
        except Exception:
            return True

    old_enabled = enabled(old_site)
    new_enabled = enabled(new_site)

    # 죽었거나 끈 사이트는 같은 작품 중복에서 밀어냄.
    if new_enabled and not old_enabled:
        return new

    if old_enabled and not new_enabled:
        return old

    old_ep = episode_sort_value(old.get("latest_episode", ""))
    new_ep = episode_sort_value(new.get("latest_episode", ""))

    # 다른 사이트가 더 높은 화수까지 이어졌으면 우선순위보다 최신 화수를 우선.
    if new_ep > old_ep:
        return new

    if new_ep < old_ep:
        return old

    old_pri = priority_index(old_site, settings)
    new_pri = priority_index(new_site, settings)

    # 같은 화수면 사이트 우선순위 적용.
    if new_pri < old_pri:
        return new

    if new_pri > old_pri:
        return old

    if str(new.get("last_seen", "")) > str(old.get("last_seen", "")):
        return new

    return old


def apply_site_duplicate_filter(rows, db):
    db = normalize_settings(db)
    settings = db.get("settings", {})

    if not settings.get("hide_site_duplicates", True):
        return rows

    grouped = {}

    for row in rows:
        key = duplicate_group_key(row)
        if not key:
            grouped[id(row)] = {
                "chosen": dict(row),
                "hidden": [],
            }
            continue

        current = grouped.get(key)
        row = dict(row)

        if current is None:
            grouped[key] = {
                "chosen": row,
                "hidden": [],
            }
            continue

        chosen = current["chosen"]
        winner = choose_duplicate_display(chosen, row, settings)

        if winner is row:
            current["hidden"].append(chosen)
            current["chosen"] = row
        else:
            current["hidden"].append(row)

    output = []

    for group in grouped.values():
        chosen = dict(group["chosen"])
        hidden = group["hidden"]

        if hidden:
            chosen["hidden_duplicate_count"] = len(hidden)
            chosen["hidden_duplicate_titles"] = [x.get("title", "") for x in hidden]
            chosen["hidden_duplicate_sites"] = [
                site_label(x.get("site", "") or get_site_key_from_url(x.get("url", "")) or get_site_key_from_title(x.get("title", "")))
                for x in hidden
            ]
        else:
            chosen["hidden_duplicate_count"] = 0
            chosen["hidden_duplicate_titles"] = []
            chosen["hidden_duplicate_sites"] = []

        output.append(chosen)

    return output


def load_db():
    if not DB_JSON.exists():
        return default_db()

    try:
        with DB_JSON.open("r", encoding="utf-8") as f:
            db = json.load(f)

        if not isinstance(db, dict):
            return default_db()

        if "items" not in db or not isinstance(db["items"], dict):
            db["items"] = {}

        db = normalize_settings(db)
        return db

    except Exception as e:
        append_log(f"DB 읽기 실패. 새로 생성함: {e}")
        return default_db()


def save_db(db):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    db = normalize_settings(db)
    db = normalize_db_urls_to_latest(db)
    db["updated_at"] = now_text()

    tmp = DB_JSON.with_suffix(".json.tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    tmp.replace(DB_JSON)


def normalize_item(item):
    title = clean_title(item.get("title", ""))
    item["title"] = title
    item.setdefault("latest_episode", "")
    item.setdefault("last_seen", "")
    item.setdefault("url", "")
    item.setdefault("status", "active")
    item.setdefault("aliases", [])
    item.setdefault("manual", {})
    item.setdefault("episode_history", {})
    item.setdefault("locked_episode", "")
    item.setdefault("blocked_episodes", [])
    item.setdefault("created_at", now_text())
    item.setdefault("updated_at", now_text())

    if item["status"] not in ["active", "deleted", "purged"]:
        item["status"] = "active"

    aliases = []
    seen = set()

    for alias in item.get("aliases", []):
        alias = clean_title(alias)
        key = title_key(alias)

        if not alias or key == title_key(title) or key in seen:
            continue

        seen.add(key)
        aliases.append(alias)

    item["aliases"] = aliases
    return item


def find_item_key(db, title):
    key = title_key(title)

    if not key:
        return ""

    if key in db["items"]:
        return key

    for item_key, item in db["items"].items():
        for alias in item.get("aliases", []):
            if title_key(alias) == key:
                return item_key

    return ""


def add_episode_history(item, episode, url="", last_seen="", source=""):
    """
    작품별로 과거 화수/URL을 DB에 저장.
    나중에 '화수되돌리기'가 이 기록을 보고 이전 화수로 복구함.
    """
    item = normalize_item(item)
    ep = episode_key(episode)

    if not ep:
        return item

    history = item.setdefault("episode_history", {})
    old = history.get(ep, {})

    # 더 최근 기록이면 URL/시간 갱신
    if not old or str(last_seen or "") >= str(old.get("last_seen", "")):
        history[ep] = {
            "episode": ep,
            "url": str(url or old.get("url", "") or ""),
            "last_seen": str(last_seen or old.get("last_seen", "") or ""),
            "source": source or old.get("source", ""),
        }

    item["episode_history"] = history
    return item


def get_episode_record(item, episode):
    item = normalize_item(item)
    ep = episode_key(episode)

    if not ep:
        return None

    return (item.get("episode_history", {}) or {}).get(ep)


def get_episode_history_list(item):
    item = normalize_item(item)
    history = item.get("episode_history", {}) or {}
    records = []

    for ep, record in history.items():
        ep_key = episode_key(ep)
        if not ep_key:
            continue

        records.append({
            "episode": ep_key,
            "url": str(record.get("url", "") or ""),
            "last_seen": str(record.get("last_seen", "") or ""),
            "source": str(record.get("source", "") or ""),
        })

    records.sort(key=lambda r: episode_sort_value(r.get("episode", "")), reverse=True)
    return records


def apply_locked_episode(item):
    """
    사용자가 화수 목록에서 직접 고른 화수는 자동 백업이 덮어쓰지 않게 고정.
    대신 새로 본 화수들은 episode_history에 계속 저장됨.
    """
    item = normalize_item(item)
    locked = episode_key(item.get("locked_episode", ""))

    if not locked:
        return item

    record = get_episode_record(item, locked)

    if record:
        item["latest_episode"] = locked
        item["url"] = str(record.get("url", "") or item.get("url", "") or "")
        item["last_seen"] = str(record.get("last_seen", "") or item.get("last_seen", "") or "")
    else:
        item["latest_episode"] = locked

    return normalize_item(item)


def get_latest_episode_from_history(item):
    item = normalize_item(item)
    records = get_episode_history_list(item)

    if not records:
        return None

    return records[0]


def add_blocked_episode(item, episode):
    item = normalize_item(item)
    ep = episode_key(episode)

    if not ep:
        return item

    blocked = set(str(x) for x in item.get("blocked_episodes", []) if str(x).strip())
    blocked.add(ep)
    item["blocked_episodes"] = sorted(blocked, key=lambda x: episode_sort_value(x))
    return item


def is_blocked_episode(item, episode):
    ep = episode_key(episode)

    if not ep:
        return False

    blocked = set(str(x) for x in item.get("blocked_episodes", []))
    return ep in blocked


def can_accept_blocked_episode(item, episode):
    """
    차단된 화수라도 현재 화수의 바로 다음 화수면 정상 진행으로 보고 허용.
    예: 24화에서 실수로 90화 → 차단 유지
        나중에 89화까지 본 뒤 90화 → 차단 해제 후 허용
    """
    item = normalize_item(item)
    current_num = episode_sort_value(item.get("latest_episode", ""))
    episode_num = episode_sort_value(episode)

    if current_num <= 0 or episode_num <= 0:
        return False

    return episode_num <= current_num + 1


def remove_blocked_episode(item, episode):
    item = normalize_item(item)
    ep = episode_key(episode)

    if not ep:
        return item

    item["blocked_episodes"] = [
        str(x) for x in item.get("blocked_episodes", [])
        if episode_key(x) != ep
    ]

    return item


def get_previous_episode_from_history(item):
    """
    현재 화수보다 낮은 기록 중 가장 높은 화수를 선택.
    예: 현재 90화, 기록에 24화가 있으면 24화로 복구.
    """
    item = normalize_item(item)
    current_ep = episode_sort_value(item.get("latest_episode", ""))
    history = item.get("episode_history", {}) or {}

    candidates = []

    for ep, record in history.items():
        n = episode_sort_value(ep)

        if n <= 0:
            continue

        if current_ep > 0 and n >= current_ep:
            continue

        candidates.append((n, ep, record))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1], candidates[0][2]


def make_item_from_row(row, status="active"):
    item = normalize_item({
        "title": clean_title(row.get("title", "")),
        "latest_episode": str(row.get("latest_episode", "") or "").strip(),
        "last_seen": str(row.get("last_seen", "") or "").strip(),
        "url": str(row.get("url", "") or "").strip(),
        "status": status,
        "aliases": [],
        "manual": {},
        "episode_history": {},
        "locked_episode": "",
        "blocked_episodes": [],
        "created_at": now_text(),
        "updated_at": now_text(),
    })

    item = add_episode_history(
        item,
        item.get("latest_episode", ""),
        item.get("url", ""),
        item.get("last_seen", ""),
        "initial",
    )

    return normalize_item(item)


def update_item_from_row(item, row):
    item = normalize_item(item)

    row_title = clean_title(row.get("title", ""))
    row_ep = str(row.get("latest_episode", "") or "").strip()
    row_seen = str(row.get("last_seen", "") or "").strip()
    row_url = str(row.get("url", "") or "").strip()

    manual = item.get("manual", {})

    if row_title and not manual.get("title") and not item.get("title"):
        item["title"] = row_title

    if row_title and title_key(row_title) != title_key(item.get("title", "")):
        aliases = item.setdefault("aliases", [])
        if all(title_key(a) != title_key(row_title) for a in aliases):
            aliases.append(row_title)

    # 모든 방문 회차는 history에 계속 저장.
    item = add_episode_history(item, row_ep, row_url, row_seen, "csv/archive")

    # 사용자가 화수 목록에서 고른 상태면 자동 최신화로 덮어쓰지 않음.
    # 단, 같은 화수를 다시 봤다면 history의 URL/시간이 갱신되고 locked 값에도 반영됨.
    if episode_key(item.get("locked_episode", "")):
        item = apply_locked_episode(item)
        item["updated_at"] = now_text()
        return normalize_item(item)

    old_ep = episode_sort_value(item.get("latest_episode", ""))
    new_ep = episode_sort_value(row_ep)

    if row_ep and new_ep >= old_ep:
        item["latest_episode"] = row_ep
        if row_seen and row_seen >= str(item.get("last_seen", "")):
            item["last_seen"] = row_seen
        if row_url:
            item["url"] = row_url

    elif row_seen and row_seen >= str(item.get("last_seen", "")) and row_ep and new_ep == old_ep:
        item["last_seen"] = row_seen
        if row_url:
            item["url"] = row_url

    if row_url and not item.get("url"):
        item["url"] = row_url

    item["updated_at"] = now_text()
    return normalize_item(item)

def merge_items(target, source, keep_status="target"):
    target = normalize_item(target)
    source = normalize_item(source)

    better = choose_better(target, source)

    if better is source:
        target["latest_episode"] = source.get("latest_episode", target.get("latest_episode", ""))
        target["last_seen"] = source.get("last_seen", target.get("last_seen", ""))
        target["url"] = source.get("url", target.get("url", ""))

    aliases = target.setdefault("aliases", [])

    for alias in [source.get("title", "")] + source.get("aliases", []):
        alias = clean_title(alias)

        if not alias:
            continue

        if title_key(alias) == title_key(target.get("title", "")):
            continue

        if all(title_key(a) != title_key(alias) for a in aliases):
            aliases.append(alias)

    manual = target.setdefault("manual", {})
    for k, v in source.get("manual", {}).items():
        manual[k] = manual.get(k) or v

    if keep_status == "source":
        target["status"] = source.get("status", target.get("status", "active"))

    target["updated_at"] = now_text()
    return normalize_item(target)


def sync_txt_from_db(db):
    deleted_or_purged = []
    purged = []

    for item in db["items"].values():
        item = normalize_item(item)
        title = item.get("title", "")

        if not title:
            continue

        if item.get("status") in ["deleted", "purged"]:
            deleted_or_purged.append(title)

        if item.get("status") == "purged":
            purged.append(title)

    write_title_list_to_txt(IGNORE_TXT, deleted_or_purged)
    write_title_list_to_txt(PURGED_TXT, purged)


def sync_db_from_sources(db, import_legacy_txt=False):
    db.setdefault("items", {})

    for csv_path in get_existing_csv_paths():
        for row in read_csv_rows(csv_path):
            row_title = clean_title(row.get("title", ""))

            if not row_title:
                continue

            found_key = find_item_key(db, row_title)

            if found_key:
                item = update_item_from_row(db["items"][found_key], row)
                db["items"][found_key] = item
            else:
                item = make_item_from_row(row, status="active")
                key = title_key(item["title"])
                if key:
                    db["items"][key] = item

    if import_legacy_txt:
        ignored = load_title_list_from_txt("localreadlog_ignore.txt")
        purged = load_title_list_from_txt("localreadlog_purged.txt")

        for key, title in ignored.items():
            found_key = find_item_key(db, title)

            if found_key:
                db["items"][found_key]["status"] = "deleted"
                db["items"][found_key]["updated_at"] = now_text()
            else:
                db["items"][key] = make_item_from_row({"title": title}, status="deleted")

        for key, title in purged.items():
            found_key = find_item_key(db, title)

            if found_key:
                db["items"][found_key]["status"] = "purged"
                db["items"][found_key]["updated_at"] = now_text()
            else:
                db["items"][key] = make_item_from_row({"title": title}, status="purged")

    fixed_items = {}

    for key, item in list(db["items"].items()):
        item = normalize_item(item)
        real_key = title_key(item.get("title", "")) or key

        if real_key in fixed_items:
            fixed_items[real_key] = merge_items(fixed_items[real_key], item, keep_status="target")
        else:
            fixed_items[real_key] = item

    db["items"] = fixed_items
    return db


def ensure_db():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    first_create = not DB_JSON.exists()
    db = load_db()
    db = sync_db_from_sources(db, import_legacy_txt=first_create)
    save_db(db)
    sync_txt_from_db(db)
    return db


def item_to_row(item):
    item = normalize_item(item)
    return {
        "title": item.get("title", ""),
        "latest_episode": item.get("latest_episode", ""),
        "last_seen": item.get("last_seen", ""),
        "url": item.get("url", ""),
        "site": item_site_key(item),
        "site_label": site_label(item_site_key(item)),
        "__removed_link__": get___removed_link__(item.get("url", "")),
        "previous_episode": (get_previous_episode_from_history(item) or ["", {}])[0],
        "locked_episode": episode_key(item.get("locked_episode", "")),
        "episode_history": get_episode_history_list(item),
        "blocked_episodes": item.get("blocked_episodes", []),
        "status": item.get("status", "active"),
        "aliases": item.get("aliases", []),
        "updated_at": item.get("updated_at", ""),
    }


def get_rows_by_status(status):
    db = ensure_db()
    rows = []

    for item in db["items"].values():
        item = normalize_item(item)

        if item.get("status") == status:
            rows.append(item_to_row(item))

    if status == "active":
        rows = apply_site_duplicate_filter(rows, db)

    return rows


# =========================
# 상태 변경/수정/합치기/백업
# =========================

def get_settings_payload():
    db = ensure_db()
    settings = db.get("settings", {})
    return {
        "site_priority": settings.get("site_priority", DEFAULT_SITE_PRIORITY),
        "hide_site_duplicates": settings.get("hide_site_duplicates", True),
        "site_labels": {k: v["label"] for k, v in SITE_SPECS.items()},
        "browser_enabled": settings.get("browser_enabled", DEFAULT_BROWSER_ENABLED),
        "browser_labels": dict(BROWSER_LABELS),
        "backup_dir": str(BACKUP_DIR),
        "default_backup_dir": str(DEFAULT_BACKUP_DIR),
        "config_path": str(CONFIG_JSON),
        "custom_backup_dir": not is_same_path(BACKUP_DIR, DEFAULT_BACKUP_DIR),
    }


def copy_current_data_to_backup_dir(new_dir):
    new_dir = Path(new_dir)
    new_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    for name in [
        "localreadlog_db.json",
        "localreadlog_ignore.txt",
        "localreadlog_purged.txt",
        "localreadlog_latest.csv",
        "localreadlog_latest_mobile.html",
        "localreadlog_latest_pc.html",
    ]:
        src = BACKUP_DIR / name
        dst = new_dir / name
        if not src.exists() or dst.exists():
            continue
        try:
            import shutil
            shutil.copy2(src, dst)
            copied.append(name)
        except Exception as e:
            append_log(f"저장 위치 파일 복사 실패: {src} -> {dst} / {e}")

    return copied


def update_backup_dir_config(path_text):
    path = expand_config_path(path_text)
    if not path:
        return False, "저장 위치가 비어 있음"

    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return False, f"폴더를 만들 수 없음: {path} / {e}"

    if path.exists() and not path.is_dir():
        return False, f"폴더가 아니라 파일임: {path}"

    copied = copy_current_data_to_backup_dir(path)

    config = load_app_config()
    config["backup_dir"] = str(path)

    try:
        with CONFIG_JSON.open("w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return False, f"설정 파일 저장 실패: {CONFIG_JSON} / {e}"

    copied_text = f" / 복사: {', '.join(copied)}" if copied else ""
    append_log(f"저장 위치 변경 예약: {path}{copied_text}")
    return True, f"저장 위치를 변경함. 재시작 후 적용됨: {path}{copied_text}"


def update_site_priority(priority_text):
    db = ensure_db()
    priority = normalize_site_priority(priority_text)

    db.setdefault("settings", {})["site_priority"] = priority
    save_db(db)

    labels = " > ".join(site_label(x) for x in priority)
    append_log(f"사이트 우선순위 변경: {labels}")
    return True, f"사이트 우선순위: {labels}"


def toggle_site_duplicate_hiding():
    db = ensure_db()
    db = normalize_settings(db)
    settings = db.setdefault("settings", {})

    current = settings.get("hide_site_duplicates", True)
    if isinstance(current, str):
        current = current.strip().lower() not in ["0", "false", "off", "no", "아니오", "끔"]
    else:
        current = bool(current)

    settings["hide_site_duplicates"] = not current
    save_db(db)

    state = "ON" if settings["hide_site_duplicates"] else "OFF"
    append_log(f"사이트 중복 숨김: {state}")
    return True, f"사이트 중복 숨김: {state}", settings["hide_site_duplicates"]


def toggle_browser_sync(browser_key):
    browser_key = str(browser_key or "").strip().lower()

    if browser_key not in DEFAULT_BROWSER_ENABLED:
        return False, "알 수 없는 브라우저", None

    db = ensure_db()
    db = normalize_settings(db)
    settings = db.setdefault("settings", {})
    enabled = settings.setdefault("browser_enabled", dict(DEFAULT_BROWSER_ENABLED))

    current = bool(enabled.get(browser_key, True))
    enabled[browser_key] = not current
    save_db(db)

    label = BROWSER_LABELS.get(browser_key, browser_key)
    state = "ON" if enabled[browser_key] else "OFF"
    append_log(f"브라우저 연동 변경: {label} {state}")

    return True, f"{label} 연동 {state}", enabled[browser_key]


def set_status(title, status):
    db = ensure_db()
    found_key = find_item_key(db, title)

    if found_key:
        item = normalize_item(db["items"][found_key])
    else:
        item = make_item_from_row({"title": title}, status=status)
        found_key = title_key(item["title"])

    item["status"] = status
    item["updated_at"] = now_text()
    db["items"][found_key] = item

    save_db(db)
    sync_txt_from_db(db)
    append_log(f"상태 변경: {item['title']} → {status}")
    return item


def edit_item(old_title, new_title, latest_episode, url):
    db = ensure_db()
    old_key = find_item_key(db, old_title)

    if not old_key:
        return False, "수정할 작품을 못 찾음"

    item = normalize_item(db["items"][old_key])
    new_title = clean_title(new_title) or item.get("title", "")

    new_key = title_key(new_title)
    conflict_key = find_item_key(db, new_title)

    if conflict_key and conflict_key != old_key:
        return False, "같은 제목의 작품이 이미 있음. 합치기 기능을 써."

    old_display_title = item.get("title", "")

    if title_key(new_title) != title_key(old_display_title):
        aliases = item.setdefault("aliases", [])
        if old_display_title and all(title_key(a) != title_key(old_display_title) for a in aliases):
            aliases.append(old_display_title)

        item["title"] = new_title
        item.setdefault("manual", {})["title"] = True

    item["latest_episode"] = str(latest_episode or "").strip()
    item.setdefault("manual", {})["latest_episode"] = True

    item["url"] = str(url or "").strip()
    item.setdefault("manual", {})["url"] = True

    item["updated_at"] = now_text()

    if new_key != old_key:
        del db["items"][old_key]

    db["items"][new_key] = normalize_item(item)

    save_db(db)
    sync_txt_from_db(db)
    append_log(f"수정: {old_display_title} → {new_title}")
    return True, "수정 완료"


def edit_title_only(old_title, new_title):
    db = ensure_db()
    old_key = find_item_key(db, old_title)

    if not old_key:
        return False, "수정할 작품을 못 찾음"

    item = normalize_item(db["items"][old_key])
    new_title = clean_title(new_title)

    if not new_title:
        return False, "새 제목이 비어 있음"

    old_display_title = item.get("title", "")

    if title_key(new_title) == title_key(old_display_title):
        return True, "변경 없음"

    new_key = title_key(new_title)
    conflict_key = find_item_key(db, new_title)

    if conflict_key and conflict_key != old_key:
        return False, "같은 제목의 작품이 이미 있음"

    aliases = item.setdefault("aliases", [])
    if old_display_title and all(title_key(a) != title_key(old_display_title) for a in aliases):
        aliases.append(old_display_title)

    item["title"] = new_title
    item.setdefault("manual", {})["title"] = True
    item["updated_at"] = now_text()

    if new_key != old_key:
        del db["items"][old_key]

    db["items"][new_key] = normalize_item(item)

    save_db(db)
    sync_txt_from_db(db)
    append_log(f"제목 수정: {old_display_title} → {new_title}")
    return True, "제목 저장 완료"


def restore_original_title(title):
    """
    수동 수정으로 생긴 별칭 중 가장 오래된 별칭을 원본명으로 보고 제목을 되돌림.
    현재 제목은 다시 별칭으로 보존한다.
    """
    db = ensure_db()
    found_key = find_item_key(db, title)

    if not found_key:
        return False, "작품을 못 찾음"

    item = normalize_item(db["items"][found_key])
    aliases = [clean_title(x) for x in item.get("aliases", []) if clean_title(x)]

    if not aliases:
        return False, "되돌릴 원본 별칭이 없음"

    old_title = item.get("title", "")
    original_title = aliases[0]

    if title_key(original_title) == title_key(old_title):
        return False, "이미 원본 제목임"

    new_key = title_key(original_title)
    conflict_key = find_item_key(db, original_title)

    if conflict_key and conflict_key != found_key:
        return False, "원본 제목과 같은 작품이 이미 있음"

    new_aliases = []
    seen = set()

    # 현재 제목은 별칭으로 보존
    if old_title and title_key(old_title) != title_key(original_title):
        seen.add(title_key(old_title))
        new_aliases.append(old_title)

    # 복구한 원본명은 별칭 목록에서 제거, 나머지는 유지
    for alias in aliases:
        key = title_key(alias)

        if not key or key == title_key(original_title) or key in seen:
            continue

        seen.add(key)
        new_aliases.append(alias)

    item["title"] = original_title
    item["aliases"] = new_aliases
    item.setdefault("manual", {}).pop("title", None)
    item["updated_at"] = now_text()

    if new_key != found_key:
        del db["items"][found_key]

    db["items"][new_key] = normalize_item(item)

    save_db(db)
    sync_txt_from_db(db)
    append_log(f"제목 원본복구: {old_title} → {original_title}")
    return True, f"원본 제목으로 복구: {original_title}"


def select_episode_from_history(title, episode):
    db = ensure_db()
    found_key = find_item_key(db, title)

    if not found_key:
        return False, "작품을 못 찾음"

    item = normalize_item(db["items"][found_key])
    ep = episode_key(episode)

    if not ep:
        return False, "화수가 비어 있음"

    record = get_episode_record(item, ep)

    if not record:
        return False, f"{ep}화 기록이 없음"

    old_episode = item.get("latest_episode", "")
    item["locked_episode"] = ep
    item["latest_episode"] = ep
    item["url"] = str(record.get("url", "") or "")
    item["last_seen"] = str(record.get("last_seen", "") or item.get("last_seen", "") or "")
    item.setdefault("manual", {})["latest_episode"] = True
    item["updated_at"] = now_text()

    db["items"][found_key] = normalize_item(item)
    save_db(db)
    sync_txt_from_db(db)

    append_log(f"화수 선택 고정: {item.get('title', title)} {old_episode}화 → {ep}화")
    return True, f"{item.get('title', title)}: {ep}화로 선택 고정"


def unlock_episode(title):
    db = ensure_db()
    found_key = find_item_key(db, title)

    if not found_key:
        return False, "작품을 못 찾음"

    item = normalize_item(db["items"][found_key])
    old_locked = episode_key(item.get("locked_episode", ""))

    item["locked_episode"] = ""
    item.get("manual", {}).pop("latest_episode", None)

    latest = get_latest_episode_from_history(item)
    if latest:
        item["latest_episode"] = latest.get("episode", "")
        item["url"] = latest.get("url", "")
        item["last_seen"] = latest.get("last_seen", item.get("last_seen", ""))

    item["updated_at"] = now_text()
    db["items"][found_key] = normalize_item(item)
    save_db(db)
    sync_txt_from_db(db)

    append_log(f"화수 선택 고정 해제: {item.get('title', title)} {old_locked or '-'}화")
    return True, f"{item.get('title', title)}: 자동 최신화로 전환"


def rollback_episode(title):
    """
    바로 이전 화수로 빠르게 되돌리는 단축 기능.
    전체 목록에서 고르려면 화면의 '화수선택'을 사용.
    """
    db = ensure_db()
    found_key = find_item_key(db, title)

    if not found_key:
        return False, "작품을 못 찾음"

    item = normalize_item(db["items"][found_key])
    previous = get_previous_episode_from_history(item)

    if not previous:
        return False, "되돌릴 이전 화수 기록이 없음"

    previous_episode, _ = previous
    return select_episode_from_history(item.get("title", title), previous_episode)

def merge_titles(source_title, target_title):
    db = ensure_db()
    source_key = find_item_key(db, source_title)
    target_key = find_item_key(db, target_title)

    if not source_key:
        return False, "합칠 원본 작품을 못 찾음"

    source = normalize_item(db["items"][source_key])

    if not target_key:
        ok, msg = edit_item(source.get("title", ""), target_title, source.get("latest_episode", ""), source.get("url", ""))
        if ok:
            append_log(f"합치기 대상 없음 → 이름 변경 처리: {source_title} → {target_title}")
        return ok, msg

    if source_key == target_key:
        return False, "같은 작품끼리는 합칠 수 없음"

    target = normalize_item(db["items"][target_key])
    merged = merge_items(target, source, keep_status="target")
    db["items"][target_key] = merged
    del db["items"][source_key]

    save_db(db)
    sync_txt_from_db(db)
    append_log(f"합치기: {source.get('title', '')} → {target.get('title', '')}")
    return True, "합치기 완료"


def run_backup_script():
    if not BACKUP_SCRIPT.exists():
        return False, f"백업 스크립트를 못 찾음: {BACKUP_SCRIPT}"

    try:
        completed = subprocess.run(
            [sys.executable, str(BACKUP_SCRIPT)],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )

        output = (completed.stdout or "") + "\n" + (completed.stderr or "")

        if completed.returncode != 0:
            append_log(f"백업 재실행 실패: {output.strip()[:500]}")
            return False, output.strip()

        db = load_db()
        db = sync_db_from_sources(db, import_legacy_txt=False)
        save_db(db)
        sync_txt_from_db(db)

        append_log("백업 재실행 완료")
        return True, output.strip()

    except Exception as e:
        append_log(f"백업 재실행 예외: {e}")
        return False, str(e)


def restart_server_soon():
    """
    더 강한 재시작 방식.
    현재 프로세스가 자기 자신을 재실행하려고 하지 않고,
    별도 helper 프로세스가 현재 PID를 종료한 뒤 새 서버를 띄운다.
    """
    script_path = str(Path(__file__).resolve())
    python_exe = sys.executable
    work_dir = str(SCRIPT_DIR)
    target_port = int(globals().get("CURRENT_SERVER_PORT", PORT))
    parent_pid = os.getpid()
    restart_log = str(BACKUP_DIR / "localreadlog_manager_restart_log.txt")

    helper_code = (
        "import os, subprocess, sys, time, signal, datetime\\n"
        f"parent_pid = {parent_pid!r}\\n"
        f"python_exe = {python_exe!r}\\n"
        f"script_path = {script_path!r}\\n"
        f"work_dir = {work_dir!r}\\n"
        f"restart_log = {restart_log!r}\\n"
        f"target_port = {target_port!r}\\n"
        "def log(msg):\\n"
        "    try:\\n"
        "        with open(restart_log, 'a', encoding='utf-8', errors='replace') as f:\\n"
        "            f.write('[' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '] ' + msg + '\\\\n')\\n"
        "    except Exception:\\n"
        "        pass\\n"
        "log('restart helper started. parent=' + str(parent_pid) + ' port=' + str(target_port))\\n"
        "time.sleep(1.2)\\n"
        "try:\\n"
        "    os.kill(parent_pid, signal.SIGTERM)\\n"
        "    log('sent SIGTERM to parent')\\n"
        "except Exception as e:\\n"
        "    log('SIGTERM failed: ' + repr(e))\\n"
        "time.sleep(1.2)\\n"
        "try:\\n"
        "    os.kill(parent_pid, signal.SIGKILL)\\n"
        "    log('sent SIGKILL to parent')\\n"
        "except Exception as e:\\n"
        "    log('SIGKILL skipped/failed: ' + repr(e))\\n"
        "time.sleep(1.0)\\n"
        "env = os.environ.copy()\\n"
        "env['BLACKTOON_MANAGER_PORT'] = str(target_port)\\n"
        "kwargs = {'cwd': work_dir, 'env': env}\\n"
        "try:\\n"
        "    out = open(restart_log, 'a', encoding='utf-8', errors='replace')\\n"
        "    kwargs['stdout'] = out\\n"
        "    kwargs['stderr'] = out\\n"
        "except Exception:\\n"
        "    out = None\\n"
        "if os.name == 'nt':\\n"
        "    kwargs['creationflags'] = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)\\n"
        "    kwargs['close_fds'] = True\\n"
        "try:\\n"
        "    subprocess.Popen([python_exe, script_path], **kwargs)\\n"
        "    log('started new server: ' + script_path)\\n"
        "except Exception as e:\\n"
        "    log('failed to start new server: ' + repr(e))\\n"
    )

    try:
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
            kwargs["close_fds"] = True

        subprocess.Popen([python_exe, "-c", helper_code], **kwargs)
        append_log(f"관리 서버 재시작 helper 실행: pid {parent_pid}, port {target_port}")
        return True, "서버 재시작 중..."
    except Exception as e:
        append_log(f"관리 서버 재시작 helper 실행 실패: {e}")
        return False, f"재시작 helper 실행 실패: {e}"


# =========================
# 응답
# =========================

def json_response(handler, payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def text_response(handler, text, status=200, content_type="text/html; charset=utf-8"):
    data = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


# =========================
# HTML
# =========================

INDEX_HTML = r'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LocalReadLog</title>
<style>
body {
    margin: 0;
    padding: 14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", sans-serif;
    background: #f3f3f3;
    color: #111;
}
.top {
    position: sticky;
    top: 0;
    z-index: 20;
    background: #f3f3f3;
    padding-bottom: 10px;
}
h1 {
    font-size: 20px;
    margin: 4px 0 10px;
}
.tabs {
    display: flex;
    gap: 8px;
    margin-bottom: 10px;
}
.tabs button {
    flex: 1;
    border: 0;
    padding: 11px 8px;
    border-radius: 10px;
    background: #ddd;
    font-weight: 800;
    cursor: pointer;
}
.tabs button.active {
    background: #111;
    color: white;
}
.actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin-bottom: 10px;
}
.actions button,
.actions a {
    border: 0;
    padding: 10px;
    border-radius: 9px;
    background: #444;
    color: white;
    font-weight: 800;
    cursor: pointer;
    text-align: center;
    text-decoration: none;
    font-size: 14px;
}
.actions a.pc { background: #111; }
.actions a.mobile { background: #333; }
.prioritybar {
    display: grid;
    grid-template-columns: 1fr 86px 76px;
    gap: 8px;
    margin-bottom: 8px;
    align-items: center;
}
.prioritybar span {
    font-size: 12px;
    color: #444;
    font-weight: 800;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.prioritybar button {
    border: 0;
    padding: 9px 6px;
    border-radius: 9px;
    background: #222;
    color: white;
    font-weight: 800;
    font-size: 12px;
    cursor: pointer;
}
.browserbar {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
    margin-bottom: 8px;
}
.browserbar button {
    border: 0;
    padding: 9px 6px;
    border-radius: 9px;
    background: #1f4e79;
    color: white;
    font-weight: 800;
    font-size: 12px;
    cursor: pointer;
}
.browserbar button.off {
    background: #777;
    color: #eee;
}
.controls {
    display: grid;
    grid-template-columns: 1fr 145px;
    gap: 8px;
    margin-bottom: 8px;
}
#search,
#sort {
    box-sizing: border-box;
    padding: 12px;
    border: 1px solid #ccc;
    border-radius: 10px;
    font-size: 15px;
}
.count {
    margin: 8px 2px;
    font-size: 13px;
    color: #666;
}
.card {
    background: white;
    border-radius: 12px;
    padding: 14px;
    margin-bottom: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}
.title-line {
    margin-bottom: 8px;
}
.title-wrap {
    display: flex;
    align-items: center;
    gap: 7px;
    min-width: 0;
    flex-wrap: wrap;
}
.site-tag {
    flex: 0 0 auto;
    display: inline-block;
    padding: 4px 8px;
    border-radius: 999px;
    background: #111;
    color: white;
    font-size: 12px;
    font-weight: 900;
    line-height: 1.25;
}
.category-tag {
    flex: 0 0 auto;
    display: inline-block;
    padding: 4px 8px;
    border-radius: 999px;
    background: #333;
    color: white;
    font-size: 12px;
    font-weight: 900;
    line-height: 1.25;
}
.ep-tag {
    flex: 0 0 auto;
    display: inline-block;
    padding: 5px 10px;
    border-radius: 999px;
    background: #555;
    color: white;
    font-size: 14px;
    font-weight: 900;
    line-height: 1.25;
}
.title {
    font-size: 17px;
    font-weight: 800;
    word-break: keep-all;
    min-width: 0;
}
@media (max-width: 520px) {
    .site-tag,
    .category-tag {
        font-size: 12px;
        padding: 4px 8px;
    }
    .ep-tag {
        font-size: 17px;
        padding: 7px 13px;
    }
}
.title-edit,
.category-edit {
    border: 0;
    padding: 8px 6px;
    border-radius: 9px;
    background: #1f4e79;
    color: white;
    font-weight: 800;
    cursor: pointer;
    font-size: 13px;
}
.category-edit {
    background: #555;
}
.aliases {
    font-size: 12px;
    color: #888;
    margin-bottom: 8px;
    word-break: keep-all;
}
.meta {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    font-size: 13px;
    color: #666;
    margin-bottom: 12px;
}
.buttons {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(72px, 1fr));
    gap: 8px;
}
.buttons a,
.buttons button {
    text-align: center;
    padding: 10px 6px;
    border-radius: 9px;
    border: 0;
    background: #111;
    color: white;
    text-decoration: none;
    font-weight: 800;
    cursor: pointer;
    font-size: 14px;
}
button.danger { background: #b00020; }
button.restore { background: #006b2e; }
button.purge { background: #555; }
button.edit { background: #1f4e79; }
button.merge { background: #754c00; }
.empty {
    padding: 30px 10px;
    text-align: center;
    color: #777;
}
.settings-box {
    background: white;
    border-radius: 12px;
    padding: 14px;
    margin-bottom: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}
.settings-box h2 {
    font-size: 17px;
    margin: 0 0 10px;
}
.setting-row {
    display: grid;
    grid-template-columns: 1fr 82px 66px 66px;
    gap: 8px;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid #eee;
}
.setting-row:last-child { border-bottom: 0; }
.setting-row .small {
    font-size: 12px;
    color: #777;
    word-break: break-all;
}
.setting-row button,
.settings-box button {
    border: 0;
    border-radius: 8px;
    padding: 8px 7px;
    background: #1f4e79;
    color: white;
    font-weight: 800;
    cursor: pointer;
    font-size: 12px;
}
.setting-row button.danger,
.settings-box button.danger {
    background: #b00020;
}
.setting-row button.off {
    background: #777;
}
.priority-list {
    display: grid;
    gap: 8px;
    margin: 10px 0;
}
.priority-item {
    display: grid;
    grid-template-columns: 32px 1fr 70px;
    gap: 8px;
    align-items: center;
    padding: 9px 10px;
    border: 1px solid #ddd;
    border-radius: 10px;
    background: #fafafa;
    cursor: grab;
    user-select: none;
}
.priority-item.dragging {
    opacity: 0.45;
}
.priority-handle {
    font-size: 18px;
    color: #555;
    text-align: center;
}
.priority-rank {
    font-size: 12px;
    color: #777;
    text-align: right;
    font-weight: 800;
}
.priority-item .small {
    font-size: 12px;
    color: #777;
    word-break: break-all;
}
.toast {
    position: fixed;
    left: 14px;
    right: 14px;
    bottom: 14px;
    background: #111;
    color: white;
    padding: 13px;
    border-radius: 10px;
    font-size: 14px;
    z-index: 99;
    display: none;
    white-space: pre-wrap;
}
.modal-bg {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.55);
    z-index: 80;
    display: none;
    align-items: center;
    justify-content: center;
    padding: 12px;
}
.modal {
    width: min(780px, 100%);
    max-height: 86vh;
    overflow: auto;
    background: white;
    border-radius: 14px;
    padding: 14px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.22);
}
.modal-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
}
.modal-title {
    font-weight: 900;
    font-size: 17px;
}
.modal-close {
    border: 0;
    background: #111;
    color: white;
    border-radius: 8px;
    padding: 8px 10px;
    font-weight: 800;
    cursor: pointer;
}
.episode-row {
    display: grid;
    grid-template-columns: 70px 1fr 70px 70px;
    gap: 8px;
    align-items: center;
    border-top: 1px solid #eee;
    padding: 8px 0;
    font-size: 13px;
}
.episode-row .ep {
    font-weight: 900;
}
.episode-row .seen {
    color: #666;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.episode-row button,
.episode-row a {
    border: 0;
    border-radius: 8px;
    padding: 8px 6px;
    background: #111;
    color: white;
    text-align: center;
    text-decoration: none;
    font-weight: 800;
    cursor: pointer;
    font-size: 12px;
}
.episode-row button.pick { background: #006b2e; }
.locked-note {
    font-size: 12px;
    color: #b00020;
    font-weight: 800;
    margin-bottom: 8px;
}

.logbox {
    background: #111;
    color: #eee;
    border-radius: 10px;
    padding: 12px;
    font-family: Consolas, monospace;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-word;
    overflow-x: auto;
    line-height: 1.45;
}
@media (min-width: 900px) {
    body {
        max-width: 1100px;
        margin: 0 auto;
        padding: 20px;
    }
    .actions {
        grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    .buttons {
        grid-template-columns: repeat(auto-fit, minmax(86px, 1fr));
    }
}
</style>
</head>
<body>
<div class="top">
    <h1>LocalReadLog</h1>
    <div class="tabs">
        <button id="tab-current" class="active" onclick="setMode('current')">현재 목록</button>
        <button id="tab-deleted" onclick="setMode('deleted')">삭제 목록</button>
        <button id="tab-settings" onclick="setMode('settings')">설정</button>
        <button id="tab-log" onclick="setMode('log')">로그</button>
    </div>
    <div class="prioritybar" id="prioritybar">
        <span id="priorityText">사이트 우선순위 로딩중</span>
        <button onclick="toggleDuplicateHiding()">중복숨김</button>
        <button onclick="restartServer()">재시작</button>
    </div>
    <div class="controls" id="controls">
        <input id="search" placeholder="작품명 검색">
        <select id="sort">
            <option value="last_seen_desc">최근 본 순</option>
            <option value="title_asc">제목 순</option>
            <option value="episode_desc">화수 높은 순</option>
            <option value="updated_desc">수정일 순</option>
        </select>
    </div>
    <div class="count" id="count"></div>
</div>

<div id="list"></div>
<div class="toast" id="toast"></div>

<div class="modal-bg" id="episodeModalBg">
    <div class="modal">
        <div class="modal-head">
            <div class="modal-title" id="episodeModalTitle">화수 선택</div>
            <button class="modal-close" onclick="closeEpisodeModal()">닫기</button>
        </div>
        <div id="episodeModalBody"></div>
    </div>
</div>

<script>
let mode = "current";
let rows = [];
let settings = {
    site_priority: ["blacktoon", "wfwf", "tkor"],
    hide_site_duplicates: true,
    site_labels: {"blacktoon": "블랙툰", "wfwf": "늑대", "tkor": "툰코"},
    browser_enabled: {"whale": true, "edge": true, "chrome": true, "firefox": true},
    browser_labels: {"whale": "Whale", "edge": "Edge", "chrome": "Chrome", "firefox": "Firefox"},
    category_labels: {"webtoon": "웹툰", "comic": "만화", "manga": "망가", "novel": "소설", "anime": "애니", "other": "기타"}
};

const list = document.getElementById("list");
const count = document.getElementById("count");
const search = document.getElementById("search");
const sort = document.getElementById("sort");
const controls = document.getElementById("controls");
const prioritybar = document.getElementById("prioritybar");
const browserbar = document.getElementById("browserbar");
const priorityText = document.getElementById("priorityText");
const toast = document.getElementById("toast");
const episodeModalBg = document.getElementById("episodeModalBg");
const episodeModalTitle = document.getElementById("episodeModalTitle");
const episodeModalBody = document.getElementById("episodeModalBody");

function showToast(msg) {
    toast.textContent = msg;
    toast.style.display = "block";
    setTimeout(() => { toast.style.display = "none"; }, 4000);
}

function escapeHtml(s) {
    return String(s ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function epNum(v) {
    const n = parseFloat(String(v || "").trim());
    return Number.isFinite(n) ? n : 0;
}

function setMode(nextMode) {
    mode = nextMode;
    document.getElementById("tab-current").classList.toggle("active", mode === "current");
    document.getElementById("tab-deleted").classList.toggle("active", mode === "deleted");
    document.getElementById("tab-settings").classList.toggle("active", mode === "settings");
    document.getElementById("tab-log").classList.toggle("active", mode === "log");
    controls.style.display = (mode === "log" || mode === "settings") ? "none" : "grid";
    prioritybar.style.display = (mode === "log" || mode === "settings") ? "none" : "grid";
    if (browserbar) browserbar.style.display = "none";
    search.value = "";
    reloadList();
}

async function api(path, data=null) {
    const opt = data ? {
        method: "POST",
        headers: {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        body: new URLSearchParams(data)
    } : {};

    const res = await fetch(path, opt);
    return await res.json();
}

function renderSettings() {
    const labels = (settings.site_priority || []).map(k => settings.site_labels?.[k] || k);
    const hide = settings.hide_site_duplicates ? "ON" : "OFF";
    priorityText.textContent = `사이트 우선순위: ${labels.join(" > ")} · 중복숨김 ${hide}`;

    const browsers = ["whale", "edge", "chrome", "firefox"];
    browsers.forEach(key => {
        const btn = document.getElementById(`browser-${key}`);
        if (!btn) return;

        const enabled = !!settings.browser_enabled?.[key];
        const label = settings.browser_labels?.[key] || key;
        btn.textContent = `${label} ${enabled ? "ON" : "OFF"}`;
        btn.classList.toggle("off", !enabled);
    });
}

async function loadSettings() {
    const data = await api("/api/settings");
    settings = data || settings;
    renderSettings();
}

async function changeSitePriority() {
    const current = (settings.site_priority || []).map(k => settings.site_labels?.[k] || k).join(", ");
    const input = prompt(
        "사이트 우선순위를 쉼표로 입력\\n\\n가능값: 블랙툰, 늑대, 툰코\\n예: 툰코, 늑대, 블랙툰",
        current
    );

    if (input === null) return;

    const data = await api("/api/set_site_priority", {priority: input});
    showToast(data.message || "변경 완료");
    await loadSettings();
    await reloadList();
}

async function toggleDuplicateHiding() {
    const data = await api("/api/toggle_duplicate_hiding", {toggle: "1"});
    showToast(data.message || "변경 완료");

    if (typeof data.hide_site_duplicates === "boolean") {
        settings.hide_site_duplicates = data.hide_site_duplicates;
        renderSettings();
    }

    await loadSettings();
    await reloadList();
}

async function toggleBrowserSync(browserKey) {
    const label = settings.browser_labels?.[browserKey] || browserKey;
    const data = await api("/api/toggle_browser", {browser: browserKey});
    showToast(data.message || `${label} 변경 완료`);

    if (typeof data.enabled === "boolean") {
        settings.browser_enabled = settings.browser_enabled || {};
        settings.browser_enabled[browserKey] = data.enabled;
        renderSettings();
    }

    await loadSettings();
    await reloadList();
}

async function restartServer() {
    if (!confirm("관리 서버를 재시작할까?\n\n8초 정도 접속이 끊겼다가 다시 켜짐.")) {
        return;
    }

    try {
        const data = await api("/api/restart_server", {restart: "1"});
        showToast(data.message || "서버 재시작 중...");
    } catch (e) {
        showToast("서버 재시작 요청됨. 잠시 뒤 새로고침함.");
    }

    setTimeout(() => {
        location.href = location.origin + "/?restarted=" + Date.now();
    }, 8000);
}


async function toggleAccessPassword() {
    const enabled = !!settings.password_enabled;

    if (enabled) {
        if (!confirm("접속 비밀번호를 끌까?\n\n끄면 같은 네트워크에서 비밀번호 없이 접속할 수 있음.")) return;
        const data = await api("/api/set_password_settings", {enabled: "0"});
        showToast(data.message || "비밀번호 보호 OFF");
        await loadSettings();
        renderSettingsPage();
        return;
    }

    const pw = prompt("새 접속 비밀번호 입력\n\nPC/모바일에서 처음 한 번만 입력하면 브라우저에 저장됨.");
    if (pw === null) return;
    if (!pw.trim()) {
        showToast("비밀번호가 비어 있음");
        return;
    }

    const data = await api("/api/set_password_settings", {enabled: "1", password: pw});
    showToast(data.message || "비밀번호 보호 ON");
    await loadSettings();
    renderSettingsPage();
}

async function changeAccessPassword() {
    const pw = prompt("새 접속 비밀번호 입력");
    if (pw === null) return;
    if (!pw.trim()) {
        showToast("비밀번호가 비어 있음");
        return;
    }

    const data = await api("/api/set_password_settings", {enabled: "1", password: pw});
    showToast(data.message || "비밀번호 변경 완료");
    await loadSettings();
    renderSettingsPage();
}


function getOrderedSiteKeys() {
    const sites = settings.sites || {};
    const priority = Array.isArray(settings.site_priority) ? settings.site_priority : [];
    const result = [];
    const seen = new Set();

    priority.forEach(key => {
        if (sites[key] && !seen.has(key)) {
            result.push(key);
            seen.add(key);
        }
    });

    Object.keys(sites).forEach(key => {
        if (!seen.has(key)) {
            result.push(key);
            seen.add(key);
        }
    });

    return result;
}

function renderPriorityRows() {
    const sites = settings.sites || {};
    const keys = getOrderedSiteKeys();

    if (!keys.length) {
        return '<div class="empty">등록된 사이트 없음</div>';
    }

    return keys.map((key, idx) => {
        const site = sites[key] || {};
        const enabled = site.enabled !== false;
        const label = site.label || key;
        const host = site.host_re || site.prefix || key;

        return `
            <div class="priority-item" draggable="true" data-site-key="${escapeHtml(key)}"
                 ondragstart="priorityDragStart(event)"
                 ondragover="priorityDragOver(event)"
                 ondrop="priorityDrop(event)"
                 ondragend="priorityDragEnd(event)">
                <div class="priority-handle">↕</div>
                <div>
                    <b>${escapeHtml(label)}${enabled ? "" : " OFF"}</b>
                    <div class="small">${escapeHtml(host)}</div>
                </div>
                <div class="priority-rank">${idx + 1}순위</div>
            </div>
        `;
    }).join("");
}

function priorityDragStart(event) {
    const item = event.currentTarget;
    item.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", item.dataset.siteKey || "");
}

function priorityDragEnd(event) {
    event.currentTarget.classList.remove("dragging");
}

function priorityDragOver(event) {
    event.preventDefault();

    const list = document.getElementById("priorityList");
    const dragging = list?.querySelector(".priority-item.dragging");
    const target = event.target.closest(".priority-item");

    if (!list || !dragging || !target || target === dragging) {
        return;
    }

    const rect = target.getBoundingClientRect();
    const after = event.clientY > rect.top + rect.height / 2;

    if (after) {
        target.after(dragging);
    } else {
        target.before(dragging);
    }

    updatePriorityRanks();
}

function priorityDrop(event) {
    event.preventDefault();
    updatePriorityRanks();
}

function updatePriorityRanks() {
    document.querySelectorAll("#priorityList .priority-item").forEach((item, idx) => {
        const rank = item.querySelector(".priority-rank");
        if (rank) {
            rank.textContent = `${idx + 1}순위`;
        }
    });
}

async function saveDraggedSitePriority() {
    const keys = [...document.querySelectorAll("#priorityList .priority-item")]
        .map(el => el.dataset.siteKey)
        .filter(Boolean);

    if (!keys.length) {
        showToast("저장할 사이트가 없음");
        return;
    }

    const data = await api("/api/set_site_priority", {priority: keys.join(",")});
    showToast(data.message || "우선순위 저장 완료");
    await loadSettings();
    renderSettingsPage();
}

function renderSettingsPage() {
    renderSettings();
    controls.style.display = "none";
    prioritybar.style.display = "none";
    if (browserbar) browserbar.style.display = "none";

    const siteEntries = Object.entries(settings.sites || {});
    const priorityLabels = (settings.site_priority || []).map(k => settings.sites?.[k]?.label || settings.site_labels?.[k] || k);

    const siteRows = siteEntries.map(([key, site]) => {
        const enabled = site.enabled !== false;
        const host = site.host_re || site.prefix || key;
        const removable = key !== "blacktoon";
        const catLabel = settings.category_labels?.[site.category || "other"] || site.category || "기타";
        return `
            <div class="setting-row">
                <div>
                    <b>${escapeHtml(site.label || key)}</b>
                    <div class="small">${escapeHtml(key)} · ${escapeHtml(host)} · 기본분류 ${escapeHtml(catLabel)}</div>
                </div>
                <button class="${enabled ? "" : "off"}" onclick="toggleSiteEnabled('${encodeURIComponent(key)}')">${enabled ? "ON" : "OFF"}</button>
                ${removable ? `<button class="danger" onclick="removeSite('${encodeURIComponent(key)}')">삭제</button>` : `<button onclick="setSiteCategory('${encodeURIComponent(key)}')">분류</button>`}
                ${removable ? `<button onclick="setSiteCategory('${encodeURIComponent(key)}')">분류</button>` : ""}
            </div>
        `;
    }).join("");

    const browserRows = Object.entries(settings.browser_labels || {}).map(([key, label]) => {
        const enabled = !!settings.browser_enabled?.[key];
        return `
            <div class="setting-row">
                <div><b>${escapeHtml(label)}</b></div>
                <button class="${enabled ? "" : "off"}" onclick="toggleBrowserSync('${key}')">${enabled ? "ON" : "OFF"}</button>
                <span></span>
            </div>
        `;
    }).join("");

    count.textContent = "설정";
    list.innerHTML = `
        <div class="settings-box">
            <h2>사이트</h2>
            <div class="small">주소를 입력해서 추적 사이트를 추가함. 예: https://wfwf464.com/</div>
            <div style="height:8px"></div>
            <button onclick="addSite()">사이트 추가</button>
            <div style="height:10px"></div>
            ${siteRows || '<div class="empty">등록된 사이트 없음</div>'}
        </div>

        <div class="settings-box">
            <h2>사이트 우선순위</h2>
            <div class="small">위아래로 드래그해서 순서를 바꾼 뒤 저장. 현재: ${escapeHtml(priorityLabels.join(" > "))}</div>
            <div id="priorityList" class="priority-list">
                ${renderPriorityRows()}
            </div>
            <button onclick="saveDraggedSitePriority()">우선순위 저장</button>
            <button onclick="toggleDuplicateHiding()">중복숨김 ${settings.hide_site_duplicates ? "ON" : "OFF"}</button>
        </div>

        <div class="settings-box">
            <h2>저장 위치</h2>
            <div class="small">DB/CSV/HTML/로그는 프로그램 폴더 안의 data 폴더에 저장됨.</div>
            <div style="word-break:break-all"><b>${escapeHtml(settings.backup_dir || "")}</b></div>
        </div>

        <div class="settings-box">
            <h2>접속 비밀번호</h2>
            <div class="small">모바일에서 접속할 때도 같은 비밀번호를 사용함. 한 번 입력하면 브라우저에 저장됨.</div>
            <div class="setting-row">
                <div>
                    <b>비밀번호 보호</b>
                    <div class="small">현재 상태: ${settings.password_enabled ? "ON" : "OFF"}</div>
                </div>
                <button class="${settings.password_enabled ? "" : "off"}" onclick="toggleAccessPassword()">${settings.password_enabled ? "ON" : "OFF"}</button>
                <button onclick="changeAccessPassword()">비밀번호 변경</button>
            </div>
        </div>

        <div class="settings-box">
            <h2>브라우저 연동</h2>
            ${browserRows}
        </div>
    `;
}

function categoryPrompt(currentValue) {
    const labels = settings.category_labels || {};
    const entries = Object.entries(labels);
    const currentLabel = labels[currentValue] || currentValue || "기타";
    const possible = entries.map(([k, v]) => v).join(", ");

    const input = prompt(
        `분류 입력\n\n가능값: ${possible}\n단행본은 만화로 분류됨.`,
        currentLabel
    );

    if (input === null) return null;
    return input.trim();
}

async function editCategory(encodedTitle) {
    const title = decodeURIComponent(encodedTitle);
    const row = findRow(title) || {};
    const input = categoryPrompt(row.category || "other");

    if (input === null || !input) return;

    const data = await api("/api/set_category", {
        title: title,
        category: input
    });

    showToast(data.message || "분류 변경 완료");
    await reloadList();
}

async function setSiteCategory(encodedKey) {
    const key = decodeURIComponent(encodedKey);
    const site = settings.sites?.[key] || {};
    const input = categoryPrompt(site.category || "other");

    if (input === null || !input) return;

    const data = await api("/api/set_site_category", {
        site: key,
        category: input
    });

    showToast(data.message || "사이트 기본분류 변경 완료");
    await loadSettings();
    renderSettingsPage();
}


async function addSite() {
    const url = prompt("추가할 사이트 주소 입력\\n예: https://wfwf464.com/", "");
    if (url === null || !url.trim()) return;

    const label = prompt("표시 이름 입력\\n예: 늑대, 툰코", "") || "";

    const data = await api("/api/add_site", {url, label});
    showToast(data.message || "사이트 추가 완료");
    await loadSettings();
    renderSettingsPage();
}

async function removeSite(encodedKey) {
    const key = decodeURIComponent(encodedKey);
    const site = settings.sites?.[key] || {};
    const label = site.label || key;

    if (!confirm(`사이트 추적에서 삭제할까?\\n\\n${label}\\n\\n기존 저장 작품은 지워지지 않고, 앞으로 방문기록만 안 읽음.`)) {
        return;
    }

    const data = await api("/api/remove_site", {site: key});
    showToast(data.message || "사이트 삭제 완료");
    await loadSettings();
    renderSettingsPage();
}

async function toggleSiteEnabled(encodedKey) {
    const key = decodeURIComponent(encodedKey);
    const data = await api("/api/toggle_site", {site: key});
    showToast(data.message || "사이트 변경 완료");
    await loadSettings();
    renderSettingsPage();
}


async function reloadList() {
    if (mode !== "log") {
        await loadSettings();
    }

    if (mode === "settings") {
        await loadSettings();
        rows = [];
        renderSettingsPage();
        return;
    }

    if (mode === "log") {
        const data = await api("/api/logs");
        rows = data.lines || [];
        renderLog();
        return;
    }

    const data = await api(mode === "current" ? "/api/list" : "/api/deleted");
    rows = data.rows || [];
    render();
}

function sortedRows(input) {
    const s = sort.value;
    const copy = [...input];

    if (s === "title_asc") {
        copy.sort((a, b) => String(a.title || "").localeCompare(String(b.title || ""), "ko"));
    } else if (s === "episode_desc") {
        copy.sort((a, b) => epNum(b.latest_episode) - epNum(a.latest_episode));
    } else if (s === "updated_desc") {
        copy.sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
    } else {
        copy.sort((a, b) => String(b.last_seen || "").localeCompare(String(a.last_seen || "")));
    }

    return copy;
}

function renderLog() {
    count.textContent = `${rows.length}줄`;
    list.innerHTML = `<div class="logbox">${escapeHtml(rows.join("\n"))}</div>`;
}

function stripSitePrefixFromTitle(title) {
    let t = String(title || "").trim();

    const labels = new Set();
    Object.values(settings.site_labels || {}).forEach(v => labels.add(String(v || "").trim()));
    Object.values(settings.sites || {}).forEach(site => labels.add(String(site?.label || "").trim()));
    ["블랙툰", "늑대", "툰코"].forEach(v => labels.add(v));

    labels.forEach(label => {
        if (!label) return;
        const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        t = t.replace(new RegExp(`^\\[${escaped}\\]\\s*`, "i"), "");
    });

    return t.trim();
}

function render() {
    const q = search.value.trim().toLowerCase();
    let filtered = rows.filter(r => {
        const text = `${r.title || ""} ${(r.aliases || []).join(" ")} ${r.latest_episode || ""} ${r.last_seen || ""} ${r.category_label || ""}`.toLowerCase();
        return !q || text.includes(q);
    });

    filtered = sortedRows(filtered);

    count.textContent = `${filtered.length}개 표시 / 전체 ${rows.length}개`;

    if (!filtered.length) {
        list.innerHTML = '<div class="empty">표시할 항목 없음</div>';
        return;
    }

    list.innerHTML = bulkToolbar() + filtered.map((r, idx) => {
        const displayTitle = stripSitePrefixFromTitle(r.title || "");
        const title = escapeHtml(displayTitle || r.title || "");
        const siteTag = escapeHtml(r.site_label || r.site || "사이트");
        const categoryTag = escapeHtml(r.category_label || r.category || "기타");
        const encodedTitle = encodeURIComponent(r.title || "");
        const ep = escapeHtml(r.latest_episode || "");
        const epTag = ep ? `<span class="ep-tag">${ep}화</span>` : "";
        const lastSeen = escapeHtml(r.last_seen || "");
        const url = escapeHtml(r.url || "");
        const histCount = (r.episode_history || []).length;
        const lockText = r.locked_episode ? `<div class="locked-note">선택 고정: ${escapeHtml(r.locked_episode)}화 · 저장된 화수 ${histCount}개</div>` : `<div class="aliases">저장된 화수: ${histCount}개</div>`;
        const duplicateText = r.hidden_duplicate_count
            ? `<div class="aliases">사이트 중복 ${escapeHtml(r.hidden_duplicate_count)}개 숨김: ${escapeHtml((r.hidden_duplicate_sites || []).join(", "))}</div>`
            : "";
        let openButton = "";
        if (r.url) {
            openButton = `<a href="${url}" target="_blank">열기</a>`;
        }
        let actionButtons = "";
        if (mode === "current") {
            actionButtons = `
                <button class="edit" onclick="openEpisodePicker('${encodedTitle}')">화수선택</button>
                <button class="danger" onclick="deleteTitle('${encodedTitle}')">삭제</button>
            `;
        } else {
            actionButtons = `
                <button class="edit" onclick="openEpisodePicker('${encodedTitle}')">화수선택</button>
                <button class="restore" onclick="restoreTitle('${encodedTitle}')">복구</button>
                <button class="purge" onclick="purgeTitle('${encodedTitle}')">완전삭제</button>
            `;
        }

        return `
        <div class="card">
            <div class="title-line">
                <div class="title-wrap">
                    <span class="site-tag">${siteTag}</span>
                    <span class="category-tag">${categoryTag}</span>
                    <div class="title">${title}</div>
                    ${epTag}
                </div>
            </div>
            ${lockText}
            ${duplicateText}
            <div class="meta">
                <span>최근: ${lastSeen || "-"}</span>
            </div>
            <div class="buttons">
                ${openButton}
                ${actionButtons}
            </div>
        </div>
        `;
    }).join("");
}

function findRow(title) {
    return rows.find(r => String(r.title || "") === String(title || ""));
}

async function deleteTitle(encodedTitle) {
    const title = decodeURIComponent(encodedTitle);
    if (!confirm(`삭제 목록에 추가할까?\n${title}`)) return;

    const data = await api("/api/delete", {title});
    showToast(data.message || "삭제 처리 완료");
    await reloadList();
}

async function restoreTitle(encodedTitle) {
    const title = decodeURIComponent(encodedTitle);
    if (!confirm(`삭제 목록에서 빼고 복구할까?\n${title}`)) return;

    const data = await api("/api/restore", {title});
    showToast(data.message || "복구 처리 완료");
    await reloadList();
}

async function purgeTitle(encodedTitle) {
    const title = decodeURIComponent(encodedTitle);
    if (!confirm(`삭제 목록에서도 숨길까?\n\n${title}\n\n현재 목록에도 안 나오고 삭제 목록에도 안 보이게 함.`)) return;

    const data = await api("/api/purge", {title});
    showToast(data.message || "완전삭제 처리 완료");
    await reloadList();
}

async function editTitleOnly(encodedTitle) {
    const oldTitle = decodeURIComponent(encodedTitle);
    const row = findRow(oldTitle) || {};

    const newTitle = prompt("제목 수정", row.title || oldTitle);
    if (newTitle === null) return;

    const trimmed = newTitle.trim();

    if (!trimmed) {
        showToast("작품명이 비어 있음");
        return;
    }

    if (trimmed === oldTitle) {
        showToast("변경 없음");
        return;
    }

    const data = await api("/api/edit_title", {
        old_title: oldTitle,
        new_title: trimmed
    });

    showToast(data.message || "제목 저장 완료");
    await reloadList();
}


async function editTitle(encodedTitle) {
    const oldTitle = decodeURIComponent(encodedTitle);
    const row = findRow(oldTitle) || {};

    const newTitle = prompt("작품명 수정", row.title || oldTitle);
    if (newTitle === null) return;

    const latestEpisode = prompt("최신 화수 수정", row.latest_episode || "");
    if (latestEpisode === null) return;

    const url = prompt("URL 수정", row.url || "");
    if (url === null) return;

    const data = await api("/api/edit", {
        old_title: oldTitle,
        new_title: newTitle,
        latest_episode: latestEpisode,
        url: url
    });

    showToast(data.message || "수정 완료");
    await reloadList();
}

async function restoreOriginalTitle(encodedTitle) {
    const title = decodeURIComponent(encodedTitle);
    const row = findRow(title) || {};
    const aliases = row.aliases || [];

    if (!aliases.length) {
        showToast("되돌릴 원본 별칭이 없음");
        return;
    }

    const original = aliases[0];

    if (!confirm(`제목을 원본명으로 되돌릴까?\n\n현재: ${title}\n원본: ${original}`)) {
        return;
    }

    const data = await api("/api/restore_title", {title});
    showToast(data.message || "원본 제목으로 복구 완료");
    await reloadList();
}


function closeEpisodeModal() {
    episodeModalBg.style.display = "none";
    episodeModalTitle.textContent = "화수 선택";
    episodeModalBody.innerHTML = "";
}

function openEpisodePicker(encodedTitle) {
    const title = decodeURIComponent(encodedTitle);
    const row = findRow(title) || {};
    const episodes = Array.isArray(row.episode_history) ? row.episode_history : [];

    episodeModalTitle.textContent = `${title} · 화수 선택`;

    if (!episodes.length) {
        episodeModalBody.innerHTML = `<p>저장된 화수 기록이 없음.</p>`;
        episodeModalBg.style.display = "flex";
        return;
    }

    const locked = row.locked_episode || "";
    const unlockButton = locked
        ? `<button class="modal-close" onclick="unlockEpisode('${encodeURIComponent(title)}')">자동최신으로 전환</button>`
        : "";

    episodeModalBody.innerHTML = `
        ${locked ? `<div class="locked-note">현재 선택 고정: ${escapeHtml(locked)}화</div>` : ""}
        ${unlockButton}
        <div style="height:8px"></div>
        ${episodes.map(e => {
            const ep = escapeHtml(e.episode || "");
            const seen = escapeHtml(e.last_seen || "-");
            const url = e.url || "";
            const open = url ? `<a href="${escapeHtml(url)}" target="_blank">열기</a>` : `<span></span>`;
            const selected = String(e.episode || "") === String(row.latest_episode || "") ? "현재" : "선택";

            return `
                <div class="episode-row">
                    <div class="ep">${ep}화</div>
                    <div class="seen">${seen}</div>
                    <button class="pick" onclick="selectEpisode('${encodeURIComponent(title)}', '${encodeURIComponent(e.episode || "")}')">${selected}</button>
                    ${open}
                </div>
            `;
        }).join("")}
    `;

    episodeModalBg.style.display = "flex";
}

async function selectEpisode(encodedTitle, encodedEpisode) {
    const title = decodeURIComponent(encodedTitle);
    const episode = decodeURIComponent(encodedEpisode);

    const data = await api("/api/select_episode", {
        title: title,
        episode: episode
    });

    showToast(data.message || "화수 선택 완료");
    closeEpisodeModal();
    await reloadList();
}

async function unlockEpisode(encodedTitle) {
    const title = decodeURIComponent(encodedTitle);

    const data = await api("/api/unlock_episode", {
        title: title
    });

    showToast(data.message || "자동최신 전환 완료");
    closeEpisodeModal();
    await reloadList();
}



async function mergeTitle(encodedTitle) {
    const sourceTitle = decodeURIComponent(encodedTitle);
    const targetTitle = prompt(`어느 작품으로 합칠까?\n\n원본: ${sourceTitle}\n\n대상 작품명을 정확히 입력`, "");

    if (targetTitle === null || !targetTitle.trim()) return;

    if (!confirm(`합치기 실행?\n\n${sourceTitle}\n→ ${targetTitle}`)) return;

    const data = await api("/api/merge", {
        source_title: sourceTitle,
        target_title: targetTitle
    });

    showToast(data.message || "합치기 완료");
    await reloadList();
}

async function runBackup() {
    showToast("백업 재실행 중...");
    const data = await api("/api/run_backup", {});
    showToast(data.message || "완료");
    await reloadList();
}

search.addEventListener("input", render);
sort.addEventListener("change", render);
reloadList();
</script>
</body>
</html>'''


def render_index():
    return INDEX_HTML


def render_live_view(kind):
    rows = sorted(
        get_rows_by_status("active"),
        key=lambda x: x.get("last_seen", ""),
        reverse=True,
    )

    if kind == "pc":
        table_rows = []

        for row in rows:
            title = html.escape(row.get("title", ""))
            ep = html.escape(row.get("latest_episode", ""))
            last_seen = html.escape(row.get("last_seen", ""))
            url = html.escape(row.get("url", ""), quote=True)
            open_link = f'<a class="open" href="{url}" target="_blank">열기</a>' if row.get("url") else ""
            table_rows.append(f"""
            <tr data-search="{title} {ep} {last_seen}">
                <td class="title">{title}</td>
                <td>{ep}화</td>
                <td>{last_seen}</td>
                <td>{open_link}</td>
            </tr>
            """)

        return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>LocalReadLog PC 화면</title>
<style>
body {{
    margin: 0;
    font-family: "Segoe UI", "Malgun Gothic", sans-serif;
    background: #f5f5f5;
    color: #111;
}}
.wrap {{ padding: 20px; }}
.top {{
    position: sticky;
    top: 0;
    z-index: 20;
    background: #f5f5f5;
    padding: 14px 0;
    border-bottom: 1px solid #ddd;
}}
h1 {{ margin: 0 0 14px; font-size: 24px; }}
#search {{
    width: 420px;
    max-width: 100%;
    padding: 10px 12px;
    font-size: 15px;
    border: 1px solid #bbb;
    border-radius: 8px;
}}
.count {{
    display: inline-block;
    margin-left: 12px;
    color: #666;
    font-size: 14px;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    background: white;
    margin-top: 16px;
    box-shadow: 0 1px 5px rgba(0,0,0,0.08);
}}
th {{
    position: sticky;
    top: 74px;
    background: #222;
    color: white;
    z-index: 10;
    padding: 10px;
    font-size: 14px;
    text-align: left;
}}
td {{
    border-bottom: 1px solid #eee;
    padding: 9px 10px;
    font-size: 14px;
}}
tr:hover {{ background: #f0f6ff; }}
.title {{ font-weight: 700; }}
.open {{
    display: inline-block;
    padding: 6px 12px;
    border-radius: 6px;
    background: #111;
    color: white;
    text-decoration: none;
    font-weight: 700;
}}
.hidden {{ display: none; }}
</style>
</head>
<body>
<div class="wrap">
    <div class="top">
        <h1>LocalReadLog PC 화면</h1>
        <input id="search" placeholder="작품명 / 화수 검색">
        <span class="count" id="count"></span>
    </div>
    <table>
        <thead>
            <tr>
                <th>작품명</th>
                <th>최신 화수</th>
                <th>최근 확인</th>
                <th>열기</th>
            </tr>
        </thead>
        <tbody>
            {''.join(table_rows)}
        </tbody>
    </table>
</div>
<script>
const search = document.getElementById("search");
const rows = [...document.querySelectorAll("tbody tr")];
const count = document.getElementById("count");
function update() {{
    const q = search.value.trim().toLowerCase();
    let visible = 0;
    rows.forEach(row => {{
        const text = row.dataset.search.toLowerCase();
        const show = !q || text.includes(q);
        row.classList.toggle("hidden", !show);
        if (show) visible++;
    }});
    count.textContent = visible + "개 표시 / 전체 " + rows.length + "개";
}}
search.addEventListener("input", update);
update();
</script>
</body>
</html>"""

    cards = []

    for row in rows:
        title = html.escape(row.get("title", ""))
        ep = html.escape(row.get("latest_episode", ""))
        last_seen = html.escape(row.get("last_seen", ""))
        url = html.escape(row.get("url", ""), quote=True)
        open_link = f'<a class="open" href="{url}" target="_blank">열기</a>' if row.get("url") else ""
        cards.append(f"""
        <div class="card" data-search="{title} {ep} {last_seen}">
            <div class="title">{title}</div>
            <div class="meta">
                <span>{ep}화</span>
                <span>{last_seen}</span>
            </div>
            <div class="quick-buttons">
                {open_link}
            </div>
        </div>
        """)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LocalReadLog 모바일 화면</title>
<style>
body {{
    margin: 0;
    padding: 14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f3f3f3;
    color: #111;
}}
.top {{
    position: sticky;
    top: 0;
    background: #f3f3f3;
    padding-bottom: 10px;
    z-index: 10;
}}
h1 {{ font-size: 20px; margin: 4px 0 12px; }}
#search {{
    width: 100%;
    box-sizing: border-box;
    padding: 12px;
    border: 1px solid #ccc;
    border-radius: 10px;
    font-size: 16px;
}}
.count {{ margin: 8px 2px; font-size: 13px; color: #666; }}
.card {{
    background: white;
    border-radius: 12px;
    padding: 14px;
    margin-bottom: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}}
.title {{
    font-size: 17px;
    font-weight: 700;
    margin-bottom: 8px;
    word-break: keep-all;
}}
.meta {{
    display: flex;
    justify-content: space-between;
    gap: 8px;
    font-size: 13px;
    color: #666;
    margin-bottom: 12px;
}}
.quick-buttons {{
    display: flex;
    gap: 8px;
}}
.open {{
    display: block;
    flex: 1;
    text-align: center;
    padding: 11px;
    border-radius: 10px;
    background: #111;
    color: white;
    text-decoration: none;
    font-weight: 700;
}}
.hidden {{ display: none; }}
</style>
</head>
<body>
<div class="top">
    <h1>LocalReadLog 모바일 화면</h1>
    <input id="search" placeholder="작품명 검색">
    <div class="count" id="count"></div>
</div>
<div id="list">
    {''.join(cards)}
</div>
<script>
const search = document.getElementById("search");
const cards = [...document.querySelectorAll(".card")];
const count = document.getElementById("count");
function update() {{
    const q = search.value.trim().toLowerCase();
    let visible = 0;
    cards.forEach(card => {{
        const text = card.dataset.search.toLowerCase();
        const show = !q || text.includes(q);
        card.classList.toggle("hidden", !show);
        if (show) visible++;
    }});
    count.textContent = visible + "개 표시 / 전체 " + cards.length + "개";
}}
search.addEventListener("input", update);
update();
</script>
</body>
</html>"""


# =========================
# 서버
# =========================

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (now_text(), fmt % args))

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            text_response(self, render_index())
            return

        if path == "/view/mobile":
            text_response(self, render_live_view("mobile"))
            return

        if path == "/view/pc":
            text_response(self, render_live_view("pc"))
            return

        if path == "/api/list":
            json_response(self, {"rows": get_rows_by_status("active")})
            return

        if path == "/api/deleted":
            json_response(self, {"rows": get_rows_by_status("deleted")})
            return

        if path == "/api/logs":
            json_response(self, {"lines": read_log_lines()})
            return

        if path == "/api/settings":
            json_response(self, get_settings_payload())
            return

        json_response(self, {"error": "not found"}, status=404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(body)

        def val(name):
            return (form.get(name) or [""])[0]

        title = clean_title(val("title"))

        if path == "/api/add_site":
            ok, msg, key = add_site_from_url(val("url"), val("label"), val("category"))
            json_response(self, {"ok": ok, "message": msg, "key": key}, status=200 if ok else 400)
            return

        if path == "/api/remove_site":
            ok, msg = remove_site(val("site"))
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/toggle_site":
            ok, msg, enabled = toggle_site_enabled(val("site"))
            json_response(self, {"ok": ok, "message": msg, "enabled": enabled}, status=200 if ok else 400)
            return

        if path == "/api/toggle_browser":
            ok, msg, enabled = toggle_browser_sync(val("browser"))
            json_response(
                self,
                {"ok": ok, "message": msg, "enabled": enabled},
                status=200 if ok else 400,
            )
            return

        if path == "/api/set_backup_dir":
            ok, msg = update_backup_dir_config(val("backup_dir"))
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/restart_server":
            ok, msg = restart_server_soon()
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 500)
            return

        if path == "/api/set_site_priority":
            ok, msg = update_site_priority(val("priority"))
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/toggle_duplicate_hiding":
            ok, msg, hide_site_duplicates = toggle_site_duplicate_hiding()
            json_response(
                self,
                {
                    "ok": ok,
                    "message": msg,
                    "hide_site_duplicates": hide_site_duplicates,
                },
                status=200 if ok else 400,
            )
            return

        if path == "/api/delete":
            if not title:
                json_response(self, {"ok": False, "message": "작품명이 비어 있음"}, status=400)
                return

            item = set_status(title, "deleted")
            ok, output = run_backup_script()

            if ok:
                msg = f"삭제 처리 완료: {item['title']}"
            else:
                msg = f"삭제 상태는 저장했지만 백업 재실행 실패: {item['title']}\n{output[:700]}"

            json_response(self, {"ok": ok, "message": msg})
            return

        if path == "/api/restore":
            if not title:
                json_response(self, {"ok": False, "message": "작품명이 비어 있음"}, status=400)
                return

            item = set_status(title, "active")
            ok, output = run_backup_script()

            if ok:
                msg = f"복구 처리 완료: {item['title']}"
            else:
                msg = f"복구 상태는 저장했지만 백업 재실행 실패: {item['title']}\n{output[:700]}"

            json_response(self, {"ok": ok, "message": msg})
            return

        if path == "/api/purge":
            if not title:
                json_response(self, {"ok": False, "message": "작품명이 비어 있음"}, status=400)
                return

            item = set_status(title, "purged")
            ok, output = run_backup_script()

            if ok:
                msg = f"완전삭제 처리 완료: {item['title']}"
            else:
                msg = f"완전삭제 상태는 저장했지만 백업 재실행 실패: {item['title']}\n{output[:700]}"

            json_response(self, {"ok": ok, "message": msg})
            return

        if path == "/api/select_episode":
            title = clean_title(val("title"))
            episode = val("episode").strip()

            ok, msg = select_episode_from_history(title, episode)
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/unlock_episode":
            title = clean_title(val("title"))

            ok, msg = unlock_episode(title)
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/rollback_episode":
            title = clean_title(val("title"))

            ok, msg = rollback_episode(title)
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/set_category":
            title = clean_title(val("title"))
            category = val("category")

            ok, msg = set_item_category(title, category)
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/set_site_category":
            ok, msg = set_site_category(val("site"), val("category"))
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/edit_title":
            old_title = clean_title(val("old_title"))
            new_title = clean_title(val("new_title"))

            ok, msg = edit_title_only(old_title, new_title)
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/restore_title":
            title = clean_title(val("title"))

            ok, msg = restore_original_title(title)
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/edit":
            old_title = clean_title(val("old_title"))
            new_title = clean_title(val("new_title"))
            latest_episode = val("latest_episode").strip()
            url = val("url").strip()

            ok, msg = edit_item(old_title, new_title, latest_episode, url)
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/merge":
            source_title = clean_title(val("source_title"))
            target_title = clean_title(val("target_title"))

            ok, msg = merge_titles(source_title, target_title)
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        if path == "/api/run_backup":
            ok, output = run_backup_script()

            if ok:
                msg = "백업 재실행 완료"
            else:
                msg = f"백업 재실행 실패\n{output[:700]}"

            json_response(self, {"ok": ok, "message": msg})
            return

        json_response(self, {"error": "not found"}, status=404)


# =========================
# 동적 사이트 설정
# =========================

DEFAULT_SITE_SPECS = {
    "blacktoon": {
        "label": "블랙툰",
        "prefix": "blacktoon",
        "host_re": r"blacktoon\d+\.com",
        "enabled": True,
    },
}

def sanitize_site_key(value):
    value = str(value or "").strip().lower()
    value = re.sub(r"^www\.", "", value)
    value = re.sub(r"[^0-9a-z가-힣_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "site"


def derive_site_spec_from_url(url, label=""):
    parsed = urlparse(str(url or "").strip())

    if not parsed.netloc:
        parsed = urlparse("https://" + str(url or "").strip())

    host = parsed.netloc.lower()
    host = re.sub(r"^www\.", "", host).split(":")[0]

    if not host or "." not in host:
        raise ValueError("주소에서 도메인을 못 찾음")

    # wfwf464.com / tkor125.com / blacktoon412.com 같은 숫자 변경 도메인 자동 대응
    match = re.match(r"^([a-zA-Z가-힣_-]+?)(\d+)(\..+)$", host)

    if match:
        prefix = match.group(1).lower()
        suffix = match.group(3).lower()
        host_re = rf"{re.escape(prefix)}\d+{re.escape(suffix)}"
        key = sanitize_site_key(prefix)
    else:
        prefix = host
        host_re = re.escape(host)
        key = sanitize_site_key(host.rsplit(".", 1)[0])

    label = clean_title(label) or key

    return key, {
        "label": label,
        "prefix": prefix,
        "host_re": host_re,
        "enabled": True,
    }


def normalize_site_specs(raw_sites):
    if not isinstance(raw_sites, dict):
        raw_sites = {}

    sites = {}

    # 블랙툰 기본값만 유지. 늑대/툰코는 주소로 추가해야 활성화됨.
    for key, spec in DEFAULT_SITE_SPECS.items():
        merged = dict(spec)
        if isinstance(raw_sites.get(key), dict):
            merged.update(raw_sites[key])
        sites[key] = merged

    for raw_key, raw_spec in raw_sites.items():
        if not isinstance(raw_spec, dict):
            continue

        key = sanitize_site_key(raw_key)
        label = clean_title(raw_spec.get("label", "")) or key
        prefix = str(raw_spec.get("prefix", "") or key).strip().lower()
        host_re = str(raw_spec.get("host_re", "") or rf"{re.escape(prefix)}\d*\.com").strip()
        enabled = raw_spec.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() not in ["0", "false", "off", "no", "아니오", "끔"]
        else:
            enabled = bool(enabled)

        sites[key] = {
            "label": label,
            "prefix": prefix,
            "host_re": host_re,
            "enabled": enabled,
        }

    return sites


def sync_global_site_specs(db):
    global SITE_SPECS
    settings = db.get("settings", {}) if isinstance(db, dict) else {}
    SITE_SPECS = normalize_site_specs(settings.get("sites", DEFAULT_SITE_SPECS))
    return SITE_SPECS


def normalize_site_priority(value, site_specs=None):
    if site_specs is None:
        site_specs = SITE_SPECS

    label_to_key = {}
    for key, spec in site_specs.items():
        label_to_key[str(spec.get("label", key)).strip().lower()] = key
        label_to_key[str(key).strip().lower()] = key

    if isinstance(value, str):
        raw_parts = re.split(r"[>,/,\s]+", value.strip())
    elif isinstance(value, list):
        raw_parts = value
    else:
        raw_parts = []

    result = []
    seen = set()

    for raw in raw_parts:
        token = str(raw or "").strip().lower()
        if not token:
            continue

        site_key = label_to_key.get(token) or SITE_NAME_ALIASES.get(token, token)

        if site_key not in site_specs or site_key in seen:
            continue

        seen.add(site_key)
        result.append(site_key)

    for site_key in site_specs.keys():
        if site_key not in seen:
            result.append(site_key)

    return result


def default_db():
    return {
        "version": 1,
        "created_at": now_text(),
        "updated_at": now_text(),
        "settings": {
            "sites": dict(DEFAULT_SITE_SPECS),
            "site_priority": list(DEFAULT_SITE_SPECS.keys()),
            "hide_site_duplicates": True,
            "browser_enabled": dict(DEFAULT_BROWSER_ENABLED),
        },
        "items": {},
    }


def normalize_settings(db):
    db.setdefault("settings", {})
    settings = db["settings"]

    if not isinstance(settings, dict):
        settings = {}
        db["settings"] = settings

    settings["sites"] = normalize_site_specs(settings.get("sites", DEFAULT_SITE_SPECS))
    sync_global_site_specs(db)

    settings["site_priority"] = normalize_site_priority(
        settings.get("site_priority", list(SITE_SPECS.keys())),
        SITE_SPECS,
    )

    raw_hide = settings.get("hide_site_duplicates", True)
    if isinstance(raw_hide, str):
        settings["hide_site_duplicates"] = raw_hide.strip().lower() not in ["0", "false", "off", "no", "아니오", "끔"]
    else:
        settings["hide_site_duplicates"] = bool(raw_hide)

    raw_browser_enabled = settings.get("browser_enabled", DEFAULT_BROWSER_ENABLED)
    if not isinstance(raw_browser_enabled, dict):
        raw_browser_enabled = {}

    browser_enabled = {}
    for key, default in DEFAULT_BROWSER_ENABLED.items():
        value = raw_browser_enabled.get(key, default)
        if isinstance(value, str):
            browser_enabled[key] = value.strip().lower() not in ["0", "false", "off", "no", "아니오", "끔"]
        else:
            browser_enabled[key] = bool(value)

    settings["browser_enabled"] = browser_enabled
    sync_global_site_specs(db)
    return db


def site_label(site_key):
    return SITE_SPECS.get(site_key, {}).get("label", site_key or "")


def extract_tracked_host_info(url):
    url = str(url or "")

    for site_key, spec in SITE_SPECS.items():
        if spec.get("enabled") is False:
            continue

        host_re = spec.get("host_re", "")
        if not host_re:
            continue

        match = re.search(
            rf"https?://(?:www\.)?({host_re})",
            url,
            re.I,
        )

        if not match:
            continue

        number = 0
        num_match = re.search(r"(\d+)(?=\.)", match.group(1))
        if num_match:
            try:
                number = int(num_match.group(1))
            except Exception:
                number = 0

        return site_key, number

    return None


def get_site_key_from_url(url):
    info = extract_tracked_host_info(url)
    return info[0] if info else ""


def get_site_key_from_title(title):
    title = str(title or "").strip()

    for key, spec in SITE_SPECS.items():
        label = re.escape(str(spec.get("label", key)))
        if re.match(rf"^\[{label}\]\s*", title, flags=re.I):
            return key

    return ""


def item_site_key(item):
    if not isinstance(item, dict):
        return ""

    site_key = get_site_key_from_url(item.get("url", ""))
    if site_key:
        return site_key

    site_key = get_site_key_from_title(item.get("title", ""))
    if site_key:
        return site_key

    for record in (item.get("episode_history", {}) or {}).values():
        if isinstance(record, dict):
            site_key = get_site_key_from_url(record.get("url", ""))
            if site_key:
                return site_key

    return "blacktoon"


def canonical_title_for_duplicate(title):
    title = clean_title(title)

    for spec in SITE_SPECS.values():
        label = re.escape(str(spec.get("label", "")))
        if label:
            title = re.sub(rf"^\[{label}\]\s*", "", title, flags=re.I).strip()

    title = re.sub(r"^\[(?:블랙툰|늑대|툰코)\]\s*", "", title).strip()
    title = re.sub(r"\s+", " ", title)
    return title.lower()


def get_latest_blacktoon_host_from_db(db):
    max_nums = {}

    sync_global_site_specs(normalize_settings(db))

    for url in collect_db_urls(db):
        info = extract_tracked_host_info(url)

        if not info:
            continue

        site_key, number = info
        if number <= 0:
            continue

        if site_key not in max_nums or number > max_nums[site_key]:
            max_nums[site_key] = number

    latest = {}

    for site_key, number in max_nums.items():
        prefix = SITE_SPECS.get(site_key, {}).get("prefix", site_key)
        latest[site_key] = f"https://{prefix}{number}.com"

    return latest


def normalize_blacktoon_url(url, latest_hosts):
    url = str(url or "").strip()

    if not url or not latest_hosts:
        return url

    if isinstance(latest_hosts, str):
        return re.sub(
            r"^https?://(?:www\.)?blacktoon\d+\.com",
            latest_hosts,
            url,
            flags=re.I,
        )

    info = extract_tracked_host_info(url)
    if not info:
        return url

    site_key, _ = info
    latest_host = latest_hosts.get(site_key)
    if not latest_host:
        return url

    host_re = SITE_SPECS.get(site_key, {}).get("host_re", "")
    if not host_re:
        return url

    return re.sub(
        rf"^https?://(?:www\.)?{host_re}",
        latest_host,
        url,
        flags=re.I,
    )


def normalize_db_urls_to_latest(db):
    latest_hosts = get_latest_blacktoon_host_from_db(db)

    if not latest_hosts:
        return db

    for item in db.get("items", {}).values():
        if not isinstance(item, dict):
            continue

        item["url"] = normalize_blacktoon_url(item.get("url", ""), latest_hosts)

        history = item.get("episode_history", {}) or {}
        for record in history.values():
            if isinstance(record, dict):
                record["url"] = normalize_blacktoon_url(record.get("url", ""), latest_hosts)

    return db


def get_settings_payload():
    db = ensure_db()
    db = normalize_settings(db)
    settings = db.get("settings", {})
    return {
        "site_priority": settings.get("site_priority", list(SITE_SPECS.keys())),
        "hide_site_duplicates": settings.get("hide_site_duplicates", True),
        "site_labels": {k: v["label"] for k, v in SITE_SPECS.items()},
        "sites": settings.get("sites", SITE_SPECS),
        "browser_enabled": settings.get("browser_enabled", DEFAULT_BROWSER_ENABLED),
        "browser_labels": dict(BROWSER_LABELS),
    }


def update_site_priority(priority_text):
    db = ensure_db()
    db = normalize_settings(db)
    priority = normalize_site_priority(priority_text, SITE_SPECS)

    db.setdefault("settings", {})["site_priority"] = priority
    save_db(db)

    labels = " > ".join(site_label(x) for x in priority)
    append_log(f"사이트 우선순위 변경: {labels}")
    return True, f"사이트 우선순위: {labels}"


def add_site_from_url(url, label=""):
    db = ensure_db()
    db = normalize_settings(db)

    try:
        key, spec = derive_site_spec_from_url(url, label)
    except Exception as e:
        return False, str(e), ""

    sites = db.setdefault("settings", {}).setdefault("sites", {})
    original_key = key
    idx = 2
    while key in sites and sites[key].get("host_re") != spec.get("host_re"):
        key = f"{original_key}_{idx}"
        idx += 1

    sites[key] = spec
    priority = normalize_site_priority(db["settings"].get("site_priority", []), sites)
    if key not in priority:
        priority.append(key)
    db["settings"]["site_priority"] = priority

    save_db(db)
    append_log(f"사이트 추가: {spec.get('label')} / {url}")
    return True, f"사이트 추가 완료: {spec.get('label')}", key


def remove_site(site_key):
    db = ensure_db()
    db = normalize_settings(db)
    site_key = str(site_key or "").strip()

    if site_key == "blacktoon":
        return False, "블랙툰 기본 사이트는 삭제하지 않음"

    sites = db.setdefault("settings", {}).setdefault("sites", {})
    if site_key not in sites:
        return False, "사이트를 못 찾음"

    label = sites[site_key].get("label", site_key)
    del sites[site_key]
    db["settings"]["site_priority"] = [x for x in db["settings"].get("site_priority", []) if x != site_key]

    save_db(db)
    append_log(f"사이트 삭제: {label}")
    return True, f"사이트 삭제 완료: {label}"


def toggle_site_enabled(site_key):
    db = ensure_db()
    db = normalize_settings(db)
    site_key = str(site_key or "").strip()

    sites = db.setdefault("settings", {}).setdefault("sites", {})
    if site_key not in sites:
        return False, "사이트를 못 찾음", None

    current = bool(sites[site_key].get("enabled", True))
    sites[site_key]["enabled"] = not current

    save_db(db)

    label = sites[site_key].get("label", site_key)
    state = "ON" if sites[site_key]["enabled"] else "OFF"
    append_log(f"사이트 연동 변경: {label} {state}")
    return True, f"{label} {state}", sites[site_key]["enabled"]



# =========================
# 범용 작품 페이지 URL / 만화·소설·애니 경로 지원
# =========================

CONTENT_CATEGORY_ALIASES = {
    "webtoons": "webtoon",
    "webtoon": "webtoon",
    "mangas": "manga",
    "manga": "manga",
    "manhwas": "manhwa",
    "manhwa": "manhwa",
    "comics": "comic",
    "comic": "comic",
    "cartoons": "cartoon",
    "cartoon": "cartoon",
    "novels": "novel",
    "novel": "novel",
    "books": "book",
    "book": "book",
    "animes": "anime",
    "anime": "anime",
    "animations": "anime",
    "animation": "anime",
    "ani": "anime",
}


def _url_origin(url):
    try:
        parsed = urlparse(str(url or "").strip())
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    return ""


def _strip_query_fragment_url(url):
    try:
        parsed = urlparse(str(url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return str(url or "").strip()
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return str(url or "").strip()


def _strip_html(value):
    return re.sub(r"\.html?$", "", str(value or ""), flags=re.I)


def _add_html_like(original_segment, new_segment):
    if re.search(r"\.html?$", str(original_segment or ""), flags=re.I):
        return f"{new_segment}.html"
    return new_segment


def _segment_looks_episode(segment):
    segment = _strip_html(segment)
    s = segment.lower()

    if not s:
        return False

    patterns = [
        r"^(?:ep|episode|e|ch|chapter|view|read|watch|play)[-_]?\d+(?:\.\d+)?$",
        r"^\d+(?:\.\d+)?$",
        r"^\d+(?:\.\d+)?(?:화|회|편|장|권|話|章)$",
        r"^(?:第)?\d+(?:\.\d+)?(?:話|章)$",
    ]

    return any(re.match(p, s, flags=re.I) for p in patterns)


def _category_index(parts):
    for i, part in enumerate(parts):
        key = _strip_html(part).lower()
        if key in CONTENT_CATEGORY_ALIASES:
            return i, CONTENT_CATEGORY_ALIASES[key]
    return None, ""


def infer___removed_link___from_url(url):
    """
    회차 URL을 작품/목록 URL로 최대한 변환.
    블랙툰은 기존 정확 패턴 유지.
    그 외에는 webtoon/manga/novel/anime 계열 경로에서 마지막 회차 조각을 제거.
    """
    url = str(url or "").strip()
    if not url:
        return ""

    # 기존 블랙툰 정확 구조
    episode_match = re.match(
        r"^(https?://(?:www\.)?blacktoon\d+\.com)/webtoons/(\d+)/\d+\.html(?:[?#].*)?$",
        url,
        flags=re.I,
    )
    if episode_match:
        return f"{episode_match.group(1)}/webtoon/{episode_match.group(2)}.html"

    series_match = re.match(
        r"^(https?://(?:www\.)?blacktoon\d+\.com/webtoon/\d+\.html)(?:[?#].*)?$",
        url,
        flags=re.I,
    )
    if series_match:
        return series_match.group(1)

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""

    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if not parts:
        return ""

    cat_idx, singular = _category_index(parts)

    # /webtoons/16340/1495572.html -> /webtoon/16340.html
    if cat_idx is not None and len(parts) >= cat_idx + 3:
        series_seg = parts[cat_idx + 1]
        ep_seg = parts[cat_idx + 2]

        if _segment_looks_episode(ep_seg) or len(parts) > cat_idx + 3:
            new_parts = list(parts[:cat_idx]) + [singular, _add_html_like(ep_seg, _strip_html(series_seg))]
            return f"{parsed.scheme}://{parsed.netloc}/" + "/".join(new_parts)

    # /manga/title/12 or /novel/title/123.html -> /manga/title
    if cat_idx is not None and len(parts) >= cat_idx + 3:
        last = parts[-1]
        if _segment_looks_episode(last):
            new_parts = parts[:-1]
            return f"{parsed.scheme}://{parsed.netloc}/" + "/".join(new_parts)

    # /view/title/12 같은 범용 구조: 마지막이 회차면 제거
    if len(parts) >= 2 and _segment_looks_episode(parts[-1]):
        return f"{parsed.scheme}://{parsed.netloc}/" + "/".join(parts[:-1])

    # 이미 작품 페이지라고 볼 수 있는 경우
    if cat_idx is not None and len(parts) >= cat_idx + 2:
        return _strip_query_fragment_url(url)

    return ""


def get___removed_link__(url):
    return infer___removed_link___from_url(url)


def normalize_item(item):
    item = dict(item or {})
    title = clean_title(item.get("title", ""))
    item["title"] = title
    item.setdefault("latest_episode", "")
    item.setdefault("last_seen", "")
    item.setdefault("url", "")
    item.setdefault("__removed_link__", "")
    item.setdefault("status", "active")
    item.setdefault("aliases", [])
    item.setdefault("manual", {})
    item.setdefault("episode_history", {})
    item.setdefault("locked_episode", "")
    item.setdefault("blocked_episodes", [])
    item.setdefault("created_at", now_text())
    item.setdefault("updated_at", now_text())

    if not item.get("__removed_link__"):
        item["__removed_link__"] = get___removed_link__(item.get("url", ""))

    if item["status"] not in ["active", "deleted", "purged"]:
        item["status"] = "active"

    aliases = []
    seen = set()

    for alias in item.get("aliases", []):
        alias = clean_title(alias)
        key = title_key(alias)

        if not alias or key == title_key(title) or key in seen:
            continue

        seen.add(key)
        aliases.append(alias)

    item["aliases"] = aliases

    history = {}
    for ep, record in (item.get("episode_history", {}) or {}).items():
        if not isinstance(record, dict):
            continue
        rec = dict(record)
        if not rec.get("__removed_link__"):
            rec["__removed_link__"] = get___removed_link__(rec.get("url", "")) or item.get("__removed_link__", "")
        history[ep] = rec
    item["episode_history"] = history

    return item


def add_episode_history(item, episode, url="", last_seen="", source="", __removed_link__=""):
    item = normalize_item(item)
    ep = episode_key(episode)

    if not ep:
        return item

    __removed_link__ = str(__removed_link__ or "").strip() or get___removed_link__(url) or item.get("__removed_link__", "")
    if __removed_link__ and not item.get("__removed_link__"):
        item["__removed_link__"] = __removed_link__

    history = item.setdefault("episode_history", {})
    old = history.get(ep, {})

    if not old or str(last_seen or "") >= str(old.get("last_seen", "")):
        history[ep] = {
            "episode": ep,
            "url": str(url or old.get("url", "") or ""),
            "__removed_link__": str(__removed_link__ or old.get("__removed_link__", "") or ""),
            "last_seen": str(last_seen or old.get("last_seen", "") or ""),
            "source": source or old.get("source", ""),
        }

    item["episode_history"] = history
    return normalize_item(item)


def get_episode_history_list(item):
    item = normalize_item(item)
    history = item.get("episode_history", {}) or {}
    records = []

    for ep, record in history.items():
        ep_key = episode_key(ep)
        if not ep_key:
            continue

        records.append({
            "episode": ep_key,
            "url": str(record.get("url", "") or ""),
            "__removed_link__": str(record.get("__removed_link__", "") or get___removed_link__(record.get("url", "")) or item.get("__removed_link__", "")),
            "last_seen": str(record.get("last_seen", "") or ""),
            "source": str(record.get("source", "") or ""),
        })

    records.sort(key=lambda r: episode_sort_value(r.get("episode", "")), reverse=True)
    return records


def apply_locked_episode(item):
    item = normalize_item(item)
    locked = episode_key(item.get("locked_episode", ""))

    if not locked:
        return item

    record = get_episode_record(item, locked)

    if record:
        item["latest_episode"] = locked
        item["url"] = str(record.get("url", "") or item.get("url", "") or "")
        item["__removed_link__"] = str(record.get("__removed_link__", "") or item.get("__removed_link__", "") or get___removed_link__(item.get("url", "")))
        item["last_seen"] = str(record.get("last_seen", "") or item.get("last_seen", "") or "")
    else:
        item["latest_episode"] = locked

    return normalize_item(item)


def make_item_from_row(row, status="active"):
    row_url = str(row.get("url", "") or "").strip()
    row___removed_link__ = str(row.get("__removed_link__", "") or "").strip() or get___removed_link__(row_url)

    item = normalize_item({
        "title": clean_title(row.get("title", "")),
        "latest_episode": str(row.get("latest_episode", "") or "").strip(),
        "last_seen": str(row.get("last_seen", "") or "").strip(),
        "url": row_url,
        "__removed_link__": row___removed_link__,
        "status": status,
        "aliases": [],
        "manual": {},
        "episode_history": {},
        "locked_episode": "",
        "blocked_episodes": [],
        "created_at": now_text(),
        "updated_at": now_text(),
    })

    item = add_episode_history(
        item,
        item.get("latest_episode", ""),
        item.get("url", ""),
        item.get("last_seen", ""),
        "initial",
        item.get("__removed_link__", ""),
    )

    return normalize_item(item)


def update_item_from_row(item, row):
    item = normalize_item(item)

    row_title = clean_title(row.get("title", ""))
    row_ep = str(row.get("latest_episode", "") or "").strip()
    row_seen = str(row.get("last_seen", "") or "").strip()
    row_url = str(row.get("url", "") or "").strip()
    row___removed_link__ = str(row.get("__removed_link__", "") or "").strip() or get___removed_link__(row_url)

    manual = item.get("manual", {})

    if row___removed_link__:
        item["__removed_link__"] = row___removed_link__

    if row_title and not manual.get("title") and not item.get("title"):
        item["title"] = row_title

    if row_title and title_key(row_title) != title_key(item.get("title", "")):
        aliases = item.setdefault("aliases", [])
        if all(title_key(a) != title_key(row_title) for a in aliases):
            aliases.append(row_title)

    item = add_episode_history(item, row_ep, row_url, row_seen, "csv/archive", row___removed_link__)

    if episode_key(item.get("locked_episode", "")):
        item = apply_locked_episode(item)
        item["updated_at"] = now_text()
        return normalize_item(item)

    old_ep = episode_sort_value(item.get("latest_episode", ""))
    new_ep = episode_sort_value(row_ep)

    if row_ep and new_ep >= old_ep:
        item["latest_episode"] = row_ep
        if row_seen and row_seen >= str(item.get("last_seen", "")):
            item["last_seen"] = row_seen
        if row_url:
            item["url"] = row_url
        if row___removed_link__:
            item["__removed_link__"] = row___removed_link__

    elif row_seen and row_seen >= str(item.get("last_seen", "")) and row_ep and new_ep == old_ep:
        item["last_seen"] = row_seen
        if row_url:
            item["url"] = row_url
        if row___removed_link__:
            item["__removed_link__"] = row___removed_link__

    if row_url and not item.get("url"):
        item["url"] = row_url
    if row___removed_link__ and not item.get("__removed_link__"):
        item["__removed_link__"] = row___removed_link__

    item["updated_at"] = now_text()
    return normalize_item(item)


def item_to_row(item):
    item = normalize_item(item)
    __removed_link__ = item.get("__removed_link__", "") or get___removed_link__(item.get("url", ""))

    if not __removed_link__:
        for record in (item.get("episode_history", {}) or {}).values():
            if isinstance(record, dict):
                __removed_link__ = record.get("__removed_link__", "") or get___removed_link__(record.get("url", ""))
                if __removed_link__:
                    break

    return {
        "title": item.get("title", ""),
        "latest_episode": item.get("latest_episode", ""),
        "last_seen": item.get("last_seen", ""),
        "url": item.get("url", ""),
        "site": item_site_key(item),
        "site_label": site_label(item_site_key(item)),
        "__removed_link__": __removed_link__,
        "previous_episode": (get_previous_episode_from_history(item) or ["", {}])[0],
        "locked_episode": episode_key(item.get("locked_episode", "")),
        "episode_history": get_episode_history_list(item),
        "blocked_episodes": item.get("blocked_episodes", []),
        "status": item.get("status", "active"),
        "aliases": item.get("aliases", []),
        "updated_at": item.get("updated_at", ""),
    }

# =========================
# 제거된 링크 보정: 블랙툰 외 사이트 / 웹툰·만화·소설·애니
# =========================

CONTENT_CATEGORY_ALIASES = {
    "webtoons": "webtoons",
    "webtoon": "webtoon",
    "toon": "toon",
    "toons": "toons",
    "mangas": "mangas",
    "manga": "manga",
    "manhwas": "manhwas",
    "manhwa": "manhwa",
    "comics": "comics",
    "comic": "comic",
    "cartoons": "cartoons",
    "cartoon": "cartoon",
    "novels": "novels",
    "novel": "novel",
    "books": "books",
    "book": "book",
    "animes": "animes",
    "anime": "anime",
    "animations": "animations",
    "animation": "animation",
    "ani": "ani",
    "웹툰": "웹툰",
    "만화": "만화",
    "소설": "소설",
    "애니": "애니",
    "애니메이션": "애니메이션",
}


def _strip_html(value):
    return re.sub(r"\.html?$", "", str(value or ""), flags=re.I)


def _strip_query_fragment_url(url):
    try:
        parsed = urlparse(str(url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return str(url or "").strip()
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return str(url or "").strip()


def _segment_looks_episode(segment):
    raw = str(segment or "").strip()
    segment = _strip_html(raw)
    s = segment.lower()

    if not s:
        return False

    patterns = [
        r"^(?:ep|episode|e|ch|chapter|view|read|watch|play|vod)[-_]?\d+(?:\.\d+)?$",
        r"^\d+(?:\.\d+)?$",
        r"^\d+(?:\.\d+)?(?:화|회|편|장|권|話|章|부)$",
        r"^(?:第)?\d+(?:\.\d+)?(?:話|章)$",
        r"^(?:화|회|편|장|권)[-_]?\d+(?:\.\d+)?$",
    ]

    return any(re.match(p, s, flags=re.I) for p in patterns)


def _category_index(parts):
    for i, part in enumerate(parts):
        key = _strip_html(part).lower()
        if key in CONTENT_CATEGORY_ALIASES:
            return i, CONTENT_CATEGORY_ALIASES[key]
    return None, ""


def infer___removed_link___from_url(url):
    url = str(url or "").strip()
    if not url:
        return ""

    # 블랙툰은 구조가 확실하므로 기존 공식 변환 유지
    episode_match = re.match(
        r"^(https?://(?:www\.)?blacktoon\d+\.com)/webtoons/(\d+)/\d+\.html(?:[?#].*)?$",
        url,
        flags=re.I,
    )
    if episode_match:
        return f"{episode_match.group(1)}/webtoon/{episode_match.group(2)}.html"

    series_match = re.match(
        r"^(https?://(?:www\.)?blacktoon\d+\.com/webtoon/\d+\.html)(?:[?#].*)?$",
        url,
        flags=re.I,
    )
    if series_match:
        return series_match.group(1)

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""

    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if not parts:
        return f"{parsed.scheme}://{parsed.netloc}/"

    cat_idx, _ = _category_index(parts)

    # 비블랙툰은 사이트마다 단수/복수 규칙이 달라서 경로명을 바꾸지 않는다.
    # /webtoons/작품/회차, /manga/작품/12, /소설/작품/123 -> 마지막 회차 조각 제거
    if len(parts) >= 2 and _segment_looks_episode(parts[-1]):
        return f"{parsed.scheme}://{parsed.netloc}/" + "/".join(parts[:-1])

    # /webtoons/작품/1495572.html처럼 회차 조각이 숫자 html이면 위에서 처리됨.
    # /webtoons/작품/view/1495572 같은 경우 마지막 두 조각 제거 후보
    if len(parts) >= 3 and parts[-2].lower() in ["view", "read", "watch", "play", "episode", "chapter", "ep", "ch"]:
        if _segment_looks_episode(parts[-1]):
            return f"{parsed.scheme}://{parsed.netloc}/" + "/".join(parts[:-2])

    # 카테고리/작품 형태면 이미 작품 주소로 판단
    if cat_idx is not None and len(parts) >= cat_idx + 2:
        return _strip_query_fragment_url(url)

    # 마지막 조각에 회차 표현이 없으면 작품 주소일 가능성이 더 큼
    if len(parts) >= 1:
        return _strip_query_fragment_url(url)

    return ""


def get___removed_link__(url):
    return infer___removed_link___from_url(url)

# =========================
# 완전삭제 후 새로 보면 자동 복구 / CSV __removed_link__ 보강
# =========================

def is_row_seen_after_status_change(item, row):
    row_seen = str(row.get("last_seen", "") or "").strip()
    updated_at = str(item.get("updated_at", "") or "").strip()

    if not row_seen:
        return False

    # 날짜 형식이 YYYY-MM-DD HH:MM:SS라 문자열 비교가 시간순 비교로 동작함.
    if not updated_at:
        return True

    return row_seen > updated_at


def update_item_from_row(item, row):
    item = normalize_item(item)

    row_title = clean_title(row.get("title", ""))
    row_ep = str(row.get("latest_episode", "") or "").strip()
    row_seen = str(row.get("last_seen", "") or "").strip()
    row_url = str(row.get("url", "") or "").strip()
    row___removed_link__ = str(row.get("__removed_link__", "") or "").strip() or get___removed_link__(row_url)

    # 완전삭제 뒤에 다시 본 기록이면 current로 부활.
    # 과거 archive/방문기록 때문에 즉시 부활하는 걸 막기 위해 삭제 시각 이후 기록만 인정.
    if item.get("status") == "purged":
        if is_row_seen_after_status_change(item, row):
            item["status"] = "active"
            append_log(f"완전삭제 항목 재등록: {item.get('title', row_title)}")
        else:
            return normalize_item(item)

    manual = item.get("manual", {})

    if row___removed_link__:
        item["__removed_link__"] = row___removed_link__

    if row_title and not manual.get("title") and not item.get("title"):
        item["title"] = row_title

    if row_title and title_key(row_title) != title_key(item.get("title", "")):
        aliases = item.setdefault("aliases", [])
        if all(title_key(a) != title_key(row_title) for a in aliases):
            aliases.append(row_title)

    item = add_episode_history(item, row_ep, row_url, row_seen, "csv/archive", row___removed_link__)

    if episode_key(item.get("locked_episode", "")):
        item = apply_locked_episode(item)
        item["updated_at"] = now_text()
        return normalize_item(item)

    old_ep = episode_sort_value(item.get("latest_episode", ""))
    new_ep = episode_sort_value(row_ep)

    if row_ep and new_ep >= old_ep:
        item["latest_episode"] = row_ep
        if row_seen and row_seen >= str(item.get("last_seen", "")):
            item["last_seen"] = row_seen
        if row_url:
            item["url"] = row_url
        if row___removed_link__:
            item["__removed_link__"] = row___removed_link__

    elif row_seen and row_seen >= str(item.get("last_seen", "")) and row_ep and new_ep == old_ep:
        item["last_seen"] = row_seen
        if row_url:
            item["url"] = row_url
        if row___removed_link__:
            item["__removed_link__"] = row___removed_link__

    if row_url and not item.get("url"):
        item["url"] = row_url
    if row___removed_link__ and not item.get("__removed_link__"):
        item["__removed_link__"] = row___removed_link__

    item["updated_at"] = now_text()
    return normalize_item(item)


# =========================
# 분류 태그: 웹툰/만화/망가/소설/애니/기타
# =========================

CATEGORY_LABELS = {
    "webtoon": "웹툰",
    "comic": "만화",
    "manga": "망가",
    "novel": "소설",
    "anime": "애니",
    "other": "기타",
}

CATEGORY_ALIASES = {
    "웹툰": "webtoon",
    "webtoon": "webtoon",
    "webtoons": "webtoon",
    "toon": "webtoon",
    "toons": "webtoon",

    "만화": "comic",
    "단행본": "comic",
    "단행": "comic",
    "comic": "comic",
    "comics": "comic",
    "cartoon": "comic",
    "cartoons": "comic",
    "manhwa": "comic",
    "manhwas": "comic",
    "book": "comic",
    "books": "comic",
    "tankobon": "comic",
    "tankoubon": "comic",

    "망가": "manga",
    "manga": "manga",
    "mangas": "manga",

    "소설": "novel",
    "novel": "novel",
    "novels": "novel",

    "애니": "anime",
    "애니메이션": "anime",
    "anime": "anime",
    "animes": "anime",
    "animation": "anime",
    "animations": "anime",
    "ani": "anime",

    "기타": "other",
    "other": "other",
    "etc": "other",
}


def normalize_category(value):
    token = str(value or "").strip().lower()
    if not token:
        return "other"

    if token in CATEGORY_LABELS:
        return token

    for alias, key in CATEGORY_ALIASES.items():
        if token == alias.lower():
            return key

    return "other"


def infer_category_from_text(*values):
    text = " ".join(str(v or "") for v in values).lower()

    # 순서 중요: 망가와 만화는 분리, 단행본은 만화
    keyword_rules = [
        ("manga", ["망가", "manga", "/manga", "mangas"]),
        ("comic", ["단행본", "단행", "만화", "comic", "comics", "cartoon", "manhwa", "tankobon", "tankoubon", "/book", "/books"]),
        ("webtoon", ["웹툰", "webtoon", "webtoons", "/toon", "/toons"]),
        ("novel", ["소설", "novel", "novels"]),
        ("anime", ["애니", "애니메이션", "anime", "animes", "animation", "ani"]),
    ]

    for category, keywords in keyword_rules:
        for keyword in keywords:
            if keyword in text:
                return category

    return "other"


def site_default_category(site_key):
    spec = SITE_SPECS.get(site_key, {}) if isinstance(SITE_SPECS, dict) else {}
    return normalize_category(spec.get("category", "other"))


def infer_row_category(row, fallback_site_key=""):
    explicit = normalize_category(row.get("category", ""))
    if explicit != "other":
        return explicit

    inferred = infer_category_from_text(
        row.get("url", ""),
        row.get("__removed_link__", ""),
        row.get("title", ""),
    )
    if inferred != "other":
        return inferred

    site_key = fallback_site_key or get_site_key_from_url(row.get("url", ""))
    return site_default_category(site_key)


def normalize_site_specs(raw_sites):
    if not isinstance(raw_sites, dict):
        raw_sites = {}

    sites = {}

    for key, spec in DEFAULT_SITE_SPECS.items():
        merged = dict(spec)
        if isinstance(raw_sites.get(key), dict):
            merged.update(raw_sites[key])
        sites[key] = merged

    for raw_key, raw_spec in raw_sites.items():
        if not isinstance(raw_spec, dict):
            continue

        key = sanitize_site_key(raw_key)
        label = clean_title(raw_spec.get("label", "")) or key
        prefix = str(raw_spec.get("prefix", "") or key).strip().lower()
        host_re = str(raw_spec.get("host_re", "") or rf"{re.escape(prefix)}\d*\.com").strip()
        enabled = raw_spec.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() not in ["0", "false", "off", "no", "아니오", "끔"]
        else:
            enabled = bool(enabled)

        sites[key] = {
            "label": label,
            "prefix": prefix,
            "host_re": host_re,
            "enabled": enabled,
            "category": normalize_category(raw_spec.get("category", "other")),
        }

    # 기본 블랙툰도 분류 없으면 웹툰
    if "blacktoon" in sites and normalize_category(sites["blacktoon"].get("category")) == "other":
        sites["blacktoon"]["category"] = "webtoon"

    return sites


def normalize_item(item):
    item = dict(item or {})
    title = clean_title(item.get("title", ""))
    item["title"] = title
    item.setdefault("latest_episode", "")
    item.setdefault("last_seen", "")
    item.setdefault("url", "")
    item.setdefault("__removed_link__", "")
    item.setdefault("status", "active")
    item.setdefault("aliases", [])
    item.setdefault("manual", {})
    item.setdefault("episode_history", {})
    item.setdefault("locked_episode", "")
    item.setdefault("blocked_episodes", [])
    item.setdefault("created_at", now_text())
    item.setdefault("updated_at", now_text())

    if not item.get("__removed_link__"):
        item["__removed_link__"] = get___removed_link__(item.get("url", ""))

    manual = item.setdefault("manual", {})
    raw_category = normalize_category(item.get("category", ""))

    if manual.get("category"):
        item["category"] = raw_category
    else:
        inferred = infer_category_from_text(item.get("url", ""), item.get("__removed_link__", ""), item.get("title", ""))
        if inferred != "other":
            item["category"] = inferred
        elif raw_category != "other":
            item["category"] = raw_category
        else:
            item["category"] = site_default_category(item_site_key(item))

    if item["status"] not in ["active", "deleted", "purged"]:
        item["status"] = "active"

    aliases = []
    seen = set()

    for alias in item.get("aliases", []):
        alias = clean_title(alias)
        key = title_key(alias)

        if not alias or key == title_key(title) or key in seen:
            continue

        seen.add(key)
        aliases.append(alias)

    item["aliases"] = aliases

    history = {}
    for ep, record in (item.get("episode_history", {}) or {}).items():
        if not isinstance(record, dict):
            continue
        rec = dict(record)
        if not rec.get("__removed_link__"):
            rec["__removed_link__"] = get___removed_link__(rec.get("url", "")) or item.get("__removed_link__", "")
        history[ep] = rec
    item["episode_history"] = history

    return item


def make_item_from_row(row, status="active"):
    row_url = str(row.get("url", "") or "").strip()
    row___removed_link__ = str(row.get("__removed_link__", "") or "").strip() or get___removed_link__(row_url)
    category = infer_row_category(row)

    item = normalize_item({
        "title": clean_title(row.get("title", "")),
        "latest_episode": str(row.get("latest_episode", "") or "").strip(),
        "last_seen": str(row.get("last_seen", "") or "").strip(),
        "url": row_url,
        "__removed_link__": row___removed_link__,
        "category": category,
        "status": status,
        "aliases": [],
        "manual": {},
        "episode_history": {},
        "locked_episode": "",
        "blocked_episodes": [],
        "created_at": now_text(),
        "updated_at": now_text(),
    })

    item = add_episode_history(
        item,
        item.get("latest_episode", ""),
        item.get("url", ""),
        item.get("last_seen", ""),
        "initial",
        item.get("__removed_link__", ""),
    )

    return normalize_item(item)


def update_item_from_row(item, row):
    item = normalize_item(item)

    row_title = clean_title(row.get("title", ""))
    row_ep = str(row.get("latest_episode", "") or "").strip()
    row_seen = str(row.get("last_seen", "") or "").strip()
    row_url = str(row.get("url", "") or "").strip()
    row___removed_link__ = str(row.get("__removed_link__", "") or "").strip() or get___removed_link__(row_url)

    if item.get("status") == "purged":
        if is_row_seen_after_status_change(item, row):
            item["status"] = "active"
            append_log(f"완전삭제 항목 재등록: {item.get('title', row_title)}")
        else:
            return normalize_item(item)

    manual = item.get("manual", {})

    if row___removed_link__:
        item["__removed_link__"] = row___removed_link__

    if row_title and not manual.get("title") and not item.get("title"):
        item["title"] = row_title

    if row_title and title_key(row_title) != title_key(item.get("title", "")):
        aliases = item.setdefault("aliases", [])
        if all(title_key(a) != title_key(row_title) for a in aliases):
            aliases.append(row_title)

    if not manual.get("category"):
        row_category = infer_row_category(row, item_site_key(item))
        if row_category != "other":
            item["category"] = row_category

    item = add_episode_history(item, row_ep, row_url, row_seen, "csv/archive", row___removed_link__)

    if episode_key(item.get("locked_episode", "")):
        item = apply_locked_episode(item)
        item["updated_at"] = now_text()
        return normalize_item(item)

    old_ep = episode_sort_value(item.get("latest_episode", ""))
    new_ep = episode_sort_value(row_ep)

    if row_ep and new_ep >= old_ep:
        item["latest_episode"] = row_ep
        if row_seen and row_seen >= str(item.get("last_seen", "")):
            item["last_seen"] = row_seen
        if row_url:
            item["url"] = row_url
        if row___removed_link__:
            item["__removed_link__"] = row___removed_link__

    elif row_seen and row_seen >= str(item.get("last_seen", "")) and row_ep and new_ep == old_ep:
        item["last_seen"] = row_seen
        if row_url:
            item["url"] = row_url
        if row___removed_link__:
            item["__removed_link__"] = row___removed_link__

    if row_url and not item.get("url"):
        item["url"] = row_url
    if row___removed_link__ and not item.get("__removed_link__"):
        item["__removed_link__"] = row___removed_link__

    item["updated_at"] = now_text()
    return normalize_item(item)


def item_to_row(item):
    item = normalize_item(item)
    __removed_link__ = item.get("__removed_link__", "") or get___removed_link__(item.get("url", ""))

    if not __removed_link__:
        for record in (item.get("episode_history", {}) or {}).values():
            if isinstance(record, dict):
                __removed_link__ = record.get("__removed_link__", "") or get___removed_link__(record.get("url", ""))
                if __removed_link__:
                    break

    category = normalize_category(item.get("category", "other"))

    return {
        "title": item.get("title", ""),
        "latest_episode": item.get("latest_episode", ""),
        "last_seen": item.get("last_seen", ""),
        "url": item.get("url", ""),
        "site": item_site_key(item),
        "site_label": site_label(item_site_key(item)),
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, "기타"),
        "__removed_link__": __removed_link__,
        "previous_episode": (get_previous_episode_from_history(item) or ["", {}])[0],
        "locked_episode": episode_key(item.get("locked_episode", "")),
        "episode_history": get_episode_history_list(item),
        "blocked_episodes": item.get("blocked_episodes", []),
        "status": item.get("status", "active"),
        "aliases": item.get("aliases", []),
        "updated_at": item.get("updated_at", ""),
    }


def get_settings_payload():
    db = ensure_db()
    db = normalize_settings(db)
    settings = db.get("settings", {})
    return {
        "site_priority": settings.get("site_priority", list(SITE_SPECS.keys())),
        "hide_site_duplicates": settings.get("hide_site_duplicates", True),
        "site_labels": {k: v["label"] for k, v in SITE_SPECS.items()},
        "sites": settings.get("sites", SITE_SPECS),
        "browser_enabled": settings.get("browser_enabled", DEFAULT_BROWSER_ENABLED),
        "browser_labels": dict(BROWSER_LABELS),
        "category_labels": dict(CATEGORY_LABELS),
        "backup_dir": str(BACKUP_DIR),
    }


def set_item_category(title, category):
    db = ensure_db()
    found_key = find_item_key(db, title)

    if not found_key:
        return False, "작품을 못 찾음"

    item = normalize_item(db["items"][found_key])
    category_key = normalize_category(category)

    item["category"] = category_key
    item.setdefault("manual", {})["category"] = True
    item["updated_at"] = now_text()
    db["items"][found_key] = normalize_item(item)

    save_db(db)
    sync_txt_from_db(db)
    append_log(f"분류 변경: {item.get('title', title)} → {CATEGORY_LABELS.get(category_key, category_key)}")
    return True, f"분류 변경: {CATEGORY_LABELS.get(category_key, '기타')}"


def set_site_category(site_key, category):
    db = ensure_db()
    db = normalize_settings(db)

    site_key = str(site_key or "").strip()
    sites = db.setdefault("settings", {}).setdefault("sites", {})

    if site_key not in sites:
        return False, "사이트를 못 찾음"

    category_key = normalize_category(category)
    sites[site_key]["category"] = category_key

    save_db(db)
    append_log(f"사이트 기본분류 변경: {sites[site_key].get('label', site_key)} → {CATEGORY_LABELS.get(category_key, category_key)}")
    return True, f"사이트 기본분류: {CATEGORY_LABELS.get(category_key, '기타')}"


def add_site_from_url(url, label="", category="other"):
    db = ensure_db()
    db = normalize_settings(db)

    try:
        key, spec = derive_site_spec_from_url(url, label)
    except Exception as e:
        return False, str(e), ""

    spec["category"] = normalize_category(category)

    sites = db.setdefault("settings", {}).setdefault("sites", {})
    original_key = key
    idx = 2
    while key in sites and sites[key].get("host_re") != spec.get("host_re"):
        key = f"{original_key}_{idx}"
        idx += 1

    sites[key] = spec
    priority = normalize_site_priority(db["settings"].get("site_priority", []), sites)
    if key not in priority:
        priority.append(key)
    db["settings"]["site_priority"] = priority

    save_db(db)
    append_log(f"사이트 추가: {spec.get('label')} / {url} / {CATEGORY_LABELS.get(spec['category'], spec['category'])}")
    return True, f"사이트 추가 완료: {spec.get('label')}", key



# =========================
# 고정 도메인 / ani.ohli24.com / 링크 보정
# =========================

def _host_from_re(host_re):
    s = str(host_re or "")
    s = s.replace(r"\.", ".")
    s = re.sub(r"\\d\+", "", s)
    s = re.sub(r"\(\?:www\\\.\)\?", "", s)
    s = s.replace("^", "").replace("$", "")
    s = s.strip()
    if re.search(r"[\\\[\]\(\)\|\?\*\+]", s):
        return ""
    return s


def _site_is_dynamic(spec):
    if bool(spec.get("dynamic")):
        return True
    if spec.get("dynamic") is False:
        return False

    prefix = str(spec.get("prefix", "") or "")
    host_re = str(spec.get("host_re", "") or "")

    if "." in prefix:
        return False

    # blacktoon\d+\.com / wfwf\d+\.com 같은 루트 도메인만 동적 도메인으로 취급
    if re.fullmatch(rf"{re.escape(prefix)}\\d\+\\\.com", host_re):
        return True

    return False


def _registered_fixed_hosts():
    hosts = []
    for key, spec in (SITE_SPECS or {}).items():
        if _site_is_dynamic(spec):
            continue

        host = _host_from_re(spec.get("host_re", "")) or str(spec.get("prefix", "") or "")
        host = re.sub(r"^www\.", "", host.lower()).strip()
        if host and "." in host:
            hosts.append((key, host))
    hosts.sort(key=lambda x: len(x[1]), reverse=True)
    return hosts


def _canonicalize_repeated_fixed_host_url(url):
    """
    잘못 만들어진 ani.ohli24.com24.com24.com... 같은 주소를
    등록된 고정 도메인 ani.ohli24.com 기준으로 되돌림.
    """
    url = str(url or "").strip()
    if not url:
        return url

    try:
        parsed = urlparse(url)
    except Exception:
        return url

    if not parsed.scheme or not parsed.netloc:
        return url

    netloc = parsed.netloc.lower()
    bare = re.sub(r"^www\.", "", netloc).split(":")[0]

    for _site_key, host in _registered_fixed_hosts():
        if bare == host:
            return url

        # ani.ohli24.com24.com24.com... -> ani.ohli24.com
        if bare.startswith(host) and re.match(r"^\d+\.com", bare[len(host):]):
            return f"{parsed.scheme}://{host}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "") + (f"#{parsed.fragment}" if parsed.fragment else "")

    # 일반적인 .com숫자.com 반복도 한 번 더 완화
    fixed = re.sub(r"(\.com)(?:\d+\.com)+$", r"\1", bare)
    if fixed != bare:
        return f"{parsed.scheme}://{fixed}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "") + (f"#{parsed.fragment}" if parsed.fragment else "")

    return url


def derive_site_spec_from_url(url, label=""):
    parsed = urlparse(str(url or "").strip())

    if not parsed.netloc:
        parsed = urlparse("https://" + str(url or "").strip())

    host = parsed.netloc.lower()
    host = re.sub(r"^www\.", "", host).split(":")[0]

    # 사용자가 이미 깨진 com24.com 주소를 넣어도 최대한 원래 도메인으로 정리
    host = re.sub(r"(\.com)(?:\d+\.com)+$", r"\1", host)

    if not host or "." not in host:
        raise ValueError("주소에서 도메인을 못 찾음")

    first_label = host.split(".", 1)[0]

    # blacktoon412.com / wfwf464.com / tkor125.com처럼 첫 라벨이 숫자로 끝나는 루트 도메인만 동적 취급.
    # ani.ohli24.com 같은 다중 라벨 도메인은 숫자가 있어도 고정 도메인으로 취급해야 함.
    match = re.match(r"^([a-zA-Z가-힣_-]+?)(\d+)$", first_label)

    if match and host.count(".") == 1:
        prefix = match.group(1).lower()
        suffix = "." + host.split(".", 1)[1].lower()
        host_re = rf"{re.escape(prefix)}\d+{re.escape(suffix)}"
        key = sanitize_site_key(prefix)
        dynamic = True
    else:
        prefix = host
        host_re = re.escape(host)
        key = sanitize_site_key(host.rsplit(".", 1)[0])
        dynamic = False

    label = clean_title(label) or key

    return key, {
        "label": label,
        "prefix": prefix,
        "host_re": host_re,
        "enabled": True,
        "dynamic": dynamic,
    }


def normalize_site_specs(raw_sites):
    if not isinstance(raw_sites, dict):
        raw_sites = {}

    sites = {}

    for key, spec in DEFAULT_SITE_SPECS.items():
        merged = dict(spec)
        if isinstance(raw_sites.get(key), dict):
            merged.update(raw_sites[key])
        # 기본 블랙툰은 동적 도메인
        if key == "blacktoon":
            merged.setdefault("host_re", r"blacktoon\d+\.com")
            merged.setdefault("dynamic", True)
        sites[key] = merged

    for raw_key, raw_spec in raw_sites.items():
        if not isinstance(raw_spec, dict):
            continue

        key = sanitize_site_key(raw_key)
        label = clean_title(raw_spec.get("label", "")) or key
        prefix = str(raw_spec.get("prefix", "") or key).strip().lower()
        host_re = str(raw_spec.get("host_re", "") or "").strip()
        enabled = raw_spec.get("enabled", True)
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() not in ["0", "false", "off", "no", "아니오", "끔"]
        else:
            enabled = bool(enabled)

        if not host_re:
            if "." in prefix:
                host_re = re.escape(prefix)
            else:
                host_re = rf"{re.escape(prefix)}\d*\.com"

        # 기존 DB에 dynamic 필드가 없던 사이트도 재판정
        if "dynamic" in raw_spec:
            dynamic = bool(raw_spec.get("dynamic"))
        else:
            dynamic = bool(re.fullmatch(rf"{re.escape(prefix)}\\d\+\\\.com", host_re) and "." not in prefix)

        sites[key] = {
            "label": label,
            "prefix": prefix,
            "host_re": host_re,
            "enabled": enabled,
            "dynamic": dynamic,
            "category": normalize_category(raw_spec.get("category", "other")) if "normalize_category" in globals() else raw_spec.get("category", "other"),
        }

    if "blacktoon" in sites:
        sites["blacktoon"]["dynamic"] = True
        sites["blacktoon"].setdefault("category", "webtoon")

    return sites


def extract_tracked_host_info(url):
    url = _canonicalize_repeated_fixed_host_url(str(url or ""))

    try:
        parsed = urlparse(url)
        host = re.sub(r"^www\.", "", parsed.netloc.lower()).split(":")[0]
    except Exception:
        host = ""

    if not host:
        return None

    for site_key, spec in (SITE_SPECS or {}).items():
        if spec.get("enabled") is False:
            continue

        host_re = str(spec.get("host_re", "") or "")
        if not host_re:
            continue

        if not re.fullmatch(host_re, host, flags=re.I):
            continue

        if not _site_is_dynamic(spec):
            return site_key, 0

        num_match = re.search(r"(\d+)(?=\.)", host)
        number = 0
        if num_match:
            try:
                number = int(num_match.group(1))
            except Exception:
                number = 0

        return site_key, number

    return None


def get_latest_blacktoon_host_from_db(db):
    max_nums = {}

    sync_global_site_specs(normalize_settings(db)) if "sync_global_site_specs" in globals() and "normalize_settings" in globals() else None

    for url in collect_db_urls(db):
        info = extract_tracked_host_info(url)
        if not info:
            continue

        site_key, number = info

        if number <= 0:
            continue

        spec = SITE_SPECS.get(site_key, {})
        if not _site_is_dynamic(spec):
            continue

        if site_key not in max_nums or number > max_nums[site_key]:
            max_nums[site_key] = number

    latest = {}

    for site_key, number in max_nums.items():
        prefix = SITE_SPECS.get(site_key, {}).get("prefix", site_key)
        latest[site_key] = f"https://{prefix}{number}.com"

    return latest


def get_latest_blacktoon_host_from_items(items):
    latest = {}

    for site_key, forced in (FORCE_LATEST_HOSTS or {}).items():
        if forced:
            latest[site_key] = forced.rstrip("/")

    max_nums = {}

    for item in items:
        url = item.get("url", "") if isinstance(item, dict) else str(item)
        info = extract_tracked_host_info(url)

        if not info:
            continue

        site_key, number = info

        if number <= 0:
            continue

        spec = SITE_SPECS.get(site_key, {})
        if not _site_is_dynamic(spec):
            continue

        if site_key in latest:
            continue

        if site_key not in max_nums or number > max_nums[site_key]:
            max_nums[site_key] = number

    for site_key, number in max_nums.items():
        prefix = SITE_SPECS.get(site_key, {}).get("prefix", site_key)
        latest[site_key] = f"https://{prefix}{number}.com"

    return latest


def normalize_blacktoon_url(url, latest_hosts=None):
    url = _canonicalize_repeated_fixed_host_url(str(url or "").strip())

    if not url:
        return url

    if isinstance(latest_hosts, str):
        if latest_hosts:
            return re.sub(
                r"^https?://(?:www\.)?blacktoon\d+\.com",
                latest_hosts.rstrip("/"),
                url,
                flags=re.I,
            )
        return url

    info = extract_tracked_host_info(url)
    if not info:
        return url

    site_key, _ = info
    spec = SITE_SPECS.get(site_key, {})

    if not _site_is_dynamic(spec):
        return url

    latest_host = (latest_hosts or {}).get(site_key)
    if not latest_host:
        return url

    host_re = spec.get("host_re", "")
    if not host_re:
        return url

    return re.sub(
        rf"^https?://(?:www\.)?{host_re}",
        latest_host.rstrip("/"),
        url,
        flags=re.I,
    )


def normalize_db_urls_to_latest(db):
    latest_hosts = get_latest_blacktoon_host_from_db(db)

    for item in db.get("items", {}).values():
        if not isinstance(item, dict):
            continue

        item["url"] = normalize_blacktoon_url(item.get("url", ""), latest_hosts)
        item["__removed_link__"] = normalize_blacktoon_url(item.get("__removed_link__", ""), latest_hosts)

        if not item.get("__removed_link__"):
            item["__removed_link__"] = infer___removed_link___from_url(item.get("url", ""))

        history = item.get("episode_history", {}) or {}
        for record in history.values():
            if isinstance(record, dict):
                record["url"] = normalize_blacktoon_url(record.get("url", ""), latest_hosts)
                record["__removed_link__"] = normalize_blacktoon_url(record.get("__removed_link__", ""), latest_hosts)
                if not record.get("__removed_link__"):
                    record["__removed_link__"] = infer___removed_link___from_url(record.get("url", ""))

    return db


def _decoded_path_parts(parsed):
    return [unquote(p) for p in parsed.path.strip("/").split("/") if p]


def _encode_path_parts(parts):
    return "/" + "/".join(quote(str(p), safe="") for p in parts)


def _remove_episode_suffix_from_title(text):
    text = unquote(str(text or "")).strip()
    text = re.sub(r"\s*(?:외전\s*)?\d+(?:\.\d+)?\s*(?:화|회|편|장|권|話|章|부)\s*$", "", text, flags=re.I)
    text = re.sub(r"\s*(?:episode|ep\.?|e|chapter|ch\.?)\s*[-_:]?\s*\d+(?:\.\d+)?\s*$", "", text, flags=re.I)
    text = re.sub(r"\s*[-–—_:]?\s*#?\d+(?:\.\d+)?\s*$", "", text)
    return text.strip()


def _segment_looks_episode(segment):
    raw = unquote(str(segment or "")).strip()
    segment = _strip_html(raw) if "_strip_html" in globals() else re.sub(r"\.html?$", "", raw, flags=re.I)
    s = segment.lower()

    if not s:
        return False

    patterns = [
        r"^(?:ep|episode|e|ch|chapter|view|read|watch|play|vod)[-_]?\d+(?:\.\d+)?$",
        r"^\d+(?:\.\d+)?$",
        r"^\d+(?:\.\d+)?(?:화|회|편|장|권|話|章|부)$",
        r"^(?:第)?\d+(?:\.\d+)?(?:話|章)$",
        r"^(?:화|회|편|장|권)[-_]?\d+(?:\.\d+)?$",
    ]

    return any(re.match(p, s, flags=re.I) for p in patterns)


def infer___removed_link___from_url(url):
    url = normalize_blacktoon_url(str(url or "").strip(), {})

    if not url:
        return ""

    episode_match = re.match(
        r"^(https?://(?:www\.)?blacktoon\d+\.com)/webtoons/(\d+)/\d+\.html(?:[?#].*)?$",
        url,
        flags=re.I,
    )
    if episode_match:
        return f"{episode_match.group(1)}/webtoon/{episode_match.group(2)}.html"

    series_match = re.match(
        r"^(https?://(?:www\.)?blacktoon\d+\.com/webtoon/\d+\.html)(?:[?#].*)?$",
        url,
        flags=re.I,
    )
    if series_match:
        return series_match.group(1)

    parsed = urlparse(url)

    if not parsed.scheme or not parsed.netloc:
        return ""

    parts = _decoded_path_parts(parsed)
    if not parts:
        return f"{parsed.scheme}://{parsed.netloc}/"

    # ani.ohli24.com 계열: /e/작품명 1화 -> /c/작품명
    # e = episode, c = content/series
    if len(parts) >= 2 and parts[0].lower() in ["e", "episode", "episodes"]:
        title_part = _remove_episode_suffix_from_title(parts[1]) or parts[1]
        new_path = _encode_path_parts(["c", title_part])
        return f"{parsed.scheme}://{parsed.netloc}{new_path}"

    if len(parts) >= 2 and parts[0].lower() in ["c", "content", "contents"]:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    cat_idx, _ = _category_index(parts) if "_category_index" in globals() else (None, "")

    if len(parts) >= 2 and _segment_looks_episode(parts[-1]):
        new_path = _encode_path_parts(parts[:-1])
        return f"{parsed.scheme}://{parsed.netloc}{new_path}"

    if len(parts) >= 3 and parts[-2].lower() in ["view", "read", "watch", "play", "episode", "chapter", "ep", "ch"]:
        if _segment_looks_episode(parts[-1]):
            new_path = _encode_path_parts(parts[:-2])
            return f"{parsed.scheme}://{parsed.netloc}{new_path}"

    if cat_idx is not None and len(parts) >= cat_idx + 2:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"



# =========================
# 사이트 OFF 필터 보강
# =========================

def _host_from_url_for_site_filter(url):
    try:
        fixed_url = _canonicalize_repeated_fixed_host_url(str(url or "")) if "_canonicalize_repeated_fixed_host_url" in globals() else str(url or "")
        parsed = urlparse(fixed_url)
        return re.sub(r"^www\.", "", parsed.netloc.lower()).split(":")[0]
    except Exception:
        return ""


def _site_key_from_url_any(url):
    """
    사이트가 OFF여도 URL의 소속 사이트를 판별한다.
    기존 get_site_key_from_url은 OFF 사이트를 무시하므로 현재 목록 필터용으로 별도 사용.
    """
    host = _host_from_url_for_site_filter(url)
    if not host:
        return ""

    for site_key, spec in (SITE_SPECS or {}).items():
        host_re = str(spec.get("host_re", "") or "")
        if not host_re:
            continue
        try:
            if re.fullmatch(host_re, host, flags=re.I):
                return site_key
        except re.error:
            continue

    return ""


def _row_site_key_any(row):
    if not isinstance(row, dict):
        return ""

    for key in ["site"]:
        value = str(row.get(key, "") or "").strip()
        if value and value in (SITE_SPECS or {}):
            return value

    for key in ["url", "__removed_link__"]:
        site_key = _site_key_from_url_any(row.get(key, ""))
        if site_key:
            return site_key

    try:
        site_key = get_site_key_from_title(row.get("title", ""))
        if site_key:
            return site_key
    except Exception:
        pass

    return ""


def _site_enabled_for_row(row, db=None):
    if db is None:
        db = load_db()
    db = normalize_settings(db)
    settings = db.get("settings", {})
    sites = settings.get("sites", {})
    site_key = _row_site_key_any(row)

    if not site_key:
        return True

    return sites.get(site_key, {}).get("enabled", True) is not False


def _filter_disabled_site_rows(rows, db=None):
    if db is None:
        db = load_db()
    db = normalize_settings(db)
    return [row for row in rows if _site_enabled_for_row(row, db)]


def get_rows_by_status(status):
    db = ensure_db()
    rows = []

    for item in db["items"].values():
        item = normalize_item(item)

        if item.get("status") == status:
            rows.append(item_to_row(item))

    if status == "active":
        rows = _filter_disabled_site_rows(rows, db)
        rows = apply_site_duplicate_filter(rows, db)

    return rows




def write_server_runtime_files(port):
    """종료 스크립트가 백그라운드 서버를 확실히 찾을 수 있게 PID/포트 파일 저장."""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        PID_TXT.write_text(str(os.getpid()), encoding="utf-8")
        PORT_TXT.write_text(str(port), encoding="utf-8")
    except Exception as e:
        append_log(f"서버 PID/포트 파일 저장 실패: {e}")


def cleanup_server_runtime_files():
    for path in [PID_TXT, PORT_TXT]:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

AUTO_BACKUP_INTERVAL_SECONDS = 60 * 60


def run_backup_script_for_auto_update(reason="1시간 자동 업데이트"):
    if not BACKUP_SCRIPT.exists():
        append_log(f"방문기록 자동 업데이트 실패: 백업 스크립트 없음 ({BACKUP_SCRIPT})")
        return

    try:
        append_log(f"방문기록 자동 업데이트 시작: {reason}")
        result = subprocess.run(
            [sys.executable, str(BACKUP_SCRIPT)],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            append_log("방문기록 자동 업데이트 완료")
        else:
            msg = (result.stderr or result.stdout or "").strip().splitlines()
            tail = " / ".join(msg[-3:]) if msg else f"exit={result.returncode}"
            append_log(f"방문기록 자동 업데이트 실패: {tail}")
    except Exception as e:
        append_log(f"방문기록 자동 업데이트 예외: {e}")


def start_auto_update_worker():
    def worker():
        while True:
            time.sleep(AUTO_BACKUP_INTERVAL_SECONDS)
            run_backup_script_for_auto_update()

    thread = threading.Thread(target=worker, name="LocalReadLogAutoUpdate", daemon=True)
    thread.start()
    append_log("1시간 자동 업데이트 활성화")

def create_server_with_fallback():
    """
    8787 포트가 Windows 예약/차단/충돌로 못 열릴 때 다른 포트로 자동 대체.
    WinError 10013은 보통 포트 예약 또는 보안 프로그램 차단 쪽이다.
    """
    errors = []

    for port in PORT_CANDIDATES:
        try:
            server = ThreadingHTTPServer((HOST, port), Handler)
            return server, port
        except OSError as e:
            errors.append(f"{port}: {e}")
            append_log(f"포트 {port} 열기 실패: {e}")

    raise OSError("사용 가능한 포트 없음: " + " / ".join(errors))


def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    db = ensure_db()

    append_log("관리 서버 시작")

    print("LocalReadLog 서버 실행 중")
    print(f"백업 폴더: {BACKUP_DIR}")
    print(f"DB 파일: {DB_JSON}")
    print(f"백업 스크립트: {BACKUP_SCRIPT}")
    print(f"등록 작품 수: {len(db.get('items', {}))}개")
    server, actual_port = create_server_with_fallback()
    globals()["CURRENT_SERVER_PORT"] = actual_port

    print(f"PC에서 열기: http://127.0.0.1:{actual_port}")
    print(f"모바일에서 열기: http://PC_IP:{actual_port}")
    if actual_port != PORT:
        print(f"주의: {PORT} 포트를 못 열어서 {actual_port} 포트로 대체 실행됨")
    print("종료하려면 Ctrl + C")
    print()

    append_log(f"관리 서버 포트: {actual_port}")
    write_server_runtime_files(actual_port)
    start_auto_update_worker()
    try:
        server.serve_forever()
    finally:
        cleanup_server_runtime_files()



# =========================
# 제거된 링크/__removed_link__ 최종 비활성화
# =========================
def infer___removed_link___from_url(url):
    return ""


def get___removed_link__(url):
    return ""


def _drop___removed_link___fields(obj):
    if isinstance(obj, dict):
        obj.pop("__removed_link__", None)
        for value in list(obj.values()):
            _drop___removed_link___fields(value)
    elif isinstance(obj, list):
        for value in obj:
            _drop___removed_link___fields(value)
    return obj

try:
    _prev_normalize_item_no_series
except NameError:
    _prev_normalize_item_no_series = normalize_item
    def normalize_item(item):
        item = _prev_normalize_item_no_series(item)
        return _drop___removed_link___fields(item)

try:
    _prev_item_to_row_no_series
except NameError:
    _prev_item_to_row_no_series = item_to_row
    def item_to_row(item):
        row = _prev_item_to_row_no_series(item)
        row.pop("__removed_link__", None)
        return row

try:
    _prev_save_db_no_series
except NameError:
    _prev_save_db_no_series = save_db
    def save_db(db):
        _drop___removed_link___fields(db)
        result = _prev_save_db_no_series(db)
        try:
            if DB_JSON.exists():
                with DB_JSON.open("r", encoding="utf-8") as f:
                    saved = json.load(f)
                _drop___removed_link___fields(saved)
                tmp = DB_JSON.with_suffix(".json.tmp")
                with tmp.open("w", encoding="utf-8") as f:
                    json.dump(saved, f, ensure_ascii=False, indent=2)
                tmp.replace(DB_JSON)
        except Exception as e:
            append_log(f"__removed_link__ 제거 후 DB 재저장 실패: {e}")
        return result


# =========================
# 레거시 작품주소 필드 제거
# =========================
_LEGACY_LINK_FIELD = "__removed_link__"

def _drop_legacy_link_fields(obj):
    if isinstance(obj, dict):
        obj.pop(_LEGACY_LINK_FIELD, None)
        for value in list(obj.values()):
            _drop_legacy_link_fields(value)
    elif isinstance(obj, list):
        for value in obj:
            _drop_legacy_link_fields(value)
    return obj

try:
    _prev_get_episode_history_list_clean
except NameError:
    _prev_get_episode_history_list_clean = get_episode_history_list
    def get_episode_history_list(item):
        return _drop_legacy_link_fields(_prev_get_episode_history_list_clean(item))

try:
    _prev_item_to_row_clean
except NameError:
    _prev_item_to_row_clean = item_to_row
    def item_to_row(item):
        return _drop_legacy_link_fields(_prev_item_to_row_clean(item))

try:
    _prev_normalize_item_clean
except NameError:
    _prev_normalize_item_clean = normalize_item
    def normalize_item(item):
        return _drop_legacy_link_fields(_prev_normalize_item_clean(item))

try:
    _prev_save_db_clean
except NameError:
    _prev_save_db_clean = save_db
    def save_db(db):
        _drop_legacy_link_fields(db)
        result = _prev_save_db_clean(db)
        try:
            if DB_JSON.exists():
                with DB_JSON.open("r", encoding="utf-8") as f:
                    saved = json.load(f)
                _drop_legacy_link_fields(saved)
                tmp = DB_JSON.with_suffix(".json.tmp")
                with tmp.open("w", encoding="utf-8") as f:
                    json.dump(saved, f, ensure_ascii=False, indent=2)
                tmp.replace(DB_JSON)
        except Exception as e:
            append_log(f"레거시 작품주소 필드 제거 후 DB 재저장 실패: {e}")
        return result


# =========================
# 접속 비밀번호 보호
# =========================
import hashlib
import secrets

AUTH_COOKIE_NAME = "localreadlog_auth"
AUTH_COOKIE_MAX_AGE = 60 * 60 * 24 * 365 * 10


def _truthy(value):
    return str(value or "").strip().lower() in ["1", "true", "on", "yes", "y", "사용", "켜기"]


def _get_auth_settings():
    db = ensure_db()
    db = normalize_settings(db)
    settings = db.setdefault("settings", {})
    settings.setdefault("password_enabled", False)
    settings.setdefault("password_salt", "")
    settings.setdefault("password_hash", "")
    settings.setdefault("auth_secret", "")
    if not settings.get("auth_secret"):
        settings["auth_secret"] = secrets.token_hex(32)
        save_db(db)
    return db, settings


def _hash_password(password, salt):
    raw = (str(salt) + "\n" + str(password)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _auth_token(settings):
    raw = (str(settings.get("auth_secret", "")) + "\n" + str(settings.get("password_hash", ""))).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_cookie_header(header):
    result = {}
    for part in str(header or "").split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def _password_required():
    try:
        _, settings = _get_auth_settings()
        return bool(settings.get("password_enabled")) and bool(settings.get("password_hash"))
    except Exception:
        return False


def _is_authenticated(handler):
    if not _password_required():
        return True
    _, settings = _get_auth_settings()
    cookies = _parse_cookie_header(handler.headers.get("Cookie", ""))
    return cookies.get(AUTH_COOKIE_NAME) == _auth_token(settings)


def _send_json_with_cookie(handler, payload, status=200, cookie_header=None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    if cookie_header:
        handler.send_header("Set-Cookie", cookie_header)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _login_cookie(settings):
    return f"{AUTH_COOKIE_NAME}={_auth_token(settings)}; Max-Age={AUTH_COOKIE_MAX_AGE}; Path=/; SameSite=Lax"


def _clear_login_cookie():
    return f"{AUTH_COOKIE_NAME}=; Max-Age=0; Path=/; SameSite=Lax"


def _render_login_page():
    return """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LocalReadLog 로그인</title>
<style>
body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f6f7f9;margin:0;padding:24px;color:#111827}
.box{max-width:420px;margin:12vh auto;background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:22px;box-shadow:0 10px 30px rgba(0,0,0,.06)}
h1{font-size:24px;margin:0 0 8px}.small{color:#6b7280;font-size:14px;line-height:1.5}input{width:100%;box-sizing:border-box;font-size:18px;padding:13px;border:1px solid #d1d5db;border-radius:12px;margin:16px 0 10px}button{width:100%;font-size:17px;font-weight:700;padding:13px;border:0;border-radius:12px;background:#111827;color:#fff}.err{color:#dc2626;font-size:14px;min-height:20px;margin-top:10px}
</style>
</head>
<body>
<div class="box">
<h1>LocalReadLog</h1>
<div class="small">접속 비밀번호를 입력하세요. 한 번 입력하면 이 브라우저에는 계속 저장됩니다.</div>
<form id="loginForm">
<input id="password" type="password" autocomplete="current-password" placeholder="비밀번호" autofocus>
<button type="submit">접속</button>
<div class="err" id="err"></div>
</form>
</div>
<script>
document.getElementById('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = new URLSearchParams({password: document.getElementById('password').value});
  const res = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'}, body});
  if (res.ok) location.reload();
  else document.getElementById('err').textContent = '비밀번호가 맞지 않음';
});
</script>
</body>
</html>"""


def _read_urlencoded_form(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    body = handler.rfile.read(length).decode("utf-8", errors="replace")
    form = parse_qs(body)
    return lambda name: (form.get(name) or [""])[0]


def _handle_login(handler):
    val = _read_urlencoded_form(handler)
    password = val("password")
    _, settings = _get_auth_settings()
    if not _password_required():
        _send_json_with_cookie(handler, {"ok": True, "message": "비밀번호 보호 OFF"}, cookie_header=_login_cookie(settings))
        return
    if _hash_password(password, settings.get("password_salt", "")) == settings.get("password_hash", ""):
        _send_json_with_cookie(handler, {"ok": True, "message": "로그인 완료"}, cookie_header=_login_cookie(settings))
        return
    _send_json_with_cookie(handler, {"ok": False, "message": "비밀번호가 맞지 않음"}, status=401)


def _handle_set_password_settings(handler):
    val = _read_urlencoded_form(handler)
    enabled = _truthy(val("enabled"))
    password = val("password")

    db, settings = _get_auth_settings()

    if enabled:
        if password.strip():
            salt = secrets.token_hex(16)
            settings["password_salt"] = salt
            settings["password_hash"] = _hash_password(password, salt)
        elif not settings.get("password_hash"):
            _send_json_with_cookie(handler, {"ok": False, "message": "비밀번호를 입력해야 ON으로 바꿀 수 있음"}, status=400)
            return
        settings["password_enabled"] = True
        save_db(db)
        _send_json_with_cookie(handler, {"ok": True, "message": "접속 비밀번호 ON"}, cookie_header=_login_cookie(settings))
        return

    settings["password_enabled"] = False
    save_db(db)
    _send_json_with_cookie(handler, {"ok": True, "message": "접속 비밀번호 OFF"}, cookie_header=_clear_login_cookie())


try:
    _prev_normalize_settings_auth
except NameError:
    _prev_normalize_settings_auth = normalize_settings
    def normalize_settings(db):
        db = _prev_normalize_settings_auth(db)
        settings = db.setdefault("settings", {})
        settings.setdefault("password_enabled", False)
        settings.setdefault("password_salt", "")
        settings.setdefault("password_hash", "")
        settings.setdefault("auth_secret", "")
        return db

try:
    _prev_get_settings_payload_auth
except NameError:
    _prev_get_settings_payload_auth = get_settings_payload
    def get_settings_payload():
        payload = _prev_get_settings_payload_auth()
        db = ensure_db()
        db = normalize_settings(db)
        settings = db.get("settings", {})
        payload["password_enabled"] = bool(settings.get("password_enabled")) and bool(settings.get("password_hash"))
        return payload

try:
    _prev_handler_get_auth
except NameError:
    _prev_handler_get_auth = Handler.do_GET
    _prev_handler_post_auth = Handler.do_POST

    def _auth_do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/auth_status":
            json_response(self, {"ok": True, "password_enabled": _password_required(), "authenticated": _is_authenticated(self)})
            return
        if not _is_authenticated(self):
            if path.startswith("/api/"):
                json_response(self, {"ok": False, "auth_required": True, "message": "비밀번호 필요"}, status=401)
            else:
                text_response(self, _render_login_page(), status=401)
            return
        return _prev_handler_get_auth(self)

    def _auth_do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/login":
            _handle_login(self)
            return
        if not _is_authenticated(self):
            json_response(self, {"ok": False, "auth_required": True, "message": "비밀번호 필요"}, status=401)
            return
        if path == "/api/set_password_settings":
            _handle_set_password_settings(self)
            return
        return _prev_handler_post_auth(self)

    Handler.do_GET = _auth_do_GET
    Handler.do_POST = _auth_do_POST



# =========================
# v15 공개판 안정화: 진단/모바일 주소/자동 업데이트 설정/DB 자동 백업
# =========================
import socket
import shutil
from datetime import timedelta

LOCALREADLOG_VERSION = "v0.1.14"
_DB_BACKUP_MAX_FILES = 20
_AUTO_UPDATE_STATE = {
    "enabled": True,
    "interval_minutes": 60,
    "last_start": "",
    "last_finish": "",
    "last_ok": None,
    "last_message": "",
    "next_run": "",
}
_AUTO_UPDATE_LOCK = threading.Lock()


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _bool_setting(value, default=False):
    if isinstance(value, str):
        t = value.strip().lower()
        if t in ["1", "true", "on", "yes", "y", "사용", "켜기"]:
            return True
        if t in ["0", "false", "off", "no", "n", "미사용", "끄기"]:
            return False
    if value is None:
        return default
    return bool(value)


def _dt_now():
    return datetime.now()


def _dt_text(dt):
    try:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _get_auto_settings_from_db():
    db = ensure_db()
    db = normalize_settings(db)
    settings = db.setdefault("settings", {})
    enabled = _bool_setting(settings.get("auto_update_enabled", True), True)
    minutes = _safe_int(settings.get("auto_update_interval_minutes", 60), 60)
    if minutes not in [30, 60, 180, 360]:
        minutes = 60
    return db, settings, enabled, minutes


def get_local_ip_addresses():
    addresses = []
    seen = set()

    def add(ip):
        ip = str(ip or "").strip()
        if not ip or ip.startswith("127.") or ip == "0.0.0.0" or ip in seen:
            return
        seen.add(ip)
        addresses.append(ip)

    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, family=socket.AF_INET):
            add(info[4][0])
    except Exception:
        pass

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.2)
        sock.connect(("8.8.8.8", 80))
        add(sock.getsockname()[0])
        sock.close()
    except Exception:
        pass

    return addresses


def _path_status(path, kind="file"):
    p = Path(path)
    if kind == "dir":
        return p.exists() and p.is_dir()
    return p.exists() and p.is_file()


def _browser_definitions_for_diagnostics():
    if "BROWSERS" in globals():
        return BROWSERS
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return [
        {"key": "whale", "name": "Whale", "type": "chromium", "user_data_dir": local / "Naver" / "Naver Whale" / "User Data"},
        {"key": "edge", "name": "Edge", "type": "chromium", "user_data_dir": local / "Microsoft" / "Edge" / "User Data"},
        {"key": "chrome", "name": "Chrome", "type": "chromium", "user_data_dir": local / "Google" / "Chrome" / "User Data"},
        {"key": "firefox", "name": "Firefox", "type": "firefox", "profile_dir": roaming / "Mozilla" / "Firefox" / "Profiles"},
    ]


def get_diagnostics_payload():
    browser_checks = []
    for browser in _browser_definitions_for_diagnostics():
        exists = False
        path_text = ""
        try:
            if browser.get("type") == "chromium":
                p = browser.get("user_data_dir")
                path_text = str(p)
                exists = bool(p and Path(p).exists())
            elif browser.get("type") == "firefox":
                p = browser.get("profile_dir")
                path_text = str(p)
                exists = bool(p and Path(p).exists())
        except Exception:
            exists = False
        browser_checks.append({
            "key": browser.get("key", ""),
            "name": browser.get("name", browser.get("key", "")),
            "path": path_text,
            "ok": exists,
        })

    db = ensure_db()
    items = db.get("items", {}) if isinstance(db, dict) else {}
    ip_list = get_local_ip_addresses()
    port = globals().get("CURRENT_SERVER_PORT", PORT)

    checks = [
        {"name": "Python", "ok": sys.version_info >= (3, 8), "detail": sys.version.split()[0]},
        {"name": "data 폴더", "ok": BACKUP_DIR.exists(), "detail": str(BACKUP_DIR)},
        {"name": "DB 파일", "ok": DB_JSON.exists(), "detail": str(DB_JSON)},
        {"name": "백업 스크립트", "ok": BACKUP_SCRIPT.exists(), "detail": str(BACKUP_SCRIPT)},
        {"name": "서버 포트", "ok": True, "detail": str(port)},
        {"name": "모바일 주소", "ok": bool(ip_list), "detail": ", ".join(f"http://{ip}:{port}" for ip in ip_list) or "PC IP를 찾지 못함"},
    ]

    return {
        "version": LOCALREADLOG_VERSION,
        "checks": checks,
        "browsers": browser_checks,
        "item_count": len(items) if isinstance(items, dict) else 0,
    }


def _latest_db_backup_info():
    backups_dir = BACKUP_DIR / "backups"
    if not backups_dir.exists():
        return {"count": 0, "latest": ""}
    files = sorted(backups_dir.glob("localreadlog_db_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {"count": len(files), "latest": files[0].name if files else ""}


def get_status_payload():
    try:
        db, settings, enabled, minutes = _get_auto_settings_from_db()
    except Exception:
        db, settings, enabled, minutes = ({}, {}, True, 60)

    port = globals().get("CURRENT_SERVER_PORT", PORT)
    local_urls = [f"http://127.0.0.1:{port}"]
    mobile_urls = [f"http://{ip}:{port}" for ip in get_local_ip_addresses()]
    db_backup = _latest_db_backup_info()

    state = dict(_AUTO_UPDATE_STATE)
    state["enabled"] = enabled
    state["interval_minutes"] = minutes
    if not state.get("next_run") and enabled:
        state["next_run"] = settings.get("next_auto_update_at", "")

    return {
        "version": LOCALREADLOG_VERSION,
        "started_at": globals().get("SERVER_STARTED_AT", ""),
        "port": port,
        "pc_urls": local_urls,
        "mobile_urls": mobile_urls,
        "backup_dir": str(BACKUP_DIR),
        "db_path": str(DB_JSON),
        "log_path": str(LOG_TXT),
        "db_backup": db_backup,
        "auto_update": state,
        "last_update_at": settings.get("last_update_at", ""),
        "last_update_ok": settings.get("last_update_ok", None),
        "last_update_message": settings.get("last_update_message", ""),
        "diagnostics": get_diagnostics_payload(),
        "password_enabled": bool(settings.get("password_enabled")) and bool(settings.get("password_hash")),
    }


def _record_update_result(ok, message="", source="manual"):
    try:
        db = ensure_db()
        db = normalize_settings(db)
        settings = db.setdefault("settings", {})
        settings["last_update_at"] = now_text()
        settings["last_update_ok"] = bool(ok)
        settings["last_update_message"] = str(message or source)[:500]
        save_db(db)
    except Exception as e:
        append_log(f"업데이트 상태 저장 실패: {e}")


def _make_db_backup_snapshot(reason="save"):
    try:
        if not DB_JSON.exists():
            return
        backups_dir = BACKUP_DIR / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = backups_dir / f"localreadlog_db_{stamp}.json"
        if not target.exists():
            shutil.copy2(DB_JSON, target)
        files = sorted(backups_dir.glob("localreadlog_db_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[_DB_BACKUP_MAX_FILES:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception as e:
        try:
            append_log(f"DB 자동 백업 실패: {e}")
        except Exception:
            pass


try:
    _prev_normalize_settings_v15
except NameError:
    _prev_normalize_settings_v15 = normalize_settings
    def normalize_settings(db):
        db = _prev_normalize_settings_v15(db)
        settings = db.setdefault("settings", {})
        settings["auto_update_enabled"] = _bool_setting(settings.get("auto_update_enabled", True), True)
        minutes = _safe_int(settings.get("auto_update_interval_minutes", 60), 60)
        if minutes not in [30, 60, 180, 360]:
            minutes = 60
        settings["auto_update_interval_minutes"] = minutes
        settings.setdefault("last_update_at", "")
        settings.setdefault("last_update_ok", None)
        settings.setdefault("last_update_message", "")
        settings.setdefault("next_auto_update_at", "")
        return db

try:
    _prev_save_db_v15
except NameError:
    _prev_save_db_v15 = save_db
    def save_db(db):
        _make_db_backup_snapshot("before_save")
        return _prev_save_db_v15(db)

try:
    _prev_get_settings_payload_v15
except NameError:
    _prev_get_settings_payload_v15 = get_settings_payload
    def get_settings_payload():
        payload = _prev_get_settings_payload_v15()
        db, settings, enabled, minutes = _get_auto_settings_from_db()
        payload["auto_update_enabled"] = enabled
        payload["auto_update_interval_minutes"] = minutes
        payload["status"] = get_status_payload()
        return payload

try:
    _prev_run_backup_script_v15
except NameError:
    _prev_run_backup_script_v15 = run_backup_script
    def run_backup_script():
        ok, output = _prev_run_backup_script_v15()
        tail = ""
        try:
            lines = str(output or "").strip().splitlines()
            tail = " / ".join(lines[-2:]) if lines else "수동 업데이트"
        except Exception:
            tail = "수동 업데이트"
        _record_update_result(ok, tail, "manual")
        return ok, output


def set_auto_update_settings(enabled_text, interval_text):
    db = ensure_db()
    db = normalize_settings(db)
    settings = db.setdefault("settings", {})
    enabled = _truthy(enabled_text) if str(enabled_text).strip() else _bool_setting(settings.get("auto_update_enabled", True), True)
    minutes = _safe_int(interval_text, settings.get("auto_update_interval_minutes", 60))
    if minutes not in [30, 60, 180, 360]:
        return False, "업데이트 간격은 30/60/180/360분만 가능"
    settings["auto_update_enabled"] = enabled
    settings["auto_update_interval_minutes"] = minutes
    if enabled:
        settings["next_auto_update_at"] = _dt_text(_dt_now() + timedelta(minutes=minutes)) if 'timedelta' in globals() else ""
    else:
        settings["next_auto_update_at"] = ""
    save_db(db)
    append_log(f"자동 업데이트 설정: {'ON' if enabled else 'OFF'} / {minutes}분")
    return True, f"자동 업데이트 {'ON' if enabled else 'OFF'} / {minutes}분"


def run_backup_script_for_auto_update(reason="자동 업데이트"):
    db, settings, enabled, minutes = _get_auto_settings_from_db()
    if not enabled:
        _AUTO_UPDATE_STATE.update({"enabled": False, "interval_minutes": minutes, "next_run": ""})
        return

    if not BACKUP_SCRIPT.exists():
        msg = f"백업 스크립트 없음 ({BACKUP_SCRIPT})"
        append_log(f"방문기록 자동 업데이트 실패: {msg}")
        _AUTO_UPDATE_STATE.update({"last_finish": now_text(), "last_ok": False, "last_message": msg})
        _record_update_result(False, msg, "auto")
        return

    if not _AUTO_UPDATE_LOCK.acquire(blocking=False):
        append_log("방문기록 자동 업데이트 건너뜀: 이전 업데이트 진행 중")
        return

    try:
        _AUTO_UPDATE_STATE.update({"enabled": True, "interval_minutes": minutes, "last_start": now_text(), "last_message": reason})
        append_log(f"방문기록 자동 업데이트 시작: {reason}")
        result = subprocess.run(
            [sys.executable, str(BACKUP_SCRIPT)],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            msg = "방문기록 자동 업데이트 완료"
            append_log(msg)
            ok = True
        else:
            lines = (result.stderr or result.stdout or "").strip().splitlines()
            tail = " / ".join(lines[-3:]) if lines else f"exit={result.returncode}"
            msg = f"방문기록 자동 업데이트 실패: {tail}"
            append_log(msg)
            ok = False
        _AUTO_UPDATE_STATE.update({"last_finish": now_text(), "last_ok": ok, "last_message": msg})
        _record_update_result(ok, msg, "auto")
    except Exception as e:
        msg = f"방문기록 자동 업데이트 예외: {e}"
        append_log(msg)
        _AUTO_UPDATE_STATE.update({"last_finish": now_text(), "last_ok": False, "last_message": msg})
        _record_update_result(False, msg, "auto")
    finally:
        _AUTO_UPDATE_LOCK.release()


def start_auto_update_worker():
    def worker():
        while True:
            try:
                db, settings, enabled, minutes = _get_auto_settings_from_db()
                if not enabled:
                    _AUTO_UPDATE_STATE.update({"enabled": False, "interval_minutes": minutes, "next_run": ""})
                    time.sleep(60)
                    continue
                next_dt = _dt_now() + timedelta(minutes=minutes)
                next_text = _dt_text(next_dt)
                _AUTO_UPDATE_STATE.update({"enabled": True, "interval_minutes": minutes, "next_run": next_text})
                try:
                    settings["next_auto_update_at"] = next_text
                    _prev_save_db_v15(db)
                except Exception:
                    pass
                time.sleep(max(60, minutes * 60))
                run_backup_script_for_auto_update(f"{minutes}분 자동 업데이트")
            except Exception as e:
                append_log(f"자동 업데이트 워커 오류: {e}")
                time.sleep(60)

    thread = threading.Thread(target=worker, name="LocalReadLogAutoUpdate", daemon=True)
    thread.start()
    try:
        _, _, enabled, minutes = _get_auto_settings_from_db()
        append_log(f"자동 업데이트 {'활성화' if enabled else '비활성화'} / {minutes}분")
    except Exception:
        append_log("자동 업데이트 워커 시작")

try:
    _prev_handler_get_v15
except NameError:
    _prev_handler_get_v15 = Handler.do_GET
    _prev_handler_post_v15 = Handler.do_POST

    def _v15_do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            if '_is_authenticated' in globals() and not _is_authenticated(self):
                json_response(self, {"ok": False, "auth_required": True, "message": "비밀번호 필요"}, status=401)
                return
            json_response(self, get_status_payload())
            return
        if path == "/api/diagnostics":
            if '_is_authenticated' in globals() and not _is_authenticated(self):
                json_response(self, {"ok": False, "auth_required": True, "message": "비밀번호 필요"}, status=401)
                return
            json_response(self, get_diagnostics_payload())
            return
        return _prev_handler_get_v15(self)

    def _v15_do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/set_auto_update":
            if '_is_authenticated' in globals() and not _is_authenticated(self):
                json_response(self, {"ok": False, "auth_required": True, "message": "비밀번호 필요"}, status=401)
                return
            val = _read_urlencoded_form(self) if '_read_urlencoded_form' in globals() else None
            if val is None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length).decode("utf-8", errors="replace")
                form = parse_qs(body)
                val = lambda name: (form.get(name) or [""])[0]
            ok, msg = set_auto_update_settings(val("enabled"), val("interval_minutes"))
            json_response(self, {"ok": ok, "message": msg, "status": get_status_payload()}, status=200 if ok else 400)
            return
        return _prev_handler_post_v15(self)

    Handler.do_GET = _v15_do_GET
    Handler.do_POST = _v15_do_POST

# INDEX_HTML 보강: 설정 탭에 상태/진단/모바일/자동 업데이트/최근 로그 박스 추가
_V15_JS = r'''

function yesNo(v) { return v ? "OK" : "확인 필요"; }
function statusBadge(ok) { return `<span class="${ok ? 'diag-ok' : 'diag-warn'}">${ok ? 'OK' : '확인 필요'}</span>`; }
function joinLines(arr) { return Array.isArray(arr) && arr.length ? arr.map(x => escapeHtml(x)).join("<br>") : "-"; }

async function refreshStatusOnly() {
    try {
        const data = await api("/api/status");
        settings.status = data;
        if (mode === "settings") renderSettingsPage();
    } catch (e) {}
}

async function setAutoUpdate(enabled, minutes) {
    const data = await api("/api/set_auto_update", {enabled: enabled ? "1" : "0", interval_minutes: String(minutes)});
    showToast(data.message || "자동 업데이트 설정 완료");
    await loadSettings();
    renderSettingsPage();
}

function renderStatusBoxes() {
    const st = settings.status || {};
    const au = st.auto_update || {};
    const diag = st.diagnostics || {};
    const checks = diag.checks || [];
    const browsers = diag.browsers || [];
    const recentLogs = (settings.recent_logs || []).slice(-8).reverse();
    const intervals = [30, 60, 180, 360];
    const currentInterval = Number(settings.auto_update_interval_minutes || au.interval_minutes || 60);
    const autoEnabled = !!(settings.auto_update_enabled ?? au.enabled);

    const checkRows = checks.map(c => `
        <div class="setting-row">
            <div><b>${escapeHtml(c.name)}</b><div class="small">${escapeHtml(c.detail || "")}</div></div>
            <div>${statusBadge(!!c.ok)}</div>
            <span></span>
        </div>
    `).join("");

    const browserRows2 = browsers.map(b => `
        <div class="setting-row">
            <div><b>${escapeHtml(b.name)}</b><div class="small">${escapeHtml(b.path || "")}</div></div>
            <div>${statusBadge(!!b.ok)}</div>
            <span></span>
        </div>
    `).join("");

    return `
        <div class="settings-box">
            <h2>처음 실행 진단</h2>
            <div class="small">문제가 생기면 여기부터 확인하면 됨.</div>
            ${checkRows || '<div class="empty">진단 정보 없음</div>'}
            <div style="height:8px"></div>
            <h3>브라우저 기록 위치</h3>
            ${browserRows2 || '<div class="empty">브라우저 정보 없음</div>'}
        </div>

        <div class="settings-box">
            <h2>접속 주소</h2>
            <div class="small">PC에서 보기</div>
            <div style="word-break:break-all"><b>${joinLines(st.pc_urls)}</b></div>
            <div style="height:8px"></div>
            <div class="small">모바일에서 보기. 휴대폰과 PC가 같은 Wi-Fi여야 함.</div>
            <div style="word-break:break-all"><b>${joinLines(st.mobile_urls)}</b></div>
        </div>

        <div class="settings-box">
            <h2>자동 업데이트</h2>
            <div class="small">백그라운드 서버가 켜져 있는 동안 방문기록을 자동 스캔함.</div>
            <div class="setting-row">
                <div>
                    <b>현재 상태: ${autoEnabled ? "ON" : "OFF"}</b>
                    <div class="small">마지막: ${escapeHtml(st.last_update_at || au.last_finish || "-")} · 다음: ${escapeHtml(au.next_run || "-")}</div>
                </div>
                <button class="${autoEnabled ? "" : "off"}" onclick="setAutoUpdate(${!autoEnabled}, ${currentInterval})">${autoEnabled ? "ON" : "OFF"}</button>
                <span></span>
            </div>
            <div class="buttons">
                ${intervals.map(m => `<button class="${currentInterval === m ? '' : 'off'}" onclick="setAutoUpdate(true, ${m})">${m === 60 ? '1시간' : m === 180 ? '3시간' : m === 360 ? '6시간' : '30분'}</button>`).join("")}
            </div>
        </div>

        <div class="settings-box">
            <h2>실행 상태</h2>
            <div class="small">버전: ${escapeHtml(st.version || "-")}</div>
            <div class="small">서버 시작: ${escapeHtml(st.started_at || "-")}</div>
            <div class="small">포트: ${escapeHtml(st.port || "-")}</div>
            <div class="small">DB 자동 백업: ${escapeHtml(String(st.db_backup?.count ?? 0))}개 보관 · 최근 ${escapeHtml(st.db_backup?.latest || "-")}</div>
            <div style="word-break:break-all" class="small">DB: ${escapeHtml(st.db_path || "")}</div>
        </div>

        <div class="settings-box">
            <h2>최근 로그</h2>
            <div class="small">최근 로그는 문제 원인 확인용임.</div>
            <div class="logbox">${escapeHtml(recentLogs.join("\n") || "로그 없음")}</div>
            <button onclick="setMode('log')">전체 로그 보기</button>
        </div>
    `;
}
'''

try:
    INDEX_HTML = INDEX_HTML.replace("</style>", "\n.diag-ok{display:inline-block;padding:4px 8px;border-radius:999px;background:#dcfce7;color:#166534;font-weight:700;font-size:12px}.diag-warn{display:inline-block;padding:4px 8px;border-radius:999px;background:#fee2e2;color:#991b1b;font-weight:700;font-size:12px}.settings-box h3{font-size:16px;margin:10px 0 6px}\n</style>")
    INDEX_HTML = INDEX_HTML.replace("function renderStatusBoxes()", "function renderStatusBoxesOld()") if "function renderStatusBoxes()" in INDEX_HTML else INDEX_HTML
    INDEX_HTML = INDEX_HTML.replace("function renderSettingsPage() {", _V15_JS + "\nfunction renderSettingsPage() {")
    INDEX_HTML = INDEX_HTML.replace("list.innerHTML = `\n        <div class=\"settings-box\">", "list.innerHTML = `\n        ${renderStatusBoxes()}\n\n        <div class=\"settings-box\">")
    INDEX_HTML = INDEX_HTML.replace("<div class=\"small\">모바일에서 접속할 때도 같은 비밀번호를 사용함. 한 번 입력하면 브라우저에 저장됨.</div>", "<div class=\"small\">모바일/다른 기기에서 접속할 때는 비밀번호 사용을 권장함. 공유기 외부 포트포워딩은 권장하지 않음. 한 번 입력하면 브라우저에 저장됨.</div>")
    INDEX_HTML = INDEX_HTML.replace("async function loadSettings() {\n    const data = await api(\"/api/settings\");\n    settings = data || settings;\n    renderSettings();\n}", "async function loadSettings() {\n    const data = await api(\"/api/settings\");\n    settings = data || settings;\n    try {\n        const logs = await api(\"/api/logs\");\n        settings.recent_logs = logs.lines || [];\n    } catch (e) {\n        settings.recent_logs = [];\n    }\n    renderSettings();\n}")
except Exception as e:
    try:
        append_log(f"INDEX_HTML v15 보강 실패: {e}")
    except Exception:
        pass

# =========================
# v16 서버 내부 관리 도구: 즉시 업데이트/종료/백업복원/내보내기/일괄처리/점검/도움말
# =========================
import urllib.parse

LOCALREADLOG_VERSION = "v0.1.14"


def _protected(handler):
    try:
        if '_is_authenticated' in globals() and not _is_authenticated(handler):
            json_response(handler, {"ok": False, "auth_required": True, "message": "비밀번호 필요"}, status=401)
            return False
    except Exception:
        pass
    return True


def _download_response(handler, data, filename, content_type="application/octet-stream"):
    if isinstance(data, str):
        data = data.encode("utf-8")
    filename = str(filename or "download.bin").replace('"', '')
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _json_file_download(handler, payload, filename):
    _download_response(handler, json.dumps(payload, ensure_ascii=False, indent=2), filename, "application/json; charset=utf-8")


def _safe_backup_filename(name):
    name = Path(str(name or "")).name
    if not re.fullmatch(r"localreadlog_db_[0-9]{8}_[0-9]{6}(?:_[0-9A-Za-z_-]+)?\.json", name):
        return ""
    return name


def _db_backups_dir():
    p = BACKUP_DIR / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_db_backup_snapshot(label="manual"):
    if not DB_JSON.exists():
        return False, "DB 파일이 아직 없음", ""
    label = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", str(label or "manual")).strip("_")[:30] or "manual"
    backups_dir = _db_backups_dir()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backups_dir / f"localreadlog_db_{stamp}_{label}.json"
    try:
        shutil.copy2(DB_JSON, target)
        append_log(f"DB 백업 생성: {target.name}")
        files = sorted(backups_dir.glob("localreadlog_db_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[_DB_BACKUP_MAX_FILES:]:
            try:
                old.unlink()
            except Exception:
                pass
        return True, f"DB 백업 생성 완료: {target.name}", target.name
    except Exception as e:
        append_log(f"DB 백업 생성 실패: {e}")
        return False, f"DB 백업 생성 실패: {e}", ""


def list_db_backup_files():
    backups_dir = _db_backups_dir()
    rows = []
    for p in sorted(backups_dir.glob("localreadlog_db_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            rows.append({"name": p.name, "size": p.stat().st_size, "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
        except Exception:
            pass
    return rows


def restore_db_backup_snapshot(name):
    safe = _safe_backup_filename(name)
    if not safe:
        return False, "백업 파일명이 올바르지 않음"
    src = _db_backups_dir() / safe
    if not src.exists():
        return False, "백업 파일을 찾지 못함"
    try:
        with src.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            return False, "백업 DB 형식이 올바르지 않음"
        create_db_backup_snapshot("before_restore")
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, DB_JSON)
        db = load_db()
        save_db(db)
        sync_txt_from_db(db)
        append_log(f"DB 백업 복원: {safe}")
        return True, f"DB 백업 복원 완료: {safe}"
    except Exception as e:
        append_log(f"DB 백업 복원 실패: {e}")
        return False, f"DB 백업 복원 실패: {e}"


def import_db_json_text(text):
    text = str(text or "").strip()
    if not text:
        return False, "가져올 JSON 내용이 비어 있음"
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            return False, "DB JSON 형식이 올바르지 않음"
        create_db_backup_snapshot("before_import")
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        tmp = DB_JSON.with_suffix(".json.import.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(DB_JSON)
        db = load_db()
        save_db(db)
        sync_txt_from_db(db)
        append_log("DB JSON 가져오기 완료")
        return True, "DB JSON 가져오기 완료"
    except Exception as e:
        append_log(f"DB JSON 가져오기 실패: {e}")
        return False, f"DB JSON 가져오기 실패: {e}"


def get_recent_rows(limit=10):
    try:
        rows = get_rows_by_status("active")
        rows = sorted(rows, key=lambda r: str(r.get("last_seen", "")), reverse=True)
        return rows[:max(1, min(int(limit), 100))]
    except Exception:
        return []


def get_issue_rows():
    db = ensure_db()
    issues = []
    groups = {}
    for key, item in list(db.get("items", {}).items()):
        item = normalize_item(item)
        row = item_to_row(item)
        title = row.get("title", "")
        status = item.get("status", "active")
        site = item_site_key(item)
        if not title:
            issues.append({"title": key, "issue": "제목 없음", "detail": "title 값이 비어 있음", "status": status})
        if status == "active" and not row.get("url"):
            issues.append({"title": title, "issue": "URL 없음", "detail": "열기 버튼을 만들 수 없음", "status": status})
        if status == "active" and episode_sort_value(row.get("latest_episode", "")) <= 0:
            issues.append({"title": title, "issue": "화수 없음", "detail": "최신 화수가 비어 있거나 0임", "status": status})
        try:
            hist = item.get("episode_history", {}) or {}
            nums = sorted([episode_sort_value(x) for x in hist.keys() if episode_sort_value(x) > 0])
            if len(nums) >= 2 and nums[-1] - nums[-2] > float(item.get("max_auto_episode_jump", 10) or 10):
                issues.append({"title": title, "issue": "화수 급상승", "detail": f"{nums[-2]:g}화 → {nums[-1]:g}화", "status": status})
        except Exception:
            pass
        g = duplicate_group_key(row)
        if g:
            groups.setdefault(g, []).append({"title": title, "site": site, "status": status})
    for vals in groups.values():
        active_vals = [v for v in vals if v.get("status") == "active"]
        if len(active_vals) >= 2:
            issues.append({"title": active_vals[0].get("title", ""), "issue": "중복 의심", "detail": ", ".join(v.get("title", "") for v in active_vals[:5]), "status": "active"})
    return issues[:500]


def run_bulk_action(action, titles_text, category=""):
    action = str(action or "").strip().lower()
    raw = str(titles_text or "").strip()
    titles = []
    if raw.startswith("["):
        try:
            titles = json.loads(raw)
        except Exception:
            titles = []
    if not titles:
        titles = [x.strip() for x in re.split(r"[\n\r]+", raw) if x.strip()]
    titles = [clean_title(x) for x in titles if clean_title(x)]
    seen = set()
    titles = [x for x in titles if not (x in seen or seen.add(x))]
    if not titles:
        return False, "선택/입력된 작품이 없음", 0
    count = 0
    messages = []
    for title in titles:
        try:
            if action in ["delete", "restore", "purge"]:
                set_status(title, {"delete": "deleted", "restore": "active", "purge": "purged"}[action])
                count += 1
            elif action == "category":
                ok, msg = set_category(title, category)
                if ok:
                    count += 1
                else:
                    messages.append(f"{title}: {msg}")
            else:
                return False, "알 수 없는 일괄 작업", 0
        except Exception as e:
            messages.append(f"{title}: {e}")
    if action in ["delete", "restore", "purge"]:
        run_backup_script()
    msg = f"일괄 처리 완료: {count}개"
    if messages:
        msg += "\n" + "\n".join(messages[:10])
    append_log(msg.replace("\n", " / "))
    return True, msg, count


def shutdown_server_soon():
    append_log("서버 화면에서 종료 요청")
    def closer():
        time.sleep(0.6)
        try:
            cleanup_server_runtime_files()
        except Exception:
            pass
        os._exit(0)
    threading.Thread(target=closer, daemon=True).start()
    return True, "서버 종료 요청 완료. 잠시 뒤 접속이 끊김."


try:
    _prev_handler_get_v16
except NameError:
    _prev_handler_get_v16 = Handler.do_GET
    _prev_handler_post_v16 = Handler.do_POST

    def _v16_do_GET(self):
        path = urlparse(self.path).path
        if path in ["/api/backups", "/api/recent", "/api/issues"] or path.startswith("/api/export/") or path.startswith("/api/download_backup/"):
            if not _protected(self):
                return
            if path == "/api/backups":
                json_response(self, {"ok": True, "backups": list_db_backup_files()})
                return
            if path == "/api/recent":
                json_response(self, {"ok": True, "rows": get_recent_rows(10)})
                return
            if path == "/api/issues":
                json_response(self, {"ok": True, "issues": get_issue_rows()})
                return
            if path == "/api/export/db":
                _json_file_download(self, ensure_db(), "localreadlog_db_export.json")
                return
            if path == "/api/export/csv":
                if LATEST_CSV.exists():
                    _download_response(self, LATEST_CSV.read_bytes(), "localreadlog_latest.csv", "text/csv; charset=utf-8")
                else:
                    json_response(self, {"ok": False, "message": "CSV 파일이 아직 없음. 먼저 지금 업데이트를 실행하세요."}, status=404)
                return
            if path == "/api/export/mobile_html":
                p = BACKUP_DIR / "localreadlog_latest_mobile.html"
                if p.exists():
                    _download_response(self, p.read_bytes(), p.name, "text/html; charset=utf-8")
                else:
                    json_response(self, {"ok": False, "message": "모바일 HTML 파일이 아직 없음."}, status=404)
                return
            if path == "/api/export/pc_html":
                p = BACKUP_DIR / "localreadlog_latest_pc.html"
                if p.exists():
                    _download_response(self, p.read_bytes(), p.name, "text/html; charset=utf-8")
                else:
                    json_response(self, {"ok": False, "message": "PC HTML 파일이 아직 없음."}, status=404)
                return
            if path.startswith("/api/download_backup/"):
                name = urllib.parse.unquote(path.rsplit("/", 1)[-1])
                safe = _safe_backup_filename(name)
                p = _db_backups_dir() / safe if safe else None
                if p and p.exists():
                    _download_response(self, p.read_bytes(), p.name, "application/json; charset=utf-8")
                else:
                    json_response(self, {"ok": False, "message": "백업 파일을 찾지 못함"}, status=404)
                return
        return _prev_handler_get_v16(self)

    def _v16_do_POST(self):
        path = urlparse(self.path).path
        if path in ["/api/create_db_backup", "/api/restore_db_backup", "/api/import_db", "/api/bulk_action", "/api/shutdown"]:
            if not _protected(self):
                return
            val = _read_urlencoded_form(self) if '_read_urlencoded_form' in globals() else None
            if val is None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length).decode("utf-8", errors="replace")
                form = parse_qs(body)
                val = lambda name: (form.get(name) or [""])[0]
            if path == "/api/create_db_backup":
                ok, msg, name = create_db_backup_snapshot(val("label") or "manual")
                json_response(self, {"ok": ok, "message": msg, "name": name, "backups": list_db_backup_files()}, status=200 if ok else 400)
                return
            if path == "/api/restore_db_backup":
                ok, msg = restore_db_backup_snapshot(val("name"))
                json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
                return
            if path == "/api/import_db":
                ok, msg = import_db_json_text(val("json_text"))
                json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
                return
            if path == "/api/bulk_action":
                ok, msg, count = run_bulk_action(val("action"), val("titles"), val("category"))
                json_response(self, {"ok": ok, "message": msg, "count": count}, status=200 if ok else 400)
                return
            if path == "/api/shutdown":
                ok, msg = shutdown_server_soon()
                json_response(self, {"ok": ok, "message": msg})
                return
        return _prev_handler_post_v16(self)

    Handler.do_GET = _v16_do_GET
    Handler.do_POST = _v16_do_POST


# INDEX_HTML v16 보강
_V16_JS = r'''

function selectedTitles() {
    return [...document.querySelectorAll('.row-select:checked')].map(x => x.value).filter(Boolean);
}
function toggleAllRows(checked) {
    document.querySelectorAll('.row-select').forEach(x => { x.checked = checked; });
}
function bulkToolbar() {
    if (!(mode === 'current' || mode === 'deleted')) return '';
    const restoreBtn = mode === 'deleted' ? `<button class="restore" onclick="bulkAction('restore')">선택 복구</button><button class="purge" onclick="bulkAction('purge')">선택 완전삭제</button>` : `<button class="danger" onclick="bulkAction('delete')">선택 삭제</button>`;
    return `<div class="settings-box bulk-box"><h2>선택 일괄 처리</h2><div class="buttons"><button onclick="toggleAllRows(true)">전체선택</button><button onclick="toggleAllRows(false)">선택해제</button>${restoreBtn}<button class="edit" onclick="bulkCategory()">선택 분류변경</button></div></div>`;
}
async function bulkAction(action) {
    const titles = selectedTitles();
    if (!titles.length) { showToast('선택된 항목 없음'); return; }
    if (!confirm(`${titles.length}개 항목을 처리할까?`)) return;
    const data = await api('/api/bulk_action', {action, titles: JSON.stringify(titles)});
    showToast(data.message || '일괄 처리 완료');
    await reloadList();
}
async function bulkCategory() {
    const titles = selectedTitles();
    if (!titles.length) { showToast('선택된 항목 없음'); return; }
    const category = prompt('분류 입력: webtoon / comic / manga / novel / anime / other', 'comic');
    if (!category) return;
    const data = await api('/api/bulk_action', {action:'category', titles: JSON.stringify(titles), category});
    showToast(data.message || '분류 변경 완료');
    await reloadList();
}
async function runBackupNow() {
    showToast('지금 업데이트 실행 중...');
    const data = await api('/api/run_backup', {});
    showToast(data.message || '업데이트 완료');
    await reloadList();
}
async function shutdownFromUI() {
    if (!confirm('정말 LocalReadLog 서버를 종료할까?')) return;
    const data = await api('/api/shutdown', {});
    showToast(data.message || '서버 종료 요청 완료');
}
async function createDbBackup() {
    const label = prompt('백업 이름 메모', 'manual');
    if (label === null) return;
    const data = await api('/api/create_db_backup', {label});
    showToast(data.message || 'DB 백업 생성 완료');
    renderManagePage();
}
async function restoreDbBackup(name) {
    if (!confirm(`이 백업으로 복원할까?\n\n${name}\n\n현재 DB는 자동으로 백업한 뒤 복원함.`)) return;
    const data = await api('/api/restore_db_backup', {name});
    showToast(data.message || '복원 완료');
    await reloadList();
}
async function importDbFromBox() {
    const box = document.getElementById('importDbBox');
    const text = box ? box.value.trim() : '';
    if (!text) { showToast('붙여넣은 JSON이 없음'); return; }
    if (!confirm('붙여넣은 JSON으로 DB를 가져올까? 현재 DB는 먼저 백업됨.')) return;
    const data = await api('/api/import_db', {json_text: text});
    showToast(data.message || '가져오기 완료');
    if (box) box.value = '';
    await reloadList();
}
async function renderManagePage() {
    count.textContent = '관리 도구';
    list.innerHTML = '<div class="empty">관리 정보 불러오는 중...</div>';
    const [backups, recent, issues] = await Promise.all([
        api('/api/backups').catch(() => ({backups:[]})),
        api('/api/recent').catch(() => ({rows:[]})),
        api('/api/issues').catch(() => ({issues:[]})),
    ]);
    const backupRows = (backups.backups || []).map(b => `
        <div class="setting-row wide-row">
            <div><b>${escapeHtml(b.name)}</b><div class="small">${escapeHtml(b.modified)} · ${Math.round((b.size || 0)/1024)} KB</div></div>
            <button onclick="restoreDbBackup('${escapeHtml(b.name)}')">복원</button>
            <a class="mini-link" href="/api/download_backup/${encodeURIComponent(b.name)}">받기</a>
        </div>
    `).join('');
    const recentRows = (recent.rows || []).map(r => `
        <div class="setting-row wide-row">
            <div><b>${escapeHtml(r.title || '')}</b><div class="small">${escapeHtml(r.latest_episode || '-')}화 · ${escapeHtml(r.last_seen || '-')}</div></div>
            ${r.url ? `<a class="mini-link" target="_blank" href="${escapeHtml(r.url)}">열기</a>` : '<span></span>'}
            <span></span>
        </div>
    `).join('');
    const issueRows = (issues.issues || []).map(i => `
        <div class="setting-row wide-row">
            <div><b>${escapeHtml(i.issue || '')}</b><div class="small">${escapeHtml(i.title || '')} · ${escapeHtml(i.detail || '')}</div></div>
            <span class="diag-warn">점검</span><span></span>
        </div>
    `).join('');
    list.innerHTML = `
        <div class="settings-box"><h2>빠른 작업</h2><div class="buttons"><button onclick="runBackupNow()">지금 업데이트</button><button onclick="createDbBackup()">DB 백업 만들기</button><button class="danger" onclick="shutdownFromUI()">서버 종료</button></div></div>
        <div class="settings-box"><h2>내보내기</h2><div class="buttons"><a href="/api/export/db">DB JSON 받기</a><a href="/api/export/csv">CSV 받기</a><a href="/api/export/mobile_html">모바일 HTML 받기</a><a href="/api/export/pc_html">PC HTML 받기</a></div></div>
        <div class="settings-box"><h2>DB 가져오기</h2><div class="small">다른 PC에서 내보낸 DB JSON 내용을 붙여넣고 가져오기. 현재 DB는 먼저 자동 백업됨.</div><textarea id="importDbBox" class="import-box" placeholder="localreadlog_db_export.json 내용을 여기에 붙여넣기"></textarea><button onclick="importDbFromBox()">붙여넣은 DB 가져오기</button></div>
        <div class="settings-box"><h2>DB 백업 목록</h2>${backupRows || '<div class="empty">백업 없음</div>'}</div>
        <div class="settings-box"><h2>최근 본 작품 10개</h2>${recentRows || '<div class="empty">최근 기록 없음</div>'}</div>
        <div class="settings-box"><h2>문제 있는 항목 점검</h2>${issueRows || '<div class="empty">점검 결과 문제 없음</div>'}</div>
    `;
}
function renderHelpPage() {
    count.textContent = '도움말';
    list.innerHTML = `
        <div class="settings-box"><h2>모바일에서 보기</h2><p>PC와 휴대폰을 같은 Wi-Fi에 연결한 뒤 설정 탭의 모바일 주소로 접속하면 됨. 모바일 접속을 쓸 거면 설정에서 비밀번호 ON 권장.</p></div>
        <div class="settings-box"><h2>비밀번호</h2><p>설정 탭에서 접속 비밀번호를 ON/OFF 할 수 있음. 한 번 로그인하면 해당 브라우저에 저장되어 다시 입력하지 않아도 됨. 쿠키 삭제, 비밀번호 변경, 다른 브라우저 사용 시에는 다시 입력해야 함.</p></div>
        <div class="settings-box"><h2>업데이트</h2><p>서버가 켜져 있으면 자동 업데이트가 동작함. 바로 갱신하고 싶으면 관리 탭의 <b>지금 업데이트</b>를 누르면 됨.</p></div>
        <div class="settings-box"><h2>백업/복원</h2><p>관리 탭에서 DB 백업 만들기, 백업 복원, DB 내보내기, DB 파일 가져오기를 할 수 있음. DB 복원/가져오기 전에는 현재 DB가 자동 백업됨.</p></div>
        <div class="settings-box"><h2>서버 종료/삭제</h2><p>서버를 끄려면 관리 탭의 <b>서버 종료</b> 또는 <b>05_Stop_Server.bat</b>를 사용. 완전히 지우려면 자동실행 해제 후 LocalReadLog 폴더를 삭제하면 됨.</p></div>
    `;
}
'''

try:
    INDEX_HTML = INDEX_HTML.replace('</style>', '\n.select-line{display:inline-flex;gap:6px;align-items:center;font-size:12px;color:#555;margin-bottom:7px}.bulk-box{border:2px solid #e5e7eb}.wide-row{grid-template-columns:1fr 82px 66px}.mini-link{display:inline-block;text-align:center;border-radius:8px;padding:8px 7px;background:#111;color:#fff;text-decoration:none;font-weight:800;font-size:12px}.import-box{box-sizing:border-box;width:100%;min-height:130px;border:1px solid #ccc;border-radius:10px;padding:10px;font-family:Consolas,monospace;font-size:12px;margin:8px 0;white-space:pre}\n</style>')
    INDEX_HTML = INDEX_HTML.replace('<button id="tab-settings" onclick="setMode(\'settings\')">설정</button>\n        <button id="tab-log" onclick="setMode(\'log\')">로그</button>', '<button id="tab-settings" onclick="setMode(\'settings\')">설정</button>\n        <button id="tab-manage" onclick="setMode(\'manage\')">관리</button>\n        <button id="tab-help" onclick="setMode(\'help\')">도움말</button>\n        <button id="tab-log" onclick="setMode(\'log\')">로그</button>')
    INDEX_HTML = INDEX_HTML.replace('document.getElementById("tab-log").classList.toggle("active", mode === "log");', 'document.getElementById("tab-log").classList.toggle("active", mode === "log");\n    const manageTab = document.getElementById("tab-manage"); if (manageTab) manageTab.classList.toggle("active", mode === "manage");\n    const helpTab = document.getElementById("tab-help"); if (helpTab) helpTab.classList.toggle("active", mode === "help");')
    INDEX_HTML = INDEX_HTML.replace('controls.style.display = (mode === "log" || mode === "settings") ? "none" : "grid";', 'controls.style.display = (["log", "settings", "manage", "help"].includes(mode)) ? "none" : "grid";')
    INDEX_HTML = INDEX_HTML.replace('prioritybar.style.display = (mode === "log" || mode === "settings") ? "none" : "grid";', 'prioritybar.style.display = (["log", "settings", "manage", "help"].includes(mode)) ? "none" : "grid";')
    INDEX_HTML = INDEX_HTML.replace('if (mode === "log") {\n        const data = await api("/api/logs");\n        rows = data.lines || [];\n        renderLog();\n        return;\n    }', 'if (mode === "log") {\n        const data = await api("/api/logs");\n        rows = data.lines || [];\n        renderLog();\n        return;\n    }\n\n    if (mode === "manage") {\n        rows = [];\n        await renderManagePage();\n        return;\n    }\n\n    if (mode === "help") {\n        rows = [];\n        renderHelpPage();\n        return;\n    }')
    INDEX_HTML = INDEX_HTML.replace('<div class="card">\n            <div class="title-line">', '<div class="card">\n            <label class="select-line"><input type="checkbox" class="row-select" value="${escapeHtml(r.title || \'\')}"> 선택</label>\n            <div class="title-line">')
    INDEX_HTML = INDEX_HTML.replace('list.innerHTML = filtered.map(r => {', 'list.innerHTML = bulkToolbar() + filtered.map(r => {')
    INDEX_HTML = INDEX_HTML.replace('search.addEventListener("input", render);\nsort.addEventListener("change", render);', 'try { search.value = localStorage.getItem("lrl.search") || ""; sort.value = localStorage.getItem("lrl.sort") || sort.value; } catch(e) {}\nsearch.addEventListener("input", () => { try { localStorage.setItem("lrl.search", search.value); } catch(e) {} render(); });\nsort.addEventListener("change", () => { try { localStorage.setItem("lrl.sort", sort.value); } catch(e) {} render(); });')
    INDEX_HTML = INDEX_HTML.replace('search.addEventListener("input", () => { try { localStorage.setItem("lrl.search", search.value); } catch(e) {} render(); });', _V16_JS + '\nsearch.addEventListener("input", () => { try { localStorage.setItem("lrl.search", search.value); } catch(e) {} render(); });')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v16 보강 실패: {e}")
    except Exception:
        pass


# =========================
# v17 DB 파일 업로드 가져오기
# =========================
LOCALREADLOG_VERSION = "v0.1.14"


def _get_multipart_boundary(content_type):
    content_type = str(content_type or "")
    m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type, flags=re.I)
    if not m:
        return b""
    boundary = (m.group(1) or m.group(2) or "").strip()
    return boundary.encode("utf-8", errors="ignore")


def _read_uploaded_db_file(handler, max_bytes=50 * 1024 * 1024):
    try:
        length = int(handler.headers.get("Content-Length", "0") or "0")
    except Exception:
        length = 0
    if length <= 0:
        return False, "업로드된 파일이 없음", "", b""
    if length > max_bytes:
        return False, "DB 파일이 너무 큼", "", b""
    content_type = handler.headers.get("Content-Type", "")
    boundary = _get_multipart_boundary(content_type)
    if not boundary:
        return False, "파일 업로드 형식이 올바르지 않음", "", b""
    body = handler.rfile.read(length)
    marker = b"--" + boundary
    for raw_part in body.split(marker):
        part = raw_part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" in part:
            header_blob, file_blob = part.split(b"\r\n\r\n", 1)
        elif b"\n\n" in part:
            header_blob, file_blob = part.split(b"\n\n", 1)
        else:
            continue
        header_text = header_blob.decode("utf-8", errors="replace")
        if "Content-Disposition" not in header_text:
            continue
        if "name=\"db_file\"" not in header_text and "name='db_file'" not in header_text:
            continue
        filename = "localreadlog_db_import.json"
        fm = re.search(r'filename=(?:"([^"]*)"|([^;\r\n]+))', header_text, flags=re.I)
        if fm:
            filename = Path((fm.group(1) or fm.group(2) or filename).strip()).name or filename
        file_blob = file_blob.rstrip(b"\r\n")
        if file_blob.endswith(b"--"):
            file_blob = file_blob[:-2].rstrip(b"\r\n")
        return True, "OK", filename, file_blob
    return False, "DB JSON 파일을 찾지 못함", "", b""


def import_db_json_bytes(filename, data):
    filename = Path(str(filename or "")).name
    if not data:
        return False, "가져올 파일 내용이 비어 있음"
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception as e:
            return False, f"DB 파일을 읽지 못함: {e}"
    ok, msg = import_db_json_text(text)
    if ok:
        append_log(f"DB 파일 가져오기 완료: {filename}")
        return True, f"DB 파일 가져오기 완료: {filename}"
    return ok, msg

try:
    _prev_handler_post_v17
except NameError:
    _prev_handler_post_v17 = Handler.do_POST

    def _v17_do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/import_db_upload":
            if not _protected(self):
                return
            ok, msg, filename, blob = _read_uploaded_db_file(self)
            if not ok:
                json_response(self, {"ok": False, "message": msg}, status=400)
                return
            ok, msg = import_db_json_bytes(filename, blob)
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return
        return _prev_handler_post_v17(self)

    Handler.do_POST = _v17_do_POST

_V17_JS = r"""
async function importDbFromFile() {
    const input = document.getElementById('importDbFile');
    if (!input || !input.files || !input.files.length) {
        showToast('가져올 DB JSON 파일을 선택하세요');
        return;
    }
    const file = input.files[0];
    if (!confirm(`${file.name}\n\n이 DB 파일로 가져올까? 현재 DB는 먼저 자동 백업됨.`)) return;
    const form = new FormData();
    form.append('db_file', file);
    showToast('DB 파일 가져오는 중...');
    let data = {};
    try {
        const res = await fetch('/api/import_db_upload', {method:'POST', body:form});
        data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) {
            alert(data.message || 'DB 파일 가져오기 실패');
            return;
        }
    } catch (e) {
        alert('DB 파일 가져오기 실패: ' + e);
        return;
    }
    showToast(data.message || 'DB 파일 가져오기 완료');
    input.value = '';
    await reloadList();
}
"""
try:
    old = '<div class="settings-box"><h2>DB 가져오기</h2><div class="small">다른 PC에서 내보낸 DB JSON 내용을 붙여넣고 가져오기. 현재 DB는 먼저 자동 백업됨.</div><textarea id="importDbBox" class="import-box" placeholder="localreadlog_db_export.json 내용을 여기에 붙여넣기"></textarea><button onclick="importDbFromBox()">붙여넣은 DB 가져오기</button></div>'
    new = '<div class="settings-box"><h2>DB 가져오기</h2><div class="small">다른 PC에서 내보낸 <b>localreadlog_db_export.json</b> 파일을 선택해서 가져오기. 현재 DB는 먼저 자동 백업됨.</div><input id="importDbFile" class="file-input" type="file" accept=".json,application/json"><button onclick="importDbFromFile()">DB 파일 가져오기</button></div>'
    INDEX_HTML = INDEX_HTML.replace(old, new)
    INDEX_HTML = INDEX_HTML.replace('search.addEventListener("input", () => { try { localStorage.setItem("lrl.search", search.value); } catch(e) {} render(); });', _V17_JS + '\nsearch.addEventListener("input", () => { try { localStorage.setItem("lrl.search", search.value); } catch(e) {} render(); });')
    INDEX_HTML = INDEX_HTML.replace('</style>', '\n.file-input{box-sizing:border-box;width:100%;border:1px solid #ccc;border-radius:10px;padding:10px;background:#fff;margin:8px 0;font-size:14px}\n</style>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v17 DB 파일 가져오기 보강 실패: {e}")
    except Exception:
        pass

# =========================
# v19 release polish: version/license-ready UI, safer restore/import UX, security notes
# =========================
LOCALREADLOG_VERSION = "v0.1.14"

_V19_JS = r"""
function reloadAfterDbChange(message) {
    showToast((message || '처리 완료') + ' · 화면을 새로고침합니다');
    setTimeout(() => { location.reload(); }, 1500);
}

async function restoreDbBackup(name) {
    if (!confirm(`이 백업으로 복원할까?\n\n${name}\n\n현재 DB는 먼저 자동 백업된 뒤 선택한 백업으로 교체됨.`)) return;
    const data = await api('/api/restore_db_backup', {name});
    reloadAfterDbChange(data.message || 'DB 백업 복원 완료');
}

async function importDbFromFile() {
    const input = document.getElementById('importDbFile');
    if (!input || !input.files || !input.files.length) {
        showToast('가져올 DB JSON 파일을 선택하세요');
        return;
    }
    const file = input.files[0];
    if (!confirm(`${file.name}\n\n이 DB 파일로 가져올까?\n\n현재 DB는 먼저 자동 백업된 뒤 선택한 파일로 교체됨.`)) return;
    const form = new FormData();
    form.append('db_file', file);
    showToast('DB 파일 가져오는 중...');
    let data = {};
    try {
        const res = await fetch('/api/import_db_upload', {method:'POST', body:form});
        data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) {
            alert(data.message || 'DB 파일 가져오기 실패');
            return;
        }
    } catch (e) {
        alert('DB 파일 가져오기 실패: ' + e);
        return;
    }
    input.value = '';
    reloadAfterDbChange(data.message || 'DB 파일 가져오기 완료');
}

function renderHelpPage() {
    count.textContent = '도움말';
    list.innerHTML = `
        <div class="settings-box"><h2>모바일에서 보기</h2><p>PC와 휴대폰을 같은 Wi-Fi에 연결한 뒤 설정 탭의 모바일 주소로 접속하면 됨. 접속이 안 되면 Windows Defender 방화벽이 막을 수 있음. 이때 06_Allow_Mobile_Access_Windows_Firewall.bat을 관리자 권한으로 실행하면 됨.</p></div>
        <div class="settings-box"><h2>비밀번호</h2><p>모바일이나 다른 기기에서 접속할 거면 설정에서 비밀번호 ON 권장. 한 번 로그인하면 해당 브라우저에 저장됨. 쿠키 삭제, 비밀번호 변경, 다른 브라우저 사용 시에는 다시 입력해야 함.</p></div>
        <div class="settings-box"><h2>업데이트</h2><p>서버가 켜져 있으면 자동 업데이트가 동작함. 바로 갱신하고 싶으면 관리 탭의 <b>지금 업데이트</b>를 누르면 됨.</p></div>
        <div class="settings-box"><h2>백업/복원</h2><p>관리 탭에서 DB 백업 만들기, 백업 복원, DB 내보내기, DB 파일 가져오기를 할 수 있음. DB 복원/가져오기 전에는 현재 DB가 자동 백업되고, 완료 후 화면이 자동 새로고침됨.</p></div>
        <div class="settings-box"><h2>서버 종료/삭제</h2><p>서버를 끄려면 관리 탭의 <b>서버 종료</b> 또는 <b>05_Stop_Server.bat</b>를 사용. 완전히 지우려면 자동실행 해제 후 LocalReadLog 폴더를 삭제하면 됨.</p></div>
        <div class="settings-box"><h2>주의</h2><p>LocalReadLog는 개인 PC와 로컬 네트워크용 도구임. 공유기 포트포워딩으로 외부 인터넷에 공개하지 않는 것을 권장함.</p></div>
    `;
}
"""

try:
    INDEX_HTML = INDEX_HTML.replace('</script>', _V19_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v19 보강 실패: {e}")
    except Exception:
        pass


# =========================
# v20 UI 정리: 설정/관리 탭 재배치, 링크화, 백업 목록 축소
# =========================
LOCALREADLOG_VERSION = "v0.1.14"

_V20_JS = r'''

function clickableLinkList(urls) {
    if (!Array.isArray(urls) || !urls.length) return '-';
    return urls.map(u => {
        const safe = escapeHtml(String(u || ''));
        return `<a class="text-link" href="${safe}" target="_blank" rel="noopener noreferrer">${safe}</a>`;
    }).join('<br>');
}

function renderDiagnosticsBlock() {
    const st = settings.status || {};
    const diag = st.diagnostics || {};
    const checks = diag.checks || [];
    const checkRows = checks.map(c => `
        <div class="setting-row">
            <div><b>${escapeHtml(c.name)}</b><div class="small">${escapeHtml(c.detail || '')}</div></div>
            <div>${statusBadge(!!c.ok)}</div>
            <span></span>
        </div>
    `).join('');
    return `<div class="settings-box"><h2>처음 실행 진단</h2><div class="small">실행이 안 되거나 목록이 비어 있으면 여기부터 확인.</div>${checkRows || '<div class="empty">진단 정보 없음</div>'}</div>`;
}

function renderBrowserHistoryBlock() {
    const st = settings.status || {};
    const diag = st.diagnostics || {};
    const browsers = diag.browsers || [];
    const browserRows2 = browsers.map(b => `
        <div class="setting-row">
            <div><b>${escapeHtml(b.name)}</b><div class="small">${escapeHtml(b.path || '')}</div></div>
            <div>${statusBadge(!!b.ok)}</div>
            <span></span>
        </div>
    `).join('');
    return `<div class="settings-box"><h2>브라우저 기록 위치</h2>${browserRows2 || '<div class="empty">브라우저 정보 없음</div>'}</div>`;
}

function renderAddressBox() {
    const st = settings.status || {};
    return `
        <div class="settings-box">
            <h2>접속 주소</h2>
            <div class="small">PC에서 보기</div>
            <div class="link-list">${clickableLinkList(st.pc_urls)}</div>
            <div style="height:10px"></div>
            <div class="small">모바일에서 보기. 휴대폰과 PC가 같은 Wi-Fi여야 함.</div>
            <div class="link-list">${clickableLinkList(st.mobile_urls)}</div>
        </div>
    `;
}

function renderAutoUpdateBox() {
    const st = settings.status || {};
    const au = st.auto_update || {};
    const intervals = [30, 60, 180, 360];
    const currentInterval = Number(settings.auto_update_interval_minutes || au.interval_minutes || 60);
    const autoEnabled = !!(settings.auto_update_enabled ?? au.enabled);
    return `
        <div class="settings-box">
            <h2>자동 업데이트</h2>
            <div class="small">백그라운드 서버가 켜져 있는 동안 방문기록을 자동 스캔함.</div>
            <div class="setting-row">
                <div>
                    <b>현재 상태: ${autoEnabled ? 'ON' : 'OFF'}</b>
                    <div class="small">마지막: ${escapeHtml(st.last_update_at || au.last_finish || '-')} · 다음: ${escapeHtml(st.next_run || au.next_run || '-')}</div>
                </div>
                <button class="${autoEnabled ? '' : 'off'}" onclick="setAutoUpdate(!${autoEnabled}, ${currentInterval})">${autoEnabled ? 'ON' : 'OFF'}</button>
                <span></span>
            </div>
            <div class="buttons">
                ${intervals.map(m => `<button class="${m === currentInterval ? '' : 'off'}" onclick="setAutoUpdate(true, ${m})">${m < 60 ? m + '분' : Math.round(m/60) + '시간'}</button>`).join('')}
            </div>
        </div>
    `;
}

function renderRuntimeStatusBox() {
    const st = settings.status || {};
    const au = st.auto_update || {};
    return `
        <div class="settings-box">
            <h2>실행 상태</h2>
            <div class="small">서버 실행 정보를 확인하는 영역.</div>
            <div class="setting-row"><div><b>버전</b><div class="small">${escapeHtml(st.version || 'v0.1.14')}</div></div><span></span><span></span></div>
            <div class="setting-row"><div><b>서버 포트</b><div class="small">${escapeHtml(String(st.port || '-'))}</div></div><span></span><span></span></div>
            <div class="setting-row"><div><b>서버 시작</b><div class="small">${escapeHtml(st.server_started_at || '-')}</div></div><span></span><span></span></div>
            <div class="setting-row"><div><b>DB 위치</b><div class="small">${escapeHtml(st.db_path || '')}</div></div><span></span><span></span></div>
            <div class="setting-row"><div><b>자동 업데이트</b><div class="small">${au.enabled ? 'ON' : 'OFF'} · ${escapeHtml(String(au.interval_minutes || '-'))}분</div></div><span></span><span></span></div>
        </div>
    `;
}

function renderSettingsPage() {
    renderSettings();
    controls.style.display = 'none';
    prioritybar.style.display = 'none';
    if (browserbar) browserbar.style.display = 'none';

    const siteEntries = Object.entries(settings.sites || {});
    const priorityLabels = (settings.site_priority || []).map(k => settings.sites?.[k]?.label || settings.site_labels?.[k] || k);

    const siteRows = siteEntries.map(([key, site]) => {
        const enabled = site.enabled !== false;
        const host = site.host_re || site.prefix || key;
        const removable = key !== 'blacktoon';
        const catLabel = settings.category_labels?.[site.category || 'other'] || site.category || '기타';
        return `
            <div class="setting-row">
                <div>
                    <b>${escapeHtml(site.label || key)}</b>
                    <div class="small">${escapeHtml(key)} · ${escapeHtml(host)} · 기본분류 ${escapeHtml(catLabel)}</div>
                </div>
                <button class="${enabled ? '' : 'off'}" onclick="toggleSiteEnabled('${encodeURIComponent(key)}')">${enabled ? 'ON' : 'OFF'}</button>
                ${removable ? `<button class="danger" onclick="removeSite('${encodeURIComponent(key)}')">삭제</button>` : `<button onclick="setSiteCategory('${encodeURIComponent(key)}')">분류</button>`}
                ${removable ? `<button onclick="setSiteCategory('${encodeURIComponent(key)}')">분류</button>` : ''}
            </div>
        `;
    }).join('');

    const browserRows = Object.entries(settings.browser_labels || {}).map(([key, label]) => {
        const enabled = !!settings.browser_enabled?.[key];
        return `
            <div class="setting-row">
                <div><b>${escapeHtml(label)}</b></div>
                <button class="${enabled ? '' : 'off'}" onclick="toggleBrowserSync('${key}')">${enabled ? 'ON' : 'OFF'}</button>
                <span></span>
            </div>
        `;
    }).join('');

    count.textContent = '설정';
    list.innerHTML = `
        <div class="settings-box">
            <h2>사이트</h2>
            <div class="small">주소를 입력해서 추적 사이트를 추가함. 예: https://example123.com/</div>
            <div style="height:8px"></div>
            <button onclick="addSite()">사이트 추가</button>
            <div style="height:10px"></div>
            ${siteRows || '<div class="empty">등록된 사이트 없음</div>'}
        </div>

        <div class="settings-box">
            <h2>사이트 우선순위</h2>
            <div class="small">위아래로 드래그해서 순서를 바꾼 뒤 저장. 현재: ${escapeHtml(priorityLabels.join(' > '))}</div>
            <div id="priorityList" class="priority-list">${renderPriorityRows()}</div>
            <button onclick="saveDraggedSitePriority()">우선순위 저장</button>
            <button onclick="toggleDuplicateHiding()">중복숨김 ${settings.hide_site_duplicates ? 'ON' : 'OFF'}</button>
        </div>

        ${renderAddressBox()}
        ${renderAutoUpdateBox()}

        <div class="settings-box">
            <h2>저장 위치</h2>
            <div class="small">DB/CSV/HTML/로그는 프로그램 폴더 안의 data 폴더에 저장됨.</div>
            <div style="word-break:break-all"><b>${escapeHtml(settings.backup_dir || '')}</b></div>
        </div>

        <div class="settings-box">
            <h2>접속 비밀번호</h2>
            <div class="small">모바일/다른 기기에서 접속할 때는 비밀번호 사용을 권장함. 공유기 외부 포트포워딩은 권장하지 않음. 한 번 입력하면 브라우저에 저장됨.</div>
            <div class="setting-row">
                <div><b>비밀번호 보호</b><div class="small">현재 상태: ${settings.password_enabled ? 'ON' : 'OFF'}</div></div>
                <button class="${settings.password_enabled ? '' : 'off'}" onclick="toggleAccessPassword()">${settings.password_enabled ? 'ON' : 'OFF'}</button>
                <button onclick="changeAccessPassword()">비밀번호 변경</button>
            </div>
        </div>

        <div class="settings-box"><h2>브라우저 연동</h2>${browserRows}</div>

        ${renderRuntimeStatusBox()}
    `;
}

async function renderManagePage() {
    count.textContent = '관리 도구';
    list.innerHTML = '<div class="empty">관리 정보 불러오는 중...</div>';
    const [backups, issues] = await Promise.all([
        api('/api/backups').catch(() => ({backups:[]})),
        api('/api/issues').catch(() => ({issues:[]})),
    ]);
    const compactBackups = (backups.backups || []).slice(0, 5);
    const backupRows = compactBackups.map(b => `
        <div class="setting-row wide-row backup-compact-row">
            <div><b>${escapeHtml(b.name)}</b><div class="small">${escapeHtml(b.modified)} · ${Math.round((b.size || 0)/1024)} KB</div></div>
            <button onclick="restoreDbBackup('${escapeHtml(b.name)}')">복원</button>
            <a class="mini-link" href="/api/download_backup/${encodeURIComponent(b.name)}">받기</a>
        </div>
    `).join('');
    const issueRows = (issues.issues || []).map(i => `
        <div class="setting-row wide-row">
            <div><b>${escapeHtml(i.issue || '')}</b><div class="small">${escapeHtml(i.title || '')} · ${escapeHtml(i.detail || '')}</div></div>
            <span class="diag-warn">점검</span><span></span>
        </div>
    `).join('');
    list.innerHTML = `
        <div class="settings-box"><h2>빠른 작업</h2><div class="buttons"><button onclick="runBackupNow()">지금 업데이트</button><button onclick="createDbBackup()">DB 백업 만들기</button><button class="danger" onclick="shutdownFromUI()">서버 종료</button></div></div>
        <div class="settings-box"><h2>내보내기</h2><div class="buttons"><a href="/api/export/db">DB JSON 받기</a><a href="/api/export/csv">CSV 받기</a><a href="/api/export/mobile_html">모바일 HTML 받기</a><a href="/api/export/pc_html">PC HTML 받기</a></div></div>
        <div class="settings-box"><h2>DB 가져오기</h2><div class="small">다른 PC에서 내보낸 DB JSON 파일을 선택해서 가져오기. 현재 DB는 먼저 자동 백업됨.</div><input id="importDbFile" type="file" accept=".json,application/json"><div style="height:8px"></div><button onclick="importDbFromFile()">DB 파일 가져오기</button></div>
        <div class="settings-box compact-backup-box"><h2>DB 백업 목록</h2><div class="small">최근 5개만 표시함. 오래된 백업은 data/backups 폴더에서 확인 가능.</div>${backupRows || '<div class="empty">백업 없음</div>'}</div>
        ${renderDiagnosticsBlock()}
        ${renderBrowserHistoryBlock()}
        <div class="settings-box"><h2>문제 있는 항목 점검</h2>${issueRows || '<div class="empty">점검 결과 문제 없음</div>'}</div>
    `;
}

function renderHelpPage() {
    count.textContent = '도움말';
    list.innerHTML = `
        <div class="settings-box"><h2>모바일에서 보기</h2><p>PC와 휴대폰을 같은 Wi-Fi에 연결한 뒤 설정 탭의 모바일 주소 링크를 누르거나 휴대폰 브라우저에 입력하면 됨. 접속이 안 되면 Windows Defender 방화벽이 막을 수 있음. 이때 06_Allow_Mobile_Access_Windows_Firewall.bat을 관리자 권한으로 실행하면 됨.</p></div>
        <div class="settings-box"><h2>비밀번호</h2><p>모바일이나 다른 기기에서 접속할 거면 설정에서 비밀번호 ON 권장. 한 번 로그인하면 해당 브라우저에 저장됨. 쿠키 삭제, 비밀번호 변경, 다른 브라우저 사용 시에는 다시 입력해야 함.</p></div>
        <div class="settings-box"><h2>업데이트</h2><p>서버가 켜져 있으면 자동 업데이트가 동작함. 바로 갱신하고 싶으면 관리 탭의 <b>지금 업데이트</b>를 누르면 됨.</p></div>
        <div class="settings-box"><h2>백업/복원</h2><p>관리 탭에서 DB 백업 만들기, 백업 복원, DB 내보내기, DB 파일 가져오기를 할 수 있음. DB 복원/가져오기 전에는 현재 DB가 자동 백업되고, 완료 후 화면이 자동 새로고침됨.</p></div>
        <div class="settings-box"><h2>서버 종료/삭제</h2><p>서버를 끄려면 관리 탭의 <b>서버 종료</b> 또는 <b>05_Stop_Server.bat</b>를 사용. 완전히 지우려면 자동실행 해제 후 LocalReadLog 폴더를 삭제하면 됨.</p></div>
        <div class="settings-box"><h2>주의</h2><p>LocalReadLog는 개인 PC와 로컬 네트워크용 도구임. 공유기 포트포워딩으로 외부 인터넷에 공개하지 않는 것을 권장함.</p></div>
    `;
}
'''

try:
    INDEX_HTML = INDEX_HTML.replace('</style>', '\n.text-link{color:#1d4ed8;font-weight:800;text-decoration:none}.text-link:hover{text-decoration:underline}.link-list{word-break:break-all;line-height:1.8;margin-top:4px}.compact-backup-box .setting-row{padding-top:8px;padding-bottom:8px}.backup-compact-row b{font-size:13px}\n</style>')
    INDEX_HTML = INDEX_HTML.replace('</script>', _V20_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v20 UI 정리 실패: {e}")
    except Exception:
        pass


# =========================
# v0.1.3 UX polish: simpler filenames, copy buttons, clearer feedback
# =========================
LOCALREADLOG_VERSION = "v0.1.14"

_V21_JS = r'''
function copyTextToClipboard(text, label='주소') {
    const value = String(text || '').trim();
    if (!value) { showToast('복사할 내용이 없음'); return; }
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(() => {
            showToast(label + ' 복사 완료');
        }).catch(() => fallbackCopyText(value, label));
    } else {
        fallbackCopyText(value, label);
    }
}

function fallbackCopyText(text, label='주소') {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.left = '-9999px';
    document.body.appendChild(area);
    area.focus();
    area.select();
    try {
        document.execCommand('copy');
        showToast(label + ' 복사 완료');
    } catch (e) {
        prompt(label + ' 복사', text);
    }
    document.body.removeChild(area);
}

function addressRows(urls, label) {
    if (!Array.isArray(urls) || !urls.length) return '<div class="empty">주소 없음</div>';
    return urls.map((u) => {
        const url = String(u || '');
        const safe = escapeHtml(url);
        const copyArg = encodeURIComponent(url);
        return `<div class="address-row">
            <a class="text-link" href="${safe}" target="_blank" rel="noopener noreferrer">${safe}</a>
            <button onclick="copyTextToClipboard(decodeURIComponent('${copyArg}'), '${label}')">복사</button>
        </div>`;
    }).join('');
}

function renderAddressBox() {
    const st = settings.status || {};
    const passwordWarning = settings.password_enabled ? '' : `
        <div class="warn-box">
            <b>비밀번호가 꺼져 있음</b><br>
            모바일이나 다른 기기에서 접속할 거면 비밀번호 ON을 권장함.
            <div style="height:8px"></div>
            <button onclick="toggleAccessPassword()">비밀번호 설정</button>
        </div>`;
    return `
        <div class="settings-box">
            <h2>접속 주소</h2>
            ${passwordWarning}
            <div class="small">PC에서 보기</div>
            <div class="link-list">${addressRows(st.pc_urls, 'PC 주소')}</div>
            <div style="height:10px"></div>
            <div class="small">모바일에서 보기. 휴대폰과 PC가 같은 Wi-Fi여야 함.</div>
            <div class="link-list">${addressRows(st.mobile_urls, '모바일 주소')}</div>
        </div>
    `;
}

function setButtonBusy(selectorText, busy) {
    document.querySelectorAll('button').forEach(btn => {
        const code = btn.getAttribute('onclick') || '';
        if (code.includes(selectorText)) {
            btn.disabled = !!busy;
            btn.dataset.oldText = btn.dataset.oldText || btn.textContent;
            btn.textContent = busy ? '처리 중...' : btn.dataset.oldText;
        }
    });
}

async function runBackupNow() {
    setButtonBusy('runBackupNow', true);
    showToast('업데이트 중... 방문기록을 다시 스캔하고 있음');
    try {
        const data = await api('/api/run_backup', {});
        showToast(data.message || '업데이트 완료');
        await loadSettings();
        if (mode === 'manage') await renderManagePage();
        else await reloadList();
    } catch (e) {
        alert('업데이트 실패: ' + e);
    } finally {
        setButtonBusy('runBackupNow', false);
    }
}

async function restoreDbBackup(name) {
    if (!confirm(`이 백업으로 복원할까?\n\n${name}\n\n현재 DB는 먼저 자동 백업된 뒤 선택한 백업으로 교체됨.\n복원 후 화면이 자동 새로고침됨.`)) return;
    showToast('복원 중... 현재 DB를 먼저 자동 백업함');
    try {
        const data = await api('/api/restore_db_backup', {name});
        reloadAfterDbChange((data.message || 'DB 백업 복원 완료') + ' · 문제 있으면 백업 목록에서 되돌릴 수 있음');
    } catch (e) {
        alert('복원 실패: ' + e);
    }
}

async function importDbFromFile() {
    const input = document.getElementById('importDbFile');
    if (!input || !input.files || !input.files.length) {
        showToast('가져올 DB JSON 파일을 선택하세요');
        return;
    }
    const file = input.files[0];
    if (!confirm(`${file.name}\n\n이 DB 파일로 가져올까?\n\n현재 DB는 먼저 자동 백업된 뒤 선택한 파일로 교체됨.\n가져오기 후 화면이 자동 새로고침됨.`)) return;
    const form = new FormData();
    form.append('db_file', file);
    showToast('DB 파일 가져오는 중... 현재 DB를 먼저 자동 백업함');
    let data = {};
    try {
        const res = await fetch('/api/import_db_upload', {method:'POST', body:form});
        data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) {
            alert(data.message || 'DB 파일 가져오기 실패');
            return;
        }
    } catch (e) {
        alert('DB 파일 가져오기 실패: ' + e);
        return;
    }
    input.value = '';
    reloadAfterDbChange((data.message || 'DB 파일 가져오기 완료') + ' · 문제 있으면 백업 목록에서 되돌릴 수 있음');
}

async function setAutoUpdate(enabled, minutes) {
    const data = await api('/api/set_auto_update', {enabled: enabled ? '1' : '0', interval_minutes: String(minutes)});
    showToast(data.message || '자동 업데이트 설정 저장 완료');
    await loadSettings();
    renderSettingsPage();
}

async function saveDraggedSitePriority() {
    const keys = [...document.querySelectorAll('#priorityList .priority-item')]
        .map(el => el.dataset.siteKey)
        .filter(Boolean);
    if (!keys.length) { showToast('저장할 사이트가 없음'); return; }
    const data = await api('/api/set_site_priority', {priority: keys.join(',')});
    showToast(data.message || '사이트 우선순위 저장 완료');
    await loadSettings();
    renderSettingsPage();
}

async function toggleSiteEnabled(encodedKey) {
    const key = decodeURIComponent(encodedKey);
    const data = await api('/api/toggle_site', {site: key});
    showToast(data.message || '사이트 설정 저장 완료');
    await loadSettings();
    renderSettingsPage();
}

async function toggleBrowserSync(browserKey) {
    const label = settings.browser_labels?.[browserKey] || browserKey;
    const data = await api('/api/toggle_browser', {browser: browserKey});
    showToast(data.message || `${label} 설정 저장 완료`);
    await loadSettings();
    if (mode === 'settings') renderSettingsPage();
    else renderSettings();
}

async function toggleDuplicateHiding() {
    const data = await api('/api/toggle_duplicate_hiding', {toggle: '1'});
    showToast(data.message || '중복숨김 설정 저장 완료');
    await loadSettings();
    if (mode === 'settings') renderSettingsPage();
    else await reloadList();
}

async function toggleAccessPassword() {
    const enabled = !!settings.password_enabled;
    if (enabled) {
        if (!confirm('접속 비밀번호를 끌까?\n\n끄면 같은 네트워크에서 비밀번호 없이 접속할 수 있음.')) return;
        const data = await api('/api/set_password_settings', {enabled: '0'});
        showToast(data.message || '비밀번호 보호 OFF 저장 완료');
        await loadSettings();
        renderSettingsPage();
        return;
    }
    const pw = prompt('새 접속 비밀번호 입력\n\nPC/모바일에서 처음 한 번만 입력하면 브라우저에 저장됨.');
    if (pw === null) return;
    if (!pw.trim()) { showToast('비밀번호가 비어 있음'); return; }
    const data = await api('/api/set_password_settings', {enabled: '1', password: pw});
    showToast(data.message || '비밀번호 보호 ON 저장 완료');
    await loadSettings();
    renderSettingsPage();
}

async function changeAccessPassword() {
    const pw = prompt('새 접속 비밀번호 입력');
    if (pw === null) return;
    if (!pw.trim()) { showToast('비밀번호가 비어 있음'); return; }
    const data = await api('/api/set_password_settings', {enabled: '1', password: pw});
    showToast(data.message || '비밀번호 변경 완료. 기존 로그인 쿠키는 다시 인증이 필요할 수 있음');
    await loadSettings();
    renderSettingsPage();
}

async function setSiteCategory(encodedKey) {
    const key = decodeURIComponent(encodedKey);
    const site = settings.sites?.[key] || {};
    const input = categoryPrompt(site.category || 'other');
    if (input === null || !input) return;
    const data = await api('/api/set_site_category', {site: key, category: input});
    showToast(data.message || '사이트 기본분류 저장 완료');
    await loadSettings();
    renderSettingsPage();
}

async function addSite() {
    const url = prompt('추가할 사이트 주소 입력\n예: https://example123.com/', '');
    if (url === null || !url.trim()) return;
    const label = prompt('표시 이름 입력\n예: 새 사이트', '') || '';
    const data = await api('/api/add_site', {url, label});
    showToast(data.message || '사이트 추가 완료');
    await loadSettings();
    renderSettingsPage();
}

async function removeSite(encodedKey) {
    const key = decodeURIComponent(encodedKey);
    const site = settings.sites?.[key] || {};
    const label = site.label || key;
    if (!confirm(`사이트 추적에서 삭제할까?\n\n${label}\n\n기존 저장 작품은 지워지지 않고, 앞으로 방문기록만 안 읽음.`)) return;
    const data = await api('/api/remove_site', {site: key});
    showToast(data.message || '사이트 삭제 완료');
    await loadSettings();
    renderSettingsPage();
}

function renderRuntimeStatusBox() {
    const st = settings.status || {};
    const au = st.auto_update || {};
    return `
        <div class="settings-box">
            <h2>실행 상태</h2>
            <div class="small">서버 실행 정보를 확인하는 영역.</div>
            <div class="setting-row"><div><b>버전</b><div class="small">${escapeHtml(st.version || 'v0.1.14')}</div></div><span></span><span></span></div>
            <div class="setting-row"><div><b>서버 포트</b><div class="small">${escapeHtml(String(st.port || '-'))}</div></div><span></span><span></span></div>
            <div class="setting-row"><div><b>서버 시작</b><div class="small">${escapeHtml(st.server_started_at || st.started_at || '-')}</div></div><span></span><span></span></div>
            <div class="setting-row"><div><b>DB 위치</b><div class="small">${escapeHtml(st.db_path || '')}</div></div><span></span><span></span></div>
            <div class="setting-row"><div><b>자동 업데이트</b><div class="small">${au.enabled ? 'ON' : 'OFF'} · ${escapeHtml(String(au.interval_minutes || '-'))}분</div></div><span></span><span></span></div>
        </div>
    `;
}

function renderHelpPage() {
    count.textContent = '도움말';
    list.innerHTML = `
        <div class="settings-box"><h2>모바일에서 보기</h2><p>PC와 휴대폰을 같은 Wi-Fi에 연결한 뒤 설정 탭의 모바일 주소 링크를 누르거나 <b>복사</b> 버튼으로 주소를 복사해서 휴대폰 브라우저에 입력하면 됨. 접속이 안 되면 Windows Defender 방화벽이 막을 수 있음. 이때 06_Allow_Mobile_Access_Windows_Firewall.bat을 관리자 권한으로 실행하면 됨.</p></div>
        <div class="settings-box"><h2>비밀번호</h2><p>모바일이나 다른 기기에서 접속할 거면 설정에서 비밀번호 ON 권장. 한 번 로그인하면 해당 브라우저에 저장됨. 쿠키 삭제, 비밀번호 변경, 다른 브라우저 사용 시에는 다시 입력해야 함.</p></div>
        <div class="settings-box"><h2>업데이트</h2><p>서버가 켜져 있으면 자동 업데이트가 동작함. 바로 갱신하고 싶으면 관리 탭의 <b>지금 업데이트</b>를 누르면 됨. 업데이트 중에는 버튼이 잠시 <b>처리 중</b>으로 바뀜.</p></div>
        <div class="settings-box"><h2>백업/복원</h2><p>관리 탭에서 DB 백업 만들기, 백업 복원, DB 내보내기, DB 파일 가져오기를 할 수 있음. DB 복원/가져오기 전에는 현재 DB가 자동 백업되고, 완료 후 화면이 자동 새로고침됨.</p></div>
        <div class="settings-box"><h2>서버 종료/삭제</h2><p>서버를 끄려면 관리 탭의 <b>서버 종료</b> 또는 <b>05_Stop_Server.bat</b>를 사용. 완전히 지우려면 자동실행 해제 후 LocalReadLog 폴더를 삭제하면 됨.</p></div>
        <div class="settings-box"><h2>주의</h2><p>LocalReadLog는 개인 PC와 로컬 네트워크용 도구임. 공유기 포트포워딩으로 외부 인터넷에 공개하지 않는 것을 권장함.</p></div>
    `;
}
'''

try:
    INDEX_HTML = INDEX_HTML.replace('</style>', '\n.address-row{display:grid;grid-template-columns:1fr 72px;gap:8px;align-items:center;margin:5px 0}.address-row button{padding:7px 8px}.warn-box{background:#fff7ed;border:1px solid #fed7aa;border-radius:10px;padding:10px;margin:8px 0;color:#7c2d12}.warn-box button{margin-top:4px}\n</style>')
    INDEX_HTML = INDEX_HTML.replace('</script>', _V21_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v0.1.3 UX 보강 실패: {e}")
    except Exception:
        pass


# =========================
# v0.1.3 UI cleanup: storage -> Management, issue check -> Log
# =========================
LOCALREADLOG_VERSION = "v0.1.14"

_V012_JS = r'''

// =========================
// v0.1.3 UI cleanup: move storage to Management, issue check to Log
// =========================
function renderStorageLocationBlock() {
    return `
        <div class="settings-box">
            <h2>저장 위치</h2>
            <div class="small">DB/CSV/HTML/로그는 프로그램 폴더 안의 data 폴더에 저장됨.</div>
            <div style="word-break:break-all"><b>${escapeHtml(settings.backup_dir || '')}</b></div>
        </div>
    `;
}

function renderSettingsPage() {
    renderSettings();
    controls.style.display = 'none';
    prioritybar.style.display = 'none';
    if (browserbar) browserbar.style.display = 'none';

    const siteEntries = Object.entries(settings.sites || {});
    const priorityLabels = (settings.site_priority || []).map(k => settings.sites?.[k]?.label || settings.site_labels?.[k] || k);

    const siteRows = siteEntries.map(([key, site]) => {
        const enabled = site.enabled !== false;
        const host = site.host_re || site.prefix || key;
        const removable = key !== 'blacktoon';
        const catLabel = settings.category_labels?.[site.category || 'other'] || site.category || '기타';
        return `
            <div class="setting-row">
                <div>
                    <b>${escapeHtml(site.label || key)}</b>
                    <div class="small">${escapeHtml(key)} · ${escapeHtml(host)} · 기본분류 ${escapeHtml(catLabel)}</div>
                </div>
                <button class="${enabled ? '' : 'off'}" onclick="toggleSiteEnabled('${encodeURIComponent(key)}')">${enabled ? 'ON' : 'OFF'}</button>
                ${removable ? `<button class="danger" onclick="removeSite('${encodeURIComponent(key)}')">삭제</button>` : `<button onclick="setSiteCategory('${encodeURIComponent(key)}')">분류</button>`}
                ${removable ? `<button onclick="setSiteCategory('${encodeURIComponent(key)}')">분류</button>` : ''}
            </div>
        `;
    }).join('');

    const browserRows = Object.entries(settings.browser_labels || {}).map(([key, label]) => {
        const enabled = !!settings.browser_enabled?.[key];
        return `
            <div class="setting-row">
                <div><b>${escapeHtml(label)}</b></div>
                <button class="${enabled ? '' : 'off'}" onclick="toggleBrowserSync('${key}')">${enabled ? 'ON' : 'OFF'}</button>
                <span></span>
            </div>
        `;
    }).join('');

    count.textContent = '설정';
    list.innerHTML = `
        <div class="settings-box">
            <h2>사이트</h2>
            <div class="small">주소를 입력해서 추적 사이트를 추가함. 예: https://example123.com/</div>
            <div style="height:8px"></div>
            <button onclick="addSite()">사이트 추가</button>
            <div style="height:10px"></div>
            ${siteRows || '<div class="empty">등록된 사이트 없음</div>'}
        </div>

        <div class="settings-box">
            <h2>사이트 우선순위</h2>
            <div class="small">위아래로 드래그해서 순서를 바꾼 뒤 저장. 현재: ${escapeHtml(priorityLabels.join(' > '))}</div>
            <div id="priorityList" class="priority-list">${renderPriorityRows()}</div>
            <button onclick="saveDraggedSitePriority()">우선순위 저장</button>
            <button onclick="toggleDuplicateHiding()">중복숨김 ${settings.hide_site_duplicates ? 'ON' : 'OFF'}</button>
        </div>

        ${renderAddressBox()}
        ${renderAutoUpdateBox()}

        <div class="settings-box">
            <h2>접속 비밀번호</h2>
            <div class="small">모바일/다른 기기에서 접속할 때는 비밀번호 사용을 권장함. 공유기 외부 포트포워딩은 권장하지 않음. 한 번 입력하면 브라우저에 저장됨.</div>
            <div class="setting-row">
                <div><b>비밀번호 보호</b><div class="small">현재 상태: ${settings.password_enabled ? 'ON' : 'OFF'}</div></div>
                <button class="${settings.password_enabled ? '' : 'off'}" onclick="toggleAccessPassword()">${settings.password_enabled ? 'ON' : 'OFF'}</button>
                <button onclick="changeAccessPassword()">비밀번호 변경</button>
            </div>
        </div>

        <div class="settings-box"><h2>브라우저 연동</h2>${browserRows}</div>

        ${renderRuntimeStatusBox()}
    `;
}

async function renderManagePage() {
    count.textContent = '관리 도구';
    list.innerHTML = '<div class="empty">관리 정보 불러오는 중...</div>';
    const backups = await api('/api/backups').catch(() => ({backups:[]}));
    const compactBackups = (backups.backups || []).slice(0, 5);
    const backupRows = compactBackups.map(b => `
        <div class="setting-row wide-row backup-compact-row">
            <div><b>${escapeHtml(b.name)}</b><div class="small">${escapeHtml(b.modified)} · ${Math.round((b.size || 0)/1024)} KB</div></div>
            <button onclick="restoreDbBackup('${escapeHtml(b.name)}')">복원</button>
            <a class="mini-link" href="/api/download_backup/${encodeURIComponent(b.name)}">받기</a>
        </div>
    `).join('');
    list.innerHTML = `
        <div class="settings-box"><h2>빠른 작업</h2><div class="buttons"><button onclick="runBackupNow()">지금 업데이트</button><button onclick="createDbBackup()">DB 백업 만들기</button><button class="danger" onclick="shutdownFromUI()">서버 종료</button></div></div>
        <div class="settings-box"><h2>내보내기</h2><div class="buttons"><a href="/api/export/db">DB JSON 받기</a><a href="/api/export/csv">CSV 받기</a><a href="/api/export/mobile_html">모바일 HTML 받기</a><a href="/api/export/pc_html">PC HTML 받기</a></div></div>
        <div class="settings-box"><h2>DB 가져오기</h2><div class="small">다른 PC에서 내보낸 DB JSON 파일을 선택해서 가져오기. 현재 DB는 먼저 자동 백업됨.</div><input id="importDbFile" type="file" accept=".json,application/json"><div style="height:8px"></div><button onclick="importDbFromFile()">DB 파일 가져오기</button></div>
        ${renderStorageLocationBlock()}
        <div class="settings-box compact-backup-box"><h2>DB 백업 목록</h2><div class="small">최근 5개만 표시함. 오래된 백업은 data/backups 폴더에서 확인 가능.</div>${backupRows || '<div class="empty">백업 없음</div>'}</div>
        ${renderDiagnosticsBlock()}
        ${renderBrowserHistoryBlock()}
    `;
}

function renderIssueRowsForLog(issues) {
    const issueRows = (issues || []).map(i => `
        <div class="setting-row wide-row">
            <div><b>${escapeHtml(i.issue || '')}</b><div class="small">${escapeHtml(i.title || '')} · ${escapeHtml(i.detail || '')}</div></div>
            <span class="diag-warn">점검</span><span></span>
        </div>
    `).join('');
    return `<div class="settings-box"><h2>문제 있는 항목 점검</h2>${issueRows || '<div class="empty">점검 결과 문제 없음</div>'}</div>`;
}

function renderLog() {
    count.textContent = `${rows.length}줄`;
    const logText = escapeHtml((rows || []).join("\n") || "로그 없음");
    list.innerHTML = `<div id="logIssuesBox" class="empty">문제 항목 점검 불러오는 중...</div><pre class="logbox">${logText}</pre>`;
    api('/api/issues').then(data => {
        const box = document.getElementById('logIssuesBox');
        if (box) box.outerHTML = renderIssueRowsForLog(data.issues || []);
    }).catch(() => {
        const box = document.getElementById('logIssuesBox');
        if (box) box.outerHTML = '<div class="settings-box"><h2>문제 있는 항목 점검</h2><div class="empty">점검 정보를 불러오지 못함</div></div>';
    });
}

function renderHelpPage() {
    count.textContent = '도움말';
    list.innerHTML = `
        <div class="settings-box"><h2>모바일에서 보기</h2><p>PC와 휴대폰을 같은 Wi-Fi에 연결한 뒤 설정 탭의 모바일 주소 링크를 누르거나 휴대폰 브라우저에 입력하면 됨. 접속이 안 되면 Windows Defender 방화벽이 막을 수 있음. 이때 06_Allow_Mobile_Access_Windows_Firewall.bat을 관리자 권한으로 실행하면 됨.</p></div>
        <div class="settings-box"><h2>비밀번호</h2><p>모바일이나 다른 기기에서 접속할 거면 설정에서 비밀번호 ON 권장. 한 번 로그인하면 해당 브라우저에 저장됨. 쿠키 삭제, 비밀번호 변경, 다른 브라우저 사용 시에는 다시 입력해야 함.</p></div>
        <div class="settings-box"><h2>업데이트</h2><p>서버가 켜져 있으면 자동 업데이트가 동작함. 바로 갱신하고 싶으면 관리 탭의 <b>지금 업데이트</b>를 누르면 됨.</p></div>
        <div class="settings-box"><h2>백업/복원</h2><p>관리 탭에서 DB 백업 만들기, 백업 복원, DB 내보내기, DB 파일 가져오기를 할 수 있음. 저장 위치, 처음 실행 진단, 브라우저 기록 위치도 관리 탭에서 확인함.</p></div>
        <div class="settings-box"><h2>점검/로그</h2><p>문제 있는 항목 점검은 로그 탭 상단에서 확인함. URL 없음, 화수 없음, 중복 의심 같은 항목을 빠르게 볼 수 있음.</p></div>
        <div class="settings-box"><h2>서버 종료/삭제</h2><p>서버를 끄려면 관리 탭의 <b>서버 종료</b> 또는 <b>05_Stop_Server.bat</b>를 사용. 완전히 지우려면 자동실행 해제 후 LocalReadLog 폴더를 삭제하면 됨.</p></div>
        <div class="settings-box"><h2>주의</h2><p>LocalReadLog는 개인 PC와 로컬 네트워크용 도구임. 공유기 포트포워딩으로 외부 인터넷에 공개하지 않는 것을 권장함.</p></div>
    `;
}
'''
try:
    INDEX_HTML = INDEX_HTML.replace('</script>', _V012_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v0.1.3 UI 정리 실패: {e}")
    except Exception:
        pass


# =========================
# v0.1.3: Windows DB save retry
# =========================
# On Windows, a just-finished browser scan or another LocalReadLog process can keep
# localreadlog_db.json / .tmp locked briefly. Retry replace operations instead of
# failing immediately with WinError 32.
try:
    _prev_save_db_v013_retry
except NameError:
    _prev_save_db_v013_retry = save_db
    def save_db(db):
        last_error = None
        for attempt in range(6):
            try:
                return _prev_save_db_v013_retry(db)
            except PermissionError as e:
                last_error = e
                if getattr(e, 'winerror', None) not in (32, 33, 5):
                    raise
                time.sleep(0.35 * (attempt + 1))
            except OSError as e:
                last_error = e
                if getattr(e, 'winerror', None) not in (32, 33, 5):
                    raise
                time.sleep(0.35 * (attempt + 1))
        raise last_error


# =========================
# v0.1.9 release polish: local folder open buttons + final manage UI
# =========================
LOCALREADLOG_VERSION = "v0.1.14"

def _safe_start_local_path(target):
    try:
        target = Path(target)
        if not target.exists():
            return False, f"경로가 없음: {target}"
        if os.name == "nt":
            os.startfile(str(target))
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return True, f"열기 요청 완료: {target}"
    except Exception as e:
        return False, f"열기 실패: {e}"


def open_localreadlog_path(kind):
    kind = str(kind or "").strip().lower()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if kind == "data":
        return _safe_start_local_path(BACKUP_DIR)
    if kind == "backups":
        p = BACKUP_DIR / "backups"
        p.mkdir(parents=True, exist_ok=True)
        return _safe_start_local_path(p)
    if kind == "log":
        if not LOG_TXT.exists():
            try:
                LOG_TXT.write_text("", encoding="utf-8")
            except Exception:
                pass
        return _safe_start_local_path(LOG_TXT if LOG_TXT.exists() else BACKUP_DIR)
    return False, "알 수 없는 열기 대상"

try:
    _prev_handler_post_v015
except NameError:
    _prev_handler_post_v015 = Handler.do_POST

    def _v015_do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/open_local_path":
            if not _protected(self):
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            data = parse_qs(raw)
            ok, msg = open_localreadlog_path((data.get("kind") or [""])[0])
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return
        return _prev_handler_post_v015(self)

    Handler.do_POST = _v015_do_POST

_V015_JS = r'''

function renderFolderOpenBlock() {
    return `
        <div class="settings-box">
            <h2>폴더 열기</h2>
            <div class="small">DB, 백업, 로그 파일 위치를 바로 열 수 있음. Windows 로컬 실행에서만 동작함.</div>
            <div class="buttons">
                <button onclick="openLocalPath('data')">data 폴더 열기</button>
                <button onclick="openLocalPath('backups')">백업 폴더 열기</button>
                <button onclick="openLocalPath('log')">로그 파일 열기</button>
            </div>
        </div>
    `;
}

async function openLocalPath(kind) {
    const data = await api('/api/open_local_path', {kind});
    showToast(data.message || '열기 요청 완료');
}

function renderStorageLocationBlock() {
    return `
        <div class="settings-box">
            <h2>저장 위치</h2>
            <div class="small">DB/CSV/HTML/로그는 프로그램 폴더 안의 data 폴더에 저장됨.</div>
            <div style="word-break:break-all"><b>${escapeHtml(settings.backup_dir || '')}</b></div>
        </div>
    `;
}

async function renderManagePage() {
    count.textContent = '관리 도구';
    list.innerHTML = '<div class="empty">관리 정보 불러오는 중...</div>';
    const backups = await api('/api/backups').catch(() => ({backups:[]}));
    const compactBackups = (backups.backups || []).slice(0, 5);
    const backupRows = compactBackups.map(b => `
        <div class="setting-row wide-row backup-compact-row">
            <div><b>${escapeHtml(b.name)}</b><div class="small">${escapeHtml(b.modified)} · ${Math.round((b.size || 0)/1024)} KB</div></div>
            <button onclick="restoreDbBackup('${escapeHtml(b.name)}')">복원</button>
            <a class="mini-link" href="/api/download_backup/${encodeURIComponent(b.name)}">받기</a>
        </div>
    `).join('');
    list.innerHTML = `
        <div class="settings-box"><h2>빠른 작업</h2><div class="buttons"><button onclick="runBackupNow()">지금 업데이트</button><button onclick="createDbBackup()">DB 백업 만들기</button><button class="danger" onclick="shutdownFromUI()">서버 종료</button></div></div>
        <div class="settings-box"><h2>내보내기</h2><div class="buttons"><a href="/api/export/db">DB JSON 받기</a><a href="/api/export/csv">CSV 받기</a><a href="/api/export/mobile_html">모바일 HTML 받기</a><a href="/api/export/pc_html">PC HTML 받기</a></div></div>
        <div class="settings-box"><h2>DB 가져오기</h2><div class="small">다른 PC에서 내보낸 DB JSON 파일을 선택해서 가져오기. 현재 DB는 먼저 자동 백업됨.</div><input id="importDbFile" type="file" accept=".json,application/json"><div style="height:8px"></div><button onclick="importDbFromFile()">DB 파일 가져오기</button></div>
        ${renderStorageLocationBlock()}
        ${renderFolderOpenBlock()}
        <div class="settings-box compact-backup-box"><h2>DB 백업 목록</h2><div class="small">최근 5개만 표시함. 전체 백업은 백업 폴더에서 확인 가능.</div>${backupRows || '<div class="empty">백업 없음</div>'}</div>
        ${renderDiagnosticsBlock()}
        ${renderBrowserHistoryBlock()}
    `;
}

'''
try:
    INDEX_HTML = INDEX_HTML.replace('</script>', _V015_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v0.1.9 UI 보강 실패: {e}")
    except Exception:
        pass


# =========================
# v0.1.9: mobile address classification
# =========================
LOCALREADLOG_VERSION = "v0.1.14"

import ipaddress

_VIRTUAL_ADAPTER_KEYWORDS = [
    "hyper-v", "vethernet", "default switch", "wsl", "docker", "vmware",
    "virtualbox", "virtual", "loopback", "npcap", "tap", "tailscale", "zerotier"
]


def _is_private_ipv4(ip):
    try:
        obj = ipaddress.ip_address(str(ip))
        return obj.version == 4 and obj.is_private and not obj.is_loopback and not obj.is_link_local
    except Exception:
        return False


def _is_172_private(ip):
    try:
        parts = str(ip).split('.')
        return len(parts) == 4 and int(parts[0]) == 172 and 16 <= int(parts[1]) <= 31
    except Exception:
        return False


def _primary_lan_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.2)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if _is_private_ipv4(ip):
            return ip
    except Exception:
        pass
    return ""


def _decode_subprocess_bytes(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    for enc in ("utf-8-sig", "utf-8", "cp949", "mbcs"):
        try:
            return value.decode(enc)
        except Exception:
            continue
    return value.decode("utf-8", errors="replace")


def _windows_ip_candidates():
    candidates = []
    if os.name != "nt":
        return candidates
    ps = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$items = @()
Get-NetIPConfiguration -ErrorAction SilentlyContinue | ForEach-Object {
  $alias = $_.InterfaceAlias
  $desc = $_.InterfaceDescription
  foreach ($addr in ($_.IPv4Address | Where-Object { $_.IPAddress -and $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' })) {
    $items += [PSCustomObject]@{ InterfaceAlias=$alias; InterfaceDescription=$desc; IPAddress=$addr.IPAddress }
  }
}
$items | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            timeout=4,
        )
        raw = _decode_subprocess_bytes(result.stdout).strip()
        if not raw:
            return candidates
        # PowerShell may prepend non-JSON noise in unusual environments. Keep only JSON-looking payload.
        first_obj = raw.find("{")
        first_arr = raw.find("[")
        starts = [x for x in [first_obj, first_arr] if x >= 0]
        if starts:
            raw = raw[min(starts):]
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        for row in data if isinstance(data, list) else []:
            if not isinstance(row, dict):
                continue
            ip = str(row.get("IPAddress", "") or "").strip()
            if not _is_private_ipv4(ip):
                continue
            candidates.append({
                "ip": ip,
                "adapter": str(row.get("InterfaceAlias", "") or "").strip(),
                "description": str(row.get("InterfaceDescription", "") or "").strip(),
                "source": "windows",
            })
    except Exception as e:
        try:
            append_log(f"모바일 주소 Windows 네트워크 조회 실패: {e}")
        except Exception:
            pass
    return candidates


def _socket_ip_candidates():
    rows = []
    seen = set()

    def add(ip, source="socket"):
        ip = str(ip or "").strip()
        if not _is_private_ipv4(ip) or ip in seen:
            return
        seen.add(ip)
        rows.append({"ip": ip, "adapter": "", "description": "", "source": source})

    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, family=socket.AF_INET):
            add(info[4][0], "hostname")
    except Exception:
        pass

    primary = _primary_lan_ip()
    if primary:
        add(primary, "default_route")
    return rows


def get_mobile_address_candidates(port=None):
    if port is None:
        port = globals().get("CURRENT_SERVER_PORT", PORT)
    primary = _primary_lan_ip()
    raw_rows = _windows_ip_candidates() or _socket_ip_candidates()
    if primary and all(r.get("ip") != primary for r in raw_rows):
        raw_rows.insert(0, {"ip": primary, "adapter": "기본 네트워크", "description": "", "source": "default_route"})

    seen = set()
    output = []
    for row in raw_rows:
        ip = str(row.get("ip", "") or "").strip()
        if not ip or ip in seen or not _is_private_ipv4(ip):
            continue
        seen.add(ip)
        adapter = str(row.get("adapter", "") or "").strip()
        desc = str(row.get("description", "") or "").strip()
        haystack = f"{adapter} {desc}".lower()
        virtual = any(k in haystack for k in _VIRTUAL_ADAPTER_KEYWORDS)
        recommended = False
        reason = ""

        if ip == primary:
            recommended = True
            reason = "추천: 현재 PC의 기본 네트워크 주소"
        elif virtual:
            recommended = False
            reason = "모바일 접속용 아님: 가상 어댑터 주소로 보임"
        elif ip.startswith("192.168.") or ip.startswith("10."):
            recommended = True
            reason = "추천 가능: 일반 로컬 네트워크 주소"
        elif _is_172_private(ip):
            recommended = False
            reason = "모바일 접속용 아님: 보조/가상 네트워크 주소일 가능성이 큼"
        else:
            recommended = False
            reason = "모바일 접속용인지 확인 필요"

        output.append({
            "ip": ip,
            "url": f"http://{ip}:{port}",
            "adapter": adapter,
            "description": desc,
            "recommended": recommended,
            "reason": reason,
        })

    if output and not any(x.get("recommended") for x in output) and primary:
        for x in output:
            if x.get("ip") == primary:
                x["recommended"] = True
                x["reason"] = "추천: 현재 PC의 기본 네트워크 주소"
                break
    return output


def get_local_ip_addresses():
    candidates = get_mobile_address_candidates(globals().get("CURRENT_SERVER_PORT", PORT))
    recommended = [x["ip"] for x in candidates if x.get("recommended")]
    if recommended:
        return recommended
    return [x["ip"] for x in candidates]

try:
    _prev_get_status_payload_v019
except NameError:
    _prev_get_status_payload_v019 = get_status_payload
    def get_status_payload():
        payload = _prev_get_status_payload_v019()
        port = payload.get("port") or globals().get("CURRENT_SERVER_PORT", PORT)
        candidates = get_mobile_address_candidates(port)
        recommended = [x for x in candidates if x.get("recommended")]
        other = [x for x in candidates if not x.get("recommended")]
        payload["mobile_address_candidates"] = candidates
        payload["mobile_recommended_urls"] = [x["url"] for x in recommended]
        payload["mobile_other_urls"] = [x["url"] for x in other]
        payload["mobile_urls"] = [x["url"] for x in recommended] or [x["url"] for x in candidates]
        try:
            diag = payload.get("diagnostics") or {}
            for check in diag.get("checks", []):
                if check.get("name") == "모바일 주소":
                    if recommended:
                        check["detail"] = ", ".join(x["url"] for x in recommended)
                    elif candidates:
                        check["detail"] = "추천 주소 없음 / " + ", ".join(x["url"] for x in candidates)
                    else:
                        check["detail"] = "PC IP를 찾지 못함"
            payload["diagnostics"] = diag
        except Exception:
            pass
        return payload

_V019_JS = r"""
function mobileAddressRows(items, label) {
    if (!Array.isArray(items) || !items.length) return '<div class="empty">주소 없음</div>';
    return items.map((item) => {
        const obj = (typeof item === 'string') ? {url:item, recommended:true, reason:'추천 주소'} : (item || {});
        const url = String(obj.url || '').trim();
        if (!url) return '';
        const safe = escapeHtml(url);
        const copyArg = encodeURIComponent(url);
        const reason = escapeHtml(obj.reason || (obj.recommended ? '추천 주소' : '모바일 접속용 아님'));
        const adapter = escapeHtml(obj.adapter || obj.description || '');
        const badge = obj.recommended ? '<span class="addr-badge good">추천</span>' : '<span class="addr-badge muted">제외</span>';
        const cls = obj.recommended ? 'address-row addr-recommended' : 'address-row addr-not-recommended';
        const link = obj.recommended
            ? `<a class="text-link" href="${safe}" target="_blank" rel="noopener noreferrer">${safe}</a>`
            : `<span class="muted-address">${safe}</span>`;
        return `<div class="${cls}">
            <div>${badge} ${link}<div class="addr-meta">${reason}${adapter ? ' · ' + adapter : ''}</div></div>
            <button onclick="copyTextToClipboard(decodeURIComponent('${copyArg}'), '${label}')">복사</button>
        </div>`;
    }).join('');
}

function renderAddressBox() {
    const st = settings.status || {};
    const candidates = Array.isArray(st.mobile_address_candidates) ? st.mobile_address_candidates : [];
    const recommended = candidates.filter(x => x && x.recommended);
    const others = candidates.filter(x => x && !x.recommended);
    const fallbackMobile = recommended.length ? recommended : (Array.isArray(st.mobile_urls) ? st.mobile_urls : []);
    const passwordWarning = settings.password_enabled ? '' : `
        <div class="warn-box">
            <b>비밀번호가 꺼져 있음</b><br>
            모바일이나 다른 기기에서 접속할 거면 비밀번호 ON을 권장함.
            <div style="height:8px"></div>
            <button onclick="toggleAccessPassword()">비밀번호 설정</button>
        </div>`;
    const otherBlock = others.length ? `
        <div style="height:10px"></div>
        <div class="small">모바일 접속용으로 쓰지 않는 주소</div>
        <div class="link-list">${mobileAddressRows(others, '제외 주소')}</div>
        <div class="small">Hyper-V, WSL, Docker, VMware 같은 가상 어댑터 주소는 휴대폰에서 접속되지 않을 수 있음.</div>
    ` : '';
    return `
        <div class="settings-box">
            <h2>접속 주소</h2>
            ${passwordWarning}
            <div class="small">PC에서 보기</div>
            <div class="link-list">${addressRows(st.pc_urls || [], 'PC 주소')}</div>
            <div style="height:10px"></div>
            <div class="small">모바일 추천 주소. 휴대폰과 PC가 같은 Wi-Fi여야 함.</div>
            <div class="link-list">${mobileAddressRows(fallbackMobile, '모바일 주소')}</div>
            ${otherBlock}
        </div>
    `;
}
"""
try:
    INDEX_HTML = INDEX_HTML.replace('</style>', '\n.addr-badge{display:inline-block;font-size:11px;border-radius:999px;padding:2px 6px;margin-right:6px}.addr-badge.good{background:#dcfce7;color:#166534}.addr-badge.muted{background:#e5e7eb;color:#374151}.addr-meta{font-size:12px;color:#666;margin-top:3px}.muted-address{color:#555;word-break:break-all}.addr-not-recommended{opacity:.88}\n</style>')
    INDEX_HTML = INDEX_HTML.replace('</script>', _V019_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v0.1.9 모바일 주소 표시 보강 실패: {e}")
    except Exception:
        pass



# =========================
# 관리 탭 문제 점검 위치 정리
# =========================
LOCALREADLOG_VERSION = "v0.1.14"

_V0110_JS = r"""
function renderIssueRowsForManage(issues) {
    const issueRows = (issues || []).map(i => `
        <div class="setting-row wide-row">
            <div><b>${escapeHtml(i.issue || '')}</b><div class="small">${escapeHtml(i.title || '')} · ${escapeHtml(i.detail || '')}</div></div>
            <span class="diag-warn">점검</span><span></span>
        </div>
    `).join('');
    return `<div class="settings-box"><h2>문제 있는 항목 점검</h2><div class="small">URL 없음, 화수 없음, 화수 급상승, 중복 의심 같은 항목을 확인함.</div>${issueRows || '<div class="empty">점검 결과 문제 없음</div>'}</div>`;
}

async function renderManagePage() {
    count.textContent = '관리 도구';
    list.innerHTML = '<div class="empty">관리 정보 불러오는 중...</div>';
    const [backups, issues] = await Promise.all([
        api('/api/backups').catch(() => ({backups:[]})),
        api('/api/issues').catch(() => ({issues:[]})),
    ]);
    const compactBackups = (backups.backups || []).slice(0, 5);
    const backupRows = compactBackups.map(b => `
        <div class="setting-row wide-row backup-compact-row">
            <div><b>${escapeHtml(b.name)}</b><div class="small">${escapeHtml(b.modified)} · ${Math.round((b.size || 0)/1024)} KB</div></div>
            <button onclick="restoreDbBackup('${escapeHtml(b.name)}')">복원</button>
            <a class="mini-link" href="/api/download_backup/${encodeURIComponent(b.name)}">받기</a>
        </div>
    `).join('');
    list.innerHTML = `
        <div class="settings-box"><h2>빠른 작업</h2><div class="buttons"><button onclick="runBackupNow()">지금 업데이트</button><button onclick="createDbBackup()">DB 백업 만들기</button><button class="danger" onclick="shutdownFromUI()">서버 종료</button></div></div>
        <div class="settings-box"><h2>내보내기</h2><div class="buttons"><a href="/api/export/db">DB JSON 받기</a><a href="/api/export/csv">CSV 받기</a><a href="/api/export/mobile_html">모바일 HTML 받기</a><a href="/api/export/pc_html">PC HTML 받기</a></div></div>
        <div class="settings-box"><h2>DB 가져오기</h2><div class="small">다른 PC에서 내보낸 DB JSON 파일을 선택해서 가져오기. 현재 DB는 먼저 자동 백업됨.</div><input id="importDbFile" type="file" accept=".json,application/json"><div style="height:8px"></div><button onclick="importDbFromFile()">DB 파일 가져오기</button></div>
        ${renderStorageLocationBlock()}
        ${renderFolderOpenBlock()}
        <div class="settings-box compact-backup-box"><h2>DB 백업 목록</h2><div class="small">최근 5개만 표시함. 전체 백업은 백업 폴더에서 확인 가능.</div>${backupRows || '<div class="empty">백업 없음</div>'}</div>
        ${renderDiagnosticsBlock()}
        ${renderBrowserHistoryBlock()}
        ${renderIssueRowsForManage(issues.issues || [])}
    `;
}

function renderLog() {
    count.textContent = `${rows.length}줄`;
    const logText = escapeHtml((rows || []).join("\n") || "로그 없음");
    list.innerHTML = `<pre class="logbox">${logText}</pre>`;
}

function renderHelpPage() {
    count.textContent = '도움말';
    list.innerHTML = `
        <div class="settings-box"><h2>모바일에서 보기</h2><p>PC와 휴대폰을 같은 Wi-Fi에 연결한 뒤 설정 탭의 모바일 추천 주소를 휴대폰 브라우저에 입력하면 됨. 접속이 안 되면 Windows Defender 방화벽이 막을 수 있음. 이때 06_Allow_Mobile_Access_Windows_Firewall.bat을 관리자 권한으로 실행하면 됨.</p></div>
        <div class="settings-box"><h2>비밀번호</h2><p>모바일이나 다른 기기에서 접속할 거면 설정에서 비밀번호 ON 권장. 한 번 로그인하면 해당 브라우저에 저장됨. 쿠키 삭제, 비밀번호 변경, 다른 브라우저 사용 시에는 다시 입력해야 함.</p></div>
        <div class="settings-box"><h2>업데이트</h2><p>서버가 켜져 있으면 자동 업데이트가 동작함. 바로 갱신하고 싶으면 관리 탭의 <b>지금 업데이트</b>를 누르면 됨.</p></div>
        <div class="settings-box"><h2>백업/복원</h2><p>관리 탭에서 DB 백업 만들기, 백업 복원, DB 내보내기, DB 파일 가져오기를 할 수 있음. 저장 위치, 처음 실행 진단, 브라우저 기록 위치도 관리 탭에서 확인함.</p></div>
        <div class="settings-box"><h2>문제 점검</h2><p>문제 있는 항목 점검은 관리 탭에서 확인함. URL 없음, 화수 없음, 중복 의심 같은 항목을 빠르게 볼 수 있음.</p></div>
        <div class="settings-box"><h2>서버 종료/삭제</h2><p>서버를 끄려면 관리 탭의 <b>서버 종료</b> 또는 <b>05_Stop_Server.bat</b>를 사용. 완전히 지우려면 자동실행 해제 후 LocalReadLog 폴더를 삭제하면 됨.</p></div>
        <div class="settings-box"><h2>주의</h2><p>LocalReadLog는 개인 PC와 로컬 네트워크용 도구임. 공유기 포트포워딩으로 외부 인터넷에 공개하지 않는 것을 권장함.</p></div>
    `;
}
"""
try:
    INDEX_HTML = INDEX_HTML.replace('</script>', _V0110_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML 관리 탭 점검 이동 실패: {e}")
    except Exception:
        pass



# =========================
# v0.1.12: 모바일 주소/상태 조회 캐시로 화면 속도 개선
# =========================
LOCALREADLOG_VERSION = "v0.1.14"
_MOBILE_ADDRESS_CACHE = {
    "at": 0.0,
    "port": None,
    "items": None,
}
_MOBILE_ADDRESS_CACHE_SECONDS = 300

try:
    _prev_get_mobile_address_candidates_v012
except NameError:
    _prev_get_mobile_address_candidates_v012 = get_mobile_address_candidates

    def get_mobile_address_candidates(port=None, force_refresh=False):
        if port is None:
            port = globals().get("CURRENT_SERVER_PORT", PORT)
        now_value = time.time()
        try:
            cached_items = _MOBILE_ADDRESS_CACHE.get("items")
            cached_port = _MOBILE_ADDRESS_CACHE.get("port")
            cached_at = float(_MOBILE_ADDRESS_CACHE.get("at") or 0)
            if (not force_refresh and cached_items is not None and cached_port == port and (now_value - cached_at) < _MOBILE_ADDRESS_CACHE_SECONDS):
                return [dict(x) for x in cached_items]
        except Exception:
            pass

        try:
            items = _prev_get_mobile_address_candidates_v012(port)
        except Exception as e:
            try:
                append_log(f"모바일 주소 조회 실패: {e}")
            except Exception:
                pass
            items = []

        try:
            _MOBILE_ADDRESS_CACHE.update({"at": now_value, "port": port, "items": [dict(x) for x in items]})
        except Exception:
            pass
        return items

try:
    _prev_get_local_ip_addresses_v012
except NameError:
    _prev_get_local_ip_addresses_v012 = get_local_ip_addresses

    def get_local_ip_addresses():
        candidates = get_mobile_address_candidates(globals().get("CURRENT_SERVER_PORT", PORT))
        recommended = [x.get("ip") for x in candidates if x.get("recommended") and x.get("ip")]
        if recommended:
            return recommended
        return [x.get("ip") for x in candidates if x.get("ip")]

try:
    _prev_handler_get_v012_perf
except NameError:
    _prev_handler_get_v012_perf = Handler.do_GET

    def _v012_perf_do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/refresh_mobile_addresses":
            if '_is_authenticated' in globals() and not _is_authenticated(self):
                json_response(self, {"ok": False, "auth_required": True, "message": "비밀번호 필요"}, status=401)
                return
            port = globals().get("CURRENT_SERVER_PORT", PORT)
            items = get_mobile_address_candidates(port, force_refresh=True)
            json_response(self, {"ok": True, "items": items, "message": "모바일 주소를 다시 확인했습니다."})
            return
        return _prev_handler_get_v012_perf(self)

    Handler.do_GET = _v012_perf_do_GET


# =========================
# v0.1.14: 화면 속도 개선 캐시
# =========================
LOCALREADLOG_VERSION = "v0.1.14"

try:
    _LRL_CACHE_LOCK
except NameError:
    _LRL_CACHE_LOCK = threading.RLock()
    _LRL_DB_CACHE = {"key": None, "db": None, "at": 0.0}
    _LRL_ROW_CACHE = {}
    _LRL_MISC_CACHE = {}


def _lrl_db_file_key():
    try:
        st = DB_JSON.stat()
        return (int(st.st_mtime_ns), int(st.st_size))
    except Exception:
        return None


def _lrl_clear_fast_caches():
    try:
        with _LRL_CACHE_LOCK:
            _LRL_ROW_CACHE.clear()
            _LRL_MISC_CACHE.clear()
    except Exception:
        pass

try:
    _prev_ensure_db_v013
except NameError:
    _prev_ensure_db_v013 = ensure_db

    def ensure_db():
        """읽기 요청에서 DB 전체 정리/저장을 반복하지 않도록 캐시한다."""
        try:
            if DB_JSON.exists():
                key = _lrl_db_file_key()
                now_value = time.time()
                with _LRL_CACHE_LOCK:
                    cached = _LRL_DB_CACHE.get("db")
                    cached_key = _LRL_DB_CACHE.get("key")
                    cached_at = float(_LRL_DB_CACHE.get("at") or 0)
                    if cached is not None and cached_key == key and (now_value - cached_at) < 15:
                        return cached
                db = load_db()
                with _LRL_CACHE_LOCK:
                    _LRL_DB_CACHE.update({"key": key, "db": db, "at": now_value})
                return db
        except Exception:
            pass
        db = _prev_ensure_db_v013()
        try:
            with _LRL_CACHE_LOCK:
                _LRL_DB_CACHE.update({"key": _lrl_db_file_key(), "db": db, "at": time.time()})
        except Exception:
            pass
        return db

try:
    _prev_save_db_v013
except NameError:
    _prev_save_db_v013 = save_db

    def save_db(db):
        result = _prev_save_db_v013(db)
        try:
            with _LRL_CACHE_LOCK:
                _LRL_DB_CACHE.update({"key": _lrl_db_file_key(), "db": db, "at": time.time()})
                _LRL_ROW_CACHE.clear()
                _LRL_MISC_CACHE.clear()
        except Exception:
            pass
        return result

try:
    _prev_get_rows_by_status_v013
except NameError:
    _prev_get_rows_by_status_v013 = get_rows_by_status

    def get_rows_by_status(status):
        key = ("rows", str(status), _lrl_db_file_key())
        now_value = time.time()
        try:
            with _LRL_CACHE_LOCK:
                item = _LRL_ROW_CACHE.get(key)
                if item and (now_value - item.get("at", 0)) < 8:
                    return item.get("value", [])
        except Exception:
            pass
        value = _prev_get_rows_by_status_v013(status)
        try:
            with _LRL_CACHE_LOCK:
                _LRL_ROW_CACHE[key] = {"at": now_value, "value": value}
        except Exception:
            pass
        return value

try:
    _prev_get_issue_rows_v013
except NameError:
    _prev_get_issue_rows_v013 = get_issue_rows

    def get_issue_rows():
        key = ("issues", _lrl_db_file_key())
        now_value = time.time()
        try:
            with _LRL_CACHE_LOCK:
                item = _LRL_MISC_CACHE.get(key)
                if item and (now_value - item.get("at", 0)) < 15:
                    return item.get("value", [])
        except Exception:
            pass
        value = _prev_get_issue_rows_v013()
        try:
            with _LRL_CACHE_LOCK:
                _LRL_MISC_CACHE[key] = {"at": now_value, "value": value}
        except Exception:
            pass
        return value

try:
    _prev_get_status_payload_v013
except NameError:
    _prev_get_status_payload_v013 = get_status_payload

    def get_status_payload():
        key = ("status", _lrl_db_file_key(), globals().get("CURRENT_SERVER_PORT", PORT))
        now_value = time.time()
        try:
            with _LRL_CACHE_LOCK:
                item = _LRL_MISC_CACHE.get(key)
                if item and (now_value - item.get("at", 0)) < 5:
                    return dict(item.get("value", {}))
        except Exception:
            pass
        value = _prev_get_status_payload_v013()
        try:
            with _LRL_CACHE_LOCK:
                _LRL_MISC_CACHE[key] = {"at": now_value, "value": dict(value)}
        except Exception:
            pass
        return value

try:
    _prev_handler_post_v013_cache
except NameError:
    _prev_handler_post_v013_cache = Handler.do_POST

    def _v013_cache_do_POST(self):
        # 상태 변경/설정 저장/업데이트 후 캐시가 남아 있지 않게 한다.
        try:
            return _prev_handler_post_v013_cache(self)
        finally:
            _lrl_clear_fast_caches()

    Handler.do_POST = _v013_cache_do_POST


# =========================
# v0.1.14: 화수 없는 방문기록은 최신 화수로 기록하지 않음
# =========================
def _lrl_valid_episode_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        n = float(text)
    except Exception:
        return ""
    if n <= 0:
        return ""
    if n.is_integer():
        return str(int(n))
    return str(n)


def _lrl_drop_invalid_episode_fields(item):
    if not isinstance(item, dict):
        return item

    item["latest_episode"] = _lrl_valid_episode_text(item.get("latest_episode", ""))
    item["locked_episode"] = _lrl_valid_episode_text(item.get("locked_episode", ""))

    cleaned_history = {}
    history = item.get("episode_history", {}) or {}
    if isinstance(history, dict):
        for ep, record in history.items():
            ep_key = _lrl_valid_episode_text(ep) or _lrl_valid_episode_text((record or {}).get("episode", "") if isinstance(record, dict) else "")
            if not ep_key:
                continue
            if isinstance(record, dict):
                rec = dict(record)
                rec["episode"] = ep_key
                cleaned_history[ep_key] = rec
    item["episode_history"] = cleaned_history

    blocked = []
    for ep in item.get("blocked_episodes", []) or []:
        ep_key = _lrl_valid_episode_text(ep)
        if ep_key:
            blocked.append(ep_key)
    item["blocked_episodes"] = blocked

    return item

try:
    _prev_normalize_item_strict_episode_v014
except NameError:
    _prev_normalize_item_strict_episode_v014 = normalize_item

    def normalize_item(item):
        return _lrl_drop_invalid_episode_fields(_prev_normalize_item_strict_episode_v014(item))

try:
    _prev_item_to_row_strict_episode_v014
except NameError:
    _prev_item_to_row_strict_episode_v014 = item_to_row

    def item_to_row(item):
        row = _prev_item_to_row_strict_episode_v014(item)
        row["latest_episode"] = _lrl_valid_episode_text(row.get("latest_episode", ""))
        row["locked_episode"] = _lrl_valid_episode_text(row.get("locked_episode", ""))
        return row

try:
    _prev_save_db_strict_episode_v014
except NameError:
    _prev_save_db_strict_episode_v014 = save_db

    def save_db(db):
        try:
            for item in (db.get("items", {}) or {}).values():
                if isinstance(item, dict):
                    _lrl_drop_invalid_episode_fields(item)
        except Exception:
            pass
        return _prev_save_db_strict_episode_v014(db)



# =========================
# v0.1.21: blank episode rows + generic numbered domain defaults
# =========================
LOCALREADLOG_VERSION = "v0.1.21"

try:
    DEFAULT_SITE_SPECS.setdefault("sbxh", {
        "label": "SBXH",
        "prefix": "sbxh",
        "host_re": r"sbxh\d+\.com",
        "enabled": True,
        "dynamic": True,
        "category": "other",
    })
except Exception:
    pass

try:
    if "sbxh" not in FORCE_LATEST_HOSTS:
        FORCE_LATEST_HOSTS["sbxh"] = ""
except Exception:
    pass

try:
    _prev_normalize_site_specs_v021
except NameError:
    _prev_normalize_site_specs_v021 = normalize_site_specs

    def normalize_site_specs(raw_sites):
        sites = _prev_normalize_site_specs_v021(raw_sites)
        sites.setdefault("sbxh", {
            "label": "SBXH",
            "prefix": "sbxh",
            "host_re": r"sbxh\d+\.com",
            "enabled": True,
            "dynamic": True,
            "category": "other",
        })
        return sites

try:
    SITE_SPECS = normalize_site_specs(SITE_SPECS)
except Exception:
    pass

try:
    _prev_get_issue_rows_blank_episode_ok_v021
except NameError:
    _prev_get_issue_rows_blank_episode_ok_v021 = get_issue_rows

    def get_issue_rows():
        rows = _prev_get_issue_rows_blank_episode_ok_v021()
        return [row for row in rows if str(row.get("issue", "")) != "화수 없음"]

try:
    _prev_get_recent_rows_blank_episode_v021
except NameError:
    _prev_get_recent_rows_blank_episode_v021 = get_recent_rows

    def get_recent_rows(limit=10):
        rows = get_rows_by_status("active")
        rows = sorted(rows, key=lambda r: str(r.get("last_seen", "")), reverse=True)
        return rows[:max(1, min(int(limit), 100))]

try:
    _prev_get_rows_by_status_blank_episode_v021
except NameError:
    _prev_get_rows_by_status_blank_episode_v021 = get_rows_by_status

    def get_rows_by_status(status):
        rows = _prev_get_rows_by_status_blank_episode_v021(status)
        for row in rows:
            if isinstance(row, dict):
                row["latest_episode"] = _lrl_valid_episode_text(row.get("latest_episode", ""))
        return rows

# 현재/삭제 목록 버튼 줄과 빈 화수 표시를 최종 UI에서 보정.
_V021_JS = r'''
function lrlEpisodeText(ep) {
    const value = String(ep || '').trim();
    return value ? value + '화' : '';
}
function lrlActionButtons(r, encodedTitle) {
    if (mode === 'current') {
        return `
            <button class="edit" onclick="openEpisodePicker('${encodedTitle}')">화수선택</button>
            <button class="category-edit" onclick="editCategory('${encodedTitle}')">분류</button>
            <button class="edit" onclick="editTitleOnly('${encodedTitle}')">제목수정</button>
            <button class="danger" onclick="deleteTitle('${encodedTitle}')">삭제</button>
        `;
    }
    return `
        <button class="edit" onclick="openEpisodePicker('${encodedTitle}')">화수선택</button>
        <button class="category-edit" onclick="editCategory('${encodedTitle}')">분류</button>
        <button class="edit" onclick="editTitleOnly('${encodedTitle}')">제목수정</button>
        <button class="restore" onclick="restoreTitle('${encodedTitle}')">복구</button>
        <button class="purge" onclick="purgeTitle('${encodedTitle}')">완전삭제</button>
    `;
}
function render() {
    const q = search.value.trim().toLowerCase();
    let filtered = rows.filter(r => {
        const text = `${r.title || ''} ${(r.aliases || []).join(' ')} ${r.latest_episode || ''} ${r.last_seen || ''} ${r.category_label || ''}`.toLowerCase();
        return !q || text.includes(q);
    });

    filtered = sortedRows(filtered);
    count.textContent = `${filtered.length}개 표시 / 전체 ${rows.length}개`;

    if (!filtered.length) {
        list.innerHTML = '<div class="empty">표시할 항목 없음</div>';
        return;
    }

    list.innerHTML = bulkToolbar() + filtered.map((r, idx) => {
        const displayTitle = stripSitePrefixFromTitle(r.title || '');
        const title = escapeHtml(displayTitle || r.title || '');
        const siteTag = escapeHtml(r.site_label || r.site || '사이트');
        const categoryTag = escapeHtml(r.category_label || r.category || '기타');
        const encodedTitle = encodeURIComponent(r.title || '');
        const epText = lrlEpisodeText(r.latest_episode || '');
        const epTag = epText ? `<span class="ep-tag">${escapeHtml(epText)}</span>` : '';
        const lastSeen = escapeHtml(r.last_seen || '');
        const url = escapeHtml(r.url || '');
        const histCount = (r.episode_history || []).length;
        const lockedText = r.locked_episode ? lrlEpisodeText(r.locked_episode) : '';
        const lockText = r.locked_episode ? `<div class="locked-note">선택 고정: ${escapeHtml(lockedText)} · 저장된 화수 ${histCount}개</div>` : `<div class="aliases">저장된 화수: ${histCount}개</div>`;
        const duplicateText = r.hidden_duplicate_count
            ? `<div class="aliases">사이트 중복 ${escapeHtml(r.hidden_duplicate_count)}개 숨김: ${escapeHtml((r.hidden_duplicate_sites || []).join(', '))}</div>`
            : '';
        const openButton = r.url ? `<a href="${url}" target="_blank">열기</a>` : '';
        const actionButtons = lrlActionButtons(r, encodedTitle);
        const checkbox = `<label class="row-check"><input class="row-select" type="checkbox" value="${escapeHtml(r.title || '')}"> 선택</label>`;

        return `
        <div class="card">
            <div class="title-line">
                <div class="title-wrap">
                    <span class="site-tag">${siteTag}</span>
                    <span class="category-tag">${categoryTag}</span>
                    <div class="title">${title}</div>
                    ${epTag}
                </div>
            </div>
            ${lockText}
            ${duplicateText}
            <div class="meta">
                <span>최근: ${lastSeen || '-'}</span>
            </div>
            <div class="buttons">
                ${checkbox}
                ${openButton}
                ${actionButtons}
            </div>
        </div>
        `;
    }).join('');
}
'''
try:
    INDEX_HTML = INDEX_HTML.replace('</script>', _V021_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v0.1.21 UI 보정 실패: {e}")
    except Exception:
        pass



# =========================
# v0.1.22: 설정 탭 사이트 이름 수정 + 사이트 기본분류 현재 목록 반영
# =========================
LOCALREADLOG_VERSION = "v0.1.22"


def _lrl_effective_category_for_item(item):
    # 수동 분류가 아니면 현재 사이트 설정을 반영한 표시 분류를 계산한다.
    item = dict(item or {})
    manual = item.get("manual", {}) if isinstance(item.get("manual", {}), dict) else {}

    if manual.get("category"):
        return normalize_category(item.get("category", "other"))

    inferred = infer_category_from_text(
        item.get("url", ""),
        item.get("__removed_link__", ""),
        item.get("title", ""),
    )
    if inferred != "other":
        return inferred

    return site_default_category(item_site_key(item))


try:
    _prev_item_to_row_site_settings_v022
except NameError:
    _prev_item_to_row_site_settings_v022 = item_to_row

    def item_to_row(item):
        row = _prev_item_to_row_site_settings_v022(item)
        try:
            site_key = row.get("site") or item_site_key(item)
            row["site"] = site_key
            row["site_label"] = site_label(site_key)

            category_key = _lrl_effective_category_for_item(item)
            row["category"] = category_key
            row["category_label"] = CATEGORY_LABELS.get(category_key, "기타")
        except Exception:
            pass
        return row


def set_site_label(site_key, label):
    db = ensure_db()
    db = normalize_settings(db)

    site_key = str(site_key or "").strip()
    label = clean_title(label)

    if not label:
        return False, "사이트 이름이 비어 있음"

    sites = db.setdefault("settings", {}).setdefault("sites", {})
    if site_key not in sites:
        return False, "사이트를 못 찾음"

    old_label = sites[site_key].get("label", site_key)
    sites[site_key]["label"] = label
    sync_global_site_specs(db)
    save_db(db)

    try:
        _lrl_clear_fast_caches()
    except Exception:
        pass

    append_log(f"사이트 이름 변경: {old_label} → {label}")
    return True, f"사이트 이름 변경: {label}"


try:
    _prev_set_site_category_v022
except NameError:
    _prev_set_site_category_v022 = set_site_category

    def set_site_category(site_key, category):
        db = ensure_db()
        db = normalize_settings(db)

        site_key = str(site_key or "").strip()
        sites = db.setdefault("settings", {}).setdefault("sites", {})

        if site_key not in sites:
            return False, "사이트를 못 찾음"

        category_key = normalize_category(category)
        old_category = normalize_category(sites[site_key].get("category", "other"))
        sites[site_key]["category"] = category_key
        sync_global_site_specs(db)

        affected = 0
        changed = 0
        for key, item in list((db.get("items", {}) or {}).items()):
            if not isinstance(item, dict):
                continue
            try:
                if item_site_key(item) != site_key:
                    continue
                old_item_category = normalize_category(item.get("category", "other"))
                item = normalize_item(item)
                manual = item.get("manual", {}) if isinstance(item.get("manual", {}), dict) else {}
                if manual.get("category"):
                    continue

                new_item_category = _lrl_effective_category_for_item(item)
                item["category"] = new_item_category
                item["updated_at"] = now_text()
                db["items"][key] = item
                affected += 1
                if old_item_category != new_item_category:
                    changed += 1
            except Exception:
                continue

        save_db(db)
        sync_txt_from_db(db)

        try:
            _lrl_clear_fast_caches()
        except Exception:
            pass

        label = sites[site_key].get("label", site_key)
        append_log(
            f"사이트 기본분류 변경: {label} / "
            f"{CATEGORY_LABELS.get(old_category, old_category)} → {CATEGORY_LABELS.get(category_key, category_key)} / "
            f"현재 목록 갱신 대상 {affected}개 / 실제 변경 {changed}개"
        )
        return True, f"사이트 기본분류: {CATEGORY_LABELS.get(category_key, '기타')} · 현재 목록 갱신 대상 {affected}개"


try:
    _prev_handler_post_v022_site_settings
except NameError:
    _prev_handler_post_v022_site_settings = Handler.do_POST

    def _v022_site_settings_do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/set_site_label":
            if '_protected' in globals() and not _protected(self):
                return

            val = _read_urlencoded_form(self) if '_read_urlencoded_form' in globals() else None
            if val is None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length).decode("utf-8", errors="replace")
                form = parse_qs(body)
                val = lambda name: (form.get(name) or [""])[0]

            ok, msg = set_site_label(val("site"), val("label"))
            json_response(self, {"ok": ok, "message": msg}, status=200 if ok else 400)
            return

        return _prev_handler_post_v022_site_settings(self)

    Handler.do_POST = _v022_site_settings_do_POST


_V022_JS = r'''
function lrlSiteEntriesInPriorityOrder() {
    const sites = settings.sites || {};
    const priority = Array.isArray(settings.site_priority) ? settings.site_priority : [];
    const result = [];
    const seen = new Set();
    priority.forEach(key => {
        if (sites[key] && !seen.has(key)) {
            seen.add(key);
            result.push([key, sites[key]]);
        }
    });
    Object.entries(sites).forEach(([key, site]) => {
        if (!seen.has(key)) result.push([key, site]);
    });
    return result;
}

async function editSiteLabel(encodedKey) {
    const key = decodeURIComponent(encodedKey);
    const site = settings.sites?.[key] || {};
    const current = site.label || key;
    const input = prompt('사이트 표시 이름 입력', current);
    if (input === null) return;
    const label = input.trim();
    if (!label) {
        showToast('사이트 이름이 비어 있음');
        return;
    }
    const data = await api('/api/set_site_label', {site: key, label});
    showToast(data.message || '사이트 이름 저장 완료');
    await loadSettings();
    if (mode === 'settings') renderSettingsPage();
    else await reloadList();
}

async function setSiteCategory(encodedKey) {
    const key = decodeURIComponent(encodedKey);
    const site = settings.sites?.[key] || {};
    const input = categoryPrompt(site.category || 'other');
    if (input === null || !input) return;
    const data = await api('/api/set_site_category', {site: key, category: input});
    showToast(data.message || '사이트 기본분류 저장 완료');
    await loadSettings();
    if (mode === 'settings') renderSettingsPage();
    else await reloadList();
}

function renderSettingsPage() {
    renderSettings();
    controls.style.display = 'none';
    prioritybar.style.display = 'none';
    if (browserbar) browserbar.style.display = 'none';

    const siteEntries = lrlSiteEntriesInPriorityOrder();
    const priorityLabels = (settings.site_priority || []).map(k => settings.sites?.[k]?.label || settings.site_labels?.[k] || k);

    const siteRows = siteEntries.map(([key, site]) => {
        const enabled = site.enabled !== false;
        const host = site.host_re || site.prefix || key;
        const removable = key !== 'blacktoon';
        const catLabel = settings.category_labels?.[site.category || 'other'] || site.category || '기타';
        return `
            <div class="setting-row site-setting-row">
                <div>
                    <b>${escapeHtml(site.label || key)}</b>
                    <div class="small">${escapeHtml(key)} · ${escapeHtml(host)} · 기본분류 ${escapeHtml(catLabel)}</div>
                </div>
                <button class="${enabled ? '' : 'off'}" onclick="toggleSiteEnabled('${encodeURIComponent(key)}')">${enabled ? 'ON' : 'OFF'}</button>
                <button onclick="editSiteLabel('${encodeURIComponent(key)}')">이름</button>
                <button onclick="setSiteCategory('${encodeURIComponent(key)}')">분류</button>
                ${removable ? `<button class="danger" onclick="removeSite('${encodeURIComponent(key)}')">삭제</button>` : '<span></span>'}
            </div>
        `;
    }).join('');

    const browserRows = Object.entries(settings.browser_labels || {}).map(([key, label]) => {
        const enabled = !!settings.browser_enabled?.[key];
        return `
            <div class="setting-row">
                <div><b>${escapeHtml(label)}</b></div>
                <button class="${enabled ? '' : 'off'}" onclick="toggleBrowserSync('${key}')">${enabled ? 'ON' : 'OFF'}</button>
                <span></span>
                <span></span>
            </div>
        `;
    }).join('');

    const addressBlock = (typeof renderAddressBox === 'function') ? renderAddressBox() : '';
    const autoUpdateBlock = (typeof renderAutoUpdateBox === 'function') ? renderAutoUpdateBox() : '';
    const runtimeBlock = (typeof renderRuntimeStatusBox === 'function') ? renderRuntimeStatusBox() : '';

    count.textContent = '설정';
    list.innerHTML = `
        <div class="settings-box">
            <h2>사이트</h2>
            <div class="small">주소를 입력해서 추적 사이트를 추가함. 사이트 이름과 기본분류는 여기서 수정함.</div>
            <div style="height:8px"></div>
            <button onclick="addSite()">사이트 추가</button>
            <div style="height:10px"></div>
            ${siteRows || '<div class="empty">등록된 사이트 없음</div>'}
        </div>

        <div class="settings-box">
            <h2>사이트 우선순위</h2>
            <div class="small">위아래로 드래그해서 순서를 바꾼 뒤 저장. 현재: ${escapeHtml(priorityLabels.join(' > '))}</div>
            <div id="priorityList" class="priority-list">${renderPriorityRows()}</div>
            <button onclick="saveDraggedSitePriority()">우선순위 저장</button>
            <button onclick="toggleDuplicateHiding()">중복숨김 ${settings.hide_site_duplicates ? 'ON' : 'OFF'}</button>
        </div>

        ${addressBlock}
        ${autoUpdateBlock}

        <div class="settings-box">
            <h2>접속 비밀번호</h2>
            <div class="small">모바일/다른 기기에서 접속할 때는 비밀번호 사용을 권장함. 공유기 외부 포트포워딩은 권장하지 않음.</div>
            <div class="setting-row">
                <div><b>비밀번호 보호</b><div class="small">현재 상태: ${settings.password_enabled ? 'ON' : 'OFF'}</div></div>
                <button class="${settings.password_enabled ? '' : 'off'}" onclick="toggleAccessPassword()">${settings.password_enabled ? 'ON' : 'OFF'}</button>
                <button onclick="changeAccessPassword()">변경</button>
                <span></span>
            </div>
        </div>

        <div class="settings-box"><h2>브라우저 연동</h2>${browserRows}</div>

        ${runtimeBlock}
    `;
}
'''

try:
    INDEX_HTML = INDEX_HTML.replace('</style>', '\n.site-setting-row{grid-template-columns:1fr 72px 72px 72px 72px}.site-setting-row span{display:block}\n@media(max-width:700px){.site-setting-row{grid-template-columns:1fr 62px 62px 62px 62px}.site-setting-row button{padding-left:4px;padding-right:4px;font-size:11px}}\n</style>')
    INDEX_HTML = INDEX_HTML.replace('</script>', _V022_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v0.1.22 사이트 설정 UI 보강 실패: {e}")
    except Exception:
        pass

# =========================
# v0.1.23: 목록 페이지네이션 + 오래된 순 정렬
# =========================
LOCALREADLOG_VERSION = "v0.1.23"

_V023_JS = r'''
let lrlPage = 1;
let lrlPageSize = 100;
let lrlLastFilterKey = '';

function lrlEnsurePaginationControls() {
    if (!controls || document.getElementById('pageSize')) return;

    const pageSize = document.createElement('select');
    pageSize.id = 'pageSize';
    pageSize.innerHTML = `
        <option value="50">50개씩</option>
        <option value="100" selected>100개씩</option>
        <option value="200">200개씩</option>
        <option value="500">500개씩</option>
        <option value="0">전체</option>
    `;
    pageSize.addEventListener('change', () => {
        lrlPageSize = Number(pageSize.value || 100);
        lrlPage = 1;
        render();
    });
    controls.appendChild(pageSize);

    const pager = document.createElement('div');
    pager.id = 'pager';
    pager.className = 'pager';
    const top = document.querySelector('.top');
    if (top && count) {
        top.insertBefore(pager, count.nextSibling);
    }
}

function lrlEnsureOldSortOption() {
    if (!sort) return;

    const oldUpdated = [...sort.options].find(opt => opt.value === 'updated_desc');
    if (oldUpdated) {
        oldUpdated.value = 'last_seen_asc';
        oldUpdated.textContent = '오래된 순';
    }

    if (![...sort.options].some(opt => opt.value === 'updated_desc')) {
        const opt = document.createElement('option');
        opt.value = 'updated_desc';
        opt.textContent = '수정일 최신순';
        sort.appendChild(opt);
    }

    if (![...sort.options].some(opt => opt.value === 'updated_asc')) {
        const opt = document.createElement('option');
        opt.value = 'updated_asc';
        opt.textContent = '수정일 오래된순';
        sort.appendChild(opt);
    }
}

function lrlResetPageIfFilterChanged(q, s) {
    const key = `${mode}|${q}|${s}|${lrlPageSize}`;
    if (key !== lrlLastFilterKey) {
        lrlPage = 1;
        lrlLastFilterKey = key;
    }
}

function lrlPageRows(input) {
    const size = Number(lrlPageSize || 0);
    if (!size || size <= 0) {
        return {pageRows: input, totalPages: 1, start: input.length ? 1 : 0, end: input.length};
    }

    const totalPages = Math.max(1, Math.ceil(input.length / size));
    if (lrlPage > totalPages) lrlPage = totalPages;
    if (lrlPage < 1) lrlPage = 1;

    const startIndex = (lrlPage - 1) * size;
    const endIndex = Math.min(startIndex + size, input.length);
    return {
        pageRows: input.slice(startIndex, endIndex),
        totalPages,
        start: input.length ? startIndex + 1 : 0,
        end: endIndex
    };
}

function lrlRenderPager(totalRows, totalPages, start, end) {
    lrlEnsurePaginationControls();
    const pager = document.getElementById('pager');
    if (!pager) return;

    if (!totalRows || totalPages <= 1) {
        pager.innerHTML = '';
        pager.style.display = 'none';
        return;
    }

    pager.style.display = 'grid';
    const pageButtons = [];
    const candidates = new Set([1, lrlPage - 2, lrlPage - 1, lrlPage, lrlPage + 1, lrlPage + 2, totalPages]);
    [...candidates]
        .filter(n => n >= 1 && n <= totalPages)
        .sort((a, b) => a - b)
        .forEach((n, idx, arr) => {
            if (idx > 0 && n - arr[idx - 1] > 1) {
                pageButtons.push(`<span class="pager-gap">...</span>`);
            }
            pageButtons.push(`<button class="${n === lrlPage ? 'active' : ''}" onclick="lrlGoPage(${n})">${n}</button>`);
        });

    pager.innerHTML = `
        <button onclick="lrlGoPage(${Math.max(1, lrlPage - 1)})" ${lrlPage <= 1 ? 'disabled' : ''}>이전</button>
        <div class="pager-pages">${pageButtons.join('')}</div>
        <button onclick="lrlGoPage(${Math.min(totalPages, lrlPage + 1)})" ${lrlPage >= totalPages ? 'disabled' : ''}>다음</button>
        <div class="pager-info">${start}-${end} / ${totalRows}</div>
    `;
}

function lrlGoPage(page) {
    lrlPage = Number(page || 1);
    render();
    window.scrollTo({top: 0, behavior: 'smooth'});
}

const lrlPrevSetModeV023 = setMode;
setMode = function(nextMode) {
    lrlPage = 1;
    lrlLastFilterKey = '';
    return lrlPrevSetModeV023(nextMode);
};

function sortedRows(input) {
    const s = sort.value;
    const copy = [...input];

    if (s === 'title_asc') {
        copy.sort((a, b) => String(a.title || '').localeCompare(String(b.title || ''), 'ko'));
    } else if (s === 'episode_desc') {
        copy.sort((a, b) => epNum(b.latest_episode) - epNum(a.latest_episode));
    } else if (s === 'updated_desc') {
        copy.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    } else if (s === 'updated_asc') {
        copy.sort((a, b) => String(a.updated_at || '').localeCompare(String(b.updated_at || '')));
    } else if (s === 'last_seen_asc') {
        copy.sort((a, b) => String(a.last_seen || '').localeCompare(String(b.last_seen || '')));
    } else {
        copy.sort((a, b) => String(b.last_seen || '').localeCompare(String(a.last_seen || '')));
    }

    return copy;
}


function bulkToolbar() {
    if (!rows.length) return '';
    const restoreBtn = mode === 'deleted'
        ? `<button class="restore" onclick="bulkAction('restore')">선택 복구</button><button class="purge" onclick="bulkAction('purge')">선택 완전삭제</button>`
        : `<button class="danger" onclick="bulkAction('delete')">선택 삭제</button>`;
    return `<div class="settings-box bulk-box"><h2>현재 페이지 선택 처리</h2><div class="buttons"><button onclick="toggleAllRows(true)">현재페이지 전체선택</button><button onclick="toggleAllRows(false)">선택해제</button>${restoreBtn}<button class="edit" onclick="bulkCategory()">선택 분류변경</button></div></div>`;
}

function render() {
    lrlEnsurePaginationControls();
    lrlEnsureOldSortOption();

    const q = search.value.trim().toLowerCase();
    const s = sort.value;
    lrlResetPageIfFilterChanged(q, s);

    let filtered = rows.filter(r => {
        const text = `${r.title || ''} ${(r.aliases || []).join(' ')} ${r.latest_episode || ''} ${r.last_seen || ''} ${r.updated_at || ''} ${r.category_label || ''}`.toLowerCase();
        return !q || text.includes(q);
    });

    filtered = sortedRows(filtered);
    const pageData = lrlPageRows(filtered);

    count.textContent = `${filtered.length}개 표시 / 전체 ${rows.length}개` + (filtered.length ? ` · ${pageData.start}-${pageData.end}번째` : '');
    lrlRenderPager(filtered.length, pageData.totalPages, pageData.start, pageData.end);

    if (!filtered.length) {
        list.innerHTML = '<div class="empty">표시할 항목 없음</div>';
        return;
    }

    list.innerHTML = bulkToolbar() + pageData.pageRows.map((r, idx) => {
        const displayTitle = stripSitePrefixFromTitle(r.title || '');
        const title = escapeHtml(displayTitle || r.title || '');
        const siteTag = escapeHtml(r.site_label || r.site || '사이트');
        const categoryTag = escapeHtml(r.category_label || r.category || '기타');
        const encodedTitle = encodeURIComponent(r.title || '');
        const epText = lrlEpisodeText(r.latest_episode || '');
        const epTag = epText ? `<span class="ep-tag">${escapeHtml(epText)}</span>` : '';
        const lastSeen = escapeHtml(r.last_seen || '');
        const updatedAt = escapeHtml(r.updated_at || '');
        const url = escapeHtml(r.url || '');
        const histCount = (r.episode_history || []).length;
        const lockedText = r.locked_episode ? lrlEpisodeText(r.locked_episode) : '';
        const lockText = r.locked_episode ? `<div class="locked-note">선택 고정: ${escapeHtml(lockedText)} · 저장된 화수 ${histCount}개</div>` : `<div class="aliases">저장된 화수: ${histCount}개</div>`;
        const duplicateText = r.hidden_duplicate_count
            ? `<div class="aliases">사이트 중복 ${escapeHtml(r.hidden_duplicate_count)}개 숨김: ${escapeHtml((r.hidden_duplicate_sites || []).join(', '))}</div>`
            : '';
        const openButton = r.url ? `<a href="${url}" target="_blank">열기</a>` : '';
        const actionButtons = lrlActionButtons(r, encodedTitle);
        const checkbox = `<label class="row-check"><input class="row-select" type="checkbox" value="${escapeHtml(r.title || '')}"> 선택</label>`;

        return `
        <div class="card">
            <div class="title-line">
                <div class="title-wrap">
                    <span class="site-tag">${siteTag}</span>
                    <span class="category-tag">${categoryTag}</span>
                    <div class="title">${title}</div>
                    ${epTag}
                </div>
            </div>
            ${lockText}
            ${duplicateText}
            <div class="meta">
                <span>최근: ${lastSeen || '-'}</span>
                <span>수정: ${updatedAt || '-'}</span>
            </div>
            <div class="buttons">
                ${checkbox}
                ${openButton}
                ${actionButtons}
            </div>
        </div>
        `;
    }).join('');
}

// v0.1.24에서 정렬/페이지/분류 컨트롤을 최종 초기화함.
'''

try:
    INDEX_HTML = INDEX_HTML.replace('</style>', '''
#pageSize {
    box-sizing: border-box;
    padding: 12px;
    border: 1px solid #ccc;
    border-radius: 10px;
    font-size: 15px;
}
.pager {
    display: none;
    grid-template-columns: 66px 1fr 66px;
    gap: 8px;
    align-items: center;
    margin: 8px 0;
}
.pager button {
    border: 0;
    padding: 9px 6px;
    border-radius: 9px;
    background: #222;
    color: white;
    font-weight: 800;
    cursor: pointer;
    font-size: 12px;
}
.pager button:disabled {
    background: #bbb;
    cursor: default;
}
.pager button.active {
    background: #1f4e79;
}
.pager-pages {
    display: flex;
    justify-content: center;
    gap: 5px;
    flex-wrap: wrap;
}
.pager-info {
    grid-column: 1 / -1;
    text-align: center;
    font-size: 12px;
    color: #666;
    font-weight: 800;
}
.pager-gap {
    padding: 7px 2px;
    color: #777;
    font-weight: 900;
}
@media (min-width: 620px) {
    .controls {
        grid-template-columns: 1fr 145px 105px;
    }
}
@media (max-width: 619px) {
    .controls {
        grid-template-columns: 1fr 1fr;
    }
    #search {
        grid-column: 1 / -1;
    }
    .pager {
        grid-template-columns: 58px 1fr 58px;
    }
}
</style>''')
    INDEX_HTML = INDEX_HTML.replace('</script>', _V023_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v0.1.23 페이지네이션 UI 보강 실패: {e}")
    except Exception:
        pass


# =========================
# v0.1.24: 정렬 옵션 중복 정리 + 분류별 보기
# =========================
LOCALREADLOG_VERSION = "v0.1.24"

_V024_JS = r'''
const LRL_CATEGORY_OPTIONS = [
    ['all', '전체 분류'],
    ['webtoon', '웹툰'],
    ['comic', '만화'],
    ['manga', '망가'],
    ['novel', '소설'],
    ['anime', '애니'],
    ['other', '기타']
];

function lrlNormalizeSortOptions() {
    if (!sort) return;
    const current = sort.value || localStorage.getItem('lrl.sort') || 'last_seen_desc';
    const fixed = [
        ['last_seen_desc', '최근 본 순'],
        ['last_seen_asc', '오래된 순'],
        ['title_asc', '제목 순'],
        ['episode_desc', '화수 높은 순'],
        ['updated_desc', '수정일 최신순'],
        ['updated_asc', '수정일 오래된순']
    ];
    sort.innerHTML = fixed.map(([value, label]) => `<option value="${value}">${label}</option>`).join('');
    sort.value = fixed.some(([value]) => value === current) ? current : 'last_seen_desc';
}

function lrlEnsureOldSortOption() {
    lrlNormalizeSortOptions();
}

function lrlEnsurePaginationControls() {
    if (!controls) return;

    let categoryFilter = document.getElementById('categoryFilter');
    if (!categoryFilter) {
        categoryFilter = document.createElement('select');
        categoryFilter.id = 'categoryFilter';
        const savedCategory = localStorage.getItem('lrl.categoryFilter') || 'all';
        categoryFilter.innerHTML = LRL_CATEGORY_OPTIONS
            .map(([value, label]) => `<option value="${value}">${label}</option>`)
            .join('');
        categoryFilter.value = LRL_CATEGORY_OPTIONS.some(([value]) => value === savedCategory) ? savedCategory : 'all';
        categoryFilter.onchange = () => {
            try { localStorage.setItem('lrl.categoryFilter', categoryFilter.value); } catch(e) {}
            lrlPage = 1;
            render();
        };
        controls.appendChild(categoryFilter);
    } else {
        categoryFilter.onchange = () => {
            try { localStorage.setItem('lrl.categoryFilter', categoryFilter.value); } catch(e) {}
            lrlPage = 1;
            render();
        };
    }

    let pageSize = document.getElementById('pageSize');
    if (!pageSize) {
        pageSize = document.createElement('select');
        pageSize.id = 'pageSize';
        const savedSize = localStorage.getItem('lrl.pageSize') || String(lrlPageSize || 100);
        pageSize.innerHTML = `
            <option value="50">50개씩</option>
            <option value="100">100개씩</option>
            <option value="200">200개씩</option>
            <option value="500">500개씩</option>
            <option value="0">전체</option>
        `;
        pageSize.value = ['50', '100', '200', '500', '0'].includes(savedSize) ? savedSize : '100';
        lrlPageSize = Number(pageSize.value || 100);
        pageSize.onchange = () => {
            lrlPageSize = Number(pageSize.value || 100);
            try { localStorage.setItem('lrl.pageSize', pageSize.value); } catch(e) {}
            lrlPage = 1;
            render();
        };
        controls.appendChild(pageSize);
    } else {
        pageSize.onchange = () => {
            lrlPageSize = Number(pageSize.value || 100);
            try { localStorage.setItem('lrl.pageSize', pageSize.value); } catch(e) {}
            lrlPage = 1;
            render();
        };
    }

    let pager = document.getElementById('pager');
    if (!pager) {
        pager = document.createElement('div');
        pager.id = 'pager';
        pager.className = 'pager';
        const top = document.querySelector('.top');
        if (top && count) top.insertBefore(pager, count.nextSibling);
    }
}

function lrlCurrentCategoryFilter() {
    const el = document.getElementById('categoryFilter');
    return el ? (el.value || 'all') : 'all';
}

function lrlResetPageIfFilterChanged(q, s, c) {
    const key = `${mode}|${q}|${s}|${c}|${lrlPageSize}`;
    if (key !== lrlLastFilterKey) {
        lrlPage = 1;
        lrlLastFilterKey = key;
    }
}

function render() {
    lrlEnsurePaginationControls();
    lrlEnsureOldSortOption();

    const q = search.value.trim().toLowerCase();
    const s = sort.value;
    const c = lrlCurrentCategoryFilter();
    lrlResetPageIfFilterChanged(q, s, c);

    let filtered = rows.filter(r => {
        const rowCategory = String(r.category || 'other');
        if (c !== 'all' && rowCategory !== c) return false;
        const text = `${r.title || ''} ${(r.aliases || []).join(' ')} ${r.latest_episode || ''} ${r.last_seen || ''} ${r.updated_at || ''} ${r.category_label || ''}`.toLowerCase();
        return !q || text.includes(q);
    });

    filtered = sortedRows(filtered);
    const pageData = lrlPageRows(filtered);
    const categoryLabel = c === 'all'
        ? ''
        : ` · ${escapeHtml((settings.category_labels || {})[c] || c)}`;

    count.textContent = `${filtered.length}개 표시 / 전체 ${rows.length}개${categoryLabel}` + (filtered.length ? ` · ${pageData.start}-${pageData.end}번째` : '');
    lrlRenderPager(filtered.length, pageData.totalPages, pageData.start, pageData.end);

    if (!filtered.length) {
        list.innerHTML = '<div class="empty">표시할 항목 없음</div>';
        return;
    }

    list.innerHTML = bulkToolbar() + pageData.pageRows.map((r, idx) => {
        const displayTitle = stripSitePrefixFromTitle(r.title || '');
        const title = escapeHtml(displayTitle || r.title || '');
        const siteTag = escapeHtml(r.site_label || r.site || '사이트');
        const categoryTag = escapeHtml(r.category_label || r.category || '기타');
        const encodedTitle = encodeURIComponent(r.title || '');
        const epText = lrlEpisodeText(r.latest_episode || '');
        const epTag = epText ? `<span class="ep-tag">${escapeHtml(epText)}</span>` : '';
        const lastSeen = escapeHtml(r.last_seen || '');
        const updatedAt = escapeHtml(r.updated_at || '');
        const url = escapeHtml(r.url || '');
        const histCount = (r.episode_history || []).length;
        const lockedText = r.locked_episode ? lrlEpisodeText(r.locked_episode) : '';
        const lockText = r.locked_episode ? `<div class="locked-note">선택 고정: ${escapeHtml(lockedText)} · 저장된 화수 ${histCount}개</div>` : `<div class="aliases">저장된 화수: ${histCount}개</div>`;
        const duplicateText = r.hidden_duplicate_count
            ? `<div class="aliases">사이트 중복 ${escapeHtml(r.hidden_duplicate_count)}개 숨김: ${escapeHtml((r.hidden_duplicate_sites || []).join(', '))}</div>`
            : '';
        const openButton = r.url ? `<a href="${url}" target="_blank">열기</a>` : '';
        const actionButtons = lrlActionButtons(r, encodedTitle);
        const checkbox = `<label class="row-check"><input class="row-select" type="checkbox" value="${escapeHtml(r.title || '')}"> 선택</label>`;

        return `
        <div class="card">
            <div class="title-line">
                <div class="title-wrap">
                    <span class="site-tag">${siteTag}</span>
                    <span class="category-tag">${categoryTag}</span>
                    <div class="title">${title}</div>
                    ${epTag}
                </div>
            </div>
            ${lockText}
            ${duplicateText}
            <div class="meta">
                <span>최근: ${lastSeen || '-'}</span>
                <span>수정: ${updatedAt || '-'}</span>
            </div>
            <div class="buttons">
                ${checkbox}
                ${openButton}
                ${actionButtons}
            </div>
        </div>
        `;
    }).join('');
}

lrlNormalizeSortOptions();
lrlEnsurePaginationControls();
'''

try:
    INDEX_HTML = INDEX_HTML.replace('</style>', '''
#categoryFilter,
#pageSize {
    box-sizing: border-box;
    padding: 12px;
    border: 1px solid #ccc;
    border-radius: 10px;
    font-size: 15px;
    background: white;
}
@media (min-width: 620px) {
    .controls {
        grid-template-columns: 1fr 145px 120px 105px;
    }
}
@media (max-width: 619px) {
    .controls {
        grid-template-columns: 1fr 1fr;
    }
    #search {
        grid-column: 1 / -1;
    }
}
</style>''')
    INDEX_HTML = INDEX_HTML.replace('</script>', _V024_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v0.1.24 정렬/분류 필터 보강 실패: {e}")
    except Exception:
        pass


# =========================
# v0.1.25: 분류 드롭다운 변경 + 분류 관리 + 설정 사이트 분류 필터
# =========================
LOCALREADLOG_VERSION = "v0.1.26"

try:
    DEFAULT_CATEGORY_LABELS_V025
except NameError:
    DEFAULT_CATEGORY_LABELS_V025 = dict(CATEGORY_LABELS)
    DEFAULT_CATEGORY_ALIASES_V025 = dict(CATEGORY_ALIASES)


def _lrl_category_key_from_label(label):
    label = clean_title(label)
    if not label:
        return ""
    base = re.sub(r"[^a-z0-9_]+", "_", label.strip().lower())
    base = re.sub(r"_+", "_", base).strip("_")
    if not base:
        digest = hashlib.md5(label.encode("utf-8", errors="ignore")).hexdigest()[:10]
        base = f"custom_{digest}"
    if base in ["all", "none", "null", "undefined"]:
        base = f"category_{base}"
    return base[:48] or "other"


def _lrl_merge_category_labels(raw_labels=None):
    labels = dict(DEFAULT_CATEGORY_LABELS_V025)
    if isinstance(raw_labels, dict):
        for raw_key, raw_label in raw_labels.items():
            label = clean_title(raw_label)
            if not label:
                continue
            key = _lrl_category_key_from_label(raw_key) or _lrl_category_key_from_label(label)
            if not key:
                continue
            labels[key] = label
    return labels


def _lrl_sync_category_globals(db=None):
    global CATEGORY_LABELS, CATEGORY_ALIASES
    raw_labels = None
    if isinstance(db, dict):
        raw_labels = db.get("settings", {}).get("category_labels")
    labels = _lrl_merge_category_labels(raw_labels)

    CATEGORY_LABELS.clear()
    CATEGORY_LABELS.update(labels)

    CATEGORY_ALIASES.clear()
    CATEGORY_ALIASES.update(DEFAULT_CATEGORY_ALIASES_V025)
    for key, label in labels.items():
        CATEGORY_ALIASES[str(key).lower()] = key
        CATEGORY_ALIASES[str(label).strip().lower()] = key

    return labels


try:
    _prev_normalize_category_v025
except NameError:
    _prev_normalize_category_v025 = normalize_category

    def normalize_category(value):
        raw = str(value or "").strip()
        if not raw:
            return "other"

        token = raw.lower()
        if token in CATEGORY_LABELS:
            return token
        if token in CATEGORY_ALIASES:
            return CATEGORY_ALIASES[token]

        for key, label in CATEGORY_LABELS.items():
            if token == str(label or "").strip().lower():
                return key

        key = _lrl_category_key_from_label(raw)
        if key in CATEGORY_LABELS:
            return key

        # 이미 저장된 사용자 분류 키는 DB 정규화 과정에서 기타로 덮어쓰지 않도록 보존한다.
        if re.fullmatch(r"[a-z0-9_]{3,64}", token) and token not in {"all", "none", "null"}:
            return token

        return "other"


try:
    _prev_normalize_settings_v025
except NameError:
    _prev_normalize_settings_v025 = normalize_settings

    def normalize_settings(db):
        db = _prev_normalize_settings_v025(db)
        settings = db.setdefault("settings", {})
        labels = _lrl_merge_category_labels(settings.get("category_labels"))
        settings["category_labels"] = labels
        _lrl_sync_category_globals(db)
        return db


try:
    _prev_get_settings_payload_v025
except NameError:
    _prev_get_settings_payload_v025 = get_settings_payload

    def get_settings_payload():
        payload = _prev_get_settings_payload_v025()
        try:
            db = ensure_db()
            db = normalize_settings(db)
            labels = _lrl_sync_category_globals(db)
            payload["category_labels"] = dict(labels)
            payload["sites"] = db.get("settings", {}).get("sites", SITE_SPECS)
            payload["site_labels"] = {k: v.get("label", k) for k, v in SITE_SPECS.items()}
        except Exception:
            payload["category_labels"] = dict(CATEGORY_LABELS)
        return payload


def add_category_label(label):
    db = ensure_db()
    db = normalize_settings(db)
    label = clean_title(label)
    if not label:
        return False, "분류 이름이 비어 있음", ""

    settings = db.setdefault("settings", {})
    labels = settings.setdefault("category_labels", _lrl_merge_category_labels())

    for key, old_label in labels.items():
        if str(old_label).strip().lower() == label.lower():
            return True, f"이미 있는 분류: {old_label}", key

    key = _lrl_category_key_from_label(label)
    base = key
    idx = 2
    while key in labels:
        key = f"{base}_{idx}"
        idx += 1

    labels[key] = label
    settings["category_labels"] = _lrl_merge_category_labels(labels)
    _lrl_sync_category_globals(db)
    save_db(db)
    append_log(f"분류 추가: {label} ({key})")
    return True, f"분류 추가: {label}", key


def set_category_label(category_key, label):
    db = ensure_db()
    db = normalize_settings(db)
    label = clean_title(label)
    if not label:
        return False, "분류 이름이 비어 있음"

    settings = db.setdefault("settings", {})
    labels = settings.setdefault("category_labels", _lrl_merge_category_labels())
    key = normalize_category(category_key)
    if key not in labels:
        key = _lrl_category_key_from_label(category_key)
    if key not in labels:
        return False, "분류를 못 찾음"

    for other_key, other_label in labels.items():
        if other_key != key and str(other_label).strip().lower() == label.lower():
            return False, "이미 같은 이름의 분류가 있음"

    old_label = labels.get(key, key)
    labels[key] = label
    settings["category_labels"] = _lrl_merge_category_labels(labels)
    _lrl_sync_category_globals(db)
    save_db(db)
    append_log(f"분류 이름 변경: {old_label} → {label}")
    return True, f"분류 이름 변경: {label}"


try:
    _prev_handler_post_v025_category_settings
except NameError:
    _prev_handler_post_v025_category_settings = Handler.do_POST

    def _v025_category_settings_do_POST(self):
        path = urlparse(self.path).path
        if path in ["/api/add_category", "/api/set_category_label"]:
            if '_protected' in globals() and not _protected(self):
                return

            val = _read_urlencoded_form(self) if '_read_urlencoded_form' in globals() else None
            if val is None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length).decode("utf-8", errors="replace")
                form = parse_qs(body)
                val = lambda name: (form.get(name) or [""])[0]

            if path == "/api/add_category":
                ok, msg, key = add_category_label(val("label"))
                json_response(self, {"ok": ok, "message": msg, "key": key, "category_labels": dict(CATEGORY_LABELS)}, status=200 if ok else 400)
                return

            ok, msg = set_category_label(val("category"), val("label"))
            json_response(self, {"ok": ok, "message": msg, "category_labels": dict(CATEGORY_LABELS)}, status=200 if ok else 400)
            return

        return _prev_handler_post_v025_category_settings(self)

    Handler.do_POST = _v025_category_settings_do_POST


_V025_JS = r'''
const LRL_DEFAULT_CATEGORY_ORDER_V025 = ['webtoon', 'comic', 'manga', 'novel', 'anime', 'other'];

function lrlCategoryEntries(includeAll=false) {
    const labels = settings.category_labels || {};
    const result = [];
    if (includeAll) result.push(['all', '전체 분류']);
    const seen = new Set();
    LRL_DEFAULT_CATEGORY_ORDER_V025.forEach(key => {
        if (Object.prototype.hasOwnProperty.call(labels, key)) {
            result.push([key, labels[key] || key]);
            seen.add(key);
        }
    });
    Object.entries(labels)
        .filter(([key]) => !seen.has(key))
        .sort((a, b) => String(a[1] || a[0]).localeCompare(String(b[1] || b[0]), 'ko'))
        .forEach(([key, label]) => result.push([key, label || key]));
    return result;
}

function lrlCategoryOptionsHtml(selected, includeAll=false) {
    const current = String(selected || (includeAll ? 'all' : 'other'));
    return lrlCategoryEntries(includeAll).map(([key, label]) => {
        const selectedAttr = String(key) === current ? ' selected' : '';
        return `<option value="${escapeHtml(key)}"${selectedAttr}>${escapeHtml(label)}</option>`;
    }).join('');
}

function lrlCategoryLabel(key) {
    return (settings.category_labels || {})[key] || key || '기타';
}

function lrlEnsurePaginationControls() {
    if (!controls) return;

    let categoryFilter = document.getElementById('categoryFilter');
    const savedCategory = localStorage.getItem('lrl.categoryFilter') || (categoryFilter ? categoryFilter.value : 'all') || 'all';
    if (!categoryFilter) {
        categoryFilter = document.createElement('select');
        categoryFilter.id = 'categoryFilter';
        controls.appendChild(categoryFilter);
    }
    categoryFilter.innerHTML = lrlCategoryOptionsHtml(savedCategory, true);
    categoryFilter.value = lrlCategoryEntries(true).some(([value]) => value === savedCategory) ? savedCategory : 'all';
    categoryFilter.onchange = () => {
        try { localStorage.setItem('lrl.categoryFilter', categoryFilter.value); } catch(e) {}
        lrlPage = 1;
        render();
    };

    let pageSize = document.getElementById('pageSize');
    if (!pageSize) {
        pageSize = document.createElement('select');
        pageSize.id = 'pageSize';
        controls.appendChild(pageSize);
    }
    const savedSize = localStorage.getItem('lrl.pageSize') || String(lrlPageSize || 100);
    pageSize.innerHTML = `
        <option value="50">50개씩</option>
        <option value="100">100개씩</option>
        <option value="200">200개씩</option>
        <option value="500">500개씩</option>
        <option value="0">전체</option>
    `;
    pageSize.value = ['50', '100', '200', '500', '0'].includes(savedSize) ? savedSize : '100';
    lrlPageSize = Number(pageSize.value || 100);
    pageSize.onchange = () => {
        lrlPageSize = Number(pageSize.value || 100);
        try { localStorage.setItem('lrl.pageSize', pageSize.value); } catch(e) {}
        lrlPage = 1;
        render();
    };

    let pager = document.getElementById('pager');
    if (!pager) {
        pager = document.createElement('div');
        pager.id = 'pager';
        pager.className = 'pager';
        const top = document.querySelector('.top');
        if (top && count) top.insertBefore(pager, count.nextSibling);
    }
}

function lrlItemCategorySelect(encodedTitle, currentCategory) {
    return `<select class="category-edit category-select" title="분류" onchange="changeItemCategoryFromSelect('${encodedTitle}', this.value)">${lrlCategoryOptionsHtml(currentCategory || 'other', false)}</select>`;
}

function lrlSiteCategorySelect(encodedKey, currentCategory) {
    return `<select class="category-edit category-select site-category-select" title="사이트 기본분류" onchange="changeSiteCategoryFromSelect('${encodedKey}', this.value)">${lrlCategoryOptionsHtml(currentCategory || 'other', false)}</select>`;
}

async function changeItemCategoryFromSelect(encodedTitle, category) {
    const title = decodeURIComponent(encodedTitle);
    if (!category) return;
    const data = await api('/api/set_category', {title, category});
    showToast(data.message || '분류 변경 완료');
    await reloadList();
}

async function changeSiteCategoryFromSelect(encodedKey, category) {
    const key = decodeURIComponent(encodedKey);
    if (!category) return;
    const data = await api('/api/set_site_category', {site: key, category});
    showToast(data.message || '사이트 기본분류 저장 완료');
    await loadSettings();
    if (mode === 'settings') renderSettingsPage();
    else await reloadList();
}

async function editCategory(encodedTitle) {
    showToast('분류는 목록의 드롭다운에서 선택해서 바꿔라');
}

async function setSiteCategory(encodedKey) {
    showToast('사이트 분류는 설정 탭의 드롭다운에서 선택해서 바꿔라');
}

function lrlActionButtons(r, encodedTitle) {
    const categorySelect = lrlItemCategorySelect(encodedTitle, r.category || 'other');
    if (mode === 'current') {
        return `
            <button class="edit" onclick="openEpisodePicker('${encodedTitle}')">화수선택</button>
            ${categorySelect}
            <button class="edit" onclick="editTitleOnly('${encodedTitle}')">제목수정</button>
            <button class="danger" onclick="deleteTitle('${encodedTitle}')">삭제</button>
        `;
    }
    return `
        <button class="edit" onclick="openEpisodePicker('${encodedTitle}')">화수선택</button>
        ${categorySelect}
        <button class="edit" onclick="editTitleOnly('${encodedTitle}')">제목수정</button>
        <button class="restore" onclick="restoreTitle('${encodedTitle}')">복구</button>
        <button class="purge" onclick="purgeTitle('${encodedTitle}')">완전삭제</button>
    `;
}

function bulkToolbar() {
    if (!(mode === 'current' || mode === 'deleted')) return '';
    const restoreBtn = mode === 'deleted'
        ? `<button class="restore" onclick="bulkAction('restore')">선택 복구</button><button class="purge" onclick="bulkAction('purge')">선택 완전삭제</button>`
        : `<button class="danger" onclick="bulkAction('delete')">선택 삭제</button>`;
    return `<div class="settings-box bulk-box"><h2>현재 페이지 선택 처리</h2><div class="buttons"><button onclick="toggleAllRows(true)">현재페이지 전체선택</button><button onclick="toggleAllRows(false)">선택해제</button>${restoreBtn}<select id="bulkCategorySelect" class="category-edit category-select" title="선택 분류">${lrlCategoryOptionsHtml('comic', false)}</select><button class="edit" onclick="bulkCategory()">선택 분류변경</button></div></div>`;
}

async function bulkCategory() {
    const titles = selectedTitles();
    if (!titles.length) { showToast('선택된 항목 없음'); return; }
    const select = document.getElementById('bulkCategorySelect');
    const category = select ? select.value : '';
    if (!category) { showToast('분류를 선택해라'); return; }
    const data = await api('/api/bulk_action', {action:'category', titles: JSON.stringify(titles), category});
    showToast(data.message || '분류 변경 완료');
    await reloadList();
}

function lrlRenderCategoryManagerBox() {
    const rows = lrlCategoryEntries(false).map(([key, label]) => `
        <div class="setting-row category-setting-row">
            <div><b>${escapeHtml(label)}</b><div class="small">${escapeHtml(key)}</div></div>
            <button onclick="editCategoryLabel('${encodeURIComponent(key)}')">수정</button>
        </div>
    `).join('');
    return `
        <div class="settings-box">
            <h2>분류 관리</h2>
            <div class="small">여기서 추가·수정한 분류는 현재 목록, 삭제 목록, 사이트 기본분류 선택에 같이 반영됨.</div>
            <div style="height:8px"></div>
            <button onclick="addCategoryLabel()">분류 추가</button>
            <div style="height:10px"></div>
            ${rows || '<div class="empty">등록된 분류 없음</div>'}
        </div>
    `;
}

async function addCategoryLabel() {
    const input = prompt('추가할 분류 이름 입력', '');
    if (input === null) return;
    const label = input.trim();
    if (!label) { showToast('분류 이름이 비어 있음'); return; }
    const data = await api('/api/add_category', {label});
    showToast(data.message || '분류 추가 완료');
    await loadSettings();
    renderSettingsPage();
}

async function editCategoryLabel(encodedKey) {
    const key = decodeURIComponent(encodedKey);
    const current = lrlCategoryLabel(key);
    const input = prompt('분류 이름 수정', current);
    if (input === null) return;
    const label = input.trim();
    if (!label) { showToast('분류 이름이 비어 있음'); return; }
    const data = await api('/api/set_category_label', {category: key, label});
    showToast(data.message || '분류 이름 저장 완료');
    await loadSettings();
    renderSettingsPage();
}

function lrlSiteCategoryFilterValue() {
    const el = document.getElementById('settingsSiteCategoryFilter');
    return el ? (el.value || 'all') : (localStorage.getItem('lrl.settingsSiteCategoryFilter') || 'all');
}

function lrlSettingsSiteFilterHtml(current) {
    return `<select id="settingsSiteCategoryFilter" class="settings-site-filter" onchange="try{localStorage.setItem('lrl.settingsSiteCategoryFilter', this.value)}catch(e){}; renderSettingsPage()">${lrlCategoryOptionsHtml(current || 'all', true)}</select>`;
}

function renderSettingsPage() {
    renderSettings();
    controls.style.display = 'none';
    prioritybar.style.display = 'none';
    if (browserbar) browserbar.style.display = 'none';

    const siteEntries = lrlSiteEntriesInPriorityOrder();
    const priorityLabels = (settings.site_priority || []).map(k => settings.sites?.[k]?.label || settings.site_labels?.[k] || k);
    const siteCategoryFilter = lrlSiteCategoryFilterValue();
    const filteredSiteEntries = siteEntries.filter(([key, site]) => {
        const cat = String(site?.category || 'other');
        return siteCategoryFilter === 'all' || cat === siteCategoryFilter;
    });

    const siteRows = filteredSiteEntries.map(([key, site]) => {
        const enabled = site.enabled !== false;
        const host = site.host_re || site.prefix || key;
        const removable = key !== 'blacktoon';
        const catLabel = lrlCategoryLabel(site.category || 'other');
        return `
            <div class="setting-row site-setting-row">
                <div>
                    <b>${escapeHtml(site.label || key)}</b>
                    <div class="small">${escapeHtml(key)} · ${escapeHtml(host)} · 기본분류 ${escapeHtml(catLabel)}</div>
                </div>
                <button class="${enabled ? '' : 'off'}" onclick="toggleSiteEnabled('${encodeURIComponent(key)}')">${enabled ? 'ON' : 'OFF'}</button>
                <button onclick="editSiteLabel('${encodeURIComponent(key)}')">이름</button>
                ${lrlSiteCategorySelect(encodeURIComponent(key), site.category || 'other')}
                ${removable ? `<button class="danger" onclick="removeSite('${encodeURIComponent(key)}')">삭제</button>` : '<span></span>'}
            </div>
        `;
    }).join('');

    const browserRows = Object.entries(settings.browser_labels || {}).map(([key, label]) => {
        const enabled = !!settings.browser_enabled?.[key];
        return `
            <div class="setting-row">
                <div><b>${escapeHtml(label)}</b></div>
                <button class="${enabled ? '' : 'off'}" onclick="toggleBrowserSync('${key}')">${enabled ? 'ON' : 'OFF'}</button>
                <span></span>
                <span></span>
            </div>
        `;
    }).join('');

    const addressBlock = (typeof renderAddressBox === 'function') ? renderAddressBox() : '';
    const autoUpdateBlock = (typeof renderAutoUpdateBox === 'function') ? renderAutoUpdateBox() : '';
    const runtimeBlock = (typeof renderRuntimeStatusBox === 'function') ? renderRuntimeStatusBox() : '';

    count.textContent = '설정';
    list.innerHTML = `
        <div class="settings-box">
            <h2>사이트</h2>
            <div class="small">주소를 입력해서 추적 사이트를 추가함. 사이트 이름과 기본분류는 여기서 수정함.</div>
            <div style="height:8px"></div>
            <button onclick="addSite()">사이트 추가</button>
            ${lrlSettingsSiteFilterHtml(siteCategoryFilter)}
            <div style="height:10px"></div>
            ${siteRows || '<div class="empty">해당 분류의 사이트 없음</div>'}
        </div>

        ${lrlRenderCategoryManagerBox()}

        <div class="settings-box">
            <h2>사이트 우선순위</h2>
            <div class="small">위아래로 드래그해서 순서를 바꾼 뒤 저장. 현재: ${escapeHtml(priorityLabels.join(' > '))}</div>
            <div id="priorityList" class="priority-list">${renderPriorityRows()}</div>
            <button onclick="saveDraggedSitePriority()">우선순위 저장</button>
            <button onclick="toggleDuplicateHiding()">중복숨김 ${settings.hide_site_duplicates ? 'ON' : 'OFF'}</button>
        </div>

        ${addressBlock}
        ${autoUpdateBlock}

        <div class="settings-box">
            <h2>접속 비밀번호</h2>
            <div class="small">모바일/다른 기기에서 접속할 때는 비밀번호 사용을 권장함. 공유기 외부 포트포워딩은 권장하지 않음.</div>
            <div class="setting-row">
                <div><b>비밀번호 보호</b><div class="small">현재 상태: ${settings.password_enabled ? 'ON' : 'OFF'}</div></div>
                <button class="${settings.password_enabled ? '' : 'off'}" onclick="toggleAccessPassword()">${settings.password_enabled ? 'ON' : 'OFF'}</button>
                <button onclick="changeAccessPassword()">변경</button>
                <span></span>
            </div>
        </div>

        <div class="settings-box"><h2>브라우저 연동</h2>${browserRows}</div>

        ${runtimeBlock}
    `;
}

// 설정을 다시 읽은 뒤 동적 분류 옵션으로 컨트롤을 다시 그림.
lrlEnsurePaginationControls();
'''

try:
    INDEX_HTML = INDEX_HTML.replace('</style>', '''
.category-select,
.settings-site-filter {
    box-sizing: border-box;
    width: 100%;
    border: 0;
    border-radius: 8px;
    padding: 10px 6px;
    background: #1f4e79;
    color: white;
    font-weight: 800;
    cursor: pointer;
    text-align: center;
    text-align-last: center;
}
.category-select option,
.settings-site-filter option {
    color: #111;
    background: #fff;
}
.settings-site-filter {
    margin-top: 8px;
    border: 1px solid #ccc;
    background: white;
    color: #111;
    text-align-last: left;
}
.category-setting-row {
    grid-template-columns: 1fr 80px;
}
.site-setting-row {
    grid-template-columns: 1fr 72px 72px 105px 72px;
}
.site-setting-row span { display:block; }
@media(max-width:700px){
    .site-setting-row{grid-template-columns:1fr 58px 58px 92px 58px}
    .site-setting-row button,.site-setting-row select{padding-left:3px;padding-right:3px;font-size:11px}
}
</style>''')
    INDEX_HTML = INDEX_HTML.replace('</script>', _V025_JS + '\n</script>')
except Exception as e:
    try:
        append_log(f"INDEX_HTML v0.1.25 분류 관리 UI 보강 실패: {e}")
    except Exception:
        pass


# =========================
# v0.1.26: v0.1.25 목록 빈 화면 긴급 수정
# =========================
LOCALREADLOG_VERSION = "v0.1.26"

try:
    # v0.1.24의 즉시 실행 초기화가 v0.1.25의 동적 분류 함수 선언으로 덮인 뒤
    # v0.1.25 상수 초기화보다 먼저 실행되면 브라우저에서 ReferenceError가 나고
    # 목록 전체가 빈 화면이 된다. 분류/페이지 컨트롤 초기화는 v0.1.25 끝부분에서
    # 다시 수행되므로, 앞쪽 즉시 호출만 제거한다.
    INDEX_HTML = INDEX_HTML.replace(
        "lrlNormalizeSortOptions();\nlrlEnsurePaginationControls();\n\n\nconst LRL_DEFAULT_CATEGORY_ORDER_V025",
        "lrlNormalizeSortOptions();\n// lrlEnsurePaginationControls는 v0.1.25 동적 분류 초기화 뒤에 실행\n\n\nconst LRL_DEFAULT_CATEGORY_ORDER_V025",
    )
except Exception as e:
    try:
        append_log(f"INDEX_HTML v0.1.26 목록 초기화 순서 보정 실패: {e}")
    except Exception:
        pass

if __name__ == "__main__":
    main()
