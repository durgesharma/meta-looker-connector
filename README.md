# meta-looker_connector

A production-ready automated pipeline that extracts daily campaign-level performance metrics from the **Meta Ads API (Facebook Marketing API)** and appends them to a **Google Sheet**. The Google Sheet acts as the live data source for **Looker Studio** dashboards.

Automated via **GitHub Actions** scheduled to run daily at **11:30 PM IST (18:00 UTC)**.

---

## Architecture Overview

```
┌─────────────────────┐
│    Meta Ads API     │ (Daily Campaign Insights: Spend, Impressions, Clicks, Leads)
└──────────┬──────────┘
           │
           │ (Scheduled GitHub Actions: 11:30 PM IST / 18:00 UTC)
           ▼
┌─────────────────────┐
│  Python Connector   │ (Auth, Deduplication, Error Handling, Batch Append)
└──────────┬──────────┘
           │
           │ (gspread + Service Account)
           ▼
┌─────────────────────┐
│    Google Sheets    │ (Date, Campaign Name, Spend, Impressions, Clicks, Leads)
└──────────┬──────────┘
           │
           │ (Native Google Connector)
           ▼
┌─────────────────────┐
│    Looker Studio    │ (Interactive Visualizations & Daily Marketing Reports)
└─────────────────────┘
```

---

## Features

- **Automated Daily Extraction**: Fetches yesterday's campaign-level metrics matching Meta Ads Manager's day-close.
- **Accurate Metric Mapping**:
  - `Date`: Formatted as `YYYY-MM-DD` (recognized natively as a Date dimension by Looker Studio).
  - `Campaign Name`: Clean string dimension.
  - `Spend`: Currency metric with 2 decimal precision.
  - `Impressions`: Numeric metric.
  - `Clicks`: Numeric metric.
  - `Leads`: Intelligent extraction from Meta's `actions` array that prioritizes standard `lead` events and checks fallbacks without double-counting.
- **Idempotent & Deduplicated**: Re-running the script on the same day will **not** create duplicate rows.
- **Zero-Data Resilience**: Gracefully exits if all campaigns were paused yesterday or had zero delivery, preventing false workflow failure alerts.
- **Secure Key Handling**: Loads Google credentials directly from an environment variable string (`GOOGLE_CREDENTIALS_JSON`) without committing sensitive files.
- **Automatic Header Initialization**: If the Google Sheet is brand new and empty, standard headers are created automatically.

---

## Required GitHub Secrets

Configure these secrets in your repository settings under **Settings > Secrets and variables > Actions > New repository secret**:

| Secret Name | Description | Example / Format |
|---|---|---|
| `META_APP_ID` | Your Meta Developer App ID | `123456789012345` |
| `META_APP_SECRET` | Your Meta Developer App Secret | `a1b2c3d4e5f6g7h8...` |
| `META_ACCESS_TOKEN` | Long-lived System User or Admin Token with `ads_read` permission | `EAA...` |
| `META_AD_ACCOUNT_ID` | Your Meta Ad Account ID (with or without `act_`) | `act_1234567890` or `1234567890` |
| `GOOGLE_CREDENTIALS_JSON` | Raw content of your Google Cloud Service Account JSON file | `{"type": "service_account", ...}` |
| `SPREADSHEET_ID` | The ID of your target Google Sheet | `1BxiMVs0XRn5n...` |

### Optional Secrets / Variables:
| Variable Name | Description | Default |
|---|---|---|
| `WORKSHEET_NAME` | Name of the sheet tab | `Sheet1` |
| `SPREADSHEET_NAME` | Alternative to `SPREADSHEET_ID` (open sheet by title) | `None` |
| `ALLOW_DUPLICATES` | Set to `true` to allow duplicate rows on re-runs | `false` |
| `TARGET_DATE` | Manual date override for backfilling (`YYYY-MM-DD`) | Yesterday |

---

## Setup Instructions

### 1. Meta Ads API Setup
1. Go to [Meta for Developers](https://developers.facebook.com/) and create a Business App.
2. In [Meta Business Suite](https://business.facebook.com/) under **Business Settings > Users > System Users**:
   - Create a System User.
   - Assign the **Marketing API** asset and grant `ads_read` permission.
   - Generate a **Permanent System User Access Token**.
3. Under **Accounts > Ad Accounts**, add the System User to your Ad Account with **Analyst** or **Admin** role.

### 2. Google Cloud Service Account Setup
1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and enable both the **Google Sheets API** and **Google Drive API**.
3. Under **IAM & Admin > Service Accounts**, create a Service Account.
4. Click on the Service Account > **Keys > Add Key > Create new key (JSON)**.
5. Download the JSON file and copy its full contents into the `GOOGLE_CREDENTIALS_JSON` secret.

> [!IMPORTANT]
> **Share your Google Sheet**: Open your Google Sheet, click **Share**, and grant **Editor** access to your Service Account email (e.g. `your-service-account@project.iam.gserviceaccount.com`).

### 3. Looker Studio Setup
1. Open [Looker Studio](https://lookerstudio.google.com/) and click **Create > Data Source**.
2. Select **Google Sheets** and choose your spreadsheet and worksheet.
3. Verify the field types:
   - `Date`: Date (`YYYYMMDD`)
   - `Campaign Name`: Text
   - `Spend`: Currency (e.g., USD, INR, EUR)
   - `Impressions`: Number
   - `Clicks`: Number
   - `Leads`: Number
4. Click **Create Report** to start building charts and scorecards!

---

## Local Development & Testing

1. Clone repository and install dependencies:
   ```bash
   git clone https://github.com/your-username/meta-looker-connector.git
   cd meta-looker-connector
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your credentials:
   ```bash
   cp .env.example .env
   ```

3. Run the script:
   ```bash
   python main.py
   ```

---

## Scheduling

The GitHub Actions workflow `.github/workflows/schedule.yml` runs daily on a cron trigger:
```yaml
schedule:
  - cron: '0 18 * * *' # 18:00 UTC = 11:30 PM IST (UTC+5:30)
```
You can also trigger it manually at any time via the **Run workflow** button in the **Actions** tab of your repository.
