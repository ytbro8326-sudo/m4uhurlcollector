"""
m4uhd.page — URL Collector
===========================
Collect every movie/series URL from /new-movies listing pages.
Saves to movies.json, movies2.json, etc. (max 1 MB each).
Tracks processed pages in page_already_processed.txt.

Usage:
    python scraper.py                 # pages 1-2 (default)
    python scraper.py 1 10            # pages 1-10
"""

import sys, json, time, random, logging, os
from curl_cffi import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from dataclasses import dataclass, asdict

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL             = "https://ww1.m4uhd.page"
START_PAGE           = int(sys.argv[1]) if len(sys.argv) > 1 else 1
END_PAGE             = int(sys.argv[2]) if len(sys.argv) > 2 else 2
DELAY_MIN            = 1.5
DELAY_MAX            = 3.0
MAX_RETRIES          = 3
TIMEOUT              = 30
MAX_FILE_MB          = 1.0   
PROCESSED_PAGES_FILE = "page_already_processed.txt"

# ── Proxies ───────────────────────────────────────────────────────────────────
PROXY_USER = "dxicdysy"
PROXY_PASS = "yndikr9coeto"

PROXY_LIST = [
    ("31.59.20.176",    6754),
    ("31.56.127.193",   7684),
    ("45.38.107.97",    6014),
    ("198.105.121.200", 6462),
    ("64.137.96.74",    6641),
    ("198.23.243.226",  6361),
    ("38.154.185.97",   6370),
    ("84.247.60.125",   6095),
    ("142.111.67.146",  5611),
    ("191.96.254.138",  6185),
]

def get_random_proxy() -> dict:
    host, port = random.choice(PROXY_LIST)
    url = f"http://{PROXY_USER}:{PROXY_PASS}@{host}:{port}"
    return {"http": url, "https": url}


# ── Data model ────────────────────────────────────────────────────────────────
@dataclass
class Entry:
    title:     str
    url:       str
    type:      str         
    serial_no: int = 0    
    imdb_id:   str = ""
    tmdb_id:   str = ""
    server1:   str = ""
    server2:   str = ""
    server3:   str = ""
    server4:   str = ""

def entry_to_record(e: Entry) -> dict:
    return {
        "serial_no": e.serial_no,
        "title":     e.title,
        "url":       e.url,
        "type":      e.type,
        "imdb_id":   e.imdb_id,
        "tmdb_id":   e.tmdb_id,
        "server1":   e.server1,
        "server2":   e.server2,
        "server3":   e.server3,
        "server4":   e.server4,
    }


# ── Page Tracking ─────────────────────────────────────────────────────────────
def init_tracker_file():
    """Creates the tracking file if it doesn't already exist."""
    if not os.path.exists(PROCESSED_PAGES_FILE):
        open(PROCESSED_PAGES_FILE, 'a', encoding="utf-8").close()
        log.info(f"Created new tracking file: {PROCESSED_PAGES_FILE}")

