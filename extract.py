"""
extract.py
----------
Kéo dữ liệu video YouTube theo DANH SÁCH CHANNEL (đọc từ 1 file
.md hoặc .txt), thay vì search theo keyword như bản cũ.

Với mỗi channel, chỉ lấy về:
    1. Video CHƯA từng thấy (video mới hoàn toàn), và
    2. Video ĐÃ thấy nhưng publish_date còn nằm trong khung REFRESH_WINDOW_MONTHS
       (mặc định 6 tháng) -> cào lại để cập nhật view/like/comment.
Video cũ hơn khung refresh thì bỏ qua, không cào lại -> tiết kiệm quota.

Để biết video nào "đã thấy", script sẽ query trực tiếp bảng
`dim_video` trong MySQL lúc bắt đầu chạy (nếu bảng chưa có / chưa
kết nối được MySQL thì coi như CHƯA có video nào từng thấy -> lần
chạy đầu tiên sẽ cào full lịch sử của từng channel).

Field lấy (giữ nguyên tên cột như bản cũ, bỏ cột `keyword`):
    video_id, video_title, channel_id, channel_name, subscriber_count,
    publish_date, video_url, duration, view_count, like_count,
    comment_count, tags, category, thumbnail_url, collection_date

Yêu cầu:
    pip install requests python-dotenv sqlalchemy pymysql

File .env (cùng thư mục, đã có sẵn .gitignore):
    YOUTUBE_API_KEY=your_key_here
    MYSQL_HOST=...
    MYSQL_USER=...
    MYSQL_PASSWORD=...
    MYSQL_DATABASE=...
    MYSQL_PORT=3306   (tùy chọn, mặc định 3306)

Input file danh sách channel (mặc định: channels.md, cùng thư mục
script), mỗi dòng 1 channel, chấp nhận các dạng:
    https://www.youtube.com/@lukebarousse
    https://www.youtube.com/channel/UCLLw7jmFsvfIVaUFsLs8mlQ
    @lukebarousse
    UCLLw7jmFsvfIVaUFsLs8mlQ
Dòng trống hoặc bắt đầu bằng "#" sẽ bị bỏ qua (coi như comment).

Cách chạy:
    python extract.py
    python extract.py --channels-file channels.md --refresh-months 6
"""

import os
import csv
import re
import argparse
import datetime as dt
import time
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

# extract.py nằm ngay tại root của project (cùng cấp với create_tables.sql,
# main.py, channels.md...) -> SCRIPT_DIR chính là project_dir, KHÔNG có
# folder scripts/ hay sql/ con bên trong.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# CONFIG — sửa trực tiếp ở đây nếu muốn chạy không cần tham số CLI
# ============================================================
CHANNELS_FILE = os.path.join(SCRIPT_DIR, "channels.md")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "data", "raw")
REFRESH_WINDOW_MONTHS = 6  # video cũ hơn mốc này (nếu đã từng cào) sẽ KHÔNG cào lại
# ============================================================

CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

FIELDNAMES = [
    "video_id", "video_title", "channel_id", "channel_name", "subscriber_count",
    "publish_date", "video_url", "duration", "view_count", "like_count",
    "comment_count", "tags", "category", "thumbnail_url", "collection_date",
]

CATEGORY_CACHE = {}
CHANNEL_STATS_CACHE = {}


def get_api_key() -> str:
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "Chưa có API key. Tạo file .env, thêm dòng: YOUTUBE_API_KEY=your_key_here"
        )
    return api_key


