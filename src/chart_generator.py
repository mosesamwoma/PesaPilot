# src/chart_generator.py
"""
Dynamic, natural-language-driven chart generation for PesaPilot.

OLD behaviour (dashboard/app.py and whatsapp/whatsapp_api.py before this):
a fixed dictionary mapped a handful of exact keywords ("bar chart", "pie
chart", "heatmap"...) straight onto one hardcoded chart function each, and
only understood a few fixed day-count windows ("7 days", "90 days", "all
time"). Anything outside that vocabulary either fell through to the wrong
chart or wasn't picked up as a chart request at all.

NEW behaviour: the user describes the chart in plain English — chart type,
metric, date range (a specific month, a named week, "last quarter", exact
dates), grouping, category filter — and an LLM call (GroqClient.
generate_chart_spec) turns that into a small structured JSON spec. One
flexible data pull (PostgresDB.get_transactions_range) and one flexible
matplotlib renderer then produce the chart, instead of a hardcoded function
per chart type. This single module is shared by both the Streamlit
dashboard (matplotlib figure via st.pyplot) and the WhatsApp bot
(matplotlib figure encoded to base64 PNG) — one engine, two front ends.
"""
from __future__ import annotations

import io
import re
import json
import base64
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

logger = logging.getLogger(__name__)

CHART_TYPES = ('bar', 'line', 'pie', 'area', 'scatter', 'histogram', 'heatmap')
METRICS = ('amount', 'count', 'transaction_cost')
GROUP_BY_COLUMNS = ('merchant_category', 'recipient', 'type', 'date', 'weekday', 'hour')
TRANSACTION_TYPES = ('spending', 'income', 'all')

DEFAULT_SPEC: Dict[str, Any] = {
    "chart_type": "bar",
    "metric": "amount",
    "group_by": "merchant_category",
    "date_from": None,
    "date_to": None,
    "category_filter": None,
    "transaction_type": "spending",
    "top_n": 12,
    "title": None,
}

# Transaction `type` values that represent money leaving the account —
# matches the convention used throughout src/database.py and src/analyzer.py.
_SPENDING_TYPES = ('debit', 'payment', 'withdrawal', 'transfer', 'airtime')


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ------------------------------------------------------------------
# Step 1: turn free text into a structured, validated chart spec
# ------------------------------------------------------------------

def _spec_system_prompt() -> str:
    return f"""You convert a user's natural-language chart request into STRICT JSON describing
how to build it from their M-Pesa transaction history.

Return ONLY one JSON object — no markdown fences, no commentary, no explanation. Exact shape:
{{
  "chart_type": one of {list(CHART_TYPES)},
  "metric": one of {list(METRICS)},
  "group_by": one of {list(GROUP_BY_COLUMNS)} or null,
  "date_from": "YYYY-MM-DD" or null,
  "date_to": "YYYY-MM-DD" or null,
  "category_filter": a merchant category (e.g. "food", "transport") or null,
  "transaction_type": one of {list(TRANSACTION_TYPES)},
  "top_n": integer 3-30,
  "title": short human-readable chart title
}}

Rules:
- Today is {_today()}. Resolve every relative date yourself into concrete YYYY-MM-DD values:
  "last week" / "this week" / "last month" / "this month" / a named month like "August" or
  "August 2026" / "last 3 months" / "this year" / "last 7 days" / "Q1" / explicit date ranges.
- If the user gives no date/time reference at all, set date_from and date_to to null (full history).
- A month name with no year means the most recent occurrence of that month (this year if it
  hasn't passed yet, otherwise last year).
- If no chart type is stated, choose the best fit: ranking categories/recipients -> "bar";
  share/percentage of a whole -> "pie"; a trend across days -> "line" (or "area" if they ask to
  see it "filled" or "cumulative" or "area chart"); how transaction sizes are spread out ->
  "histogram"; category-by-weekday patterns -> "heatmap"; relationship between two numeric
  things, or "correlate" -> "scatter".
- "spending"/"expenses"/"paid"/"spent" -> transaction_type "spending". "received"/"income"/
  "got paid"/"credited" -> "income". Otherwise "all".
- "transaction cost"/"fees"/"charges"/"how much m-pesa charged me" mentioned -> metric
  "transaction_cost".
- group_by should be null only for a histogram, or a plain trend line/area with no explicit
  grouping requested (e.g. "spending over time" with no "by category").
- top_n defaults to 12; use the user's number if they give one ("top 5", "top ten", "top 3
  categories").
- title should be short, specific, and mention the resolved period in words if one was given
  (e.g. "Food Spending — August 2026", "Top 5 Recipients This Week").
"""


