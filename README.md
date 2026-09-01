# 🎯 Google Maps B2B Lead Generation Scraper

A high-performance, production-ready Google Maps scraper and lead enrichment pipeline engineered for B2B sales teams, agencies, and marketers. It extracts comprehensive business profiles from Google Maps and automatically visits business websites to discover direct email addresses, social media links (LinkedIn, Instagram, Facebook, Twitter/X, TikTok), and contact pages.

---

## 🌟 Key Features

- **Google Maps Data Extraction**:
  - Business Name & Primary Category
  - Star Rating & Review Counts
  - Verified Phone Numbers
  - Full Addresses (Street, City, State, Postal Code, Country)
  - Official Website URLs
  - Operating Hours & Current Status (e.g. *Open ⋅ Closes 9 PM*)
  - Geographic Coordinates (Latitude & Longitude)
  - Claimed / Verified Business Status
- **Automatic Website Lead Enrichment**:
  - Asynchronously crawls discovered websites to find **direct business emails** (`info@`, `contact@`, `sales@`, etc.).
  - Extracts active **social media profiles** (LinkedIn, Instagram, Facebook, Twitter/X, YouTube, TikTok).
  - Automatically identifies dedicated `/contact`, `/contact-us`, and `/about` pages.
- **Deduplication Engine**:
  - Automatically removes duplicates across multiple search queries and regional keywords.
- **Multiple Export Formats**:
  - **CSV**: Standard UTF-8 BOM encoding ready for cold outreach tools (Instantly, Apollo, Lemlist, Smartlead, HubSpot).
  - **Excel (`.xlsx`)**: Styled headers, auto-adjusted column widths, and clean formatting.
  - **JSON / JSONL**: Structured data for backend developer pipelines.
- **Two User Interfaces**:
  - **CLI Tool**: Real-time terminal progress bars, colored output tables, and customizable parameters.
  - **Web UI Dashboard**: Interactive Streamlit application to search, preview tables, and download leads with 1 click.

---

## 🚀 Quick Start

### 1. Installation

1. Clone or navigate to the repository:
   ```bash
   cd Scrapper
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies and Playwright browser:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

---

## 💻 Usage

### Option A: Command Line Interface (CLI)

#### 1. Single Query Search
Scrape the top 20 dentists in Austin, TX and enrich with emails/socials:
```bash
python main.py -q "Dentists in Austin, TX" -l 20 --enrich -o outputs/austin_dentists.csv
```

#### 2. Batch Search Queries from a File
Scrape multiple queries specified in a file (e.g. `sample_queries.txt`):
```bash
python main.py -f sample_queries.txt --limit 50 --format xlsx -o outputs/b2b_leads.xlsx
```

#### 3. CLI Command Options:
| Flag | Short | Description | Default |
| :--- | :--- | :--- | :--- |
| `--query` | `-q` | Single Google Maps search query | `None` |
| `--file` | `-f` | Path to text file with one query per line | `None` |
| `--limit` | `-l` | Maximum leads to extract per query (`0` for all) | `20` |
| `--enrich` / `--no-enrich` | | Crawl websites for emails & social media handles | `True` |
| `--captcha-solver` | | Enable Bit Solver extension to auto-solve CAPTCHAs | `False` |
| `--solver-ext` | | Bit Solver extension (`captchasonic` or `nopecha`) | `captchasonic` |
| `--solver-path` | | Custom directory path to solver extension | `Bit Solver/extensions/...` |
| `--proxy` | | Single HTTP/SOCKS5 proxy (`http://user:pass@host:port` or `host:port:user:pass`) | `None` |
| `--proxy-file` | | Path to file with rotating proxy list (one per line) | `None` |
| `--format` | | Export format: `csv`, `xlsx`, `json`, `all` | `csv` |
| `--output` | `-o` | Destination filepath for exported file | `outputs/leads_<date>.csv` |
| `--headless` / `--no-headless` | | Toggle headless browser mode | `True` (headless) |
| `--concurrency` | | Concurrent workers for website crawling | `10` |
| `--delay` | | Delay between map interactions in seconds | `1.0` |

