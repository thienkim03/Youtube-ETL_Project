-- ============================================================
-- create_tables.sql
-- Chạy 1 LẦN DUY NHẤT lúc setup ban đầu (VD chạy bằng DBeaver).
-- Không chạy lại mỗi lần pipeline chạy — load.py chỉ INSERT/UPDATE
-- dữ liệu, không đụng vào cấu trúc bảng.
-- ============================================================

-- ------------------------------------------------------------
-- 1. STAGING: bảng landing tạm, chứa dữ liệu THÔ của 1 lần chạy
--    pipeline. Bị TRUNCATE (xoá sạch) và ghi lại mỗi lần load.py
--    chạy — không dùng để lưu trữ lâu dài, chỉ là bước đệm để
--    SQL bên dưới tách ra dim/fact.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging_video_raw (
    video_id            VARCHAR(20)   NOT NULL,
    video_title         VARCHAR(500),
    channel_id          VARCHAR(30)   NOT NULL,
    channel_name        VARCHAR(255),
    subscriber_count    BIGINT        NULL,
    publish_date        DATETIME      NOT NULL,
    video_url           VARCHAR(255),
    duration            VARCHAR(20),
    duration_seconds    INT,
    duration_category   VARCHAR(50),
    view_count          BIGINT        NOT NULL DEFAULT 0,
    like_count          BIGINT        NOT NULL DEFAULT 0,
    comment_count       BIGINT        NOT NULL DEFAULT 0,
    tags                TEXT,
    category             VARCHAR(100),
    thumbnail_url        VARCHAR(500),
    collection_date       DATE         NOT NULL
);

-- ------------------------------------------------------------
-- 2. DIM_CHANNEL: 1 dòng / channel, gần như không đổi.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_channel (
    channel_id      VARCHAR(30)   NOT NULL,
    channel_name    VARCHAR(255),
    first_seen_date DATE          NOT NULL,
    PRIMARY KEY (channel_id)
);

-- ------------------------------------------------------------
-- 3. DIM_VIDEO: 1 dòng / video, chỉ field TĨNH. Insert 1 lần
--    duy nhất khi video được phát hiện lần đầu, không update lại.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_video (
    video_id            VARCHAR(20)   NOT NULL,
    channel_id          VARCHAR(30)   NOT NULL,
    video_title         VARCHAR(500),
    publish_date         DATETIME      NOT NULL,
    duration             VARCHAR(20),
    duration_seconds     INT,
    duration_category    VARCHAR(50),
    tags                 TEXT,
    category              VARCHAR(100),
    thumbnail_url         VARCHAR(500),
    video_url             VARCHAR(255),
    first_collected_date  DATE          NOT NULL,
    PRIMARY KEY (video_id),
    CONSTRAINT fk_dimvideo_channel FOREIGN KEY (channel_id) REFERENCES dim_channel(channel_id),
    INDEX idx_channel_publish (channel_id, publish_date)
);

-- ------------------------------------------------------------
-- 4. FACT_VIDEO_METRICS: 1 dòng / video / lần cào (snapshot).
--    Đây là bảng append theo thời gian, giữ lịch sử tăng trưởng.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_video_metrics (
    video_id            VARCHAR(20)  NOT NULL,
    snapshot_date        DATE         NOT NULL,
    view_count           BIGINT       NOT NULL DEFAULT 0,
    like_count            BIGINT       NOT NULL DEFAULT 0,
    comment_count         BIGINT       NOT NULL DEFAULT 0,
    subscriber_count      BIGINT       NULL,
    created_at             TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (video_id, snapshot_date),
    CONSTRAINT fk_fact_video FOREIGN KEY (video_id) REFERENCES dim_video(video_id),
    INDEX idx_snapshot_date (snapshot_date)
);

-- ------------------------------------------------------------
-- 5. VIEW: luôn trả về snapshot MỚI NHẤT của mỗi video, join sẵn
--    với dim_video — dùng cho Power BI / query nhanh, không cần
--    tự viết lại logic MAX(snapshot_date) mỗi lần.
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW vw_video_latest AS
SELECT
    d.video_id,
    d.video_title,
    d.channel_id,
    c.channel_name,
    d.publish_date,
    d.duration,
    d.duration_category,
    d.category,
    d.tags,
    d.thumbnail_url,
    f.view_count,
    f.like_count,
    f.comment_count,
    f.subscriber_count,
    f.snapshot_date
FROM dim_video d
JOIN dim_channel c ON c.channel_id = d.channel_id
JOIN fact_video_metrics f ON f.video_id = d.video_id
WHERE f.snapshot_date = (
    SELECT MAX(f2.snapshot_date)
    FROM fact_video_metrics f2
    WHERE f2.video_id = d.video_id
);