def parse_chart_request(groq_client, description: str) -> Dict[str, Any]:
    """Ask the LLM to turn `description` into a validated chart spec dict.
    Falls back to a small keyword heuristic if the LLM call or JSON parse
    fails outright, so the feature degrades gracefully instead of erroring."""
    spec = dict(DEFAULT_SPEC)
    raw = ""
    try:
        raw = groq_client.generate_chart_spec(description, _spec_system_prompt())
        cleaned = re.sub(r'^```(json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(cleaned)
        for k in spec:
            if k in parsed and parsed[k] not in (None, ""):
                spec[k] = parsed[k]
    except Exception as e:
        logger.warning(f"Chart spec parse failed ({e!r}); raw={raw[:200]!r}. Using heuristic fallback.")
        spec.update(_heuristic_spec(description))

    # ── sanitize every field so a bad/partial LLM response can never crash
    #    the renderer or query builder downstream ──
    if spec.get("chart_type") not in CHART_TYPES:
        spec["chart_type"] = "bar"
    if spec.get("metric") not in METRICS:
        spec["metric"] = "amount"
    if spec.get("group_by") not in GROUP_BY_COLUMNS:
        spec["group_by"] = None if spec["chart_type"] == "histogram" else "merchant_category"
    if spec.get("transaction_type") not in TRANSACTION_TYPES:
        spec["transaction_type"] = "spending"
    try:
        spec["top_n"] = max(3, min(30, int(spec.get("top_n") or 12)))
    except (TypeError, ValueError):
        spec["top_n"] = 12
    for date_key in ("date_from", "date_to"):
        val = spec.get(date_key)
        if val:
            try:
                datetime.strptime(str(val), "%Y-%m-%d")
            except ValueError:
                spec[date_key] = None
    if spec.get("category_filter"):
        spec["category_filter"] = str(spec["category_filter"]).strip().lower()
    if not spec.get("title"):
        spec["title"] = _default_title(spec)
    return spec


def _heuristic_spec(description: str) -> Dict[str, Any]:
    """Keyword-only fallback used only when the LLM call fails entirely
    (network error, empty response, malformed JSON) — covers the most
    common phrasing so the feature never hard-fails.

    Uses \\b word-boundary matching rather than plain substring checks:
    short tokens like "pie", "area", "line" are common substrings of
    ordinary words ("recipients" contains "pie", "clearance" contains
    "area", "airline" contains "line"), so a naive `in` check would
    misfire on totally unrelated requests.
    """
    text = description.lower()
    spec: Dict[str, Any] = {}

    def has(word: str) -> bool:
        return re.search(rf'\b{re.escape(word)}\b', text) is not None

    if has('pie'):
        spec['chart_type'] = 'pie'
    elif has('heatmap') or 'heat map' in text:
        spec['chart_type'] = 'heatmap'
    elif has('histogram') or has('distribution'):
        spec['chart_type'] = 'histogram'
        spec['group_by'] = None
    elif has('scatter'):
        spec['chart_type'] = 'scatter'
    elif has('area'):
        spec['chart_type'] = 'area'
    elif has('line') or has('trend') or 'over time' in text:
        spec['chart_type'] = 'line'

    if has('cost') or has('fee') or has('fees') or has('charge') or has('charges'):
        spec['metric'] = 'transaction_cost'
    if 'received' in text or 'income' in text or 'credited' in text:
        spec['transaction_type'] = 'income'

    for word in ('recipient', 'recipients', 'merchant', 'merchants'):
        if has(word):
            spec['group_by'] = 'recipient'
            break

    days = None
    m = re.search(r'last\s+(\d{1,3})\s*day', text)
    if m:
        days = int(m.group(1))
    elif 'last week' in text or 'this week' in text:
        days = 7
    elif 'last month' in text or 'this month' in text:
        days = 30
    elif '90 days' in text or 'last 3 months' in text or 'last quarter' in text:
        days = 90
    elif 'this year' in text or 'last year' in text:
        days = 365
    if days:
        spec['date_from'] = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        spec['date_to'] = datetime.now().strftime('%Y-%m-%d')

    m = re.search(r'top\s+(\d{1,2})', text)
    if m:
        spec['top_n'] = int(m.group(1))

    return spec


def _default_title(spec: Dict[str, Any]) -> str:
    metric_label = {
        'amount': 'Spending', 'count': 'Transaction Count', 'transaction_cost': 'Transaction Costs',
    }[spec['metric']]
    period = ""
    if spec.get('date_from') and spec.get('date_to'):
        period = f" ({spec['date_from']} to {spec['date_to']})"
    elif spec.get('date_from'):
        period = f" (since {spec['date_from']})"
    cat = f" — {str(spec['category_filter']).title()}" if spec.get('category_filter') else ""
    group_label = (spec.get('group_by') or 'day').replace('_', ' ')
    return f"{metric_label} by {group_label}{cat}{period}".strip()


# ------------------------------------------------------------------
# Step 2: pull exactly the data the spec needs
# ------------------------------------------------------------------

def fetch_chart_data(db, spec: Dict[str, Any]) -> pd.DataFrame:
    rows = db.get_transactions_range(
        date_from=spec.get('date_from'), date_to=spec.get('date_to'), limit=20000,
    )
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df['timestamp'] = pd.to_datetime(df['timestamp'], format='ISO8601', errors='coerce')
    df = df.dropna(subset=['timestamp'])
    if df.empty:
        return df

    df['amount'] = pd.to_numeric(df.get('amount'), errors='coerce').fillna(0)
    df['transaction_cost'] = pd.to_numeric(df.get('transaction_cost'), errors='coerce').fillna(0)
    df['merchant_category'] = df.get('merchant_category').fillna('other')
    df['recipient'] = df.get('recipient').fillna('Unknown')
    df['count'] = 1  # lets metric='count' reuse the same sum-based groupby path everywhere below

    ttype = spec.get('transaction_type', 'spending')
    if ttype == 'spending':
        df = df[df['type'].isin(_SPENDING_TYPES)]
    elif ttype == 'income':
        df = df[df['type'] == 'credit']
    # ttype == 'all' -> no filter

    if spec.get('category_filter'):
        df = df[df['merchant_category'].str.lower() == spec['category_filter']]

    df['date'] = df['timestamp'].dt.date.astype(str)
    df['weekday'] = df['timestamp'].dt.day_name()
    df['hour'] = df['timestamp'].dt.hour

    return df


# ------------------------------------------------------------------
# Step 3: render — one flexible matplotlib renderer for every chart type
# ------------------------------------------------------------------

_DARK = dict(bg='#0f1117', panel='#1e2130', grid='#2d3250', text='#c8cdd8',
             accent='#00d4aa', accent2='#ff4b6e')
_LIGHT = dict(bg='white', panel='white', grid='#e0e0e0', text='#333333',
              accent='#2E86AB', accent2='#ff4b6e')


def _style(ax, fig, theme: dict, title: str) -> None:
    fig.patch.set_facecolor(theme['bg'])
    ax.set_facecolor(theme['panel'])
    ax.set_title(title, fontsize=14, fontweight='bold', color=theme['text'], pad=14)
    ax.tick_params(colors=theme['text'])
    for spine in ax.spines.values():
        spine.set_color(theme['grid'])
    ax.grid(True, color=theme['grid'], alpha=0.4, linewidth=0.6)
    ax.xaxis.label.set_color(theme['text'])
    ax.yaxis.label.set_color(theme['text'])


def build_figure(df: pd.DataFrame, spec: Dict[str, Any], dark: bool = True):
    """Returns (fig, summary_text) on success, or (None, message) when
    there's nothing to plot — `message` is then a user-facing explanation."""
    theme = _DARK if dark else _LIGHT
    metric = spec['metric']
    chart_type = spec['chart_type']
    group_by = spec['group_by']
    title = spec.get('title') or _default_title(spec)
    metric_label = metric.replace('_', ' ').title()

    if df is None or df.empty:
        return None, "No transactions found for that request — try widening the date range."

    fig, ax = plt.subplots(figsize=(11, 6.5))

    try:
        if chart_type == 'histogram':
            values = df[df[metric] > 0][metric]
            if values.empty or len(values) < 2:
                plt.close(fig)
                return None, "Not enough positive amounts to build a distribution from."
            ax.hist(values, bins=25, color=theme['accent'], edgecolor=theme['bg'])
            mean_val = values.mean()
            ax.axvline(mean_val, color=theme['accent2'], linestyle='--', linewidth=1.5,
                        label=f"Avg KES {mean_val:,.0f}")
            ax.set_xlabel(f'{metric_label} (KES)')
            ax.set_ylabel('Number of transactions')
            ax.legend(facecolor=theme['panel'], edgecolor=theme['grid'], labelcolor=theme['text'])
            _style(ax, fig, theme, title)
            summary = (f"Average KES {mean_val:,.0f}, median KES {values.median():,.0f}, "
                       f"across {len(values)} transactions.")

        elif chart_type == 'heatmap':
            pivot = df.pivot_table(values=metric, index='merchant_category', columns='weekday',
                                    aggfunc='sum', fill_value=0)
            day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            cols = [d for d in day_order if d in pivot.columns]
            if not cols or pivot.empty or pivot.values.max() == 0:
                plt.close(fig)
                return None, "Not enough data yet for a heatmap."
            pivot = pivot[cols]
            im = ax.imshow(pivot.values, cmap='YlOrRd', aspect='auto')
            ax.set_xticks(range(len(cols)))
            ax.set_xticklabels(cols, rotation=45, ha='right')
            ax.set_yticks(range(len(pivot.index)))
            ax.set_yticklabels(pivot.index)
            vmax = pivot.values.max()
            for i in range(len(pivot.index)):
                for j in range(len(cols)):
                    val = pivot.values[i, j]
                    if val > 0:
                        ax.text(j, i, f"{val:,.0f}", ha='center', va='center',
                                 color='black' if val < vmax * 0.6 else 'white', fontsize=8)
            cbar = fig.colorbar(im, ax=ax, shrink=0.8, label=f'{metric_label} (KES)')
            cbar.ax.yaxis.set_tick_params(color=theme['text'])
            plt.setp(cbar.ax.get_yticklabels(), color=theme['text'])
            cbar.ax.yaxis.label.set_color(theme['text'])
            _style(ax, fig, theme, title)
            summary = f"Heatmap of {metric_label.lower()} across {len(pivot.index)} categories and {len(cols)} weekdays."

        elif chart_type == 'scatter':
            key = group_by or 'recipient'
            grouped = df.groupby(key).agg(total=(metric, 'sum'), tx_count=(metric, 'count')).reset_index()
            grouped = grouped[grouped['total'] != 0]
            if grouped.empty:
                plt.close(fig)
                return None, "No data to plot for that grouping."
            ax.scatter(grouped['tx_count'], grouped['total'], color=theme['accent'], s=80, alpha=0.85,
                        edgecolors=theme['bg'])
            for _, row in grouped.nlargest(min(8, len(grouped)), 'total').iterrows():
                ax.annotate(str(row[key])[:18], (row['tx_count'], row['total']),
                             color=theme['text'], fontsize=8, xytext=(4, 4), textcoords='offset points')
            ax.set_xlabel('Number of transactions')
            ax.set_ylabel(f'Total {metric_label} (KES)')
            _style(ax, fig, theme, title)
            summary = f"{len(grouped)} {key.replace('_', ' ')} groups plotted by count vs total {metric_label.lower()}."

        elif chart_type in ('line', 'area'):
            daily = df.groupby('date')[metric].sum().reset_index().sort_values('date')
            if daily.empty:
                plt.close(fig)
                return None, "No data over this period."
            dates = pd.to_datetime(daily['date'])
            ax.plot(dates, daily[metric], color=theme['accent2'], linewidth=2, marker='o', markersize=3)
            if chart_type == 'area':
                ax.fill_between(dates, daily[metric], color=theme['accent2'], alpha=0.15)
            avg_val = daily[metric].mean()
            ax.axhline(avg_val, color=theme['accent'], linestyle='--', linewidth=1.2,
                        label=f"Avg KES {avg_val:,.0f}/day")
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
            fig.autofmt_xdate(rotation=45)
            ax.set_ylabel(f'{metric_label} (KES)')
            ax.legend(facecolor=theme['panel'], edgecolor=theme['grid'], labelcolor=theme['text'])
            _style(ax, fig, theme, title)
            peak = daily.loc[daily[metric].idxmax()]
            summary = (f"Peak: {peak['date']} at KES {peak[metric]:,.0f}. "
                       f"Average KES {avg_val:,.0f}/day across {len(daily)} days.")

        elif chart_type == 'pie':
            key = group_by or 'merchant_category'
            grouped = df.groupby(key)[metric].sum().sort_values(ascending=False)
            grouped = grouped[grouped > 0]
            if grouped.empty:
                plt.close(fig)
                return None, "No positive totals to chart for that grouping."
            top_n = spec.get('top_n', 12)
            if len(grouped) > top_n:
                other = grouped.iloc[top_n:].sum()
                grouped = grouped.iloc[:top_n].copy()
                if other > 0:
                    grouped['Other'] = other
            colors = plt.cm.tab20(range(len(grouped)))
            ax.pie(grouped.values, labels=grouped.index.astype(str), autopct='%1.1f%%', colors=colors,
                    textprops={'color': theme['text'], 'fontsize': 9}, pctdistance=0.8)
            ax.set_title(title, fontsize=14, fontweight='bold', color=theme['text'], pad=14)
            fig.patch.set_facecolor(theme['bg'])
            top_label = grouped.index[0]
            total = grouped.sum()
            summary = f"{top_label} is the largest share at KES {grouped.iloc[0]:,.0f} ({grouped.iloc[0] / total * 100:.0f}%)."

        else:  # bar (default, also covers "top merchants" / "top recipients" via group_by='recipient')
            key = group_by or 'merchant_category'
            grouped = df.groupby(key)[metric].sum().sort_values(ascending=True)
            grouped = grouped[grouped != 0]
            if grouped.empty:
                plt.close(fig)
                return None, "No data to chart for that grouping."
            top_n = spec.get('top_n', 12)
            grouped = grouped.tail(top_n)
            max_val = grouped.max() or 1
            colors = plt.cm.viridis([v / max_val for v in grouped.values])
            bars = ax.barh(grouped.index.astype(str), grouped.values, color=colors)
            for bar, val in zip(bars, grouped.values):
                ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f" KES {val:,.0f}",
                        va='center', color=theme['text'], fontsize=8)
            ax.set_xlabel(f'{metric_label} (KES)')
            _style(ax, fig, theme, title)
            top_label = grouped.index[-1]
            summary = f"Top: {top_label} at KES {grouped.iloc[-1]:,.0f}, across {len(grouped)} groups."

        plt.tight_layout()
        return fig, summary
    except Exception as e:
        logger.error(f"build_figure failed (chart_type={chart_type}): {e}")
        plt.close(fig)
        return None, f"Couldn't build that chart: {e}"


