# NO_SPREADSHEET_EXPORT_20260612
# LOCALREADLOG_GITHUB_READY_20260612
# NO_SERIES_ALL_FIXED_20260612
import csv
import os
import re
import shutil
import sqlite3
import tempfile
import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, quote, unquote



# =========================
# 설정
# =========================

APP_DISPLAY_NAME = "LocalReadLog"
SCRIPT_DIR = Path(__file__).resolve().parent
APP_ROOT_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.name.lower() == "core" else SCRIPT_DIR
CONFIG_JSON = APP_ROOT_DIR / "localreadlog_config.json"

# 비워두면 방문기록/기존 CSV/DB에서 각 사이트별 가장 큰 숫자 도메인을 최신 주소로 판단.
# 직접 고정하려면 예:
# FORCE_LATEST_HOSTS = {
#     "blacktoon": "https://blacktoon412.com",
#     "wfwf": "https://wfwf464.com",
#     "tkor": "https://tkor125.com",
# }
FORCE_LATEST_HOST = ""  # 구버전 호환용. blacktoon에만 적용.
FORCE_LATEST_HOSTS = {
    "blacktoon": FORCE_LATEST_HOST,
    "wfwf": "",
    "tkor": "",
}

SITE_SPECS = {
    "blacktoon": {
        "label": "블랙툰",
        "prefix": "blacktoon",
        "host_re": r"blacktoon\d+\.com",
    },
    "wfwf": {
        "label": "늑대",
        "prefix": "wfwf",
        "host_re": r"wfwf\d+\.com",
    },
    "tkor": {
        "label": "툰코",
        "prefix": "tkor",
        "host_re": r"tkor\d+\.com",
    },
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

TRACKED_HOST_RE = re.compile(
    r"^https?://(?:www\.)?(?:blacktoon\d+|wfwf\d+|tkor\d+)\.com/",
    re.I,
)

MAX_ARCHIVE_FILES = 50

LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))

BROWSERS = [
    {
        "key": "whale",
        "name": "Whale",
        "type": "chromium",
        "user_data_dir": LOCALAPPDATA / "Naver" / "Naver Whale" / "User Data",
    },
    {
        "key": "edge",
        "name": "Edge",
        "type": "chromium",
        "user_data_dir": LOCALAPPDATA / "Microsoft" / "Edge" / "User Data",
    },
    {
        "key": "chrome",
        "name": "Chrome",
        "type": "chromium",
        "user_data_dir": LOCALAPPDATA / "Google" / "Chrome" / "User Data",
    },
    {
        "key": "firefox",
        "name": "Firefox",
        "type": "firefox",
        "profile_dir": APPDATA / "Mozilla" / "Firefox" / "Profiles",
    },
]

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


def find_onedrive_dir():
    """
    개인용/회사/학교용 OneDrive 실제 경로 자동 감지.
    """
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
        print(f"설정 파일 읽기 실패: {CONFIG_JSON} / {e}")
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
LATEST_HTML = BACKUP_DIR / "localreadlog_latest_mobile.html"
LATEST_PC_HTML = BACKUP_DIR / "localreadlog_latest_pc.html"
IGNORE_TXT = BACKUP_DIR / "localreadlog_ignore.txt"
PURGED_TXT = BACKUP_DIR / "localreadlog_purged.txt"
DB_JSON = BACKUP_DIR / "localreadlog_db.json"



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
            shutil.copy2(old_path, new_path)
            return old_path
    except Exception as e:
        print(f"기존 파일 이전 실패: {new_path} / {e}")
    return None


def migrate_legacy_file_if_needed(new_path, old_path):
    return migrate_first_existing_file_if_needed(new_path, [old_path]) is not None

EXISTING_SCAN_DIRS = [
    BACKUP_DIR,
    BACKUP_DIR / "archive",
]


BLACKTOON_RE = TRACKED_HOST_RE

SERIES_PAGE_RE = re.compile(
    r"^https?://(?:www\.)?blacktoon\d+\.com/webtoon/(\d+)\.html(?:[?#].*)?$",
    re.I,
)

EPISODE_PAGE_RE = re.compile(
    r"^https?://(?:www\.)?blacktoon\d+\.com/webtoons/(\d+)/(\d+)\.html(?:[?#].*)?$",
    re.I,
)


# =========================
# 기본 정리 함수
# =========================

def chrome_time_to_kst(chrome_time):
    if not chrome_time:
        return ""

    utc_time = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=chrome_time)
    kst_time = utc_time.astimezone(timezone(timedelta(hours=9)))
    return kst_time.strftime("%Y-%m-%d %H:%M:%S")


def firefox_time_to_kst(unix_microseconds):
    if not unix_microseconds:
        return ""

    try:
        utc_time = datetime.fromtimestamp(int(unix_microseconds) / 1_000_000, tz=timezone.utc)
        kst_time = utc_time.astimezone(timezone(timedelta(hours=9)))
        return kst_time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def clean_title(title):
    title = (title or "").strip()
    title = re.sub(r"\s+", " ", title)

    remove_patterns = [
        r"\s*BlackToon\s*블랙툰\s*-\s*무료웹툰\s*웹툰미리보기\s*$",
        r"\s*BlackToon\s*블랙툰.*$",
        r"\s*-\s*BlackToon\s*블랙툰.*$",
        r"\s*\|\s*BlackToon\s*블랙툰.*$",
        r"\s*-\s*무료웹툰\s*웹툰미리보기\s*$",

        r"\s*-\s*늑대닷컴.*$",
        r"\s*\|\s*늑대닷컴.*$",
        r"\s*늑대닷컴\s*-\s*무료웹툰.*$",
        r"\s*WFWF.*$",

        r"\s*-\s*툰코.*$",
        r"\s*\|\s*툰코.*$",
        r"\s*툰코.*무료웹툰.*$",
        r"\s*Toonkor.*$",
        r"\s*Tkor.*$",
    ]

    for pattern in remove_patterns:
        title = re.sub(pattern, "", title, flags=re.I)

    return title.strip()


def normalize_title(title):
    return re.sub(r"\s+", " ", clean_title(title)).strip()


def is_bad_title(title):
    title = normalize_title(title)

    if not title:
        return True

    bad_titles = {
        "BlackToon 블랙툰 - 무료웹툰 웹툰미리보기",
        "BlackToon 블랙툰",
        "블랙툰",
        "무료웹툰 웹툰미리보기",
        "블랙툰 공식 채널 – Telegram",
        "늑대닷컴",
        "WFWF",
        "툰코",
        "Toonkor",
        "Tkor",
        "홈",
        "메인",
    }

    return title in bad_titles


def parse_episode_number(title):
    title = clean_title(title)
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*화", title)

    if not matches:
        return ""

    number_text = matches[-1]

    try:
        number = float(number_text)
        if number.is_integer():
            return str(int(number))
        return str(number)
    except Exception:
        return number_text


def episode_sort_value(value):
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0


def infer_series_title_from_episode_title(episode_title):
    title = clean_title(episode_title)

    # 예: 0125 - 무당기협 125화 -> 무당기협 125화
    title = re.sub(r"^\d{3,5}\s*[-–—]\s*", "", title)

    # 예: 무당기협 125화 -> 무당기협
    title = re.sub(r"\s*(?:외전\s*)?\d+(?:\.\d+)?\s*화.*$", "", title)

    return title.strip()


def get_site_key(url):
    url = str(url or "").strip()

    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""

    host = re.sub(r"^www\.", "", host)

    for site_key, spec in SITE_SPECS.items():
        if re.fullmatch(spec["host_re"], host, flags=re.I):
            return site_key

    return ""


def site_label(site_key):
    return SITE_SPECS.get(site_key, {}).get("label", site_key or "")


def display_title_for_site(site_key, title):
    title = clean_title(title)

    if not title:
        return ""

    if site_key == "blacktoon":
        return title

    label = site_label(site_key)

    if label and not title.startswith(f"[{label}]"):
        return f"[{label}] {title}"

    return title


def get_site_key_from_title(title):
    title = str(title or "").strip()
    match = re.match(r"^\[(블랙툰|늑대|툰코)\]\s*", title)

    if not match:
        return ""

    return SITE_NAME_ALIASES.get(match.group(1), "")


def infer_site_key_from_row(row):
    site_key = get_site_key(row.get("url", ""))
    if site_key:
        return site_key

    return get_site_key_from_title(row.get("title", "")) or "blacktoon"


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
    old_site = infer_site_key_from_row(old)
    new_site = infer_site_key_from_row(new)

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
    db = normalize_db_settings(db)
    settings = db.get("settings", {})

    if not settings.get("hide_site_duplicates", True):
        return rows

    grouped = {}

    for row in rows:
        key = duplicate_group_key(row)
        if not key:
            grouped[id(row)] = {"chosen": row, "hidden": []}
            continue

        current = grouped.get(key)

        if current is None:
            grouped[key] = {"chosen": row, "hidden": []}
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
        output.append(group["chosen"])

    return output


def generic_series_id_from_url(site_key, url):
    """
    URL 구조를 정확히 모르는 사이트용 fallback.
    마지막 숫자/slug 조각 하나를 회차로 보고 제거한 path를 그룹키로 사용.
    제목으로 그룹핑이 실패할 때만 사용.
    """
    try:
        path = urlparse(url).path.strip("/")
    except Exception:
        path = ""

    if not path:
        return f"{site_key}:root"

    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        parts = parts[:-1]

    normalized = "/".join(parts) or path
    normalized = re.sub(r"\d+(?:\.html)?$", "", normalized)
    normalized = re.sub(r"[^0-9A-Za-z가-힣_/-]+", "_", normalized).strip("_")

    return f"{site_key}:url:{normalized or path}"


def extract_series_page_info(row):
    url = row.get("url", "")
    site_key = get_site_key(url)

    if not site_key:
        return None

    title = clean_title(row.get("clean_title", "") or row.get("raw_title", ""))

    if is_bad_title(title):
        return None

    blacktoon_match = SERIES_PAGE_RE.match(url)
    if blacktoon_match:
        return {
            "site": site_key,
            "series_id": f"{site_key}:id:{blacktoon_match.group(1)}",
            "title": display_title_for_site(site_key, title),
        }

    # 다른 사이트는 제목에 화수가 없고, 루트가 아닌 페이지를 작품 후보로 봄.
    if parse_episode_number(title):
        return None

    try:
        path = urlparse(url).path.strip("/")
    except Exception:
        path = ""

    if not path:
        return None

    return {
        "site": site_key,
        "series_id": f"{site_key}:title:{normalize_title(title)}",
        "title": display_title_for_site(site_key, title),
    }


def extract_episode_page_info(row, series_titles=None):
    if series_titles is None:
        series_titles = {}

    url = row.get("url", "")
    site_key = get_site_key(url)

    if not site_key:
        return None

    episode_title = clean_title(row.get("clean_title", "") or row.get("raw_title", ""))
    latest_episode = parse_episode_number(episode_title)

    if not latest_episode:
        return None

    if is_bad_title(episode_title):
        return None

    blacktoon_match = EPISODE_PAGE_RE.match(url)
    if blacktoon_match:
        series_id = f"{site_key}:id:{blacktoon_match.group(1)}"

        if looks_like_episode_only_title(episode_title):
            title = series_titles.get(series_id, "")
        else:
            title = series_titles.get(series_id) or infer_series_title_from_episode_title(episode_title)

        if not title:
            title = f"작품ID {blacktoon_match.group(1)}"

        return {
            "site": site_key,
            "series_id": series_id,
            "title": display_title_for_site(site_key, title),
            "latest_episode": latest_episode,
            "url": url,
        }

    title = infer_series_title_from_episode_title(episode_title)

    if title:
        series_id = f"{site_key}:title:{normalize_title(title)}"
    else:
        series_id = generic_series_id_from_url(site_key, url)
        title = series_id.rsplit(":", 1)[-1] or "제목없음"

    return {
        "site": site_key,
        "series_id": series_id,
        "title": display_title_for_site(site_key, title),
        "latest_episode": latest_episode,
        "url": url,
    }


def blacktoon_series_id_from_url(url):
    url = str(url or "").strip()

    episode_match = EPISODE_PAGE_RE.match(url)
    if episode_match:
        return episode_match.group(1)

    series_match = SERIES_PAGE_RE.match(url)
    if series_match:
        return series_match.group(1)

    return ""


def looks_like_episode_only_title(title):
    """
    방문기록 제목이 작품명이 아니라 '134화', '제134화', '1495572' 같은 값만 찍힌 경우 감지.
    """
    title = clean_title(title)
    title = re.sub(r"^\[(?:블랙툰|늑대|툰코)\]\s*", "", title).strip()

    if not title:
        return True

    patterns = [
        r"^\d+(?:\.\d+)?\s*화$",
        r"^제\s*\d+(?:\.\d+)?\s*화$",
        r"^\d{3,}$",
        r"^episode\s*\d+$",
        r"^ep\.?\s*\d+$",
    ]

    return any(re.match(pattern, title, flags=re.I) for pattern in patterns)


def db_item_series_id(item):
    item = normalize_db_item(item)

    for url in [item.get("url", "")]:
        series_id = blacktoon_series_id_from_url(url)
        if series_id:
            return series_id

    for record in (item.get("episode_history", {}) or {}).values():
        if not isinstance(record, dict):
            continue

        series_id = blacktoon_series_id_from_url(record.get("url", ""))
        if series_id:
            return series_id

    return ""


def find_db_item_key_by_blacktoon_series(db, series_id):
    series_id = str(series_id or "").strip()

    if not series_id:
        return ""

    for item_key, raw_item in db.get("items", {}).items():
        item = normalize_db_item(raw_item)

        if db_item_series_id(item) == series_id:
            return item_key

    return ""


