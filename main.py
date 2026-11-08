#!/usr/bin/env python3
"""
Meta Ads to Google Sheets (Looker Studio Connector)
===================================================
A production-grade Python script that fetches yesterday's campaign-level
performance data (Date, Campaign Name, Spend, Impressions, Clicks, Leads)
from the Meta Ads API and appends it cleanly to Google Sheets for Looker
Studio consumption.

Author: Senior Python Developer & API Integration Expert
Project: meta-looker_connector
"""

import os
import sys
import json
import logging
from typing import List, Dict, Any, Tuple, Optional

# Load local .env file if available (useful for local testing)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
import gspread
from google.oauth2.service_account import Credentials
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.exceptions import FacebookRequestError

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("meta-looker-connector")

# Standard headers required for Looker Studio schema mapping
SHEET_HEADERS = [
    "Date",
    "Campaign Name",
    "Spend",
    "Impressions",
    "Clicks",
    "Leads",
]

# Google OAuth2 scopes required for managing spreadsheets
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ---------------------------------------------------------------------------
# Configuration Validation
# ---------------------------------------------------------------------------
def validate_environment() -> Dict[str, str]:
    """
    Validates that all required environment variables are set.
    Returns a dictionary of validated configurations or raises an error.
    """
    required_vars = [
        "META_APP_ID",
        "META_APP_SECRET",
        "META_ACCESS_TOKEN",
        "META_AD_ACCOUNT_ID",
        "GOOGLE_CREDENTIALS_JSON",
    ]

    missing_vars = [var for var in required_vars if not os.getenv(var, "").strip()]

    spreadsheet_id = os.getenv("SPREADSHEET_ID", "").strip()
    spreadsheet_name = os.getenv("SPREADSHEET_NAME", "").strip()

    if not spreadsheet_id and not spreadsheet_name:
        missing_vars.append("SPREADSHEET_ID or SPREADSHEET_NAME")

    if missing_vars:
        logger.error(
            "Missing required environment variables:\n  - %s",
            "\n  - ".join(missing_vars),
        )
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    # Sanitize Ad Account ID: Meta requires 'act_' prefix
    ad_account_id = os.getenv("META_AD_ACCOUNT_ID", "").strip()
    if not ad_account_id.startswith("act_"):
        ad_account_id = f"act_{ad_account_id}"

    config = {
        "meta_app_id": os.getenv("META_APP_ID", "").strip(),
        "meta_app_secret": os.getenv("META_APP_SECRET", "").strip(),
        "meta_access_token": os.getenv("META_ACCESS_TOKEN", "").strip(),
        "meta_ad_account_id": ad_account_id,
        "google_credentials_json": os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip(),
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_name": spreadsheet_name,
        "worksheet_name": os.getenv("WORKSHEET_NAME", "Sheet1").strip(),
        "allow_duplicates": os.getenv("ALLOW_DUPLICATES", "false").lower() in ("true", "1", "yes"),
        "target_date": os.getenv("TARGET_DATE", "").strip(),  # Optional YYYY-MM-DD override
    }

    return config


# ---------------------------------------------------------------------------
# Metric Parsing Helpers
# ---------------------------------------------------------------------------
def extract_leads(actions: Optional[List[Dict[str, Any]]]) -> int:
    """
    Extracts total leads count from the Meta Ads 'actions' array.

    Meta categorizes leads under the standard 'lead' action_type.
    To prevent double-counting when multiple granular actions are present,
    it checks for 'lead' first. If 'lead' is missing, it falls back to
    alternative lead-specific action types (e.g. Instant Forms, Pixel lead).
    """
    if not actions or not isinstance(actions, list):
        return 0

    # 1. Primary check: standard aggregated 'lead' action type
    for action in actions:
        if action.get("action_type") == "lead":
            try:
                return int(float(action.get("value", 0)))
            except (ValueError, TypeError):
                return 0

    # 2. Fallback check: specific lead-generating action types
    fallback_types = {
        "onsite_conversion.lead_grouped",
        "offsite_conversion.fb_pixel_lead",
        "leadgen.other",
        "contact",
        "submit_application",
    }
    for action in actions:
        if action.get("action_type") in fallback_types:
            try:
                return int(float(action.get("value", 0)))
            except (ValueError, TypeError):
                return 0

    return 0


