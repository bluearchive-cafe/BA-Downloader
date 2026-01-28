import os
import json
import shutil
import zipfile
import tempfile
import subprocess
import requests
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

INFO_PATH = "info_jp.json"
BUNDLE_INFO_PATH = "Android_PatchPack/BundlePackingInfo.json"
OUTPUT_REPO = "output"
ASSET_STUDIO = "./AssetStudio/AssetStudioModCLI"
MAX_WORKERS = 3
DOWNLOAD_TIMEOUT = 30
MAX_RETRIES = 5


def load_addressable_url():
    with open(INFO_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["AddressableCatalogUrl"].rstrip("/") + "/"


def extract_spine_info(name: str):
    lower = name.lower()
    m = re.search(r"spinecharacters-([^-/]+)", lower)
    if m:
        return "spinecharacters", m.group(1)
    m = re.search(r"spinelobbies-([^-/]+)", lower)
    if m:
        return "spinelobbies", m.group(1)
    return None, None


def is_normal_bundle(name: str) -> bool:
    lower = name.lower()
    if not lower.endswith(".bundle"):
        return False
    blocked = ["spinecharacters", "spinelobbies", "spinebackground", "materials", "textassets"]
    return not any(b in lower for b in blocked)


def collect_target_zips():
    with open(BUNDLE_INFO_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    zips = set()
    for pack in data.get("FullPatchPacks", []):
        for bf in pack.get("BundleFiles", []):
            if bf["Name"].endswith(".bundle"):
                zips.add(pack["PackName"])
                break
    return sorted(zips)


def download_file(url, path):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            start = time.time()
            with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)
            if time.time() - start > DOWNLOAD_TIMEOUT:
                raise TimeoutError
            return
        except Exception:
            if os.path.exists(path):
                os.remove(path)
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2)


def run_assetstudio(input_dir, out_dir, asset_type, group_opt):
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run(
        [ASSET_STUDIO, input_dir, "-t", asset_type, "-o", out_dir, "-g", group_opt],
        check=True
    )


def process_zip(base_url, zip_name):
    zip_url = urljoin(base_url, f"Android_PatchPack/{zip_name}")
    zip_path = os.path.abspath(zip_name)
    download_file(zip_url, zip_path)

    extract_dir = tempfile.mkdtemp(prefix="jp_zip_")
    normal_dir = tempfile.mkdtemp(prefix="jp_normal_")
    out_dir = os.path.join(OUTPUT_REPO, os.path.splitext(zip_name)[0])

    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(extract_dir)

        for root, _, files in os.walk(extract_dir):
            for f in files:
                if not f.endswith(".bundle"):
                    continue

                full_path = os.path.join(root, f)
                spine_type, char_name = extract_spine_info(f)

                if spine_type:
                    lower = f.lower()
                    if "textures" in lower:
                        temp_dir = tempfile.mkdtemp(prefix="jp_spine_")
                        shutil.copy(full_path, os.path.join(temp_dir, f))
                        run_assetstudio(temp_dir,
                                        os.path.join(spine_type, char_name),
                                        "tex2d", "type")
                        shutil.rmtree(temp_dir, ignore_errors=True)

                    elif "textassets" in lower:
                        temp_dir = tempfile.mkdtemp(prefix="jp_spine_")
                        shutil.copy(full_path, os.path.join(temp_dir, f))
                        run_assetstudio(temp_dir,
                                        os.path.join(spine_type, char_name),
                                        "textAsset", "type")
                        shutil.rmtree(temp_dir, ignore_errors=True)

                    continue

                if is_normal_bundle(f):
                    shutil.copy(full_path, os.path.join(normal_dir, f))

        if os.listdir(normal_dir):
            run_assetstudio(normal_dir, out_dir, "tex2d", "none")

    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
        shutil.rmtree(normal_dir, ignore_errors=True)
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