def maybe_fix_episode_only_db_title(items, db_key, correct_title):
    """
    DB에 이미 '134화' 같은 잘못된 제목으로 저장된 항목이 있으면
    /webtoon/{series_id}.html에서 얻은 진짜 작품명으로 키/제목을 교정.
    """
    if not db_key or db_key not in items:
        return db_key

    correct_title = clean_title(correct_title)

    if not correct_title or looks_like_episode_only_title(correct_title):
        return db_key

    item = normalize_db_item(items.get(db_key, {}))
    old_title = item.get("title", "")

    if not looks_like_episode_only_title(old_title):
        return db_key

    aliases = item.setdefault("aliases", [])
    if old_title and db_title_key(old_title) != db_title_key(correct_title):
        if all(db_title_key(x) != db_title_key(old_title) for x in aliases):
            aliases.append(old_title)

    item["title"] = correct_title
    item.setdefault("manual", {})["title"] = True

    new_key = db_title_key(correct_title)

    if new_key and new_key != db_key:
        # 새 키가 이미 있으면 기존 항목에 history를 흡수
        if new_key in items:
            target = normalize_db_item(items[new_key])
            for ep, record in (item.get("episode_history", {}) or {}).items():
                target.setdefault("episode_history", {})[ep] = record

            if episode_sort_value(item.get("latest_episode", "")) > episode_sort_value(target.get("latest_episode", "")):
                target["latest_episode"] = item.get("latest_episode", "")
                target["last_seen"] = item.get("last_seen", "")
                target["url"] = item.get("url", "")

            target_aliases = target.setdefault("aliases", [])
            for alias in item.get("aliases", []):
                if all(db_title_key(x) != db_title_key(alias) for x in target_aliases):
                    target_aliases.append(alias)

            items[new_key] = normalize_db_item(target)
            del items[db_key]
        else:
            del items[db_key]
            items[new_key] = normalize_db_item(item)

        return new_key

    items[db_key] = normalize_db_item(item)
    return db_key


def make_merge_key(item):
    title = normalize_title(item.get("title", ""))

    if title:
        return f"title:{title}"

    return ""


def choose_better(old, new):
    """
    기준:
    1. latest_episode가 더 높은 쪽
    2. 화수가 같으면 last_seen이 더 최근인 쪽
    """
    old_ep = episode_sort_value(old.get("latest_episode", ""))
    new_ep = episode_sort_value(new.get("latest_episode", ""))

    if new_ep > old_ep:
        return new

    if new_ep < old_ep:
        return old

    if new.get("last_seen", "") > old.get("last_seen", ""):
        return new

    # 같은 화수/시간이면 URL이 있는 쪽 우선
    if not old.get("url") and new.get("url"):
        return new

    return old


# =========================
# ignore 처리
# =========================

def get_ignore_file_paths():
    """프로그램 폴더의 localreadlog_ignore.txt만 읽음."""
    paths = [
        BACKUP_DIR / "localreadlog_ignore.txt",
    ]

    unique = []
    seen = set()

    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)

    return unique


def load_ignore_titles():
    ignore_titles = set()

    for path in get_ignore_file_paths():
        if not path.exists():
            continue

        try:
            with path.open("r", encoding="utf-8-sig") as f:
                for line in f:
                    title = normalize_title(line)
                    if not title or title.startswith("#"):
                        continue
                    ignore_titles.add(title)

        except Exception as e:
            print(f"ignore 파일 읽기 실패: {path}")
            print(e)

    return ignore_titles


def is_ignored_title(title, ignore_titles):
    title = normalize_title(title)
    return bool(title and title in ignore_titles)


def apply_ignore_filter(rows, ignore_titles):
    if not ignore_titles:
        return rows

    filtered = []
    removed = []

    for row in rows:
        title = normalize_title(row.get("title", ""))
        if title in ignore_titles:
            removed.append(title)
            continue
        filtered.append(row)

    removed_unique = sorted(set(removed))

    if removed_unique:
        print(f"ignore 적용: {len(removed_unique)}개 제외")
        for title in removed_unique[:30]:
            print(f"- {title}")
        if len(removed_unique) > 30:
            print(f"...외 {len(removed_unique) - 30}개")

    return filtered


# =========================
# localreadlog_db.json 연동
# =========================


def db_title_key(title):
    return normalize_title(title).lower()


def db_episode_key(value):
    n = episode_sort_value(value)
    if n <= 0:
        return ""
    if n.is_integer():
        return str(int(n))
    return str(n)


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


def normalize_db_settings(db):
    db.setdefault("settings", {})
    settings = db["settings"]

    if not isinstance(settings, dict):
        settings = {}
        db["settings"] = settings

    settings["site_priority"] = normalize_site_priority(settings.get("site_priority", DEFAULT_SITE_PRIORITY))

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


def load_manager_db():
    """
    관리 서버가 쓰는 localreadlog_db.json 읽기.
    여기서 deleted/purged/blocked_episodes를 백업 생성에도 반영해야
    서버에서 복구/되돌리기한 내용이 다음 자동 백업 때 되살아나지 않음.
    """
    if not DB_JSON.exists():
        return normalize_db_settings({"items": {}})

    try:
        with DB_JSON.open("r", encoding="utf-8") as f:
            db = json.load(f)

        if not isinstance(db, dict):
            return normalize_db_settings({"items": {}})

        items = db.get("items", {})
        if not isinstance(items, dict):
            db["items"] = {}

        db = normalize_db_settings(db)
        return db

    except Exception as e:
        print(f"DB 읽기 실패: {DB_JSON}")
        print(e)
        return normalize_db_settings({"items": {}})


