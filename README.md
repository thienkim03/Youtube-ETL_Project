# YouTube ETL Project

## 1. Project Overview

This project demonstrates a simple ETL (Extract, Transform, Load) pipeline using Python and SQL Server.

The pipeline extracts video metadata from YouTube, transforms the raw data into a clean and structured format, then loads the processed data into SQL Server for further analysis.

---

## 2. Objectives

- Build a complete ETL pipeline using Python and SQL Server
- Extract YouTube video metadata automatically
- Clean and standardize the extracted data
- Load the processed dataset into SQL Server
- Create a reusable and maintainable data pipeline

---

## 3. Data Source

| Item | Description |
|------|-------------|
| Source | YouTube |
| Input | YouTube video URLs |
| Extraction Tool | Python |
| Output | CSV |

### Example Fields

| Field | Description |
|------|-------------|
| Video ID | Unique identifier of the video |
| Video Title | Video title |
| Channel Name | Name of the YouTube channel |
| Publish Date | Date the video was published |
| Video URL | Original YouTube video URL |
| Duration | Video duration |
| View Count | Number of views |
| Like Count | Number of likes |
| Comment Count | Number of comments |
| Tags | Video tags |
| Category | Video category |
| Thumbnail URL | Thumbnail image URL |
| Collection Date | Date when the data was extracted |

---

## 4. Project Workflow

```text
YouTube
    │
    ▼
Python (Extract)
    │
    ▼
data/raw/raw_youtube_YYYYMMDD.csv
    │
    ▼
Python (Transform)
• Remove duplicates
• Handle missing values
• Convert data types
• Rename columns
• Standardize formats
    │
    ▼
data/processed/cleaned_youtube_YYYYMMDD.csv
    │
    ▼
SQL Server (Load)
    │
    ▼
dbo.video_statistics
```

---

## 5. Project Structure

```text
Youtube-ETL_Project/
│
├── data/
│   ├── raw/
│   └── processed/
│
├── scripts/
│   ├── extract.py
│   ├── transform.py
│   ├── load.py
│   └── run_pipeline.py
│
├── sql/
│   └── create_tables.sql
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 6. ETL Process

### 6.1 Extract

**Tool:** Python

The extraction script collects video metadata from YouTube and stores the raw dataset in CSV format.

**Output**

```text
data/raw/raw_youtube_YYYYMMDD.csv
```

---

### 6.2 Transform

**Tool:** pandas

The transformation process includes:

- Removing duplicate records
- Handling missing values
- Converting data types
- Formatting dates
- Renaming columns
- Standardizing text values

**Output**

```text
data/processed/cleaned_youtube_YYYYMMDD.csv
```

---

### 6.3 Load

**Tool:** SQL Server

The cleaned dataset is loaded into SQL Server for storage and future analysis.

Database

```text
YouTubeDB
```

Table

```text
dbo.video_statistics
```

---

## 7. Technologies

| Category | Technology |
|----------|------------|
| Programming Language | Python |
| Data Processing | pandas |
| Storage | CSV |
| Database | SQL Server |
| Database Connector | pyodbc / SQLAlchemy |
| Version Control | Git & GitHub |

---

## 8. Future Improvements

- Automate the pipeline using Windows Task Scheduler
- Support incremental loading
- Add logging and error handling
- Build Power BI dashboards
- Containerize the project using Docker

---

## 9. Project Status

✅ Extract completed

✅ Transform completed

✅ Load completed

🚧 Dashboard and scheduling planned for future versions

---

## 10. Author

**Kim Vu Thien**

Data Analyst | Python | SQL | ETL
