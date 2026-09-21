import os
import io
import base64
import argparse
from datetime import datetime
import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Headless backend for image rendering
import matplotlib.pyplot as plt
import pytz

# --- Configuration ---
KOBO_TOKEN = 'c9f74ae5302d5d2dc168e0a8376f486024a5ffca'  # API Authentication Token
DEFAULT_FORM_ID = 'aGdUiP79mWAbGWCYdMPhrg'             # Set your form ID here

COLOR_YES = '#007bff'                                  # Blue
COLOR_NO = '#ff4d4f'                                   # Red
LOCAL_TZ = pytz.timezone('America/New_York')


def get_local_timestamp_str():
    """Returns current time in local timezone string."""
    utc_now = datetime.now(pytz.utc)
    local_now = utc_now.astimezone(LOCAL_TZ)
    return local_now.strftime("%Y-%m-%d %H:%M %Z")


def fetch_form_title_and_labels(form_id):
    """Fetches form definition to get title and question labels."""
    url = f'https://kf.kobotoolbox.org/api/v2/assets/{form_id}/?format=json'
    headers = {'Authorization': f'Token {KOBO_TOKEN}'}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            title = data.get('name', form_id)
            labels = {}
            if 'content' in data and 'survey' in data['content']:
                for q in data['content']['survey']:
                    if 'name' in q and 'label' in q:
                        lbl = q['label']
                        if isinstance(lbl, list) and len(lbl) > 0:
                            lbl = lbl[0]
                        labels[q['name']] = str(lbl)
            return title, labels
    except Exception:
        pass
    return form_id, {}