def save_manager_db(db):
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        db = normalize_db_settings(db)
        db = normalize_manager_db_urls_to_latest(db)
        db["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tmp = DB_JSON.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        tmp.replace(DB_JSON)
    except Exception as e:
        print("DB 저장 실패:")
        print(e)


def normalize_db_item(item):
    item = dict(item or {})
    item["title"] = clean_title(item.get("title", ""))
    item.setdefault("latest_episode", "")
    item.setdefault("last_seen", "")
    item.setdefault("url", "")
    item.setdefault("status", "active")
    item.setdefault("aliases", [])
    item.setdefault("manual", {})
    item.setdefault("episode_history", {})
    item.setdefault("locked_episode", "")
    item.setdefault("blocked_episodes", [])

    if item["status"] not in ["active", "deleted", "purged"]:
        item["status"] = "active"

    aliases = []
    seen = set()
    title_key = db_title_key(item.get("title", ""))

    for alias in item.get("aliases", []):
        alias = clean_title(alias)
        key = db_title_key(alias)
        if not alias or key == title_key or key in seen:
            continue
        seen.add(key)
        aliases.append(alias)

    item["aliases"] = aliases
    item["blocked_episodes"] = [db_episode_key(x) for x in item.get("blocked_episodes", []) if db_episode_key(x)]
    return item


def find_db_item_key(db, title):
    key = db_title_key(title)
    if not key:
        return ""

    items = db.get("items", {})

    if key in items:
        return key

    for item_key, raw_item in items.items():
        item = normalize_db_item(raw_item)
        if db_title_key(item.get("title", "")) == key:
            return item_key
        for alias in item.get("aliases", []):
            if db_title_key(alias) == key:
                return item_key

    return ""


def db_item_to_row(item):
    item = normalize_db_item(item)
    return {
        "title": item.get("title", ""),
        "latest_episode": str(item.get("latest_episode", "") or "").strip(),
        "last_seen": str(item.get("last_seen", "") or "").strip(),
        "url": str(item.get("url", "") or "").strip(),
    }


def get_db_episode_record(item, episode):
    item = normalize_db_item(item)
    ep = db_episode_key(episode)
    if not ep:
        return None
    return (item.get("episode_history", {}) or {}).get(ep)


def get_db_latest_history_record(item):
    item = normalize_db_item(item)
    history = item.get("episode_history", {}) or {}
    records = []

    for ep, record in history.items():
        ep_key = db_episode_key(ep)
        if not ep_key:
            continue
        records.append((episode_sort_value(ep_key), ep_key, record))

    if not records:
        return None

    records.sort(key=lambda x: x[0], reverse=True)
    return records[0][1], records[0][2]


def db_item_locked_row(item):
    item = normalize_db_item(item)
    locked = db_episode_key(item.get("locked_episode", ""))

    if not locked:
        return None

    record = get_db_episode_record(item, locked)

    if record:
        return {
            "title": item.get("title", ""),
            "latest_episode": locked,
            "last_seen": str(record.get("last_seen", "") or item.get("last_seen", "") or ""),
            "url": str(record.get("url", "") or item.get("url", "") or ""),
        }

    return {
        "title": item.get("title", ""),
        "latest_episode": locked,
        "last_seen": item.get("last_seen", ""),
        "url": item.get("url", ""),
    }


def is_blocked_by_db(item, episode):
    ep = db_episode_key(episode)
    if not ep:
        return False
    item = normalize_db_item(item)
    return ep in set(item.get("blocked_episodes", []))


def can_accept_blocked_by_db(item, episode):
    """
    차단된 화수라도 현재 DB 화수의 바로 다음 화수면 정상 진행으로 보고 허용.
    예: DB 24화 + 후보 90화 → 무시
        DB 89화 + 후보 90화 → 차단 해제 후 반영
    """
    item = normalize_db_item(item)
    current_num = episode_sort_value(item.get("latest_episode", ""))
    episode_num = episode_sort_value(episode)

    if current_num <= 0 or episode_num <= 0:
        return False

    return episode_num <= current_num + 1


def remove_blocked_by_db(item, episode):
    item = normalize_db_item(item)
    ep = db_episode_key(episode)

    if not ep:
        return item

    item["blocked_episodes"] = [
        str(x) for x in item.get("blocked_episodes", [])
        if db_episode_key(x) != ep
    ]

    return item


def update_db_item_from_chosen_row(item, row):
    """
    백업 py 단독 실행만으로도 DB의 현재 화수/URL이 따라가게 함.
    locked_episode가 있으면 사용자가 고른 화수를 유지.
    """
    item = normalize_db_item(item)

    locked_row = db_item_locked_row(item)
    if locked_row and locked_row.get("latest_episode"):
        item["latest_episode"] = locked_row.get("latest_episode", "")
        item["last_seen"] = locked_row.get("last_seen", item.get("last_seen", ""))
        item["url"] = locked_row.get("url", item.get("url", ""))
        return normalize_db_item(item)

    row_ep = db_episode_key(row.get("latest_episode", ""))
    item_ep = db_episode_key(item.get("latest_episode", ""))

    if not row_ep:
        return item

    row_num = episode_sort_value(row_ep)
    item_num = episode_sort_value(item_ep)

    if row_num >= item_num:
        item["latest_episode"] = row_ep
        item["last_seen"] = str(row.get("last_seen", "") or item.get("last_seen", "") or "")
        if row.get("url"):
            item["url"] = str(row.get("url", "") or "")

    return normalize_db_item(item)


def add_db_history(item, row, source="backup"):
    item = normalize_db_item(item)
    ep = db_episode_key(row.get("latest_episode", ""))
    if not ep:
        return item

    history = item.setdefault("episode_history", {})
    old = history.get(ep, {})
    row_seen = str(row.get("last_seen", "") or "")

    if not old or row_seen >= str(old.get("last_seen", "")):
        history[ep] = {
            "episode": ep,
            "url": str(row.get("url", "") or old.get("url", "") or ""),
            "last_seen": row_seen or str(old.get("last_seen", "") or ""),
            "source": source,
        }

    item["episode_history"] = history
    return item


def choose_row_with_db(db_item, candidate_row):
    """
    DB item과 후보 row 중 최종 저장할 row 선택.
    - locked_episode가 있으면 사용자가 고른 화수/링크를 최종값으로 유지.
    - 후보 row는 버리지 않고 episode_history에 저장됨.
    - locked_episode가 없으면 기존처럼 더 높은 화수로 자동 최신화.
    """
    db_item = normalize_db_item(db_item)
    locked_row = db_item_locked_row(db_item)

    if locked_row and locked_row.get("latest_episode"):
        return locked_row

    db_row = db_item_to_row(db_item)

    cand_ep = db_episode_key(candidate_row.get("latest_episode", ""))
    db_ep = db_episode_key(db_row.get("latest_episode", ""))

    if not cand_ep:
        return db_row if db_ep else candidate_row

    if not db_ep:
        return candidate_row

    cand_num = episode_sort_value(cand_ep)
    db_num = episode_sort_value(db_ep)

    if cand_num > db_num:
        result = dict(candidate_row)
        if db_item.get("manual", {}).get("title") and db_row.get("title"):
            result["title"] = db_row["title"]
        return result

    if db_num >= cand_num:
        return db_row

    return candidate_row


def is_row_seen_after_status_change(item, row):
    row_seen = str(row.get("last_seen", "") or "").strip()
    updated_at = str(item.get("updated_at", "") or "").strip()

    if not row_seen:
        return False

    if not updated_at:
        return True

    return row_seen > updated_at


def apply_manager_db_rules(rows):
    """
    최종 저장 직전 DB 규칙 적용.
    이 함수가 백업 py에서 핵심임.
    서버에서 삭제/복구/완전삭제/화수되돌리기한 결과가 자동 백업에 반영됨.
    """
    db = load_manager_db()
    items = db.get("items", {})

    if not items:
        return rows

    output = []
    used_db_keys = set()
    removed_by_status = []

    for row in rows:
        title = row.get("title", "")
        db_key = find_db_item_key(db, title)

        if not db_key:
            series_id = blacktoon_series_id_from_url(row.get("url", ""))
            db_key = find_db_item_key_by_blacktoon_series(db, series_id)

        if not db_key:
            db_item = normalize_db_item({
                "title": clean_title(row.get("title", "")),
                "latest_episode": str(row.get("latest_episode", "") or "").strip(),
                "last_seen": str(row.get("last_seen", "") or "").strip(),
                "url": str(row.get("url", "") or "").strip(),
                "__removed_link__": str(row.get("__removed_link__", "") or "").strip() or infer___removed_link___from_url(row.get("url", "")),
                "category": normalize_category(row.get("category", "")) or infer_category_from_text(row.get("url", ""), row.get("__removed_link__", ""), row.get("title", "")),
                "status": "active",
                "aliases": [],
                "manual": {},
                "episode_history": {},
                "locked_episode": "",
                "blocked_episodes": [],
            })
            db_item = add_db_history(db_item, row, source="backup_rows")
            db_key = db_title_key(db_item.get("title", ""))
            if db_key:
                items[db_key] = db_item
                used_db_keys.add(db_key)
            output.append(row)
            continue

        db_key = maybe_fix_episode_only_db_title(items, db_key, title)
        used_db_keys.add(db_key)
        db_item = normalize_db_item(items.get(db_key, {}))
        status = db_item.get("status", "active")

        # 후보 기록도 DB history에 보존
        db_item = add_db_history(db_item, row, source="backup_rows")
        items[db_key] = db_item

        if status == "purged":
            if is_row_seen_after_status_change(db_item, row):
                db_item["status"] = "active"
                status = "active"
                print(f"완전삭제 후 재방문 감지: {db_item.get('title', title)}")
            else:
                removed_by_status.append(db_item.get("title", title))
                continue

        if status == "deleted":
            removed_by_status.append(db_item.get("title", title))
            continue

        chosen = choose_row_with_db(db_item, row)
        if chosen:
            output.append(chosen)
            db_item = update_db_item_from_chosen_row(db_item, chosen)
            if status == "active":
                db_item["status"] = "active"
            items[db_key] = db_item

    # DB에는 있는데 rows에는 없는 active 항목도 살림.
    # 화수되돌리기 직후 archive/CSV 후보가 전부 blocked라 빠지는 경우 대비.
    for db_key, raw_item in items.items():
        if db_key in used_db_keys:
            continue

        db_item = normalize_db_item(raw_item)
        if db_item.get("status") != "active":
            continue

        db_row = db_item_to_row(db_item)
        if db_row.get("title") and db_row.get("latest_episode"):
            output.append(db_row)

    if removed_by_status:
        removed_unique = sorted(set(removed_by_status))
        print(f"DB 상태 적용: {len(removed_unique)}개 제외")
        for title in removed_unique[:30]:
            print(f"- {title}")
        if len(removed_unique) > 30:
            print(f"...외 {len(removed_unique) - 30}개")

    db["items"] = items
    save_manager_db(db)

    # 같은 제목 중복 제거
    merged = {}
    for row in output:
        key = make_merge_key(row)
        if not key:
            continue
        old = merged.get(key)
        merged[key] = row if old is None else choose_better(old, row)

    merged_rows = list(merged.values())
    merged_rows = apply_site_duplicate_filter(merged_rows, db)
    return merged_rows


# =========================
# URL 처리
# =========================

def extract_blacktoon_host_number(url):
    """
    구버전 이름 유지. 실제로는 tracked site의 (site_key, number)를 반환할 때 쓰는 보조 함수와 같이 사용.
    """
    info = extract_tracked_host_info(url)
    if not info:
        return None
    return info[1]


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


def get_latest_blacktoon_host_from_items(items):
    """
    이름은 구버전 호환용.
    반환값은 {"blacktoon": "...", "wfwf": "...", "tkor": "..."} 형태.
    """
    latest = {}

    for site_key, forced in FORCE_LATEST_HOSTS.items():
        if forced:
            latest[site_key] = forced.rstrip("/")

    max_nums = {}

    for item in items:
        url = item.get("url", "") if isinstance(item, dict) else str(item)
        info = extract_tracked_host_info(url)

        if not info:
            continue

        site_key, number = info

        if site_key in latest:
            continue

        if site_key not in max_nums or number > max_nums[site_key]:
            max_nums[site_key] = number

    for site_key, number in max_nums.items():
        prefix = SITE_SPECS[site_key]["prefix"]
        latest[site_key] = f"https://{prefix}{number}.com"

    return latest


def normalize_blacktoon_url(url, latest_hosts):
    """
    이름은 구버전 호환용. 블랙툰/늑대닷컴/툰코 모두 처리.
    """
    url = (url or "").strip()

    if not url or not latest_hosts:
        return url

    if isinstance(latest_hosts, str):
        # 구버전 호출 호환: 블랙툰만 변환
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


def collect_manager_db_urls(db):
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


def get_latest_blacktoon_host_from_manager_db(db):
    return get_latest_blacktoon_host_from_items(collect_manager_db_urls(db))


def normalize_manager_db_urls_to_latest(db, latest_hosts=None):
    if not latest_hosts:
        latest_hosts = get_latest_blacktoon_host_from_manager_db(db)

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


def format_latest_hosts(latest_hosts):
    if not latest_hosts:
        return ""

    if isinstance(latest_hosts, str):
        return latest_hosts

    return ", ".join(
        f"{site_label(k)}={v}" for k, v in sorted(latest_hosts.items()) if v
    )


def make_csv_hyperlink(url):
    url = (url or "").strip()

    if not url:
        return ""

    safe_url = url.replace('"', '""')
    return f'=HYPERLINK("{safe_url}","열기")'


# =========================
# 기존 CSV / archive 읽기
# =========================

def get_existing_csv_paths():
    paths = []

    for scan_dir in EXISTING_SCAN_DIRS:
        if not scan_dir.exists():
            continue

        for name in ["localreadlog_latest.csv"]:
            p = scan_dir / name
            if p.exists():
                paths.append(p)

        for pattern in ["localreadlog_latest_*.csv"]:
            paths.extend(p for p in scan_dir.glob(pattern) if p.exists())

    unique_paths = []
    seen = set()

    for p in paths:
        try:
            real = str(p.resolve())
        except Exception:
            real = str(p)

        if real in seen:
            continue

        seen.add(real)
        unique_paths.append(p)

    return unique_paths


def load_csv_to_dict(csv_path):
    data = {}

    if not csv_path.exists():
        return data

    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                item = {
                    "title": clean_title(row.get("title", "")),
                    "latest_episode": (row.get("latest_episode") or "").strip(),
                    "last_seen": (row.get("last_seen") or "").strip(),
                    "url": (row.get("url") or "").strip(),
                }

                key = make_merge_key(item)
                if not key:
                    continue

                old = data.get(key)
                data[key] = item if old is None else choose_better(old, item)

    except Exception as e:
        print(f"기존 CSV 읽기 실패: {csv_path}")
        print(e)

    return data


def load_existing_latest():
    merged = {}
    csv_paths = get_existing_csv_paths()

    for csv_path in csv_paths:
        csv_data = load_csv_to_dict(csv_path)

        for key, item in csv_data.items():
            old = merged.get(key)
            merged[key] = item if old is None else choose_better(old, item)

    print(f"기존/아카이브 CSV 읽은 개수: {len(csv_paths)}개")
    return merged


def make_backup_copy():
    if not LATEST_CSV.exists():
        return

    archive_dir = BACKUP_DIR / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = archive_dir / f"localreadlog_latest_{now}.csv"

    try:
        shutil.copy2(LATEST_CSV, backup_path)
        print(f"기존 백업 사본 생성: {backup_path}")
    except Exception as e:
        print("기존 백업 사본 생성 실패:")
        print(e)
        return

    try:
        archive_files = list(archive_dir.glob("localreadlog_latest_*.csv"))
        archive_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        for old_file in archive_files[MAX_ARCHIVE_FILES:]:
            try:
                old_file.unlink()
                print(f"오래된 archive 삭제: {old_file}")
            except Exception as e:
                print(f"오래된 archive 삭제 실패: {old_file}")
                print(e)

    except Exception as e:
        print("archive 정리 실패:")
        print(e)


# =========================
# 브라우저 방문기록 읽기
# =========================

def find_history_files(browser):
    browser_type = browser.get("type", "chromium")

    if browser_type == "firefox":
        profile_dir = browser.get("profile_dir")

        if not profile_dir or not Path(profile_dir).exists():
            return []

        return [p for p in Path(profile_dir).glob("*/places.sqlite") if p.is_file()]

    user_data_dir = browser["user_data_dir"]

    if not user_data_dir.exists():
        return []

    return [p for p in user_data_dir.glob("*/History") if p.is_file()]


def copy_history_file(history_path, browser_name, idx):
    safe_name = re.sub(r"[^a-zA-Z0-9_]+", "_", browser_name)
    tmp_path = Path(tempfile.gettempdir()) / f"{safe_name}_history_blacktoon_{os.getpid()}_{idx}.db"
    shutil.copy2(history_path, tmp_path)
    return tmp_path


def read_chromium_history_rows(browser, history_path, tmp_history, profile_name):
    browser_name = browser["name"]
    rows = []

    conn = sqlite3.connect(tmp_history)
    cur = conn.cursor()

    cur.execute("""
        SELECT url, title, last_visit_time, visit_count
        FROM urls
        WHERE url LIKE '%blacktoon%'
           OR url LIKE '%wfwf%'
           OR url LIKE '%tkor%'
        ORDER BY last_visit_time DESC
    """)

    for url, title, last_visit_time, visit_count in cur.fetchall():
        url = url or ""

        if not TRACKED_HOST_RE.match(url):
            continue

        rows.append({
            "browser": browser_name,
            "profile": profile_name,
            "url": url,
            "raw_title": title or "",
            "clean_title": clean_title(title),
            "last_seen": chrome_time_to_kst(last_visit_time),
            "visit_count": visit_count or 0,
        })

    conn.close()
    return rows


def read_firefox_history_rows(browser, history_path, tmp_history, profile_name):
    browser_name = browser["name"]
    rows = []

    conn = sqlite3.connect(tmp_history)
    cur = conn.cursor()

    cur.execute("""
        SELECT url, title, last_visit_date, visit_count
        FROM moz_places
        WHERE url LIKE '%blacktoon%'
           OR url LIKE '%wfwf%'
           OR url LIKE '%tkor%'
        ORDER BY last_visit_date DESC
    """)

    for url, title, last_visit_date, visit_count in cur.fetchall():
        url = url or ""

        if not TRACKED_HOST_RE.match(url):
            continue

        rows.append({
            "browser": browser_name,
            "profile": profile_name,
            "url": url,
            "raw_title": title or "",
            "clean_title": clean_title(title),
            "last_seen": firefox_time_to_kst(last_visit_date),
            "visit_count": visit_count or 0,
        })

    conn.close()
    return rows


def read_browser_blacktoon_rows(browser):
    browser_name = browser["name"]
    history_files = find_history_files(browser)

    rows = []
    searched_db_count = 0

    for idx, history_path in enumerate(history_files):
        profile_name = history_path.parent.name
        tmp_history = None

        try:
            tmp_history = copy_history_file(history_path, browser_name, idx)
        except Exception as e:
            print(f"{browser_name} 방문기록 복사 실패: {history_path}")
            print(e)
            continue

        try:
            if browser.get("type") == "firefox":
                profile_rows = read_firefox_history_rows(browser, history_path, tmp_history, profile_name)
            else:
                profile_rows = read_chromium_history_rows(browser, history_path, tmp_history, profile_name)

            searched_db_count += 1
            rows.extend(profile_rows)

        except Exception as e:
            print(f"{browser_name} 방문기록 읽기 실패: {history_path}")
            print(e)

        finally:
            if tmp_history:
                try:
                    Path(tmp_history).unlink(missing_ok=True)
                except Exception:
                    pass

    return rows, searched_db_count


def get_browser_enabled_settings():
    db = load_manager_db()
    settings = db.get("settings", {})
    enabled = settings.get("browser_enabled", DEFAULT_BROWSER_ENABLED)

    result = {}
    for browser in BROWSERS:
        key = browser.get("key")
        result[key] = bool(enabled.get(key, True))

    return result


def read_all_blacktoon_rows():
    all_rows = []
    stats = {}
    enabled = get_browser_enabled_settings()

    for browser in BROWSERS:
        browser_key = browser.get("key", browser.get("name", "").lower())
        browser_name = browser["name"]

        if not enabled.get(browser_key, True):
            stats[browser_name] = {
                "db_count": 0,
                "tracked_count": 0,
                "blacktoon_count": 0,
                "enabled": False,
            }
            print(f"- {browser_name}: 연동 꺼짐")
            continue

        rows, db_count = read_browser_blacktoon_rows(browser)
        all_rows.extend(rows)

        stats[browser_name] = {
            "db_count": db_count,
            "tracked_count": len(rows),
            "blacktoon_count": len(rows),
            "enabled": True,
        }

    return all_rows, stats


# =========================
# 방문기록 -> 최신 화수 변환
# =========================

def sync_all_episode_history_from_browser(rows, ignore_titles=None):
    """
    브라우저 방문기록에 남아 있는 모든 회차 URL을 localreadlog_db.json의 episode_history에 저장.
    블랙툰/늑대닷컴/툰코를 같은 DB에서 관리함.
    """
    if ignore_titles is None:
        ignore_titles = set()

    db = load_manager_db()
    items = db.get("items", {})
    series_titles = {}

    for row in rows:
        info = extract_series_page_info(row)
        if not info:
            continue

        series_titles.setdefault(info["series_id"], info["title"])

    changed = 0

    for row in rows:
        info = extract_episode_page_info(row, series_titles)
        if not info:
            continue

        title = info["title"]

        if is_ignored_title(title, ignore_titles):
            continue

        item_row = {
            "title": title,
            "latest_episode": info["latest_episode"],
            "last_seen": row["last_seen"],
            "url": info["url"],
        }

        db_key = find_db_item_key(db, title)

        if not db_key and info.get("site") == "blacktoon":
            series_id = blacktoon_series_id_from_url(info.get("url", ""))
            db_key = find_db_item_key_by_blacktoon_series(db, series_id)

        if db_key:
            db_key = maybe_fix_episode_only_db_title(items, db_key, title)
            item = normalize_db_item(items.get(db_key, {}))
        else:
            item = normalize_db_item({
                "title": title,
                "latest_episode": info["latest_episode"],
                "last_seen": row["last_seen"],
                "url": info["url"],
                "status": "active",
                "aliases": [],
                "manual": {},
                "episode_history": {},
                "locked_episode": "",
                "blocked_episodes": [],
            })
            db_key = db_title_key(title)

        before_count = len(item.get("episode_history", {}) or {})
        item = add_db_history(item, item_row, source=f"{info['site']}_browser_history")

        # locked_episode가 없을 때만 DB 현재값 자동 갱신.
        if not db_episode_key(item.get("locked_episode", "")):
            chosen = choose_row_with_db(item, item_row)
            if chosen:
                item = update_db_item_from_chosen_row(item, chosen)

        items[db_key] = normalize_db_item(item)

        after_count = len(item.get("episode_history", {}) or {})
        if after_count > before_count:
            changed += 1

    db["items"] = items
    latest_hosts = get_latest_blacktoon_host_from_items(rows)
    db = normalize_manager_db_urls_to_latest(db, latest_hosts)
    save_manager_db(db)

    if changed:
        print(f"DB 전체 회차 기록 저장: 새 회차 {changed}개")

    if latest_hosts:
        print(f"DB 저장 링크 최신 도메인으로 정리: {format_latest_hosts(latest_hosts)}")



def _lrl_live_latest_hosts_from_rows(items):
    latest = {}
    try:
        for site_key, forced in (FORCE_LATEST_HOSTS or {}).items():
            if forced:
                latest[site_key] = forced.rstrip("/")
    except Exception:
        pass

    max_nums = {}
    for item in items or []:
        if isinstance(item, dict):
            url = item.get("url", "")
            title = item.get("title") or item.get("clean_title") or item.get("raw_title") or ""
        else:
            url = str(item)
            title = ""
        if _lrl_history_title_is_connection_error(title):
            continue
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

def build_latest_from_history(rows, ignore_titles=None):
    global _LRL_OBSERVED_LIVE_HOSTS
    if ignore_titles is None:
        ignore_titles = set()

    _LRL_OBSERVED_LIVE_HOSTS = _lrl_live_latest_hosts_from_rows(rows)

    series_titles = {}

    for row in rows:
        info = extract_series_page_info(row)
        if not info:
            continue

        series_titles.setdefault(info["series_id"], info["title"])

    latest_by_series = {}
    total_episode_pages = 0

    for row in rows:
        info = extract_episode_page_info(row, series_titles)
        if not info:
            continue

        total_episode_pages += 1

        title = info["title"]

        if is_ignored_title(title, ignore_titles):
            continue

        item = {
            "title": title,
            "latest_episode": info["latest_episode"],
            "last_seen": row["last_seen"],
            "url": info["url"],
        }

        old = latest_by_series.get(info["series_id"])
        latest_by_series[info["series_id"]] = item if old is None else choose_better(old, item)

    return latest_by_series, total_episode_pages


# =========================
# 출력 파일 생성
# =========================

def save_latest_html(rows):
    cards = []

    for row in rows:
        title = html.escape(str(row.get("title", "")))
        latest_episode = html.escape(_lrl_episode_display_label(row.get("latest_episode", "")))
        last_seen = html.escape(str(row.get("last_seen", "")))
        url = html.escape(str(row.get("url", "")), quote=True)

        cards.append(f"""
        <div class="card" data-search="{title} {latest_episode} {last_seen}">
            <div class="title">{title}</div>
            <div class="meta">
                <span>{latest_episode}</span>
                <span>{last_seen}</span>
            </div>
            <a class="open" href="{url}" target="_blank">열기</a>
        </div>
        """)

    content = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LocalReadLog 최신 기록</title>
<style>
body {{
    margin: 0;
    padding: 14px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f3f3f3;
    color: #111;
}}
h1 {{
    font-size: 20px;
    margin: 4px 0 12px;
}}
.top {{
    position: sticky;
    top: 0;
    background: #f3f3f3;
    padding-bottom: 10px;
    z-index: 10;
}}
#search {{
    width: 100%;
    box-sizing: border-box;
    padding: 12px;
    border: 1px solid #ccc;
    border-radius: 10px;
    font-size: 16px;
}}
.count {{
    margin: 8px 2px;
    font-size: 13px;
    color: #666;
}}
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
.open {{
    display: block;
    text-align: center;
    padding: 11px;
    border-radius: 10px;
    background: #111;
    color: white;
    text-decoration: none;
    font-weight: 700;
}}
.hidden {{
    display: none;
}}
</style>
</head>
<body>
<div class="top">
    <h1>LocalReadLog 최신 기록</h1>
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
</html>
"""

    LATEST_HTML.write_text(content, encoding="utf-8")


def save_latest_pc_html(rows):
    table_rows = []

    for row in rows:
        title = html.escape(str(row.get("title", "")))
        latest_episode = html.escape(_lrl_episode_display_label(row.get("latest_episode", "")))
        last_seen = html.escape(str(row.get("last_seen", "")))
        url_text = html.escape(str(row.get("url", "")))
        url_attr = html.escape(str(row.get("url", "")), quote=True)

        table_rows.append(f"""
        <tr data-search="{title} {latest_episode} {last_seen} {url_text}">
            <td class="title">{title}</td>
            <td class="episode">{latest_episode}</td>
            <td class="time">{last_seen}</td>
            <td class="open-cell"><a class="open" href="{url_attr}" target="_blank">열기</a></td>
            <td class="url"><a href="{url_attr}" target="_blank">{url_text}</a></td>
        </tr>
        """)

    content = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>LocalReadLog 최신 기록 PC</title>
<style>
body {{
    margin: 0;
    font-family: "Segoe UI", "Malgun Gothic", sans-serif;
    background: #f5f5f5;
    color: #111;
}}
.wrap {{
    padding: 20px;
}}
h1 {{
    margin: 0 0 14px;
    font-size: 24px;
}}
.top {{
    position: sticky;
    top: 0;
    z-index: 20;
    background: #f5f5f5;
    padding: 14px 0;
    border-bottom: 1px solid #ddd;
}}
#search {{
    width: 420px;
    max-width: 100%;
    padding: 10px 12px;
    font-size: 15px;
    border: 1px solid #bbb;
    border-radius: 8px;
    box-sizing: border-box;
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
    white-space: nowrap;
}}
td {{
    border-bottom: 1px solid #eee;
    padding: 9px 10px;
    font-size: 14px;
    vertical-align: middle;
}}
tr:hover {{
    background: #f0f6ff;
}}
.title {{
    font-weight: 700;
    min-width: 180px;
}}
.episode {{
    width: 90px;
    text-align: center;
    white-space: nowrap;
}}
.time {{
    width: 170px;
    white-space: nowrap;
    color: #555;
}}
.open-cell {{
    width: 70px;
    text-align: center;
}}
.open {{
    display: inline-block;
    padding: 6px 12px;
    border-radius: 6px;
    background: #111;
    color: white;
    text-decoration: none;
    font-weight: 700;
}}
.url {{
    max-width: 520px;
    word-break: break-all;
    color: #555;
}}
.url a {{
    color: #555;
    text-decoration: none;
}}
.url a:hover {{
    text-decoration: underline;
}}
.hidden {{
    display: none;
}}
</style>
</head>
<body>
<div class="wrap">
    <div class="top">
        <h1>LocalReadLog 최신 기록 PC</h1>
        <input id="search" placeholder="작품명 / 화수 / 주소 검색">
        <span class="count" id="count"></span>
    </div>

    <table>
        <thead>
            <tr>
                <th>작품명</th>
                <th>최신 화수</th>
                <th>최근 확인</th>
                <th>열기</th>
                <th>URL</th>
            </tr>
        </thead>
        <tbody>{''.join(table_rows)}</tbody>
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
</html>
"""

    LATEST_PC_HTML.write_text(content, encoding="utf-8")