#### 4. Examples with Proxies & Bit Solver
```bash
# Scrape with single proxy and Bit Solver (CaptchaSonic)
python main.py -q "Real Estate in Miami, FL" -l 30 --proxy "http://user:pass@proxy.example.com:8000" --captcha-solver

# Scrape with rotating proxy file and NopeCHA solver
python main.py -f sample_queries.txt --proxy-file proxies.txt --captcha-solver --solver-ext nopecha
```

---

### Option B: Interactive Web UI Dashboard (Streamlit)

Launch the interactive web dashboard:
```bash
streamlit run app.py
```

Then open your browser at `http://localhost:8501`. You can:
1. Enter search queries or paste a list of queries.
2. Toggle **Proxy** and **Bit Solver (Captcha)** settings in the sidebar.
3. Configure limit sliders and enrichment settings.
4. Watch the real-time scraping progress.
5. Preview the interactive lead data table.
6. Download leads directly as **CSV**, **Excel (.xlsx)**, or **JSON**.

---

## 📁 Project Structure

```
Scrapper/
├── main.py                     # CLI entry point
├── app.py                      # Streamlit interactive web dashboard
├── sample_queries.txt          # Ready-to-use sample queries
├── requirements.txt            # Python dependencies
├── src/
│   ├── __init__.py
│   ├── config.py               # Constants, User-Agents, contact regex patterns
│   ├── models.py               # Pydantic schemas (BusinessLead, ScrapeConfig)
│   ├── maps_scraper.py         # Async Playwright Google Maps scraper
│   ├── enricher.py             # Async website crawler for emails & socials
│   ├── exporter.py             # CSV, XLSX, JSON exporters
│   └── utils.py                # URL cleaning, coordinates parsing, deduplication
└── tests/
    ├── __init__.py
    ├── test_enricher.py        # Email/social regex & utility tests
    └── test_models_exporter.py # Data models & file export tests
```

---

## 🧪 Running Tests

Run the test suite with `pytest`:
```bash
pytest -v tests/
```

---

## 📄 Output Data Schema

The generated files include the following fields:

| Field Name | Description | Example |
| :--- | :--- | :--- |
| **Business Name** | Official name of business | `ATX Family Dental` |
| **Category** | Primary industry category | `Dentist` |
| **Rating** | Google Maps star rating | `4.9` |
| **Review Count** | Total customer reviews | `154` |
| **Phone** | Clean formatted phone number | `+1 512-717-3147` |
| **Email** | Primary direct business email | `info@atxfamilydental.com` |
| **All Emails** | Comma-separated list of all emails | `info@atxfamilydental.com, contact@atxfamilydental.com` |
| **Website** | Clean official website URL | `https://www.atxfamilydental.com` |
| **LinkedIn** | LinkedIn company/profile link | `https://www.linkedin.com/company/...` |
| **Instagram** | Instagram profile link | `https://www.instagram.com/atxfamilydental/` |
| **Facebook** | Facebook page URL | `https://www.facebook.com/...` |
| **Twitter/X** | Twitter/X profile link | `https://twitter.com/...` |
| **YouTube** | YouTube channel link | `https://youtube.com/...` |
| **TikTok** | TikTok account link | `https://tiktok.com/@...` |
| **Contact Page** | Direct link to contact page | `https://www.atxfamilydental.com/contact/` |
| **Address** | Full physical address | `1700 S 1st St, Austin, TX 78704, United States` |
| **City** | Extracted city | `Austin` |
| **State** | Extracted state | `TX` |
| **Postal Code** | Extracted ZIP/Postal Code | `78704` |
| **Country** | Extracted country | `United States` |
| **Status** | Operating hours/status | `Closed · Opens 8 AM` |
| **Is Claimed** | Verified Google listing | `Yes` / `No` |
| **Latitude / Longitude** | Geolocation coordinates | `30.2482229`, `-97.7559705` |
| **Google Maps URL** | Place link on Google Maps | `https://www.google.com/maps/place/...` |
| **Search Query** | Keyword query used | `Dentists in Austin, TX` |
| **Enrichment Status** | Status of website crawling | `enriched` |