# ------------------------------------------------------------
# Đọc & chuẩn hoá danh sách channel từ file input
# ------------------------------------------------------------
def parse_channels_file(path: str) -> list:
    """Đọc file .md/.txt, mỗi dòng 1 channel (URL hoặc handle hoặc channel_id).
    Trả về list các "raw_ref" (chuỗi thô), việc resolve ra channel_id thật
    làm ở bước sau (resolve_channel_id) vì cần gọi API."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Không tìm thấy file danh sách channel: {path}. "
            f"Tạo file này, mỗi dòng 1 link/handle channel YouTube."
        )
    refs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Bỏ marker gạch đầu dòng nếu người dùng viết dạng list markdown "- https://..."
            line = re.sub(r"^[-*]\s*", "", line)
            refs.append(line)
    return refs


def extract_handle_or_id(raw_ref: str) -> dict:
    """Từ 1 dòng input, xác định đây là channel_id (UCxxxx) hay handle (@xxxx).
    Trả về dict {"type": "id" | "handle", "value": ...}"""
    ref = raw_ref.strip()

    # Dạng URL: https://www.youtube.com/channel/UCxxxx
    m = re.search(r"youtube\.com/channel/([A-Za-z0-9_-]+)", ref)
    if m:
        return {"type": "id", "value": m.group(1)}

    # Dạng URL: https://www.youtube.com/@handle
    m = re.search(r"youtube\.com/@([A-Za-z0-9_.-]+)", ref)
    if m:
        return {"type": "handle", "value": m.group(1)}

    # Dạng channel_id trần: UCxxxxxxxxxxxxxxxxxxxxxx (24 ký tự, bắt đầu UC)
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", ref):
        return {"type": "id", "value": ref}

    # Dạng @handle trần
    if ref.startswith("@"):
        return {"type": "handle", "value": ref[1:]}

    # Fallback: coi như handle
    return {"type": "handle", "value": ref}


def resolve_channel_id(ref: dict, api_key: str) -> str:
    """Gọi channels.list để lấy channel_id thật từ handle (nếu cần)."""
    if ref["type"] == "id":
        return ref["value"]

    params = {"part": "id", "forHandle": ref["value"], "key": api_key}
    resp = requests.get(CHANNELS_URL, params=params)
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        print(f"   [CẢNH BÁO] Không tìm thấy channel cho handle '@{ref['value']}', bỏ qua.")
        return None
    return items[0]["id"]


def get_channel_details(channel_ids: list, api_key: str) -> dict:
    """Trả về {channel_id: {"uploads_playlist": ..., "channel_name": ..., "subscriber_count": ...}}"""
    details = {}
    for i in range(0, len(channel_ids), 50):
        chunk = channel_ids[i : i + 50]
        params = {
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(chunk),
            "key": api_key,
        }
        resp = requests.get(CHANNELS_URL, params=params)
        resp.raise_for_status()
        for item in resp.json().get("items", []):
            stats = item.get("statistics", {})
            sub_count = "hidden" if stats.get("hiddenSubscriberCount") else int(stats.get("subscriberCount", 0) or 0)
            details[item["id"]] = {
                "uploads_playlist": item["contentDetails"]["relatedPlaylists"]["uploads"],
                "channel_name": item["snippet"]["title"],
                "subscriber_count": sub_count,
            }
        time.sleep(0.2)
    return details


# ------------------------------------------------------------
# Biết video nào "đã thấy" -> query MySQL (bảng dim_video)
# ------------------------------------------------------------
def get_known_videos() -> dict:
    """Trả về {video_id: publish_date (datetime)} từ bảng dim_video.
    Nếu chưa kết nối được MySQL / bảng chưa tồn tại -> trả về dict rỗng
    (coi như chưa từng cào video nào, sẽ cào full lịch sử)."""
    try:
        from sqlalchemy import create_engine, text

        mysql_host = os.getenv("MYSQL_HOST")
        mysql_user = os.getenv("MYSQL_USER")
        mysql_password = os.getenv("MYSQL_PASSWORD")
        mysql_database = os.getenv("MYSQL_DATABASE")
        mysql_port = int(os.getenv("MYSQL_PORT", "3306"))

        if not all([mysql_host, mysql_user, mysql_password, mysql_database]):
            print("   [INFO] Thiếu biến môi trường MySQL trong .env -> bỏ qua bước check known video.")
            return {}

        encoded_password = quote_plus(mysql_password)
        url = f"mysql+pymysql://{mysql_user}:{encoded_password}@{mysql_host}:{mysql_port}/{mysql_database}?charset=utf8mb4"
        engine = create_engine(url)

        with engine.begin() as conn:
            rows = conn.execute(text("SELECT video_id, publish_date FROM dim_video")).fetchall()
        return {row[0]: row[1] for row in rows}

    except Exception as e:
        print(f"   [INFO] Không đọc được dim_video từ MySQL ({e}) -> coi như chưa có video nào từng cào.")
        return {}


# ------------------------------------------------------------
# Duyệt uploads playlist của 1 channel, quyết định video nào cần cào
# ------------------------------------------------------------
def collect_video_ids_for_channel(
    uploads_playlist_id: str,
    api_key: str,
    known_videos: dict,
    refresh_cutoff: dt.datetime,
) -> list:
    """Trả về list video_id cần gọi videos.list (video mới + video cần refresh).
    Dừng phân trang ngay khi gặp 1 video ĐÃ BIẾT và publish_date cũ hơn refresh_cutoff,
    vì playlist trả về theo thứ tự mới -> cũ nên các video sau đó chắc chắn cũ hơn nữa."""
    to_fetch = []
    page_token = None

    while True:
        params = {
            "part": "contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": 50,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(PLAYLIST_ITEMS_URL, params=params)
        if not resp.ok:
            print(f"   [LỖI API playlistItems] Status {resp.status_code}: {resp.text[:200]}")
            resp.raise_for_status()
        data = resp.json()

        stop = False
        for item in data.get("items", []):
            content = item.get("contentDetails", {})
            video_id = content.get("videoId")
            published_at_str = content.get("videoPublishedAt")
            if not video_id:
                continue

            if video_id not in known_videos:
                # Video mới hoàn toàn -> luôn lấy
                to_fetch.append(video_id)
                continue

            # Video đã biết -> chỉ lấy lại nếu còn trong khung refresh
            known_publish_date = known_videos[video_id]
            if isinstance(known_publish_date, str):
                known_publish_date = dt.datetime.fromisoformat(known_publish_date.replace("Z", "+00:00"))
            known_publish_date = known_publish_date.replace(tzinfo=None)

            if known_publish_date >= refresh_cutoff:
                to_fetch.append(video_id)
            else:
                # Video đã biết + đã cũ hơn khung refresh -> mọi video sau đó
                # trong playlist (cũ hơn nữa) cũng vậy -> dừng luôn channel này.
                stop = True
                break

        if stop:
            break

        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(0.2)

    return to_fetch


def parse_duration(iso_duration: str) -> str:
    match = re.match(
        r"P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        iso_duration,
    )
    if not match:
        return "00:00:00"
    parts = match.groupdict()
    days = int(parts["days"] or 0)
    hours = int(parts["hours"] or 0) + days * 24
    minutes = int(parts["minutes"] or 0)
    seconds = int(parts["seconds"] or 0)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def get_category_map(api_key: str, region_code: str = "VN") -> dict:
    if CATEGORY_CACHE:
        return CATEGORY_CACHE
    url = "https://www.googleapis.com/youtube/v3/videoCategories"
    params = {"part": "snippet", "regionCode": region_code, "key": api_key}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    for item in resp.json().get("items", []):
        CATEGORY_CACHE[item["id"]] = item["snippet"]["title"]
    return CATEGORY_CACHE


def get_video_details(video_ids: list, api_key: str, channel_details: dict) -> list:
    """Gọi videos.list lấy full metadata cho danh sách video_id đã chọn."""
    records = []
    category_map = get_category_map(api_key)
    collection_date = dt.datetime.now().strftime("%Y-%m-%d")

    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        params = {"part": "snippet,statistics,contentDetails", "id": ",".join(chunk), "key": api_key}
        resp = requests.get(VIDEOS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})
            video_id = item.get("id")
            channel_id = snippet.get("channelId", "")
            sub_count = channel_details.get(channel_id, {}).get("subscriber_count", "Unknown")

            records.append({
                "video_id": video_id,
                "video_title": snippet.get("title", ""),
                "channel_id": channel_id,
                "channel_name": snippet.get("channelTitle", ""),
                "subscriber_count": sub_count,
                "publish_date": snippet.get("publishedAt", ""),
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
                "duration": parse_duration(content.get("duration", "PT0S")),
                "view_count": int(stats.get("viewCount", 0) or 0),
                "like_count": int(stats.get("likeCount", 0) or 0),
                "comment_count": int(stats.get("commentCount", 0) or 0),
                "tags": "|".join(snippet.get("tags", [])),
                "category": category_map.get(snippet.get("categoryId", ""), "Unknown"),
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "collection_date": collection_date,
            })
        time.sleep(0.2)

    return records


def save_to_csv(records: list, filepath: str) -> str:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(records)
    except PermissionError:
        raise PermissionError(
            f"Không ghi được file '{filepath}' vì đang bị khóa (có thể đang mở trong Excel)."
        )
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Kéo dữ liệu YouTube theo danh sách channel")
    parser.add_argument("--channels-file", default=CHANNELS_FILE, help="File .md/.txt chứa list channel, mỗi dòng 1 channel")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Thư mục lưu CSV output")
    parser.add_argument("--refresh-months", type=int, default=REFRESH_WINDOW_MONTHS,
                         help="Video đã biết cũ hơn N tháng thì KHÔNG cào lại metric")
    args = parser.parse_args()

    api_key = get_api_key()

    print(f"[1/5] Đọc danh sách channel từ: {args.channels_file}")
    raw_refs = parse_channels_file(args.channels_file)
    print(f"   -> {len(raw_refs)} channel trong file input")

    print("[2/5] Resolve channel handle -> channel_id ...")
    channel_ids = []
    for ref_str in raw_refs:
        ref = extract_handle_or_id(ref_str)
        cid = resolve_channel_id(ref, api_key)
        if cid:
            channel_ids.append(cid)
        time.sleep(0.1)
    print(f"   -> Resolve được {len(channel_ids)}/{len(raw_refs)} channel")

    print("[3/5] Lấy uploads playlist + thông tin channel ...")
    channel_details = get_channel_details(channel_ids, api_key)

    print("[4/5] Đọc video đã biết từ MySQL (dim_video) để quyết định cào gì ...")
    known_videos = get_known_videos()
    print(f"   -> Đã biết {len(known_videos)} video từ các lần chạy trước")

    refresh_cutoff = dt.datetime.now() - dt.timedelta(days=args.refresh_months * 30)

    all_video_ids = []
    for cid in channel_ids:
        detail = channel_details.get(cid)
        if not detail:
            continue
        video_ids = collect_video_ids_for_channel(
            detail["uploads_playlist"], api_key, known_videos, refresh_cutoff
        )
        print(f"   - {detail['channel_name']}: {len(video_ids)} video cần cào (mới + refresh)")
        all_video_ids.extend(video_ids)

    print(f"[5/5] Lấy chi tiết metadata cho {len(all_video_ids)} video ...")
    records = get_video_details(all_video_ids, api_key, channel_details)
    records.sort(key=lambda r: int(r.get("view_count", 0) or 0), reverse=True)

    collection_date = dt.datetime.now().strftime("%Y%m%d")
    filepath = os.path.join(args.output_dir, f"raw_youtube_{collection_date}.csv")
    save_to_csv(records, filepath)

    latest_raw_path = os.path.join(args.output_dir, "latest_raw_path.txt")
    with open(latest_raw_path, "w", encoding="utf-8") as f:
        f.write(filepath)

    print(f"\n✅ Hoàn tất. {len(records)} video được cào -> {filepath}")


if __name__ == "__main__":
    main()