def save_latest_files(rows):
    latest_hosts = get_latest_blacktoon_host_from_items(rows)

    if latest_hosts:
        db = load_manager_db()
        db = normalize_manager_db_urls_to_latest(db, latest_hosts)
        save_manager_db(db)

    output_rows = []

    for row in rows:
        new_row = dict(row)
        new_row["title"] = clean_title(new_row.get("title", ""))
        new_row["url"] = normalize_blacktoon_url(new_row.get("url", ""), latest_hosts)
        new_row["__removed_link__"] = normalize_blacktoon_url(
            new_row.get("__removed_link__", "") or infer___removed_link___from_url(new_row.get("url", "")),
            latest_hosts,
        )
        new_row["category"] = category_label_for_row(new_row)
        new_row["open"] = make_csv_hyperlink(new_row.get("url", ""))
        output_rows.append(new_row)

    with LATEST_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["title", "latest_episode", "last_seen", "category", "open", "url", "__removed_link__"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(output_rows)

    save_latest_html(output_rows)
    save_latest_pc_html(output_rows)

    if latest_hosts:
        print(f"URL 최신 도메인으로 정리: {format_latest_hosts(latest_hosts)}")

    print(f"CSV 저장: {LATEST_CSV}")
    print(f"모바일 HTML 저장: {LATEST_HTML}")
    print(f"PC HTML 저장: {LATEST_PC_HTML}")


# =========================
# 실행
# =========================

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
        label_to_key[str(key).strip().lower()] = key
        label_to_key[str(spec.get("label", key)).strip().lower()] = key

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


def normalize_db_settings(db):
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


def get_dynamic_site_specs():
    db = load_manager_db()
    db = normalize_db_settings(db)
    return db.get("settings", {}).get("sites", DEFAULT_SITE_SPECS)


def site_label(site_key):
    return SITE_SPECS.get(site_key, {}).get("label", site_key or "")


def get_site_key(url):
    url = str(url or "").strip()

    try:
        host = urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return ""

    host = re.sub(r"^www\.", "", host)

    for site_key, spec in SITE_SPECS.items():
        if spec.get("enabled") is False:
            continue

        host_re = spec.get("host_re", "")
        if not host_re:
            continue

        if re.fullmatch(host_re, host, flags=re.I):
            return site_key

    return ""


def extract_tracked_host_info(url):
    url = str(url or "")

    for site_key, spec in SITE_SPECS.items():
        if spec.get("enabled") is False:
            continue

        host_re = spec.get("host_re", "")
        if not host_re:
            continue

        match = re.search(rf"https?://(?:www\.)?({host_re})", url, re.I)
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


def url_matches_dynamic_site(url):
    return bool(get_site_key(url))


def build_history_like_patterns(site_specs):
    patterns = []

    for spec in site_specs.values():
        if spec.get("enabled") is False:
            continue

        prefix = str(spec.get("prefix", "") or "").strip()
        host_re = str(spec.get("host_re", "") or "").strip()

        if prefix:
            patterns.append(f"%{prefix}%")

        # host_re가 example\d+\.com이면 example 정도라도 LIKE에 사용
        plain = re.sub(r"\\d\+", "", host_re)
        plain = re.sub(r"\\\.", ".", plain)
        plain = re.sub(r"[^0-9A-Za-z가-힣.-]+", "", plain)
        if plain and plain not in ["com", ".com"]:
            patterns.append(f"%{plain.split('.')[0]}%")

    unique = []
    seen = set()
    for p in patterns:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    return unique


def read_chromium_history_rows(browser, history_path, tmp_history, profile_name):
    browser_name = browser["name"]
    rows = []
    site_specs = get_dynamic_site_specs()
    like_patterns = build_history_like_patterns(site_specs)

    if not like_patterns:
        return rows

    conn = sqlite3.connect(tmp_history)
    cur = conn.cursor()

    where_sql = " OR ".join(["url LIKE ?"] * len(like_patterns))
    cur.execute(f"""
        SELECT url, title, last_visit_time, visit_count
        FROM urls
        WHERE {where_sql}
        ORDER BY last_visit_time DESC
    """, like_patterns)

    for url, title, last_visit_time, visit_count in cur.fetchall():
        url = url or ""

        if not url_matches_dynamic_site(url):
            continue

        rows.append({
            "browser": browser_name,
            "profile": profile_name,
            "url": url,
            "raw_title": title or "",
            "clean_title": clean_title(title),
            "last_seen": chrome_time_to_kst(last_visit_time),
            "visit_count": visit_count or 0,
        })

    conn.close()
    return rows


def read_firefox_history_rows(browser, history_path, tmp_history, profile_name):
    browser_name = browser["name"]
    rows = []
    site_specs = get_dynamic_site_specs()
    like_patterns = build_history_like_patterns(site_specs)

    if not like_patterns:
        return rows

    conn = sqlite3.connect(tmp_history)
    cur = conn.cursor()

    where_sql = " OR ".join(["url LIKE ?"] * len(like_patterns))
    cur.execute(f"""
        SELECT url, title, last_visit_date, visit_count
        FROM moz_places
        WHERE {where_sql}
        ORDER BY last_visit_date DESC
    """, like_patterns)

    for url, title, last_visit_date, visit_count in cur.fetchall():
        url = url or ""

        if not url_matches_dynamic_site(url):
            continue

        rows.append({
            "browser": browser_name,
            "profile": profile_name,
            "url": url,
            "raw_title": title or "",
            "clean_title": clean_title(title),
            "last_seen": firefox_time_to_kst(last_visit_date),
            "visit_count": visit_count or 0,
        })

    conn.close()
    return rows


def get_latest_blacktoon_host_from_items(items):
    latest = {}
    max_nums = {}

    for item in items:
        url = item.get("url", "") if isinstance(item, dict) else str(item)
        info = extract_tracked_host_info(url)

        if not info:
            continue

        site_key, number = info
        if number <= 0:
            continue

        if site_key not in max_nums or number > max_nums[site_key]:
            max_nums[site_key] = number

    for site_key, number in max_nums.items():
        prefix = SITE_SPECS.get(site_key, {}).get("prefix", site_key)
        latest[site_key] = f"https://{prefix}{number}.com"

    return latest


def normalize_blacktoon_url(url, latest_hosts):
    url = (url or "").strip()

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


def normalize_manager_db_urls_to_latest(db, latest_hosts=None):
    if not latest_hosts:
        latest_hosts = get_latest_blacktoon_host_from_manager_db(db)

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


def format_latest_hosts(latest_hosts):
    if not latest_hosts:
        return ""

    if isinstance(latest_hosts, str):
        return latest_hosts

    return ", ".join(
        f"{site_label(k)}={v}" for k, v in sorted(latest_hosts.items()) if v
    )


# =========================
# 범용 작품/회차 인식: 웹툰·만화·소설·애니
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


def parse_episode_number(title):
    title = clean_title(title)

    patterns = [
        r"(?:외전\s*)?(\d+(?:\.\d+)?)\s*(?:화|회|편|장|권|話|章)",
        r"(?:第)\s*(\d+(?:\.\d+)?)\s*(?:話|章)",
        r"(?:episode|ep\.?|e|chapter|ch\.?)\s*[-_:]?\s*(\d+(?:\.\d+)?)",
        r"(?:^|[\s\-_])#?(\d+(?:\.\d+)?)\s*$",
    ]

    matches = []
    for pattern in patterns:
        matches.extend(re.findall(pattern, title, flags=re.I))

    if not matches:
        return ""

    number_text = str(matches[-1])

    try:
        number = float(number_text)
        if number.is_integer():
            return str(int(number))
        return str(number)
    except Exception:
        return number_text


def infer_series_title_from_episode_title(episode_title):
    title = clean_title(episode_title)

    # 예: 0125 - 무당기협 125화 -> 무당기협 125화
    title = re.sub(r"^\d{3,6}\s*[-–—]\s*", "", title)

    # 뒤쪽 회차 표현 제거: 웹툰/만화/소설/애니 공통
    title = re.sub(
        r"\s*(?:외전\s*)?\d+(?:\.\d+)?\s*(?:화|회|편|장|권|話|章).*$",
        "",
        title,
        flags=re.I,
    )
    title = re.sub(
        r"\s*(?:episode|ep\.?|e|chapter|ch\.?)\s*[-_:]?\s*\d+(?:\.\d+)?.*$",
        "",
        title,
        flags=re.I,
    )
    title = re.sub(r"\s*[-–—_:]?\s*#?\d+(?:\.\d+)?\s*$", "", title)

    return title.strip()


def infer___removed_link___from_url(url):
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

    # 범용: 마지막 조각이 회차면 제거
    if len(parts) >= 2 and _segment_looks_episode(parts[-1]):
        return f"{parsed.scheme}://{parsed.netloc}/" + "/".join(parts[:-1])

    # 이미 작품 페이지일 가능성
    if cat_idx is not None and len(parts) >= cat_idx + 2:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    return ""


def generic_series_id_from_url(site_key, url, assume_episode=False):
    try:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
    except Exception:
        path = ""

    if not path:
        return f"{site_key}:root"

    parts = [p for p in path.split("/") if p]

    if assume_episode and len(parts) >= 2:
        __removed_link__ = infer___removed_link___from_url(url)
        if __removed_link__:
            try:
                series_path = urlparse(__removed_link__).path.strip("/")
                return f"{site_key}:url:{series_path}"
            except Exception:
                pass

        parts = parts[:-1]

    normalized = "/".join(parts) or path
    normalized = re.sub(r"[^0-9A-Za-z가-힣_./-]+", "_", normalized).strip("_")

    return f"{site_key}:url:{normalized or path}"


def extract_series_page_info(row):
    url = row.get("url", "")
    site_key = get_site_key(url)

    if not site_key:
        return None

    title = clean_title(row.get("clean_title", "") or row.get("raw_title", ""))

    if is_bad_title(title):
        return None

    blacktoon_match = SERIES_PAGE_RE.match(url)
    if blacktoon_match:
        return {
            "site": site_key,
            "series_id": f"{site_key}:id:{blacktoon_match.group(1)}",
            "title": display_title_for_site(site_key, title),
            "__removed_link__": infer___removed_link___from_url(url) or url,
        }

    if parse_episode_number(title):
        return None

    __removed_link__ = infer___removed_link___from_url(url)

    if not __removed_link__:
        return None

    return {
        "site": site_key,
        "series_id": generic_series_id_from_url(site_key, __removed_link__, assume_episode=False),
        "title": display_title_for_site(site_key, title),
        "__removed_link__": __removed_link__,
    }


def extract_episode_page_info(row, series_titles=None):
    if series_titles is None:
        series_titles = {}

    url = row.get("url", "")
    site_key = get_site_key(url)

    if not site_key:
        return None

    episode_title = clean_title(row.get("clean_title", "") or row.get("raw_title", ""))
    latest_episode = parse_episode_number(episode_title)

    if not latest_episode:
        return None

    if is_bad_title(episode_title):
        return None

    blacktoon_match = EPISODE_PAGE_RE.match(url)
    if blacktoon_match:
        series_id = f"{site_key}:id:{blacktoon_match.group(1)}"
        data = series_titles.get(series_id, {})

        if isinstance(data, str):
            data = {"title": data}

        if looks_like_episode_only_title(episode_title):
            title = data.get("title", "")
        else:
            title = data.get("title") or infer_series_title_from_episode_title(episode_title)

        if not title:
            title = f"작품ID {blacktoon_match.group(1)}"

        return {
            "site": site_key,
            "series_id": series_id,
            "title": display_title_for_site(site_key, title),
            "latest_episode": latest_episode,
            "url": url,
            "__removed_link__": data.get("__removed_link__") or infer___removed_link___from_url(url),
        }

    series_id = generic_series_id_from_url(site_key, url, assume_episode=True)
    data = series_titles.get(series_id, {})

    if isinstance(data, str):
        data = {"title": data}

    title = data.get("title") or infer_series_title_from_episode_title(episode_title)

    if not title:
        title = series_id.rsplit(":", 1)[-1] or "제목없음"

    return {
        "site": site_key,
        "series_id": series_id,
        "title": display_title_for_site(site_key, title),
        "latest_episode": latest_episode,
        "url": url,
        "__removed_link__": data.get("__removed_link__") or infer___removed_link___from_url(url),
    }


def normalize_db_item(item):
    item = dict(item or {})
    item["title"] = clean_title(item.get("title", ""))
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

    if not item.get("__removed_link__"):
        item["__removed_link__"] = infer___removed_link___from_url(item.get("url", ""))

    if item["status"] not in ["active", "deleted", "purged"]:
        item["status"] = "active"

    aliases = []
    seen = set()
    title_key_value = db_title_key(item.get("title", ""))

    for alias in item.get("aliases", []):
        alias = clean_title(alias)
        key = db_title_key(alias)
        if not alias or key == title_key_value or key in seen:
            continue
        seen.add(key)
        aliases.append(alias)

    item["aliases"] = aliases
    item["blocked_episodes"] = [db_episode_key(x) for x in item.get("blocked_episodes", []) if db_episode_key(x)]

    history = {}
    for ep, record in (item.get("episode_history", {}) or {}).items():
        if not isinstance(record, dict):
            continue
        rec = dict(record)
        if not rec.get("__removed_link__"):
            rec["__removed_link__"] = infer___removed_link___from_url(rec.get("url", "")) or item.get("__removed_link__", "")
        history[ep] = rec
    item["episode_history"] = history

    return item


def db_item_to_row(item):
    item = normalize_db_item(item)
    return {
        "title": item.get("title", ""),
        "latest_episode": str(item.get("latest_episode", "") or "").strip(),
        "last_seen": str(item.get("last_seen", "") or "").strip(),
        "url": str(item.get("url", "") or "").strip(),
        "__removed_link__": str(item.get("__removed_link__", "") or infer___removed_link___from_url(item.get("url", "")) or "").strip(),
    }


def db_item_locked_row(item):
    item = normalize_db_item(item)
    locked = db_episode_key(item.get("locked_episode", ""))

    if not locked:
        return None

    record = get_db_episode_record(item, locked)

    if record:
        return {
            "title": item.get("title", ""),
            "latest_episode": locked,
            "last_seen": str(record.get("last_seen", "") or item.get("last_seen", "") or ""),
            "url": str(record.get("url", "") or item.get("url", "") or ""),
            "__removed_link__": str(record.get("__removed_link__", "") or item.get("__removed_link__", "") or ""),
        }

    return {
        "title": item.get("title", ""),
        "latest_episode": locked,
        "last_seen": item.get("last_seen", ""),
        "url": item.get("url", ""),
        "__removed_link__": item.get("__removed_link__", ""),
    }


def add_db_history(item, row, source="backup"):
    item = normalize_db_item(item)
    ep = db_episode_key(row.get("latest_episode", ""))
    if not ep:
        return item

    history = item.setdefault("episode_history", {})
    old = history.get(ep, {})
    row_seen = str(row.get("last_seen", "") or "")
    __removed_link__ = str(row.get("__removed_link__", "") or "").strip() or infer___removed_link___from_url(row.get("url", "")) or item.get("__removed_link__", "")

    if __removed_link__ and not item.get("__removed_link__"):
        item["__removed_link__"] = __removed_link__

    if not old or row_seen >= str(old.get("last_seen", "")):
        history[ep] = {
            "episode": ep,
            "url": str(row.get("url", "") or old.get("url", "") or ""),
            "__removed_link__": str(__removed_link__ or old.get("__removed_link__", "") or ""),
            "last_seen": row_seen or str(old.get("last_seen", "") or ""),
            "source": source,
        }

    item["episode_history"] = history
    return normalize_db_item(item)


def update_db_item_from_chosen_row(item, row):
    item = normalize_db_item(item)

    locked_row = db_item_locked_row(item)
    if locked_row and locked_row.get("latest_episode"):
        item["latest_episode"] = locked_row.get("latest_episode", "")
        item["last_seen"] = locked_row.get("last_seen", item.get("last_seen", ""))
        item["url"] = locked_row.get("url", item.get("url", ""))
        item["__removed_link__"] = locked_row.get("__removed_link__", item.get("__removed_link__", ""))
        return normalize_db_item(item)

    row_ep = db_episode_key(row.get("latest_episode", ""))
    item_ep = db_episode_key(item.get("latest_episode", ""))

    if not row_ep:
        return item

    row_num = episode_sort_value(row_ep)
    item_num = episode_sort_value(item_ep)
    row___removed_link__ = str(row.get("__removed_link__", "") or "").strip() or infer___removed_link___from_url(row.get("url", ""))

    if row___removed_link__:
        item["__removed_link__"] = row___removed_link__

    if row_num >= item_num:
        item["latest_episode"] = row_ep
        item["last_seen"] = str(row.get("last_seen", "") or item.get("last_seen", "") or "")
        if row.get("url"):
            item["url"] = str(row.get("url", "") or "")
        if row___removed_link__:
            item["__removed_link__"] = row___removed_link__

    return normalize_db_item(item)


def sync_all_episode_history_from_browser(rows, ignore_titles=None):
    if ignore_titles is None:
        ignore_titles = set()

    db = load_manager_db()
    items = db.get("items", {})
    series_titles = {}

    for row in rows:
        info = extract_series_page_info(row)
        if not info:
            continue

        series_titles.setdefault(info["series_id"], {
            "title": info.get("title", ""),
            "__removed_link__": info.get("__removed_link__", ""),
        })

    changed = 0

    for row in rows:
        info = extract_episode_page_info(row, series_titles)
        if not info:
            continue

        title = info["title"]

        if is_ignored_title(title, ignore_titles):
            continue

        item_row = {
            "title": title,
            "latest_episode": info["latest_episode"],
            "last_seen": row["last_seen"],
            "url": info["url"],
            "__removed_link__": info.get("__removed_link__", ""),
        }

        db_key = find_db_item_key(db, title)

        if not db_key and info.get("site") == "blacktoon":
            series_id = blacktoon_series_id_from_url(info.get("url", ""))
            db_key = find_db_item_key_by_blacktoon_series(db, series_id)

        if db_key:
            db_key = maybe_fix_episode_only_db_title(items, db_key, title)
            item = normalize_db_item(items.get(db_key, {}))
        else:
            item = normalize_db_item({
                "title": title,
                "latest_episode": info["latest_episode"],
                "last_seen": row["last_seen"],
                "url": info["url"],
                "__removed_link__": info.get("__removed_link__", ""),
                "status": "active",
                "aliases": [],
                "manual": {},
                "episode_history": {},
                "locked_episode": "",
                "blocked_episodes": [],
            })
            db_key = db_title_key(title)

        before_count = len(item.get("episode_history", {}) or {})
        item = add_db_history(item, item_row, source=f"{info['site']}_browser_history")

        if info.get("__removed_link__"):
            item["__removed_link__"] = info.get("__removed_link__", "")

        if not db_episode_key(item.get("locked_episode", "")):
            chosen = choose_row_with_db(item, item_row)
            if chosen:
                item = update_db_item_from_chosen_row(item, chosen)

        items[db_key] = normalize_db_item(item)

        after_count = len(item.get("episode_history", {}) or {})
        if after_count > before_count:
            changed += 1

    db["items"] = items
    latest_hosts = get_latest_blacktoon_host_from_items(rows)
    db = normalize_manager_db_urls_to_latest(db, latest_hosts)
    save_manager_db(db)

    if changed:
        print(f"DB 전체 회차 기록 저장: 새 회차 {changed}개")

    if latest_hosts:
        print(f"DB 저장 링크 최신 도메인으로 정리: {format_latest_hosts(latest_hosts)}")


def build_latest_from_history(rows, ignore_titles=None):
    if ignore_titles is None:
        ignore_titles = set()

    series_titles = {}

    for row in rows:
        info = extract_series_page_info(row)
        if not info:
            continue

        series_titles.setdefault(info["series_id"], {
            "title": info.get("title", ""),
            "__removed_link__": info.get("__removed_link__", ""),
        })

    latest_by_series = {}
    total_episode_pages = 0

    for row in rows:
        info = extract_episode_page_info(row, series_titles)
        if not info:
            continue

        total_episode_pages += 1

        title = info["title"]

        if is_ignored_title(title, ignore_titles):
            continue

        item = {
            "title": title,
            "latest_episode": info["latest_episode"],
            "last_seen": row["last_seen"],
            "url": info["url"],
            "__removed_link__": info.get("__removed_link__", ""),
        }

        old = latest_by_series.get(info["series_id"])
        latest_by_series[info["series_id"]] = item if old is None else choose_better(old, item)

    return latest_by_series, total_episode_pages

# =========================
# 작품 주소 보정: 블랙툰 외 사이트 / 웹툰·만화·소설·애니
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

    if len(parts) >= 2 and _segment_looks_episode(parts[-1]):
        return f"{parsed.scheme}://{parsed.netloc}/" + "/".join(parts[:-1])

    if len(parts) >= 3 and parts[-2].lower() in ["view", "read", "watch", "play", "episode", "chapter", "ep", "ch"]:
        if _segment_looks_episode(parts[-1]):
            return f"{parsed.scheme}://{parsed.netloc}/" + "/".join(parts[:-2])

    if cat_idx is not None and len(parts) >= cat_idx + 2:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    if len(parts) >= 1:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    return ""

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


def category_label(category):
    return CATEGORY_LABELS.get(normalize_category(category), "기타")


def category_label_for_row(row):
    category = normalize_category(row.get("category", ""))
    if category == "other":
        category = infer_category_from_text(row.get("url", ""), row.get("__removed_link__", ""), row.get("title", ""))

    if category == "other":
        site_key = get_site_key(row.get("url", ""))
        try:
            db = load_manager_db()
            db = normalize_db_settings(db)
            site_category = db.get("settings", {}).get("sites", {}).get(site_key, {}).get("category", "")
            category = normalize_category(site_category)
        except Exception:
            pass

    return category_label(category)


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

    if "blacktoon" in sites and normalize_category(sites["blacktoon"].get("category")) == "other":
        sites["blacktoon"]["category"] = "webtoon"

    return sites


def normalize_db_item(item):
    item = dict(item or {})
    item["title"] = clean_title(item.get("title", ""))
    item.setdefault("latest_episode", "")
    item.setdefault("last_seen", "")
    item.setdefault("url", "")
    item.setdefault("__removed_link__", "")
    item.setdefault("category", "")
    item.setdefault("status", "active")
    item.setdefault("aliases", [])
    item.setdefault("manual", {})
    item.setdefault("episode_history", {})
    item.setdefault("locked_episode", "")
    item.setdefault("blocked_episodes", [])

    if not item.get("__removed_link__"):
        item["__removed_link__"] = infer___removed_link___from_url(item.get("url", ""))

    manual = item.setdefault("manual", {})
    category = normalize_category(item.get("category", ""))

    if not manual.get("category"):
        inferred = infer_category_from_text(item.get("url", ""), item.get("__removed_link__", ""), item.get("title", ""))
        if inferred != "other":
            category = inferred
        elif category == "other":
            try:
                site_key = get_site_key(item.get("url", ""))
                category = normalize_category(SITE_SPECS.get(site_key, {}).get("category", "other"))
            except Exception:
                pass

    item["category"] = category

    if item["status"] not in ["active", "deleted", "purged"]:
        item["status"] = "active"

    aliases = []
    seen = set()
    title_key_value = db_title_key(item.get("title", ""))

    for alias in item.get("aliases", []):
        alias = clean_title(alias)
        key = db_title_key(alias)
        if not alias or key == title_key_value or key in seen:
            continue
        seen.add(key)
        aliases.append(alias)

    item["aliases"] = aliases
    item["blocked_episodes"] = [db_episode_key(x) for x in item.get("blocked_episodes", []) if db_episode_key(x)]

    history = {}
    for ep, record in (item.get("episode_history", {}) or {}).items():
        if not isinstance(record, dict):
            continue
        rec = dict(record)
        if not rec.get("__removed_link__"):
            rec["__removed_link__"] = infer___removed_link___from_url(rec.get("url", "")) or item.get("__removed_link__", "")
        history[ep] = rec
    item["episode_history"] = history

    return item


def db_item_to_row(item):
    item = normalize_db_item(item)
    return {
        "title": item.get("title", ""),
        "latest_episode": str(item.get("latest_episode", "") or "").strip(),
        "last_seen": str(item.get("last_seen", "") or "").strip(),
        "url": str(item.get("url", "") or "").strip(),
        "__removed_link__": str(item.get("__removed_link__", "") or infer___removed_link___from_url(item.get("url", "")) or "").strip(),
        "category": category_label(item.get("category", "other")),
    }


def add_db_history(item, row, source="backup"):
    item = normalize_db_item(item)
    ep = db_episode_key(row.get("latest_episode", ""))
    if not ep:
        return item

    history = item.setdefault("episode_history", {})
    old = history.get(ep, {})
    row_seen = str(row.get("last_seen", "") or "")
    __removed_link__ = str(row.get("__removed_link__", "") or "").strip() or infer___removed_link___from_url(row.get("url", "")) or item.get("__removed_link__", "")

    if __removed_link__ and not item.get("__removed_link__"):
        item["__removed_link__"] = __removed_link__

    if not item.get("manual", {}).get("category"):
        category = normalize_category(row.get("category", ""))
        if category == "other":
            category = infer_category_from_text(row.get("url", ""), __removed_link__, row.get("title", ""))
        if category != "other":
            item["category"] = category

    if not old or row_seen >= str(old.get("last_seen", "")):
        history[ep] = {
            "episode": ep,
            "url": str(row.get("url", "") or old.get("url", "") or ""),
            "__removed_link__": str(__removed_link__ or old.get("__removed_link__", "") or ""),
            "last_seen": row_seen or str(old.get("last_seen", "") or ""),
            "source": source,
        }

    item["episode_history"] = history
    return normalize_db_item(item)


def update_db_item_from_chosen_row(item, row):
    item = normalize_db_item(item)

    locked_row = db_item_locked_row(item)
    if locked_row and locked_row.get("latest_episode"):
        item["latest_episode"] = locked_row.get("latest_episode", "")
        item["last_seen"] = locked_row.get("last_seen", item.get("last_seen", ""))
        item["url"] = locked_row.get("url", item.get("url", ""))
        item["__removed_link__"] = locked_row.get("__removed_link__", item.get("__removed_link__", ""))
        return normalize_db_item(item)

    row_ep = db_episode_key(row.get("latest_episode", ""))
    item_ep = db_episode_key(item.get("latest_episode", ""))

    if not row_ep:
        return item

    row_num = episode_sort_value(row_ep)
    item_num = episode_sort_value(item_ep)
    row___removed_link__ = str(row.get("__removed_link__", "") or "").strip() or infer___removed_link___from_url(row.get("url", ""))

    if row___removed_link__:
        item["__removed_link__"] = row___removed_link__

    if not item.get("manual", {}).get("category"):
        category = normalize_category(row.get("category", ""))
        if category == "other":
            category = infer_category_from_text(row.get("url", ""), row___removed_link__, row.get("title", ""))
        if category != "other":
            item["category"] = category

    if row_num >= item_num:
        item["latest_episode"] = row_ep
        item["last_seen"] = str(row.get("last_seen", "") or item.get("last_seen", "") or "")
        if row.get("url"):
            item["url"] = str(row.get("url", "") or "")
        if row___removed_link__:
            item["__removed_link__"] = row___removed_link__

    return normalize_db_item(item)

def load_purged_title_keys_from_db():
    """
    완전삭제(purged)는 localreadlog_ignore.txt에도 들어가지만,
    다시 방문했는지 판단하려면 브라우저 방문기록을 먼저 읽어야 함.
    그래서 ignore 선필터에서 purged만 빼고, apply_manager_db_rules에서
    last_seen > updated_at 조건으로 실제 복구 여부를 판단하게 함.
    """
    db = load_manager_db()
    result = set()

    for item in db.get("items", {}).values():
        if not isinstance(item, dict):
            continue

        if item.get("status") != "purged":
            continue

        title = normalize_title(item.get("title", ""))
        if title:
            result.add(title)

        for alias in item.get("aliases", []) or []:
            alias_title = normalize_title(alias)
            if alias_title:
                result.add(alias_title)

    return result



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
# 사이트 OFF 출력 필터 보강
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
    기존 get_site_key는 OFF 사이트를 무시하므로 출력 필터용으로 별도 사용.
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
        db = load_manager_db()
    db = normalize_db_settings(db)
    settings = db.get("settings", {})
    sites = settings.get("sites", {})
    site_key = _row_site_key_any(row)

    if not site_key:
        return True

    return sites.get(site_key, {}).get("enabled", True) is not False


def _filter_disabled_site_rows(rows, db=None):
    if db is None:
        db = load_manager_db()
    db = normalize_db_settings(db)
    return [row for row in rows if _site_enabled_for_row(row, db)]


_ORIGINAL_save_latest_files = save_latest_files

def save_latest_files(rows):
    db = load_manager_db()
    db = normalize_db_settings(db)
    rows = _filter_disabled_site_rows(rows, db)
    return _ORIGINAL_save_latest_files(rows)

def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    ignore_titles = load_ignore_titles()
    # deleted는 계속 숨기되, purged는 재방문 감지를 위해 선필터에서 제외하지 않음.
    ignore_titles = ignore_titles - load_purged_title_keys_from_db()
    existing_latest = load_existing_latest()

    # 기존 백업/archive에서 읽힌 기록도 먼저 삭제 목록 적용
    existing_latest = {
        key: item
        for key, item in existing_latest.items()
        if not is_ignored_title(item.get("title", ""), ignore_titles)
    }

    rows, stats = read_all_blacktoon_rows()

    if rows:
        sync_all_episode_history_from_browser(rows, ignore_titles)

    # 브라우저 기록이 없어도 기존 CSV/archive를 기준으로 출력 파일 재생성.
    # 이렇게 해야 ignore로 삭제한 작품이 HTML에서도 반영됨.
    if not rows:
        latest_rows = list(existing_latest.values())
        latest_rows = apply_ignore_filter(latest_rows, ignore_titles)
        latest_rows = apply_manager_db_rules(latest_rows)
        latest_rows.sort(key=lambda x: x.get("last_seen", ""), reverse=True)

        if latest_rows:
            make_backup_copy()
            save_latest_files(latest_rows)

        print("웨일/엣지에서 추적 사이트 방문기록을 못 찾음.")
        print("기존 백업 기준으로 파일을 갱신함." if latest_rows else "기존 백업도 없어 파일을 갱신하지 않음.")
        print()
        print(f"기존 백업 개수: {len(existing_latest)}개")
        print(f"기존 백업 파일: {LATEST_CSV}")
        print()
        print("브라우저별 확인 결과:")
        for browser_name, stat in stats.items():
            if stat.get("enabled") is False:
                print(f"- {browser_name}: 연동 꺼짐")
            else:
                print(f"- {browser_name}: History DB {stat['db_count']}개, 추적 사이트 기록 {stat['blacktoon_count']}개")
        return

    new_latest_by_series, total_episode_pages = build_latest_from_history(rows, ignore_titles)

    if total_episode_pages == 0:
        latest_rows = list(existing_latest.values())
        latest_rows = apply_ignore_filter(latest_rows, ignore_titles)
        latest_rows = apply_manager_db_rules(latest_rows)
        latest_rows.sort(key=lambda x: x.get("last_seen", ""), reverse=True)

        if latest_rows:
            make_backup_copy()
            save_latest_files(latest_rows)

        print("추적 사이트 기록은 있지만 회차 페이지 기록이 없음.")
        print("기존 백업 기준으로 파일을 갱신함." if latest_rows else "기존 백업도 없어 파일을 갱신하지 않음.")
        print()
        print(f"기존 백업 개수: {len(existing_latest)}개")
        print(f"기존 백업 파일: {LATEST_CSV}")
        return

    merged = dict(existing_latest)

    for new_item in new_latest_by_series.values():
        key = make_merge_key(new_item)
        if not key:
            continue

        old_item = merged.get(key)
        merged[key] = new_item if old_item is None else choose_better(old_item, new_item)

    latest_rows = list(merged.values())
    latest_rows = apply_ignore_filter(latest_rows, ignore_titles)
    latest_rows = apply_manager_db_rules(latest_rows)
    latest_rows.sort(key=lambda x: x.get("last_seen", ""), reverse=True)

    make_backup_copy()
    save_latest_files(latest_rows)

    print("웨일 + 엣지 통합 백업 완료")
    print()
    print("브라우저별 확인 결과:")
    for browser_name, stat in stats.items():
        print(f"- {browser_name}: History DB {stat['db_count']}개, 추적 사이트 기록 {stat['blacktoon_count']}개")

    print()
    print(f"추적 사이트 전체 방문기록: {len(rows)}개")
    print(f"회차 페이지 기록: {total_episode_pages}개")
    print(f"기존 백업 기록: {len(existing_latest)}개")
    print(f"새로 확인한 작품: {len(new_latest_by_series)}개")
    print(f"최종 저장 작품: {len(latest_rows)}개")
    print()
    print(f"최종 백업 파일: {LATEST_CSV}")



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
    _prev_normalize_db_item_no_series
except NameError:
    _prev_normalize_db_item_no_series = normalize_db_item
    def normalize_db_item(item):
        item = _prev_normalize_db_item_no_series(item)
        return _drop___removed_link___fields(item)

try:
    _prev_save_manager_db_no_series
except NameError:
    _prev_save_manager_db_no_series = save_manager_db
    def save_manager_db(db):
        _drop___removed_link___fields(db)
        result = _prev_save_manager_db_no_series(db)
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
            print(f"__removed_link__ 제거 후 DB 재저장 실패: {e}")
        return result

try:
    _prev_save_latest_files_no_series
except NameError:
    _prev_save_latest_files_no_series = save_latest_files
    def save_latest_files(rows):
        clean_rows = []
        for row in rows:
            clean_rows.append(_drop___removed_link___fields(dict(row)))
        return _prev_save_latest_files_no_series(clean_rows)


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
    _prev_normalize_db_item_clean
except NameError:
    _prev_normalize_db_item_clean = normalize_db_item
    def normalize_db_item(item):
        return _drop_legacy_link_fields(_prev_normalize_db_item_clean(item))

try:
    _prev_save_manager_db_clean
except NameError:
    _prev_save_manager_db_clean = save_manager_db
    def save_manager_db(db):
        _drop_legacy_link_fields(db)
        result = _prev_save_manager_db_clean(db)
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
            print(f"레거시 작품주소 필드 제거 후 DB 재저장 실패: {e}")
        return result

try:
    _prev_save_latest_files_clean
except NameError:
    _prev_save_latest_files_clean = save_latest_files
    def save_latest_files(rows):
        return _prev_save_latest_files_clean(_drop_legacy_link_fields([dict(row) for row in rows]))



# =========================
# v15 DB 자동 백업/자동 업데이트 설정 기본값
# =========================
_DB_BACKUP_MAX_FILES = 20


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


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


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
        print(f"DB 자동 백업 실패: {e}")

try:
    _prev_normalize_db_settings_v15
except NameError:
    _prev_normalize_db_settings_v15 = normalize_db_settings
    def normalize_db_settings(db):
        db = _prev_normalize_db_settings_v15(db)
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
    _prev_save_manager_db_v15
except NameError:
    _prev_save_manager_db_v15 = save_manager_db
    def save_manager_db(db):
        _make_db_backup_snapshot("before_save")
        return _prev_save_manager_db_v15(db)


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
    _prev_normalize_db_item_strict_episode_v014
except NameError:
    _prev_normalize_db_item_strict_episode_v014 = normalize_db_item

    def normalize_db_item(item):
        return _lrl_drop_invalid_episode_fields(_prev_normalize_db_item_strict_episode_v014(item))

try:
    _prev_extract_episode_page_info_strict_episode_v014
except NameError:
    _prev_extract_episode_page_info_strict_episode_v014 = extract_episode_page_info

    def extract_episode_page_info(row, series_titles=None):
        info = _prev_extract_episode_page_info_strict_episode_v014(row, series_titles)
        if not info:
            return None
        ep = _lrl_valid_episode_text(info.get("latest_episode", ""))
        if not ep:
            return None
        info = dict(info)
        info["latest_episode"] = ep
        return info

try:
    _prev_save_manager_db_strict_episode_v014
except NameError:
    _prev_save_manager_db_strict_episode_v014 = save_manager_db

    def save_manager_db(db):
        try:
            for item in (db.get("items", {}) or {}).values():
                if isinstance(item, dict):
                    _lrl_drop_invalid_episode_fields(item)
        except Exception:
            pass
        return _prev_save_manager_db_strict_episode_v014(db)



# =========================
# v0.1.21: confirmed episode parsing + generic numbered domains + blank episode detail rows
# =========================
_LRL_VERSION = "v0.1.21"
_LRL_OBSERVED_LIVE_HOSTS = {}

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
    if "sbxh" not in SITE_NAME_ALIASES:
        SITE_NAME_ALIASES["sbxh"] = "sbxh"
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


def _lrl_history_title_is_connection_error(title):
    t = str(title or "").strip().lower()
    if not t:
        return False
    bad_parts = [
        "접속할 수 없음", "사이트에 연결할 수 없음", "연결할 수 없음", "페이지를 열 수 없음",
        "웹페이지를 사용할 수 없음", "문제 발생", "오류", "err_", "dns_probe", "timed out",
        "this site can", "this site can't", "site can", "can't be reached", "cannot be reached",
        "server ip address could not be found", "404 not found", "502 bad gateway",
        "503 service unavailable", "504 gateway timeout",
    ]
    return any(x in t for x in bad_parts)


def _lrl_format_episode_number(number_text):
    number_text = str(number_text or "").strip()
    try:
        number = float(number_text)
        if number <= 0:
            return ""
        if number.is_integer():
            return str(int(number))
        return str(number)
    except Exception:
        return number_text


def parse_episode_number(title):
    """
    제목에 명확한 회차 표식이 있을 때만 화수로 인정한다.
    URL의 긴 숫자/slug, 제목 끝 숫자, '오해 (2)' 같은 괄호 숫자는 회차로 쓰지 않는다.
    """
    title = clean_title(title)
    if not title:
        return ""

    patterns = [
        r"(?:제\s*)?(\d+(?:\.\d+)?)\s*(?:화|회|편|장|권)(?=$|[\s\-–—_:|/\\)\]】』》,，.。!！?？])",
        r"(?:챕터|챕\.?)\s*[-_:：#.]?\s*(\d+(?:\.\d+)?)",
        r"(?:chapter|chap\.?|ch\.?)\s*[-_:：#.]?\s*(\d+(?:\.\d+)?)\b",
        r"(?:episode|ep\.?)\s*[-_:：#.]?\s*(\d+(?:\.\d+)?)\b",
        r"(?:第)\s*(\d+(?:\.\d+)?)\s*(?:話|章)",
        r"(\d+(?:\.\d+)?)\s*(?:話|章)(?=$|[\s\-–—_:|/\\)\]】』》,，.。!！?？])",
    ]

    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, title, flags=re.I):
            found.append((match.start(), match.group(1)))

    if not found:
        return ""

    found.sort(key=lambda x: x[0])
    return _lrl_format_episode_number(found[-1][1])


