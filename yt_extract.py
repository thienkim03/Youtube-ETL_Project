"""
extract.py
----------
Kéo dữ liệu video YouTube theo (nhiều) từ khóa, filter trong tháng hiện tại.
Chỉ xuất ra CSV. Gom dữ liệu theo THÁNG: nếu chạy nhiều lần trong cùng
1 tháng (nhiều ngày, nhiều keyword khác nhau), dữ liệu sẽ được APPEND
vào cùng 1 file duy nhất của tháng đó thay vì tạo file mới mỗi lần chạy.

Field lấy:
    Video ID, Video Title, Channel ID, Channel Name, Subscriber Count, Publish Date,
    Video URL, Duration, View Count, Like Count, Comment Count, Tags, Category,
    Thumbnail URL, Keyword, Collection Date

Yêu cầu:
    pip install requests python-dotenv

Cách lấy API Key:
    1. Vào https://console.cloud.google.com/
    2. Tạo project mới (hoặc dùng project có sẵn)
    3. Bật "YouTube Data API v3"
    4. Vào Credentials > Create Credentials > API Key
    5. Tạo file .env cùng thư mục với script này, thêm dòng:
       YOUTUBE_API_KEY=your_key_here
       (file .env đã được thêm vào .gitignore, không bị đẩy lên GitHub)

Cách chạy:
    # 1 keyword
    python extract.py --keyword "data analyst" --max-results 100

    # nhiều keyword cùng lúc (cách nhau bằng dấu phẩy)
    python extract.py --keyword "data analyst,data engineer,business analyst" --max-results 100
"""

import os
import csv
import argparse
import datetime as dt
import calendar
import time
import requests
from dotenv import load_dotenv

# Đọc file .env (nếu có) và nạp vào biến môi trường của process hiện tại.
# File .env KHÔNG được commit lên Git (đã thêm vào .gitignore).
load_dotenv(override=True)

# ============================================================
# CONFIG - SỬA CÁC GIÁ TRỊ Ở ĐÂY, KHÔNG CẦN TRUYỀN THAM SỐ DÒNG LỆNH
# Nếu muốn chạy kiểu "python extract.py" trực tiếp trong VS Code / IDE
# thì chỉ cần sửa các dòng bên dưới rồi bấm Run.
# ============================================================
# Thư mục chứa chính file script này -> dùng làm nơi xuất CSV mặc định.
# Cách này KHÔNG phụ thuộc vào việc bạn đứng ở đâu (cwd) khi chạy lệnh python,
# luôn xuất ra đúng "cái folder đang chứa yt_extract.py", tránh lỗi path tương
# đối ../data sai chỗ tuỳ theo cách chạy (terminal, notebook, VS Code Run...).
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

KEYWORDS = ["data analyst"]       # danh sách chủ đề muốn theo dõi, có thể thêm nhiều: ["data analyst", "data engineer"]
MAX_RESULTS = 100                 # số lượng video muốn lấy CHO MỖI keyword
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "data", "raw")  # luôn ra đúng <folder_script>/data/raw, không phụ thuộc cwd lúc chạy
# ============================================================

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

FIELDNAMES = [
    "video_id",
    "video_title",
    "channel_id",
    "channel_name",
    "subscriber_count",
    "publish_date",
    "video_url",
    "duration",
    "view_count",
    "like_count",
    "comment_count",
    "tags",
    "category",
    "thumbnail_url",
    "keyword",
    "collection_date",
]

# cache subscriber_count theo channel_id, tránh gọi API trùng lặp cho cùng 1 kênh
CHANNEL_STATS_CACHE = {}
# map category_id -> tên category (YouTube trả về id số, cần map sang tên)
CATEGORY_CACHE = {}


def parse_keywords(raw: str) -> list:
    """Tách chuỗi keyword cách nhau bằng dấu phẩy thành list, bỏ khoảng trắng thừa."""
    return [k.strip() for k in raw.split(",") if k.strip()]


def get_channel_stats(channel_ids: list, api_key: str) -> dict:
    """Trả về dict {channel_id: subscriber_count}, chỉ gọi API cho channel_id chưa có trong cache."""
    to_fetch = [cid for cid in set(channel_ids) if cid not in CHANNEL_STATS_CACHE]

    for i in range(0, len(to_fetch), 50):  # API chỉ cho tối đa 50 id / request
        chunk = to_fetch[i : i + 50]
        params = {
            "part": "statistics",
            "id": ",".join(chunk),
            "key": api_key,
        }
        resp = requests.get(CHANNELS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            channel_id = item.get("id")
            stats = item.get("statistics", {})
            if stats.get("hiddenSubscriberCount"):
                CHANNEL_STATS_CACHE[channel_id] = "hidden"
            else:
                CHANNEL_STATS_CACHE[channel_id] = stats.get("subscriberCount", 0)

        time.sleep(0.2)

    return CHANNEL_STATS_CACHE


def get_api_key():
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "Chưa có API key. Tạo file .env ở cùng thư mục với script, "
            "thêm dòng: YOUTUBE_API_KEY=your_key_here"
        )
    return api_key