# ---------------------------------------------------------------------------
# Meta Ads API Client
# ---------------------------------------------------------------------------
def fetch_meta_campaign_insights(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Fetches yesterday's campaign-level performance data from Meta Ads API.
    Handles authentication, error logging, and empty data scenarios.
    """
    logger.info("Initializing Meta Ads API SDK...")
    try:
        FacebookAdsApi.init(
            app_id=config["meta_app_id"],
            app_secret=config["meta_app_secret"],
            access_token=config["meta_access_token"],
        )
    except Exception as e:
        logger.error(f"Failed to initialize Meta Ads API SDK: {e}")
        raise

    account = AdAccount(config["meta_ad_account_id"])

    fields = [
        "date_start",
        "campaign_name",
        "spend",
        "impressions",
        "clicks",
        "actions",
    ]

    params: Dict[str, Any] = {
        "level": "campaign",
    }

    if config["target_date"]:
        # Manual date override for backfilling historical days
        logger.info(f"Using manual target date range: {config['target_date']}")
        params["time_range"] = {
            "since": config["target_date"],
            "until": config["target_date"],
        }
    else:
        # Default: Meta's native 'yesterday' preset respects the Ad Account's timezone
        params["date_preset"] = "yesterday"

    logger.info(
        f"Querying Meta Insights for Ad Account: {config['meta_ad_account_id']} "
        f"(level=campaign, params={params})..."
    )

    try:
        insights_cursor = account.get_insights(fields=fields, params=params)
        insights = [dict(item) for item in insights_cursor]
        logger.info(f"Successfully retrieved {len(insights)} campaign insight record(s) from Meta.")
        return insights

    except FacebookRequestError as e:
        error_code = e.api_error_code()
        subcode = e.api_error_subcode()
        msg = e.api_error_message()
        logger.error(f"Meta Ads API Error: [Code {error_code}] (Subcode {subcode}): {msg}")

        # Provide user-friendly guidance for common authentication errors
        if error_code in (190, 102, 10):
            logger.error(
                "Your META_ACCESS_TOKEN appears to be expired or invalid. "
                "Please generate a long-lived System User Token in Meta Business Manager."
            )
        elif error_code == 200:
            logger.error(
                "Permission Denied. Ensure your System User has 'ads_read' permissions "
                "and is assigned to the Ad Account as an Analyst or Admin."
            )
        raise

    except requests.exceptions.Timeout as e:
        logger.error(f"Meta Ads API request timed out: {e}")
        raise

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error while connecting to Meta Ads API: {e}")
        raise


# ---------------------------------------------------------------------------
# Google Sheets Client (gspread)
# ---------------------------------------------------------------------------
def get_google_worksheet(config: Dict[str, Any]) -> Tuple[gspread.Worksheet, str]:
    """
    Authenticates with Google Sheets using the Service Account JSON string,
    opens the designated spreadsheet, and returns the target worksheet.
    """
    logger.info("Authenticating with Google Sheets via Service Account JSON...")
    try:
        creds_dict = json.loads(config["google_credentials_json"])
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse GOOGLE_CREDENTIALS_JSON as valid JSON. "
            "Ensure the secret contains the raw contents of your Service Account JSON key."
        )
        raise e

    service_account_email = creds_dict.get("client_email", "Unknown")
    logger.info(f"Service Account Identity: {service_account_email}")

    try:
        credentials = Credentials.from_service_account_info(
            creds_dict,
            scopes=GOOGLE_SCOPES,
        )
        client = gspread.authorize(credentials)
    except Exception as e:
        logger.error(f"Google authentication failed: {e}")
        raise

    # Open Spreadsheet by ID (preferred) or by Name
    spreadsheet = None
    try:
        if config["spreadsheet_id"]:
            logger.info(f"Opening Google Spreadsheet by ID: {config['spreadsheet_id']}")
            spreadsheet = client.open_by_key(config["spreadsheet_id"])
        elif config["spreadsheet_name"]:
            logger.info(f"Opening Google Spreadsheet by Name: '{config['spreadsheet_name']}'")
            spreadsheet = client.open(config["spreadsheet_name"])
    except gspread.exceptions.SpreadsheetNotFound:
        logger.error(
            f"Spreadsheet not found! Make sure you shared the Google Sheet with your "
            f"Service Account email: '{service_account_email}' with 'Editor' permissions."
        )
        raise
    except gspread.exceptions.APIError as e:
        logger.error(f"Google Sheets API Error while opening spreadsheet: {e}")
        raise

    # Open Worksheet/Tab
    target_tab = config["worksheet_name"]
    try:
        worksheet = spreadsheet.worksheet(target_tab)
        logger.info(f"Opened target worksheet: '{target_tab}'")
    except gspread.exceptions.WorksheetNotFound:
        logger.warning(
            f"Worksheet '{target_tab}' not found. Falling back to the first available tab: '{spreadsheet.sheet1.title}'."
        )
        worksheet = spreadsheet.sheet1

    return worksheet, service_account_email


# ---------------------------------------------------------------------------
# Data Sync & Append Logic
# ---------------------------------------------------------------------------
def sync_data_to_sheet(worksheet: gspread.Worksheet, insights: List[Dict[str, Any]], allow_duplicates: bool = False) -> int:
    """
    Transforms campaign insights, checks for headers, deduplicates entries,
    and appends the rows cleanly using USER_ENTERED formatting.
    Returns the number of rows appended.
    """
    # 1. Inspect existing values to check headers and deduplicate
    existing_data = worksheet.get_all_values()

    # 2. Ensure headers exist if sheet is completely blank
    if not existing_data:
        logger.info("Worksheet is blank. Adding standard headers row for Looker Studio...")
        worksheet.append_row(SHEET_HEADERS, value_input_option="USER_ENTERED")
        existing_keys = set()
    else:
        # Check existing (Date, Campaign Name) pairs for idempotency
        existing_keys = set()
        # Row 0 is assumed to be headers; rows 1+ are data
        for row in existing_data[1:]:
            if len(row) >= 2:
                # Key: (date_str, campaign_name_str)
                existing_keys.add((row[0].strip(), row[1].strip()))
        logger.info(f"Found {len(existing_data) - 1} existing data row(s) in worksheet.")

    # 3. Transform and format insight records
    rows_to_append: List[List[Any]] = []
    skipped_duplicates = 0

    for item in insights:
        date_str = str(item.get("date_start", "")).strip()
        campaign_name = str(item.get("campaign_name", "Unknown Campaign")).strip()

        # Parse numeric metrics cleanly
        try:
            spend = round(float(item.get("spend", 0.0)), 2)
        except (ValueError, TypeError):
            spend = 0.0

        try:
            impressions = int(item.get("impressions", 0))
        except (ValueError, TypeError):
            impressions = 0

        try:
            clicks = int(item.get("clicks", 0))
        except (ValueError, TypeError):
            clicks = 0

        leads = extract_leads(item.get("actions"))

        # Row format matching SHEET_HEADERS
        row = [
            date_str,
            campaign_name,
            spend,
            impressions,
            clicks,
            leads,
        ]

        # Duplicate check
        row_key = (date_str, campaign_name)
        if not allow_duplicates and row_key in existing_keys:
            logger.info(f"Skipping duplicate row for campaign '{campaign_name}' on date '{date_str}'.")
            skipped_duplicates += 1
            continue

        rows_to_append.append(row)
        logger.info(
            f"Prepared row: Date={date_str} | Campaign='{campaign_name}' | "
            f"Spend=${spend:.2f} | Imp={impressions} | Clicks={clicks} | Leads={leads}"
        )

    if skipped_duplicates > 0:
        logger.info(f"Skipped {skipped_duplicates} duplicate campaign row(s).")

    # 4. Append new rows
    if not rows_to_append:
        logger.info("No new rows to append. Everything is already up to date!")
        return 0

    logger.info(f"Appending {len(rows_to_append)} new row(s) to Google Sheets with USER_ENTERED format...")
    try:
        # value_input_option="USER_ENTERED" allows numbers and dates to be stored natively
        # so Looker Studio can immediately aggregate them as metrics.
        worksheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        logger.info(f"Successfully appended {len(rows_to_append)} row(s).")
        return len(rows_to_append)
    except Exception as e:
        logger.error(f"Failed to append rows to Google Sheets: {e}")
        raise


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------
def main() -> int:
    """
    Main entry point for GitHub Actions execution.
    Returns 0 on success, 1 on critical failure.
    """
    logger.info("==============================================================")
    logger.info("Starting Daily Meta Ads to Google Sheets (Looker) Sync")
    logger.info("==============================================================")

    try:
        # Step 1: Validate environment configuration
        config = validate_environment()

        # Step 2: Fetch yesterday's campaign performance from Meta Ads
        insights = fetch_meta_campaign_insights(config)

        # Handle empty data scenario (e.g. paused ads, zero delivery)
        if not insights:
            logger.info(
                "No campaign performance data returned for yesterday. "
                "(Ads may have been paused or had zero delivery)."
            )
            logger.info("Process finished cleanly with nothing to append.")
            return 0

        # Step 3: Connect to Google Sheets
        worksheet, _ = get_google_worksheet(config)

        # Step 4: Sync data to sheet with deduplication
        appended_count = sync_data_to_sheet(
            worksheet=worksheet,
            insights=insights,
            allow_duplicates=config["allow_duplicates"],
        )

        logger.info("==============================================================")
        logger.info(f"Sync completed successfully. Appended {appended_count} row(s).")
        logger.info("==============================================================")
        return 0

    except Exception as e:
        logger.exception(f"Fatal error during sync execution: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