def infer_series_title_from_episode_title(episode_title):
    title = clean_title(episode_title)
    title = re.sub(r"^\d{3,6}\s*[-–—]\s*", "", title)

    remove_patterns = [
        r"\s*[-–—_:：]?\s*(?:외전\s*)?(?:제\s*)?\d+(?:\.\d+)?\s*(?:화|회|편|장|권).*$",
        r"\s*[-–—_:：]?\s*(?:챕터|챕\.?)\s*[-_:：#.]?\s*\d+(?:\.\d+)?.*$",
        r"\s*[-–—_:：]?\s*(?:chapter|chap\.?|ch\.?|episode|ep\.?)\s*[-_:：#.]?\s*\d+(?:\.\d+)?.*$",
        r"\s*[-–—_:：]?\s*(?:第)\s*\d+(?:\.\d+)?\s*(?:話|章).*$",
        r"\s*[-–—_:：]?\s*\d+(?:\.\d+)?\s*(?:話|章).*$",
    ]
    for pattern in remove_patterns:
        title = re.sub(pattern, "", title, flags=re.I).strip()

    title = re.sub(r"\s*[-–—_:：]+\s*$", "", title).strip()
    return title


def _lrl_clean_page_title_for_series(title):
    title = clean_title(title)
    title = re.sub(r"\s*[|｜].*$", "", title).strip()
    title = re.sub(r"\s*[-–—]\s*(?:SBXH|NewToki|뉴토끼|마나토끼|북토끼)\s*$", "", title, flags=re.I).strip()
    return title


