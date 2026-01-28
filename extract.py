import os
import json
import shutil
import zipfile
import tempfile
import subprocess
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

INFO_PATH = "info_jp.json"
BUNDLE_INFO_PATH = "Android_PatchPack/BundlePackingInfo.json"
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


def collect_target_zips():
    with open(BUNDLE_INFO_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    zips = set()
    for pack in data.get("FullPatchPacks", []):
        zip_name = pack["PackName"]
        for bf in pack.get("BundleFiles", []):
            if bundle_match(bf["Name"]):
                zips.add(zip_name)
                break
    return sorted(zips)


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


def filter_bundles_only(root_dir):
    for root, dirs, files in os.walk(root_dir, topdown=False):
        for f in files:
            full_path = os.path.join(root, f)
            if not bundle_match(f):
                os.remove(full_path)
        if not os.listdir(root):
            shutil.rmtree(root, ignore_errors=True)


def process_zip(base_url, zip_name):
    zip_url = urljoin(base_url, f"Android_PatchPack/{zip_name}")
    zip_path = os.path.abspath(zip_name)

    download_file(zip_url, zip_path)

    temp_dir = tempfile.mkdtemp(prefix="bundle_")
    out_dir = os.path.join(OUTPUT_REPO, os.path.splitext(zip_name)[0])
    os.makedirs(out_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(temp_dir)

        filter_bundles_only(temp_dir)

        subprocess.run(
            [ASSET_STUDIO, temp_dir, "-t", "tex2d", "-o", out_dir, "-g", "none"],
            check=True
        )

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if os.path.exists(zip_path):
            os.remove(zip_path)


def main():
    base_url = load_addressable_url()
    zips = collect_target_zips()

    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        futures = [ex.submit(process_zip, base_url, z) for z in zips]
        for f in as_completed(futures):
            f.result()


if __name__ == "__main__":
    main()
