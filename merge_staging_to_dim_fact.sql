-- ============================================================
-- merge_staging_to_dim_fact.sql
-- Chạy MỖI LẦN pipeline load xong staging_video_raw.
-- 3 bước, nên bọc trong 1 transaction (xem load.py) để đảm bảo
-- không bị dở dang nếu có lỗi giữa chừng.
-- ============================================================

-- Bước 1: tách dim_channel — channel mới thì insert, channel cũ bỏ qua
INSERT IGNORE INTO dim_channel (channel_id, channel_name, first_seen_date)
SELECT DISTINCT
    s.channel_id,
    s.channel_name,
    s.collection_date
FROM staging_video_raw s;

-- Bước 2: tách dim_video — chỉ insert video CHƯA từng có (không update lại field tĩnh)
INSERT IGNORE INTO dim_video (
    video_id, channel_id, video_title, publish_date, duration,
    duration_seconds, duration_category, tags, category,
    thumbnail_url, video_url, first_collected_date
)
SELECT
    s.video_id, s.channel_id, s.video_title, s.publish_date, s.duration,
    s.duration_seconds, s.duration_category, s.tags, s.category,
    s.thumbnail_url, s.video_url, s.collection_date
FROM staging_video_raw s
WHERE NOT EXISTS (
    SELECT 1 FROM dim_video d WHERE d.video_id = s.video_id
);

-- Bước 3: tách fact_video_metrics — mỗi dòng staging = 1 snapshot.
-- Upsert theo (video_id, snapshot_date) để phòng trường hợp chạy
-- pipeline 2 lần trong cùng 1 ngày (ghi đè số liệu của đúng ngày đó).
INSERT INTO fact_video_metrics (
    video_id, snapshot_date, view_count, like_count, comment_count, subscriber_count
)
SELECT
    s.video_id, s.collection_date, s.view_count, s.like_count, s.comment_count, s.subscriber_count
FROM staging_video_raw s
ON DUPLICATE KEY UPDATE
    view_count      = VALUES(view_count),
    like_count       = VALUES(like_count),
    comment_count    = VALUES(comment_count),
    subscriber_count = VALUES(subscriber_count);