def _lrl_series_title_from_title(title, latest_episode=""):
    title = _lrl_clean_page_title_for_series(title)
    if not title:
        return ""
    if latest_episode:
        inferred = infer_series_title_from_episode_title(title)
        if inferred:
            return inferred
    # 회차가 없으면 부제목을 화수처럼 쓰지 않는다. '작품명 - 부제'는 작품명만 사용.
    parts = re.split(r"\s+[-–—]\s+", title, maxsplit=1)
    if len(parts) >= 2 and parts[0].strip():
        return parts[0].strip()
    return title.strip()


def _lrl_path_parts(url):
    try:
        parsed = urlparse(str(url or ""))
        parts = [unquote(p) for p in parsed.path.strip("/").split("/") if p]
        return parsed, parts
    except Exception:
        return None, []


def _lrl_work_url_from_detail_url(url):
    url = normalize_blacktoon_url(str(url or "").strip(), {}) if "normalize_blacktoon_url" in globals() else str(url or "").strip()
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

    parsed, parts = _lrl_path_parts(url)
    if not parsed or not parsed.scheme or not parsed.netloc:
        return ""

    if not parts:
        return f"{parsed.scheme}://{parsed.netloc}/"

    # ani.ohli24.com 같은 고정 도메인은 동적 숫자 도메인으로 오인하지 않고, 기존 /e -> /c 보정만 유지.
    if len(parts) >= 2 and parts[0].lower() in ["e", "episode", "episodes"]:
        title_part = _remove_episode_suffix_from_title(parts[1]) if "_remove_episode_suffix_from_title" in globals() else parts[1]
        title_part = title_part or parts[1]
        new_path = _encode_path_parts(["c", title_part]) if "_encode_path_parts" in globals() else "/c/" + quote(title_part, safe="")
        return f"{parsed.scheme}://{parsed.netloc}{new_path}"

    if len(parts) >= 2 and parts[0].lower() in ["c", "content", "contents"]:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    cat_idx, _cat = _category_index(parts) if "_category_index" in globals() else (None, "")

    # /novel/작품ID/글ID, /manhwa/작품ID/slug 구조는 마지막 조각을 회차로 쓰지 않고 작품 주소만 만든다.
    if cat_idx is not None and len(parts) >= cat_idx + 3:
        new_parts = parts[:cat_idx + 2]
        new_path = _encode_path_parts(new_parts) if "_encode_path_parts" in globals() else "/" + "/".join(quote(str(p), safe="") for p in new_parts)
        return f"{parsed.scheme}://{parsed.netloc}{new_path}"

    if len(parts) >= 2 and _segment_looks_episode(parts[-1]):
        new_path = _encode_path_parts(parts[:-1]) if "_encode_path_parts" in globals() else "/" + "/".join(quote(str(p), safe="") for p in parts[:-1])
        return f"{parsed.scheme}://{parsed.netloc}{new_path}"

    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _lrl_path_is_content_detail_url(url):
    parsed, parts = _lrl_path_parts(url)
    if not parsed or not parts:
        return False
    cat_idx, _cat = _category_index(parts) if "_category_index" in globals() else (None, "")
    return cat_idx is not None and len(parts) >= cat_idx + 3