def fetch_kobo_data(token, target_form_id):
    """Fetches submission data for the target Kobo form."""
    print(f"Connecting to KoboToolbox API for Form ID: {target_form_id}...")
    headers = {'Authorization': f'Token {token}'}
    
    discovery_url = 'https://kf.kobotoolbox.org/api/v2/assets/?format=json'
    try:
        response = requests.get(discovery_url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to list assets. Status: {response.status_code}")
        assets_list = response.json().get('results', [])
    except Exception as e:
        print(f"Warning: KF discovery failed ({e}). Trying KC server...")
        discovery_url = 'https://kc.kobotoolbox.org/api/v2/assets/?format=json'
        response = requests.get(discovery_url, headers=headers)
        assets_list = response.json().get('results', [])

    available_assets = {a['uid']: {'url': a['data'], 'name': a['name']} for a in assets_list}
    asset_info = available_assets.get(target_form_id)

    if not asset_info:
        raise Exception(f"Form ID '{target_form_id}' was not found in your account.")

    print(f"  -> Found Form: '{asset_info['name']}'. Fetching submissions...")
    data_resp = requests.get(asset_info['url'], headers=headers)
    
    if data_resp.status_code == 200:
        form_data = data_resp.json().get('results', [])
        return form_data, asset_info['name']
    else:
        raise Exception(f"Failed to retrieve data. Status code: {data_resp.status_code}")


def apply_date_filter(df, args):
    """Filters records by date range and prints active time options to stdout."""
    print("\n--- Time Options & Date Filtering ---")
    
    if '_submission_time' not in df.columns:
        print("  Active Filter Window : ALL TIME (No '_submission_time' field found)")
        print("-------------------------------------\n")
        return df, "All Time"

    df['_submission_time'] = pd.to_datetime(df['_submission_time'])
    
    start_date = None
    end_date = None
    label_parts = []

    if args.today:
        now_local = datetime.now(LOCAL_TZ)
        start_date = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        label_parts.append(f"Today ({start_date.strftime('%Y-%m-%d')})")
    else:
        if args.start:
            try:
                start_date = pd.to_datetime(args.start).tz_localize(LOCAL_TZ)
                label_parts.append(f"From {start_date.strftime('%Y-%m-%d %H:%M')}")
            except Exception:
                print("  Warning: Invalid --start date string provided. Ignoring.")
        if args.end:
            try:
                end_date = pd.to_datetime(args.end).tz_localize(LOCAL_TZ)
                label_parts.append(f"To {end_date.strftime('%Y-%m-%d %H:%M')}")
            except Exception:
                print("  Warning: Invalid --end date string provided. Ignoring.")

    # Output active filtering bounds to stdout
    print(f"  Current Local Time   : {datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  Filter Setting       : {'TODAY ONLY' if args.today else ('CUSTOM RANGE' if (args.start or args.end) else 'ALL TIME')}")
    print(f"  Start Boundary       : {start_date.strftime('%Y-%m-%d %H:%M:%S %Z') if start_date else 'Unbounded (Beginning of time)'}")
    print(f"  End Boundary         : {end_date.strftime('%Y-%m-%d %H:%M:%S %Z') if end_date else 'Unbounded (Present/Future)'}")

    initial_count = len(df)

    if start_date:
        if df['_submission_time'].dt.tz is None:
            df['_submission_time'] = df['_submission_time'].dt.tz_localize('UTC').dt.tz_convert(LOCAL_TZ)
        df = df[df['_submission_time'] >= start_date]

    if end_date:
        if df['_submission_time'].dt.tz is None:
            df['_submission_time'] = df['_submission_time'].dt.tz_localize('UTC').dt.tz_convert(LOCAL_TZ)
        df = df[df['_submission_time'] <= end_date]

    print(f"  Submissions Retained : {len(df)} of {initial_count}")
    print("-------------------------------------\n")

    filter_label = " ".join(label_parts) if label_parts else "All Time"
    return df, filter_label


def generate_bar_chart_base64(df, column_name, filter_label, title):
    """Generates bar chart image encoded as Base64."""
    records = df[column_name].dropna()
    if records.empty:
        return None

    counts = records.value_counts()
    unique_vals_lower = set([str(v).lower() for v in counts.index])

    if 'yes' in unique_vals_lower or 'no' in unique_vals_lower:
        x_labels = ['yes', 'no']
        y_vals = [counts.get(k, 0) for k in x_labels]
        bar_colors = [COLOR_YES, COLOR_NO]
    else:
        x_labels = counts.index.tolist()
        y_vals = counts.values.tolist()
        bar_colors = '#007bff'

    display_labels = [str(lbl).replace('_', ' ').title() for lbl in x_labels]

    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(display_labels, y_vals, color=bar_colors)
    ax.set_ylabel('Count')
    ax.set_title(title)

    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + 0.05, 
                f"{int(height)}", ha='center', va='bottom')

    timestamp_str = f"Updated: {get_local_timestamp_str()} | Filter: {filter_label}"
    plt.figtext(0.99, 0.01, timestamp_str, ha='right', va='bottom', fontsize=8, color='gray')

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"


def build_text_comments_html(df, text_cols, label_map):
    """Lists every individual text comment without charts."""
    comments_found = False
    html = '<div class="card"><h2>Submitted Comments & Text Entries</h2>'

    for col in text_cols:
        q_label = label_map.get(col, col.replace('_', ' ').title())
        non_empty = df[df[col].notna() & (df[col].astype(str).str.strip() != '')]
        
        if not non_empty.empty:
            comments_found = True
            html += f'<h3>{q_label}</h3><ul class="comment-list">'
            for idx, row in non_empty.iterrows():
                time_str = ""
                if '_submission_time' in row and pd.notna(row['_submission_time']):
                    time_str = f' <span class="comment-time">({pd.to_datetime(row["_submission_time"]).strftime("%Y-%m-%d %H:%M")})</span>'
                html += f'<li>"{str(row[col]).strip()}"{time_str}</li>'
            html += '</ul>'

    if not comments_found:
        html += '<p style="color: #7f8c8d; font-style: italic;">No text comments were submitted for this period.</p>'

    html += '</div>'
    return html