def to_rfc3339(date_str: str, end_of_day: bool = False) -> str:
    time_part = "T23:59:59Z" if end_of_day else "T00:00:00Z"
    return f"{date_str}{time_part}"


def parse_duration(iso_duration: str) -> str:
    import re
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


def search_video_ids(
    keyword: str,
    api_key: str,
    published_after: str = None,
    published_before: str = None,
    max_results: int = 50,
) -> list:
    """Search video theo keyword + khoảng thời gian, trả về list video_id."""
    video_ids = []
    page_token = None

    while len(video_ids) < max_results:
        params = {
            "part": "id",
            "q": keyword,
            "type": "video",
            "maxResults": min(50, max_results - len(video_ids)),
            "key": api_key,
            "order": "viewCount",
        }
        if published_after:
            params["publishedAfter"] = to_rfc3339(published_after)
        if published_before:
            params["publishedBefore"] = to_rfc3339(published_before, end_of_day=True)
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(SEARCH_URL, params=params)
        if not resp.ok:
            try:
                err_json = resp.json()
                err_msg = err_json.get("error", {}).get("message", "")
                err_reason = err_json.get("error", {}).get("errors", [{}])[0].get("reason", "")
                print(f"   [LỖI API] Status {resp.status_code} | reason={err_reason} | message={err_msg}", flush=True)
            except Exception:
                print(f"   [LỖI API] Status {resp.status_code}: {resp.text}", flush=True)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            video_ids.append(item["id"]["videoId"])

        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(0.2)

    return video_ids[:max_results]


def get_video_details(video_ids: list, api_key: str, keyword: str) -> list:
    """Gọi videos.list để lấy full metadata (snippet + statistics + contentDetails)."""
    records = []
    category_map = get_category_map(api_key)
    collection_date = dt.datetime.now().strftime("%Y-%m-%d")

    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(chunk),
            "key": api_key,
        }
        resp = requests.get(VIDEOS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})
            video_id = item.get("id")

            record = {
                "video_id": video_id,
                "video_title": snippet.get("title", ""),
                "channel_id": snippet.get("channelId", ""),
                "channel_name": snippet.get("channelTitle", ""),
                "publish_date": snippet.get("publishedAt", ""),
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
                "duration": parse_duration(content.get("duration", "PT0S")),
                "view_count": int(stats.get("viewCount", 0) or 0),
                "like_count": int(stats.get("likeCount", 0) or 0),
                "comment_count": int(stats.get("commentCount", 0) or 0),
                "tags": "|".join(snippet.get("tags", [])),
                "category": category_map.get(snippet.get("categoryId", ""), "Unknown"),
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "keyword": keyword,
                "collection_date": collection_date,
            }
            records.append(record)

        time.sleep(0.2)

    channel_ids = [r["channel_id"] for r in records if r["channel_id"]]
    channel_stats = get_channel_stats(channel_ids, api_key)
    for r in records:
        sub_count = channel_stats.get(r["channel_id"], "Unknown")
        r["subscriber_count"] = sub_count if sub_count in ("hidden", "Unknown") else int(sub_count)

    return records


# Bảng tên tháng viết tắt cố định (không dùng strftime %b vì phụ thuộc locale
# của máy - nếu Windows set locale tiếng Việt thì %b sẽ ra "Th01" thay vì "Jan").
MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def get_month_range(year: int, month: int) -> tuple[str, str]:
    """Trả về ngày đầu và cuối tháng dạng YYYY-MM-DD để truyền vào YouTube API."""
    if month not in MONTH_ABBR:
        raise ValueError("month must be between 1 and 12")

    last_day = calendar.monthrange(year, month)[1]
    published_after = dt.date(year, month, 1).strftime("%Y-%m-%d")
    published_before = dt.date(year, month, last_day).strftime("%Y-%m-%d")
    return published_after, published_before


def get_monthly_filepath(output_dir: str, year: int, month: int) -> str:
    """File output đặt tên theo THÁNG dạng 'raw_youtube_Jan_2026.csv', không theo
    ngày -> nhiều lần chạy trong cùng 1 tháng sẽ cùng ghi/gộp vào đúng 1 file duy
    nhất (khác tháng thì tên tự khác nhau, không bao giờ trùng tên giữa các tháng)."""
    os.makedirs(output_dir, exist_ok=True)
    month_str = f"{MONTH_ABBR[month]}_{year}"
    return os.path.join(output_dir, f"raw_youtube_{month_str}.csv")