def get_processed_pages() -> set:
    """Reads the processed pages file and returns a set of completed page numbers."""
    processed = set()
    with open(PROCESSED_PAGES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.isdigit():
                processed.add(int(line))
    return processed

def mark_page_processed(page: int) -> None:
    """Appends a successfully scraped page number to the tracker file."""
    with open(PROCESSED_PAGES_FILE, "a", encoding="utf-8") as f:
        f.write(f"{page}\n")


# ── Helpers ───────────────────────────────────────────────────────────────────
def http_get(url: str) -> str | None:
    for attempt in range(1, MAX_RETRIES + 1):
        proxy = get_random_proxy()
        host  = proxy["http"].split("@")[1]
        try:
            S = requests.Session(impersonate="chrome124")
            S.proxies.update(proxy)
            r = S.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            log.info(f"  ✓ via {host}")
            return r.text
        except Exception as e:
            log.warning(f"GET {url} attempt {attempt}/{MAX_RETRIES} via {host} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
    return None

def parse_listing_page(html: str) -> list[Entry]:
    soup    = BeautifulSoup(html, "html.parser")
    entries = []
    for item in soup.select("div.item"):
        anchor = item.select_one("div.imagecover > a")
        if not anchor:
            continue
        href = anchor.get("href", "").strip()
        if not href:
            continue
        url   = urljoin(BASE_URL, href)
        title = anchor.get("title", "").strip() or anchor.get_text(strip=True)
        kind  = "series" if "/watch-tvseries-" in url else "movie"
        entries.append(Entry(title=title, url=url, type=kind))
    return entries

def collect_urls(start: int, end: int) -> list[Entry]:
    all_entries: list[Entry] = []
    processed_pages = get_processed_pages()
    
    for page in range(start, end + 1):
        if page in processed_pages:
            log.info(f"Skipping page {page}/{end} — already processed.")
            continue
            
        url  = f"{BASE_URL}/new-movies?page={page}"
        log.info(f"Listing page {page}/{end} → {url}")
        
        html = http_get(url)
        if html is None:
            log.warning(f"Skipping listing page {page} due to fetch failure.")
            continue
            
        found = parse_listing_page(html)
        log.info(f"Page {page}: {len(found)} entries collected.")
        all_entries.extend(found)
        
        # Mark as processed only after a successful fetch and parse
        mark_page_processed(page)
        
        if page < end:
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            
    log.info(f"Total URLs collected on this run: {len(all_entries)}")
    return all_entries


# ── Global State & Deduplication ──────────────────────────────────────────────
def load_global_state() -> tuple[set, int]:
    seen_urls = set()
    max_serial = 0
    file_index = 1
    
    while True:
        fname = get_json_filename(file_index)
        if not os.path.exists(fname):
            break
        try:
            with open(fname, "r", encoding="utf-8") as f:
                records = json.load(f)
                for rec in records:
                    if "url" in rec:
                        seen_urls.add(rec["url"])
                    if "serial_no" in rec:
                        max_serial = max(max_serial, rec.get("serial_no", 0))
        except Exception as e:
            log.warning(f"Could not parse {fname} for deduplication state: {e}")
            pass
        file_index += 1
        
    return seen_urls, max_serial


# ── Save with 1 MB splitting ──────────────────────────────────────────────────
def get_json_filename(index: int) -> str:
    return "movies.json" if index == 1 else f"movies{index}.json"

def load_existing(filename: str) -> list[dict]:
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_with_split(new_entries: list[Entry]) -> None:
    max_bytes    = MAX_FILE_MB * 1024 * 1024
    new_records  = [entry_to_record(e) for e in new_entries]

    file_index   = 1
    while True:
        fname = get_json_filename(file_index)
        if not os.path.exists(fname):
            break
        size = os.path.getsize(fname)
        if size < max_bytes:
            break
        file_index += 1

    current_records = load_existing(get_json_filename(file_index))

    for record in new_records:
        current_records.append(record)
        serialized = json.dumps(current_records, indent=2, ensure_ascii=False)

        if len(serialized.encode("utf-8")) > max_bytes:
            current_records.pop()
            fname = get_json_filename(file_index)
            with open(fname, "w", encoding="utf-8") as f:
                f.write(json.dumps(current_records, indent=2, ensure_ascii=False))
            log.info(f"File {fname} reached 1 MB limit — starting {get_json_filename(file_index + 1)}")
            file_index     += 1
            current_records = [record]

    fname = get_json_filename(file_index)
    with open(fname, "w", encoding="utf-8") as f:
        f.write(json.dumps(current_records, indent=2, ensure_ascii=False))
    log.info(f"Saved to {fname} ({len(current_records)} total records in this file)")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Ensure our tracking file exists right away
    init_tracker_file()

    log.info(f"=== Collecting URLs (pages {START_PAGE}–{END_PAGE}) ===")
    entries = collect_urls(START_PAGE, END_PAGE)

    if not entries:
        log.info("No new URLs collected. Either pages were skipped or parsing failed.")
        sys.exit(0)

    log.info("Checking for duplicates against existing JSON files...")
    seen_urls, current_max_serial = load_global_state()
    
    unique_entries = []
    for e in entries:
        if e.url not in seen_urls:
            current_max_serial += 1
            e.serial_no = current_max_serial
            unique_entries.append(e)
            seen_urls.add(e.url) 
            
    if not unique_entries:
        log.info("All scraped URLs are already in your JSON files. Nothing new to add!")
        print(f"\n{'='*65}")
        print("Done! No new unique records to save.")
        print(f"{'='*65}")
        sys.exit(0)

    save_with_split(unique_entries)

    movies = sum(1 for e in unique_entries if e.type == "movie")
    series = sum(1 for e in unique_entries if e.type == "series")
    print(f"\n{'='*65}")
    print(f"Done!  {len(unique_entries)} NEW unique entries added  |  {movies} movies  |  {series} series")
    print(f"{'='*65}")
    print(f"{'S.No':<6} {'Type':<8} {'Title':<35} URL")
    print("-" * 65)
    for e in unique_entries:
        print(f"{e.serial_no:<6} {e.type:<8} {e.title[:34]:<35} {e.url}")
