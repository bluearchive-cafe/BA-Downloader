import os
import json
import shutil
import tempfile
import subprocess
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

INFO_PATH = "info_cn.json"
BUNDLE_INFO_PATH = "Android/bundleDownloadInfo.json"
OUTPUT_REPO = "output"
ASSET_STUDIO = "./AssetStudio/AssetStudioModCLI"
MAX_WORKERS = 4
DOWNLOAD_TIMEOUT = 30
MAX_RETRIES = 5


def load_addressable_url():
    with open(INFO_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["AddressableCatalogUrl"].rstrip("/") + "/"


def bundle_match(name: str) -> bool:
    name = name.lower()
    if not name.endswith(".bundle"):
        return False
    if not ("textures" in name or "mx-addressableasset-ui" in name):
        return False
    blocked = ["mx-spine", "mx-npcs", "mx-obstacles", "mx-cafe", "mx-characters"]
    return not any(b in name for b in blocked)


def collect_target_bundles():
    with open(BUNDLE_INFO_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    bundles = []
    for b in data.get("BundleFiles", []):
        name = b.get("Name", "")
        if bundle_match(name):
            bundles.append(name)

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
                raise TimeoutError("Download exceeded limit")

            return
        except Exception:
            if os.path.exists(path):
                os.remove(path)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2)


def process_bundle(base_url, bundle_name):
    url = urljoin(base_url, f"AssetBundles/Android/{bundle_name}")
    bundle_path = os.path.abspath(bundle_name)

    download_file(url, bundle_path)

    temp_dir = tempfile.mkdtemp(prefix="bundle_")
    os.makedirs(OUTPUT_REPO, exist_ok=True)

    try:
        moved_path = os.path.join(temp_dir, bundle_name)
        shutil.move(bundle_path, moved_path)

        subprocess.run(
            [ASSET_STUDIO, temp_dir, "-t", "tex2d", "-o", OUTPUT_REPO, "-g", "type"],
            check=True
        )

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if os.path.exists(bundle_path):
            os.remove(bundle_path)


def main():
    base_url = load_addressable_url()
    bundles = collect_target_bundles()

    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        futures = [ex.submit(process_bundle, base_url, b) for b in bundles]
        for f in as_completed(futures):
            f.result()


if __name__ == "__main__":
    main()