def load_existing_records(filepath: str) -> list:
    """Đọc dữ liệu đã có sẵn trong file tháng (nếu file đã tồn tại từ lần chạy trước)."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def merge_and_dedupe(existing: list, new_records: list) -> list:
    """Gộp dữ liệu cũ + mới, dedupe theo (video_id, keyword, collection_date).
    Nếu trùng key -> giữ bản MỚI (ghi đè view/like/comment cập nhật hơn).
    Nếu khác collection_date (chạy khác ngày trong tháng) -> giữ cả hai, tạo lịch sử."""
    merged = {}
    for r in existing + new_records:
        key = (r["video_id"], r["keyword"], r["collection_date"])
        merged[key] = r  # ghi đè -> bản xuất hiện sau (new_records) thắng nếu trùng key
    return list(merged.values())


def save_to_csv(records: list, filepath: str) -> str:
    try:
        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(records)
    except PermissionError:
        raise PermissionError(
            f"Không ghi được file '{filepath}' vì đang bị khóa. "
            f"Khả năng cao file này đang MỞ trong Excel/chương trình khác — hãy đóng lại rồi chạy lại script."
        )
    return filepath


def run_for_keyword(keyword: str, api_key: str, max_results: int, published_after: str, published_before: str) -> list:
    print(f"\n--- Keyword: '{keyword}' ---")
    print(f"[1/2] Đang search video trong khoảng {published_after} -> {published_before} ...")
    video_ids = search_video_ids(
        keyword=keyword,
        api_key=api_key,
        published_after=published_after,
        published_before=published_before,
        max_results=max_results,
    )
    print(f"   -> Tìm được {len(video_ids)} video")

    print("[2/2] Đang lấy chi tiết metadata ...")
    records = get_video_details(video_ids, api_key, keyword)
    return records


def main():
    parser = argparse.ArgumentParser(description="Kéo dữ liệu YouTube theo nhiều từ khóa, gom output theo tháng")
    parser.add_argument("--keyword", default=",".join(KEYWORDS),
                         help="Một hoặc nhiều từ khóa, cách nhau bằng dấu phẩy. VD: \"data analyst,data engineer\"")
    parser.add_argument("--max-results", type=int, default=MAX_RESULTS, help="Số lượng video muốn lấy MỖI keyword")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Thư mục lưu file CSV output (mặc định: <folder_script>/data/raw)")
    parser.add_argument("--year", type=int, help="Năm muốn lấy dữ liệu. VD: 2026")
    parser.add_argument("--month", type=int, help="Tháng muốn lấy dữ liệu, từ 1 đến 12")
    args = parser.parse_args()

    keywords = parse_keywords(args.keyword)
    if not keywords:
        raise ValueError("Không có keyword nào hợp lệ. Kiểm tra lại --keyword.")

    api_key = get_api_key()

    if args.year is None:
        args.year = int(input("Enter the year (YYYY): "))
    if args.month is None:
        args.month = int(input("Enter the month (1-12): "))

    published_after, published_before = get_month_range(args.year, args.month)

    print(f"Sẽ cào {len(keywords)} keyword: {keywords}")
    print(f"Khoảng thời gian: {published_after} -> {published_before}")

    all_new_records = []
    for kw in keywords:
        records = run_for_keyword(kw, api_key, args.max_results, published_after, published_before)
        all_new_records.extend(records)

    # Sort theo view_count giảm dần trong từng lần chạy
    all_new_records.sort(key=lambda r: int(r.get("view_count", 0) or 0), reverse=True)

    filepath = get_monthly_filepath(args.output_dir, args.year, args.month)
    existing_records = load_existing_records(filepath)
    if existing_records:
        print(f"\n[GOM THÁNG] File '{filepath}' đã có {len(existing_records)} dòng từ lần chạy trước, đang gộp thêm ...")

    merged_records = merge_and_dedupe(existing_records, all_new_records)

    save_to_csv(merged_records, filepath)

    latest_raw_path = os.path.join(args.output_dir, "latest_raw_path.txt")
    with open(latest_raw_path, "w", encoding="utf-8") as f:
        f.write(filepath)

    print(f"\n✅ Hoàn tất. File tháng hiện có tổng {len(merged_records)} dòng: {filepath}")
    print(f"Latest raw path saved to: {latest_raw_path}")


if __name__ == "__main__":
    main()