def run_local_report():
    parser = argparse.ArgumentParser(description="Generate targeted HTML report for Kobo Form.")
    parser.add_argument('--form_id', type=str, default=DEFAULT_FORM_ID, help="Kobo Form Asset ID")
    parser.add_argument('--today', action='store_true', help="Filter submissions for today only")
    parser.add_argument('--start', type=str, help="Start date/time boundary (e.g. YYYY-MM-DD HH:MM)")
    parser.add_argument('--end', type=str, help="End date/time boundary (e.g. YYYY-MM-DD HH:MM)")
    
    args = parser.parse_args()

    form_title, label_map = fetch_form_title_and_labels(args.form_id)
    raw_data, fetched_name = fetch_kobo_data(KOBO_TOKEN, args.form_id)
    
    df = pd.DataFrame(raw_data)
    df, filter_lbl = apply_date_filter(df, args)

    if df.empty:
        print("No records found matching the specified time parameters. Exiting.")
        return

    ignore_system_cols = [
        'form_name', 'email', 'username', 'deviceid', 'subscriberid', 
        'simserial', 'phonenumber', 'start', 'end', 'timestamp', 'Form_Completed',
        'meta/instanceID', 'meta/rootUuid'
    ]

    discrete_cols = []
    text_cols = []

    for col in df.columns:
        if col.startswith('_') or col in ignore_system_cols or 'formhub' in col.lower():
            continue
        
        unique_vals = df[col].dropna().unique()
        num_unique = len(unique_vals)
        
        # Binary or simple discrete options get bar charts; text/compound choices do not.
        if 0 < num_unique <= 15 and all(len(str(v)) <= 30 for v in unique_vals):
            discrete_cols.append(col)
        elif num_unique > 0:
            text_cols.append(col)

    # Build HTML Content
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{form_title} - Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f4f6f8; margin: 0; padding: 30px; color: #333; }}
        .header {{ text-align: center; margin-bottom: 30px; }}
        .header h1 {{ color: #1a252f; margin-bottom: 5px; }}
        .meta {{ color: #7f8c8d; font-size: 0.9em; }}
        .card {{ background: white; border-radius: 8px; padding: 25px; margin: 0 auto 30px auto; max-width: 850px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }}
        .chart-grid {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; max-width: 900px; margin: 0 auto 30px auto; }}
        .chart-card {{ background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); width: 100%; max-width: 420px; }}
        .chart-card img {{ width: 100%; height: auto; }}
        .comment-list {{ padding-left: 20px; line-height: 1.6; }}
        .comment-list li {{ margin-bottom: 8px; color: #2c3e50; font-size: 1.05em; }}
        .comment-time {{ font-size: 0.8em; color: #95a5a6; }}
        h2 {{ color: #2c3e50; border-bottom: 2px solid #edf2f7; padding-bottom: 10px; margin-top: 0; }}
        h3 {{ color: #34495e; font-size: 1.1em; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{form_title}</h1>
        <p class="meta">Form ID: {args.form_id} | Total Submissions: {len(df)} | Timeframe: {filter_lbl}</p>
    </div>
"""

    # 1. Render Bar Charts (For standard discrete choices only)
    if discrete_cols:
        html_content += '<div class="chart-grid">'
        for col in discrete_cols:
            q_label = label_map.get(col, col.replace('_', ' ').title())
            b64_img = generate_bar_chart_base64(df, col, filter_lbl, q_label)
            if b64_img:
                html_content += f'<div class="chart-card"><img src="{b64_img}" alt="{q_label}"></div>'
        html_content += '</div>'

    # 2. Render Text Comments/Entries List (No charts for these)
    if text_cols:
        html_content += build_text_comments_html(df, text_cols, label_map)

    html_content += "</body>\n</html>"

    output_filename = "compoundchoices.html"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Report successfully generated and saved to: '{output_filename}'")


if __name__ == "__main__":
    run_local_report()