def _lrl_series_id_from_url(site_key, url, assume_episode=False):
    work_url = _lrl_work_url_from_detail_url(url) if assume_episode else str(url or "")
    if assume_episode and not work_url:
        work_url = str(url or "")
    try:
        parsed = urlparse(work_url)
        path = parsed.path.strip("/")
    except Exception:
        path = ""
    if not path:
        return f"{site_key}:root"
    normalized = re.sub(r"[^0-9A-Za-z가-힣_./-]+", "_", unquote(path)).strip("_")
    return f"{site_key}:url:{normalized or path}"


def infer___removed_link___from_url(url):
    # 이름은 레거시 호환용이다. work_url 필드를 저장하지 않기 위해 최종 저장 단계에서는 계속 제거된다.
    return _lrl_work_url_from_detail_url(url)


def get___removed_link__(url):
    return ""


def generic_series_id_from_url(site_key, url, assume_episode=False):
    return _lrl_series_id_from_url(site_key, url, assume_episode)


def extract_series_page_info(row):
    url = row.get("url", "")
    site_key = get_site_key(url)
    if not site_key:
        return None

    title = _lrl_clean_page_title_for_series(row.get("clean_title", "") or row.get("raw_title", ""))
    if is_bad_title(title) or _lrl_history_title_is_connection_error(title):
        return None

    work_url = _lrl_work_url_from_detail_url(url)
    if not work_url:
        return None

    try:
        # 상세 URL은 여기서 작품명 후보로만 쓰고, 실제 기록은 extract_episode_page_info에서 처리한다.
        if urlparse(url).path.rstrip("/") != urlparse(work_url).path.rstrip("/"):
            return None
    except Exception:
        return None

    return {
        "site": site_key,
        "series_id": _lrl_series_id_from_url(site_key, work_url, assume_episode=False),
        "title": display_title_for_site(site_key, title),
        "__removed_link__": work_url,
    }


def extract_episode_page_info(row, series_titles=None):
    if series_titles is None:
        series_titles = {}

    url = row.get("url", "")
    site_key = get_site_key(url)
    if not site_key:
        return None

    episode_title = clean_title(row.get("clean_title", "") or row.get("raw_title", ""))
    if is_bad_title(episode_title) or _lrl_history_title_is_connection_error(episode_title):
        return None

    latest_episode = parse_episode_number(episode_title) or ""
    is_detail_url = _lrl_path_is_content_detail_url(url)
    work_url = _lrl_work_url_from_detail_url(url)

    if not latest_episode and not is_detail_url:
        return None

    blacktoon_match = EPISODE_PAGE_RE.match(url)
    if blacktoon_match and latest_episode:
        series_id = f"{site_key}:id:{blacktoon_match.group(1)}"
    else:
        series_id = _lrl_series_id_from_url(site_key, url, assume_episode=True)

    data = series_titles.get(series_id, {})
    if isinstance(data, str):
        data = {"title": data}

    if blacktoon_match and latest_episode and looks_like_episode_only_title(episode_title):
        title = data.get("title", "")
    else:
        title = data.get("title") or _lrl_series_title_from_title(episode_title, latest_episode)

    if not title:
        title = series_id.rsplit(":", 1)[-1] or "제목없음"

    return {
        "site": site_key,
        "series_id": series_id,
        "title": display_title_for_site(site_key, title),
        "latest_episode": latest_episode,
        "url": url,
        "__removed_link__": data.get("__removed_link__") or work_url,
        "category": infer_category_from_text(url, work_url, episode_title) if "infer_category_from_text" in globals() else "",
    }


