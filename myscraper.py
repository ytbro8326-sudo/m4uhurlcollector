import re
import sys
import json
import os
import time
import random
import requests
import base64
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from itertools import cycle

# ── API Configurations ───────────────────────────────────────────
GITHUB_TOKEN = os.getenv("PAT_TOKEN") # Kept as a GitHub Secret
TMDB_API_KEY = "6fad3f86b8452ee232deb7977d7dcf58" # Hardcoded as requested

REPO_OWNER = "ytbro8326-sudo"
REPO_NAME = "m4uhurlcollector"
FILE_PATH = "movies4.json"
BRANCH = "main"

GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
GITHUB_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# ── Local File Configuration ─────────────────────────────────────
JSON_SOURCE_URL = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/refs/heads/{BRANCH}/{FILE_PATH}"
ERROR_FILE = "error_facing.txt"

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

# ── Core Functions ───────────────────────────────────────────────
def get_tmdb_id_from_imdb(imdb_id):
    """Uses the TMDb Find API to get the TMDb ID using an IMDb ID."""
    if not TMDB_API_KEY:
        return ""
        
    url = f"https://api.themoviedb.org/3/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        # Check movie results first, then TV show results
        if data.get("movie_results"):
            return str(data["movie_results"][0]["id"])
        elif data.get("tv_results"):
            return str(data["tv_results"][0]["id"])
            
    except Exception as e:
        print(f"  [!] Failed to fetch TMDb ID for {imdb_id}: {e}")
        
    return ""

def push_to_github(data):
    """Pushes the updated JSON dictionary back to the GitHub repository."""
    print("\n[+] Preparing to push updates to GitHub...")
    try:
        get_req = requests.get(GITHUB_API_URL, headers=GITHUB_HEADERS)
        get_req.raise_for_status()
        sha = get_req.json()['sha']

        json_str = json.dumps(data, indent=4)
        encoded_content = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')

        payload = {
            "message": "Auto-update movies4.json with extracted server URLs and IDs",
            "content": encoded_content,
            "sha": sha,
            "branch": BRANCH
        }

        put_req = requests.put(GITHUB_API_URL, headers=GITHUB_HEADERS, json=payload)
        put_req.raise_for_status()
        print("[+] Successfully committed and pushed to GitHub!")

    except Exception as e:
        print(f"[-] Failed to push to GitHub: {e}")

def log_error(url):
    with open(ERROR_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")

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
                if not ep_ids: return []
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
                log_error(target_url)
                return []

# ── Main Loop ────────────────────────────────────────────────────
def main():
    if not os.path.exists(ERROR_FILE):
        open(ERROR_FILE, "w", encoding="utf-8").close()

    print(f"[*] Fetching base JSON from GitHub...")
    r = requests.get(JSON_SOURCE_URL)
    r.raise_for_status()
    data = r.json()

    print(f"[*] Total records to process: {len(data)}")

    try:
        for item in data:
            target_url = item.get("url")
            
            # Skip if URL is missing or if server1 is already populated
            if not target_url or item.get("server1"):
                continue

            print(f"-> Processing: {item.get('title', 'Unknown Title')}")
            embeds = extract_servers(target_url)

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
                # Look for "tt" followed by 7 to 10 digits
                match = re.search(r'(tt\d{7,10})', url)
                if match:
                    found_imdb_id = match.group(1)
                    break
            
            if found_imdb_id:
                item["imdb_id"] = found_imdb_id
                print(f"   Found IMDb ID: {found_imdb_id}")
                
                # Ping TMDb API
                tmdb_id = get_tmdb_id_from_imdb(found_imdb_id)
                if tmdb_id:
                    item["tmdb_id"] = tmdb_id
                    print(f"   Fetched TMDb ID: {tmdb_id}")

            print(f"   Processed and mapped {len(embeds)} servers.")

    except KeyboardInterrupt:
        print("\n[!] Script manually interrupted. Pushing current progress...")
        push_to_github(data)
        sys.exit(0)
    except Exception as e:
        print(f"\n[!] Unexpected error: {e}. Pushing current progress...")
        push_to_github(data)
        sys.exit(1)

    print("\n[*] Processing complete!")
    push_to_github(data)

if __name__ == "__main__":
    main()
