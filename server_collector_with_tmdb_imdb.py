import re
import sys
import json
import os
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from itertools import cycle

# ── API Configurations ───────────────────────────────────────────
TMDB_API_KEY = "6fad3f86b8452ee232deb7977d7dcf58" 

# File paths
TARGET_JSON = os.getenv("TARGET_JSON", "movies.json")
PROCESSED_FILE = "list_of_already_processed_urls.txt"
ERROR_FILE = "list_of_facing_error.txt"

# ── Proxies ──────────────────────────────────────────────────────
PROXY_USER = "dxicdysy"
PROXY_PASS = "yndikr9coeto"

PROXY_LIST_RAW = [
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

formatted_proxies = [
    f"http://{PROXY_USER}:{PROXY_PASS}@{ip}:{port}" for ip, port in PROXY_LIST_RAW
]
proxy_pool = cycle(formatted_proxies)

# ── Single Session ───────────────────────────────────────────────
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", 
    "X-Requested-With": "XMLHttpRequest"
})

def set_new_proxy():
    new_proxy = next(proxy_pool)
    S.proxies.update({
        "http": new_proxy,
        "https": new_proxy,
    })
    safe_display = new_proxy.split('@')[-1]
    print(f"  [*] Rotating IP... Now using proxy: {safe_display}")

set_new_proxy()

# ── File I/O Helpers ──────────────────────────────────────────────
def init_files():
    """Creates tracking files if they don't exist and returns processed URLs."""
    if not os.path.exists(PROCESSED_FILE):
        open(PROCESSED_FILE, "w", encoding="utf-8").close()
    if not os.path.exists(ERROR_FILE):
        open(ERROR_FILE, "w", encoding="utf-8").close()
        
    with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def log_processed(url):
    with open(PROCESSED_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")

def log_error(url, error_msg):
    with open(ERROR_FILE, "a", encoding="utf-8") as f:
        f.write(f"{url} | ERROR: {error_msg}\n")

# ── Core Functions ───────────────────────────────────────────────
def get_tmdb_id_from_imdb(imdb_id):
    if not TMDB_API_KEY:
        return ""
        
    url = f"https://api.themoviedb.org/3/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        if data.get("movie_results"):
            return str(data["movie_results"][0]["id"])
        elif data.get("tv_results"):
            return str(data["tv_results"][0]["id"])
            
    except Exception as e:
        print(f"  [!] Failed to fetch TMDb ID for {imdb_id}: {e}")
        
    return ""

def base(url):
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"

def csrf(html):
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    return m.group(1) if m else ""

def spans(html):
    soup = BeautifulSoup(html, "html.parser")
    return [
        (s.get_text(strip=True), s["data"])
        for s in soup.find_all("span", attrs={"data": True})
        if len(s.get("data","")) > 10
    ]

def iframe(html):
    m = re.search(r'<iframe[^>]+src="([^"]+)"', html)
    return m.group(1) if m else ""

def post(url, data, ref):
    r = S.post(url, data=data, headers={"Referer": ref, "Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
    r.raise_for_status()
    return r.text

def extract_servers(target_url, max_retries=3):
    for attempt in range(max_retries):
        try:
            delay = random.uniform(2.5, 5.0)
            time.sleep(delay)

            html = S.get(target_url, timeout=15).text
            token = csrf(html)
            root = base(target_url)

            if "/watch-tvseries-" in target_url:
                ep_ids = re.findall(r'idepisode=["\'](\w+)["\']', html)
                if not ep_ids: 
                    return []
                ep_id = ep_ids[0]  
                server_html = post(f"{root}/ajaxtv", {"idepisode": ep_id, "_token": token}, target_url)
                servers = spans(server_html)
            else:
                servers = spans(html)

            extracted_urls = []
            for label, data in servers:
                embed_html = post(f"{root}/ajax", {"m4u": data, "_token": token}, target_url)
                url = iframe(embed_html)
                if url:
                    extracted_urls.append(url)
                    
            return extracted_urls

        except requests.exceptions.RequestException as e:
            print(f"  [!] Attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                set_new_proxy()
            else:
                print(f"  [!] Exhausted all retries for {target_url}.")
                log_error(target_url, f"Failed after {max_retries} retries: {str(e)}")
                return []
        except Exception as e:
            log_error(target_url, f"Unexpected extraction error: {str(e)}")
            return []

# ── Main Loop ────────────────────────────────────────────────────
def main():
    print(f"[*] Starting job for file: {TARGET_JSON}")
    
    # Check if target JSON actually exists
    if not os.path.exists(TARGET_JSON):
        print(f"[!] Error: {TARGET_JSON} not found in repository.")
        sys.exit(1)
        
    processed_urls = init_files()

    with open(TARGET_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"[*] Total records in {TARGET_JSON}: {len(data)}")

    try:
        for item in data:
            target_url = item.get("url")
            
            # Skip if URL is missing, already populated, or already in processed list
            if not target_url or item.get("server1") or target_url in processed_urls:
                continue

            print(f"-> Processing: {item.get('title', 'Unknown Title')} ({target_url})")
            
            try:
                embeds = extract_servers(target_url)
                
                # If extraction returned empty, log as an error but don't crash
                if not embeds:
                    log_error(target_url, "No embeds found or extraction failed.")
                    continue

                # Map the servers
                for i in range(1, 5):
                    server_key = f"server{i}"
                    if i <= len(embeds):
                        item[server_key] = embeds[i-1]
                    else:
                        item[server_key] = ""

                # Extract IMDb ID and fetch TMDb ID
                found_imdb_id = ""
                for url in embeds:
                    match = re.search(r'(tt\d{7,10})', url)
                    if match:
                        found_imdb_id = match.group(1)
                        break
                
                if found_imdb_id:
                    item["imdb_id"] = found_imdb_id
                    print(f"   Found IMDb ID: {found_imdb_id}")
                    
                    tmdb_id = get_tmdb_id_from_imdb(found_imdb_id)
                    if tmdb_id:
                        item["tmdb_id"] = tmdb_id
                        print(f"   Fetched TMDb ID: {tmdb_id}")

                print(f"   Processed and mapped {len(embeds)} servers.")
                
                # Add to successful processing list
                processed_urls.add(target_url)
                log_processed(target_url)

            except Exception as e:
                print(f"  [!] Error processing item: {e}")
                log_error(target_url, f"Item processing crashed: {str(e)}")

    except KeyboardInterrupt:
        print("\n[!] Script manually interrupted. Saving JSON...")
    finally:
        # Always write the updated JSON data back out
        with open(TARGET_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        print(f"[*] Saved updates to {TARGET_JSON}.")

if __name__ == "__main__":
    main()
