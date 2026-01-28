import os
import json
import shutil
import tempfile
import subprocess
import requests
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

INFO_PATH = "info_cn.json"
BUNDLE_INFO_PATH = "Android/bundleDownloadInfo.json"
OUTPUT_REPO = "output"
ASSET_STUDIO = "./AssetStudio/AssetStudioModCLI"
MAX_WORKERS = 4
DOWNLOAD_TIMEOUT = 30
MAX_RETRIES = 5
CLEAN_INTERVAL = 500

processed_count = 0
lock = threading.Lock()

BLOCKED = ["spinecharacters", "spinelobbies", "spinebackground", "materials", "textassets"]

BATCH_DIR = "bundle_batch"
os.makedirs(BATCH_DIR, exist_ok=True)
os.makedirs(OUTPUT_REPO, exist_ok=True)


def load_addressable_url():
    with open(INFO_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["AddressableCatalogUrl"].rstrip("/") + "/"


def bundle_allowed(name: str) -> bool:
    n = name.lower()
    if not n.endswith(".bundle"):
        return False
    return not any(b in n for b in BLOCKED)


def collect_target_bundles():
    with open(BUNDLE_INFO_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    bundles = [b["Name"] for b in data.get("BundleFiles", []) if bundle_allowed(b.get("Name", ""))]
    return sorted(set(bundles))


def download_file(url, path):
    for attempt in range(1, MAX_RETRIES + 1):
        start_time = time.time()
        try:
            with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)

            if time.time() - start_time > DOWNLOAD_TIMEOUT:
                raise TimeoutError

            return
        except Exception:
            if os.path.exists(path):
                os.remove(path)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2)


def run_extraction_batch():
    temp_dir = tempfile.mkdtemp(prefix="batch_")
    try:
        for name in os.listdir(BATCH_DIR):
            src = os.path.join(BATCH_DIR, name)
            dst = os.path.join(temp_dir, name)
            shutil.move(src, dst)

        subprocess.run(
            [ASSET_STUDIO, temp_dir, "-t", "tex2d", "-o", OUTPUT_REPO, "-g", "type"],
            check=True
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def process_bundle(base_url, bundle_name):
    global processed_count

    url = urljoin(base_url, f"AssetBundles/Android/{bundle_name}")
    bundle_path = os.path.join(BATCH_DIR, bundle_name)

    download_file(url, bundle_path)

    with lock:
        processed_count += 1
        if processed_count % CLEAN_INTERVAL == 0:
            run_extraction_batch()


def main():
    base_url = load_addressable_url()
    bundles = collect_target_bundles()

    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        futures = [ex.submit(process_bundle, base_url, b) for b in bundles]
        for f in as_completed(futures):
            f.result()

    if os.listdir(BATCH_DIR):
        run_extraction_batch()


if __name__ == "__main__":
    main()