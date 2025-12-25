import os
import re
import shutil
import zipfile
import tempfile
from pathlib import Path

import streamlit as st
from icrawler.builtin import BingImageCrawler


def safe_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s if s else "query"


def make_zip_from_folder(folder_path: str, zip_path: str):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(folder_path):
            for fn in files:
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, folder_path)
                z.write(fp, arcname=rel)


def count_images(folder: str) -> int:
    p = Path(folder)
    if not p.exists():
        return 0
    exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}
    return sum(1 for f in p.rglob("*") if f.is_file() and f.suffix.lower() in exts)


def download_until_target(
    keyword: str,
    download_dir: str,
    target: int,
    min_fraction: float = 0.66,
    round_batch_size: int = 80,
    max_rounds: int = 12,
):
    """
    تلاش می‌کند دقیقاً target عکس دانلود کند.
    اگر نشد، حداقل min_fraction * target را هدف می‌گیرد.
    با offset نتایج بعدی Bing را می‌گیرد تا گیر نکند.
    """
    min_needed = max(1, int(target * min_fraction))

    crawler = BingImageCrawler(
        storage={"root_dir": download_dir},
        feeder_threads=1,
        parser_threads=2,
        downloader_threads=6,
    )

    offset = 0
    last_count = 0
    stagnant_rounds = 0

    for r in range(1, max_rounds + 1):
        current = count_images(download_dir)
        if current >= target:
            return current, True  # exact reached

        # اگر چند دور پشت سر هم پیشرفتی نبود، زودتر قطع کن
        if current == last_count:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0
            last_count = current

        if stagnant_rounds >= 3 and current >= min_needed:
            return current, False  # good enough
        if stagnant_rounds >= 4 and current < min_needed:
            break

        remaining = target - current
        # هر دور کمی بیشتر از remaining درخواست می‌دهیم چون بخشی fail می‌شود
        batch = min(round_batch_size, max(30, remaining * 2))

        # مهم: offset باعث می‌شود نتایج بعدی را بگیرد
        crawler.crawl(
            keyword=keyword,
            offset=offset,
            max_num=int(batch),
        )
        offset += int(batch)

    final = count_images(download_dir)
    return final, final >= target


st.set_page_config(page_title="Bing Image ZIP Downloader", layout="centered")
st.title("Bing Image ZIP Downloader")
st.caption("Downloads images from Bing Images results and packs them into a ZIP.")

query = st.text_input("Search term (e.g. skin stapler)")
limit = st.number_input("Number of images (target)", min_value=1, max_value=300, value=100, step=10)

min_fraction = st.slider("Minimum acceptable fraction", min_value=0.50, max_value=1.00, value=0.66, step=0.01)
max_rounds = st.slider("Max search rounds", min_value=3, max_value=20, value=12, step=1)

if st.button("Download & Build ZIP"):
    q = safe_name(query)

    if not q or q == "query":
        st.error("Please enter a valid search term.")
        st.stop()

    with st.spinner("Downloading images from Bing Images and creating ZIP..."):
        tmpdir = tempfile.mkdtemp(prefix="imgdl_")
        download_dir = os.path.join(tmpdir, "downloads")
        zip_path = os.path.join(tmpdir, f"{q}.zip")

        try:
            os.makedirs(download_dir, exist_ok=True)

            got, exact = download_until_target(
                keyword=q,
                download_dir=download_dir,
                target=int(limit),
                min_fraction=float(min_fraction),
                round_batch_size=80,
                max_rounds=int(max_rounds),
            )

            min_needed = max(1, int(int(limit) * float(min_fraction)))

            if got == 0:
                st.error("No images were downloaded. Try a broader query.")
                st.stop()
            if got < min_needed:
                st.warning(
                    f"Only downloaded {got} images (minimum target fraction was {min_needed}). "
                    "Creating ZIP with available images."
                )

            make_zip_from_folder(download_dir, zip_path)
            
            with open(zip_path, "rb") as f:
                zip_bytes = f.read()

            if exact:
                st.success(f"Done! Downloaded {got} images (target reached).")
            else:
                st.success(f"Done! Downloaded {got} images (at least minimum achieved).")

            st.download_button(
                label="Download ZIP",
                data=zip_bytes,
                file_name=f"{q}.zip",
                mime="application/zip",
            )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