# ------------------------------------------------------------------
# Public entrypoints
# ------------------------------------------------------------------

def generate_dynamic_chart(analyzer, description: str, dark: bool = True) -> Dict[str, Any]:
    """Full pipeline: free-text description -> spec -> data -> matplotlib
    figure. `analyzer` is a src.analyzer.MpesaAnalyzer instance (used for
    its .groq and .db). Returns a dict with keys:
      fig     - matplotlib Figure, or None if nothing could be plotted
      spec    - the resolved chart spec (useful for logging/debugging)
      summary - one-line, human-readable takeaway from the chart (None on error)
      error   - user-facing explanation (None on success)
    """
    spec = parse_chart_request(analyzer.groq, description)
    df = fetch_chart_data(analyzer.db, spec)
    fig, message = build_figure(df, spec, dark=dark)
    return {
        'fig': fig,
        'spec': spec,
        'summary': message if fig is not None else None,
        'error': None if fig is not None else message,
    }


def figure_to_base64(fig) -> Optional[str]:
    """Encode a matplotlib figure as a base64 PNG string, matching the
    format the WhatsApp bot (whatsapp/whatsapp_api.py) already expects from
    its other chart functions. Closes the figure after encoding."""
    if fig is None:
        return None
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor=fig.get_facecolor())
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return encoded