def build_latest_from_history(rows, ignore_titles=None):
    global _LRL_OBSERVED_LIVE_HOSTS
    if ignore_titles is None:
        ignore_titles = set()

    _LRL_OBSERVED_LIVE_HOSTS = _lrl_live_latest_hosts_from_rows(rows)

    series_titles = {}
    for row in rows:
        info = extract_series_page_info(row)
        if not info:
            continue
        series_titles.setdefault(info["series_id"], {
            "title": info.get("title", ""),
            "__removed_link__": info.get("__removed_link__", ""),
        })

    latest_by_series = {}
    total_episode_pages = 0
    for row in rows:
        info = extract_episode_page_info(row, series_titles)
        if not info:
            continue

        total_episode_pages += 1
        title = info["title"]
        if is_ignored_title(title, ignore_titles):
            continue

        item = {
            "title": title,
            "latest_episode": info.get("latest_episode", ""),
            "last_seen": row.get("last_seen", ""),
            "url": info.get("url", ""),
            "__removed_link__": info.get("__removed_link__", ""),
            "category": info.get("category", "") or infer_category_from_text(info.get("url", ""), info.get("__removed_link__", ""), title),
        }
        old = latest_by_series.get(info["series_id"])
        latest_by_series[info["series_id"]] = item if old is None else choose_better(old, item)

    return latest_by_series, total_episode_pages

try:
    _prev_update_db_item_from_chosen_row_v021
except NameError:
    _prev_update_db_item_from_chosen_row_v021 = update_db_item_from_chosen_row

    def update_db_item_from_chosen_row(item, row):
        before_ep = db_episode_key((item or {}).get("latest_episode", ""))
        row_ep = db_episode_key((row or {}).get("latest_episode", ""))
        item = _prev_update_db_item_from_chosen_row_v021(item, row)
        if not row_ep and not before_ep:
            if row.get("last_seen"):
                item["last_seen"] = str(row.get("last_seen", "") or item.get("last_seen", ""))
            if row.get("url"):
                item["url"] = str(row.get("url", "") or item.get("url", ""))
            row_category = normalize_category(row.get("category", "")) if "normalize_category" in globals() else ""
            if row_category and row_category != "other" and not item.get("manual", {}).get("category"):
                item["category"] = row_category
        return normalize_db_item(item)

try:
    _prev_apply_manager_db_rules_v021
except NameError:
    _prev_apply_manager_db_rules_v021 = apply_manager_db_rules

    def apply_manager_db_rules(rows):
        output = _prev_apply_manager_db_rules_v021(rows)
        try:
            db = load_manager_db()
            db = normalize_db_settings(db)
            existing = set()
            for row in output:
                key = make_merge_key(row) or db_title_key(row.get("title", ""))
                if key:
                    existing.add(key)
            extra = []
            for raw_item in (db.get("items", {}) or {}).values():
                if not isinstance(raw_item, dict):
                    continue
                item = normalize_db_item(raw_item)
                if item.get("status") != "active":
                    continue
                row = db_item_to_row(item)
                if not row.get("title") or not row.get("url"):
                    continue
                key = make_merge_key(row) or db_title_key(row.get("title", ""))
                if key in existing:
                    continue
                # 화수가 비어 있는 작품도 현재 목록에 남긴다.
                extra.append(row)
                existing.add(key)
            if extra:
                output = list(output) + extra
                output = apply_site_duplicate_filter(output, db)
        except Exception:
            pass
        return output

try:
    _prev_get_latest_host_from_items_v021
except NameError:
    _prev_get_latest_host_from_items_v021 = get_latest_blacktoon_host_from_items

    def get_latest_blacktoon_host_from_items(items):
        observed = dict(globals().get("_LRL_OBSERVED_LIVE_HOSTS", {}) or {})
        if observed:
            return observed
        latest = _lrl_live_latest_hosts_from_rows(items)
        return latest or _prev_get_latest_host_from_items_v021(items)

try:
    _prev_save_latest_pc_html_blank_episode_v021
except NameError:
    _prev_save_latest_pc_html_blank_episode_v021 = save_latest_pc_html

    def save_latest_pc_html(rows):
        result = _prev_save_latest_pc_html_blank_episode_v021(rows)
        try:
            for path in [LATEST_PC_HTML, LATEST_HTML]:
                if path.exists():
                    text = path.read_text(encoding="utf-8", errors="replace")
                    text = text.replace(">화</td>", "></td>").replace("<span>화</span>", "<span></span>")
                    path.write_text(text, encoding="utf-8")
        except Exception:
            pass
        return result


# =========================
# v0.1.27: 화수 없는 상세 페이지는 부제목을 화수 칸에 표시
# =========================
_LRL_VERSION = "v0.1.28"


def _lrl_numeric_episode_text_v027(value):
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


def _lrl_safe_subtitle_text_v027(value):
    text = clean_title(value)
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip(" -–—_:：|/\\")
    if not text:
        return ""
    if re.match(r"^https?://", text, flags=re.I):
        return ""
    if re.fullmatch(r"[0-9A-Za-z_-]{12,}", text):
        return ""
    if len(text) > 80:
        text = text[:80].rstrip()
    return text


def _lrl_episode_display_value_v027(value):
    numeric = _lrl_numeric_episode_text_v027(value)
    if numeric:
        return numeric
    return _lrl_safe_subtitle_text_v027(value)


def _lrl_episode_display_label(value):
    value = _lrl_episode_display_value_v027(value)
    if not value:
        return ""
    return f"{value}화" if _lrl_numeric_episode_text_v027(value) else value


# 기존 v0.1.14의 strict 필터가 latest_episode의 부제목을 지우지 않게 덮어쓴다.
def _lrl_valid_episode_text(value):
    return _lrl_episode_display_value_v027(value)


def _lrl_drop_invalid_episode_fields(item):
    if not isinstance(item, dict):
        return item

    item["latest_episode"] = _lrl_episode_display_value_v027(item.get("latest_episode", ""))
    item["locked_episode"] = _lrl_numeric_episode_text_v027(item.get("locked_episode", ""))

    cleaned_history = {}
    history = item.get("episode_history", {}) or {}
    if isinstance(history, dict):
        for ep, record in history.items():
            ep_key = _lrl_numeric_episode_text_v027(ep)
            if not ep_key and isinstance(record, dict):
                ep_key = _lrl_numeric_episode_text_v027(record.get("episode", ""))
            if not ep_key:
                continue
            if isinstance(record, dict):
                rec = dict(record)
                rec["episode"] = ep_key
                cleaned_history[ep_key] = rec
    item["episode_history"] = cleaned_history

    blocked = []
    for ep in item.get("blocked_episodes", []) or []:
        ep_key = _lrl_numeric_episode_text_v027(ep)
        if ep_key:
            blocked.append(ep_key)
    item["blocked_episodes"] = blocked
    return item


def _lrl_subtitle_from_page_title_v027(title):
    title = _lrl_clean_page_title_for_series(title) if "_lrl_clean_page_title_for_series" in globals() else clean_title(title)
    if not title or parse_episode_number(title):
        return ""

    candidates = []
    splitters = [
        r"\s+[-–—]\s+",
        r"\s+[:：]\s+",
    ]
    for splitter in splitters:
        parts = [p.strip() for p in re.split(splitter, title, maxsplit=1) if p.strip()]
        if len(parts) >= 2:
            candidates.append(parts[1])

    bracket = re.search(r"(?:\s+|^)[\[【『「](.+?)[\]】』」]\s*$", title)
    if bracket:
        candidates.append(bracket.group(1))

    for cand in candidates:
        cand = _lrl_safe_subtitle_text_v027(cand)
        if not cand:
            continue
        if re.fullmatch(r"[\(\[【]?\s*\d+(?:\.\d+)?\s*[\)\]】]?", cand):
            continue
        if is_bad_title(cand):
            continue
        return cand
    return ""


try:
    _prev_extract_episode_page_info_v027
except NameError:
    _prev_extract_episode_page_info_v027 = extract_episode_page_info

    def extract_episode_page_info(row, series_titles=None):
        info = _prev_extract_episode_page_info_v027(row, series_titles)
        if not info:
            return None
        info = dict(info)
        if not _lrl_numeric_episode_text_v027(info.get("latest_episode", "")):
            subtitle = _lrl_subtitle_from_page_title_v027(row.get("clean_title", "") or row.get("raw_title", ""))
            if subtitle:
                info["latest_episode"] = subtitle
        else:
            info["latest_episode"] = _lrl_numeric_episode_text_v027(info.get("latest_episode", ""))
        return info


try:
    _prev_update_db_item_from_chosen_row_v027
except NameError:
    _prev_update_db_item_from_chosen_row_v027 = update_db_item_from_chosen_row

    def update_db_item_from_chosen_row(item, row):
        row_display = _lrl_episode_display_value_v027((row or {}).get("latest_episode", ""))
        item = _prev_update_db_item_from_chosen_row_v027(item, row)
        if row_display and not _lrl_numeric_episode_text_v027(row_display):
            if not db_episode_key(item.get("latest_episode", "")) and not db_episode_key(item.get("locked_episode", "")):
                item["latest_episode"] = row_display
                if row.get("last_seen"):
                    item["last_seen"] = str(row.get("last_seen", "") or item.get("last_seen", ""))
                if row.get("url"):
                    item["url"] = str(row.get("url", "") or item.get("url", ""))
        return normalize_db_item(item)


# =========================
# v0.1.28: 괄호 숫자만 있는 부제목도 화수 칸에 표시
# =========================
_LRL_VERSION = "v0.1.28"


def _lrl_is_bare_number_v028(value):
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", str(value or "").strip()))


def _lrl_is_bracketed_number_subtitle_v028(value):
    text = str(value or "").strip()
    return bool(re.fullmatch(r"(?:\(\s*\d+(?:\.\d+)?\s*\)|（\s*\d+(?:\.\d+)?\s*）|\[\s*\d+(?:\.\d+)?\s*\]|【\s*\d+(?:\.\d+)?\s*】)", text))


def _lrl_remove_subtitle_suffix_from_title_v028(title, subtitle):
    title = clean_title(title)
    subtitle = str(subtitle or "").strip()
    if not title or not subtitle:
        return title

    escaped = re.escape(subtitle)
    title = re.sub(rf"\s*[-–—:：]\s*{escaped}\s*$", "", title).strip()
    title = re.sub(rf"\s+{escaped}\s*$", "", title).strip()
    return re.sub(r"\s*[-–—:：]+\s*$", "", title).strip() or title


def _lrl_subtitle_from_page_title_v027(title):
    title = _lrl_clean_page_title_for_series(title) if "_lrl_clean_page_title_for_series" in globals() else clean_title(title)
    if not title or parse_episode_number(title):
        return ""

    candidates = []
    splitters = [
        r"\s+[-–—]\s+",
        r"\s+[:：]\s+",
    ]
    for splitter in splitters:
        parts = [p.strip() for p in re.split(splitter, title, maxsplit=1) if p.strip()]
        if len(parts) >= 2:
            candidates.append(parts[1])

    # 제목 끝이 작품명 (1), 작품명（2）처럼 괄호 숫자만 있는 경우도 부제목으로 인정한다.
    trailing_number_bracket = re.search(r"(\(\s*\d+(?:\.\d+)?\s*\)|（\s*\d+(?:\.\d+)?\s*）)\s*$", title)
    if trailing_number_bracket:
        candidates.append(trailing_number_bracket.group(1))

    trailing_square_number = re.search(r"(\[\s*\d+(?:\.\d+)?\s*\]|【\s*\d+(?:\.\d+)?\s*】)\s*$", title)
    if trailing_square_number:
        candidates.append(trailing_square_number.group(1))

    bracket = re.search(r"(?:\s+|^)[\[【『「](.+?)[\]】』」]\s*$", title)
    if bracket:
        candidates.append(bracket.group(1))

    for cand in candidates:
        cand = _lrl_safe_subtitle_text_v027(cand)
        if not cand:
            continue
        # 숫자만 단독으로 있는 '1'은 화수로 오인될 수 있으므로 제외한다.
        # 단, '(1)', '（1）', '[1]'처럼 괄호가 붙은 숫자는 부제목으로 그대로 허용한다.
        if _lrl_is_bare_number_v028(cand) and not _lrl_is_bracketed_number_subtitle_v028(cand):
            continue
        if is_bad_title(cand):
            continue
        return cand
    return ""


try:
    _prev_extract_episode_page_info_v028
except NameError:
    _prev_extract_episode_page_info_v028 = extract_episode_page_info

    def extract_episode_page_info(row, series_titles=None):
        info = _prev_extract_episode_page_info_v028(row, series_titles)
        if not info:
            return None
        info = dict(info)
        if not _lrl_numeric_episode_text_v027(info.get("latest_episode", "")):
            subtitle = _lrl_subtitle_from_page_title_v027(row.get("clean_title", "") or row.get("raw_title", ""))
            if subtitle:
                info["latest_episode"] = subtitle
                current_title = str(info.get("title", "") or "")
                cleaned_title = _lrl_remove_subtitle_suffix_from_title_v028(current_title, subtitle)
                if cleaned_title:
                    info["title"] = cleaned_title
        else:
            info["latest_episode"] = _lrl_numeric_episode_text_v027(info.get("latest_episode", ""))
        return info


if __name__ == "__main__":
    main()


# v0.1.29 release marker
_LRL_VERSION = "v0.1.29"
