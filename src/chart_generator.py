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
import matplotlib.ticker as mticker
import seaborn as sns

from src.constants import SPENDING_TYPES
from src.parse_sms import MpesaParser
from src.timeutil import now_nairobi

logger = logging.getLogger(__name__)

CHART_TYPES = (
    'bar', 'line', 'pie', 'donut', 'area', 'scatter',
    'histogram', 'heatmap', 'box', 'violin', 'stacked_bar',
)
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

_SPENDING_TYPES = SPENDING_TYPES
_NO_DISTRIBUTION_METRIC = ('histogram', 'box', 'violin')


def _today() -> str:
    return now_nairobi().strftime("%Y-%m-%d")


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
  "category_filter": one of {list(MpesaParser.CATEGORIES)} or null,
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
  share/percentage of a whole -> "pie" (or "donut" if they say "donut"/"doughnut"); a trend
  across days -> "line" (or "area" if they ask to see it "filled" or "cumulative" or "area
  chart"); how transaction sizes are spread out overall -> "histogram"; how amounts vary or
  spread WITHIN each category/recipient (variability, consistency, outliers) -> "box"; a
  richer view of that same per-group spread -> "violin"; category-by-weekday patterns as one
  cell per combination -> "heatmap"; the same category-by-weekday breakdown as bars piled on
  top of each other -> "stacked_bar"; relationship between two numeric things, or "correlate"
  -> "scatter".
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

    if spec.get("chart_type") not in CHART_TYPES:
        spec["chart_type"] = "bar"
    if spec.get("metric") not in METRICS:
        spec["metric"] = "amount"
    if spec.get("group_by") not in GROUP_BY_COLUMNS:
        spec["group_by"] = None if spec["chart_type"] == "histogram" else "merchant_category"
    if spec.get("transaction_type") not in TRANSACTION_TYPES:
        spec["transaction_type"] = "spending"
    if spec.get("chart_type") in _NO_DISTRIBUTION_METRIC and spec.get("metric") == "count":
        spec["metric"] = "amount"
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
    text = description.lower()
    spec: Dict[str, Any] = {}

    def has(word: str) -> bool:
        return re.search(rf'\b{re.escape(word)}\b', text) is not None

    if has('donut') or has('doughnut'):
        spec['chart_type'] = 'donut'
    elif has('pie'):
        spec['chart_type'] = 'pie'
    elif has('stacked') and ('bar' in text or 'day' in text or 'week' in text):
        spec['chart_type'] = 'stacked_bar'
    elif has('heatmap') or 'heat map' in text:
        spec['chart_type'] = 'heatmap'
    elif has('violin'):
        spec['chart_type'] = 'violin'
    elif (has('box') or has('boxen') or has('spread') or has('outlier') or has('outliers')
          or has('variability') or has('consistency')):
        spec['chart_type'] = 'box'
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
        spec['date_from'] = (now_nairobi() - timedelta(days=days)).strftime('%Y-%m-%d')
        spec['date_to'] = now_nairobi().strftime('%Y-%m-%d')

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
    elif spec.get('date_to'):
        period = f" (until {spec['date_to']})"
    cat = f" — {str(spec['category_filter']).title()}" if spec.get('category_filter') else ""
    group_label = (spec.get('group_by') or 'day').replace('_', ' ')
    return f"{metric_label} by {group_label}{cat}{period}".strip()


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

    if 'amount' in df.columns:
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
    else:
        df['amount'] = 0
    if 'transaction_cost' in df.columns:
        df['transaction_cost'] = pd.to_numeric(df['transaction_cost'], errors='coerce').fillna(0)
    else:
        df['transaction_cost'] = 0
    if 'merchant_category' in df.columns:
        df['merchant_category'] = df['merchant_category'].fillna('other')
    else:
        df['merchant_category'] = 'other'
    if 'recipient' in df.columns:
        df['recipient'] = df['recipient'].fillna('Unknown')
    else:
        df['recipient'] = 'Unknown'
    df['count'] = 1

    ttype = spec.get('transaction_type', 'spending')
    if ttype == 'spending':
        df = df[df['type'].isin(_SPENDING_TYPES)]
    elif ttype == 'income':
        df = df[df['type'] == 'credit']

    if spec.get('category_filter'):
        df = df[df['merchant_category'].str.lower() == spec['category_filter']]

    df['date'] = df['timestamp'].dt.date.astype(str)
    df['weekday'] = df['timestamp'].dt.day_name()
    df['hour'] = df['timestamp'].dt.hour

    return df


_DARK = dict(bg='#0f1117', panel='#1e2130', grid='#2d3250', text='#c8cdd8',
             accent='#00d4aa', accent2='#ff4b6e', muted='#8892a4')
_LIGHT = dict(bg='white', panel='#fbfbfd', grid='#e0e0e0', text='#333333',
              accent='#2E86AB', accent2='#ff4b6e', muted='#6b7280')

_PALETTE_CATEGORICAL = 'Set2'
_PALETTE_SEQUENTIAL = 'crest'
_PALETTE_HEATMAP = 'rocket_r'
_PALETTE_SCATTER = 'flare'
_PALETTE_DISTRIBUTION = 'mako'
_PALETTE_STACKED = 'viridis'

_DAY_ORDER = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def _seaborn_rc(theme: dict) -> dict:
    return {
        'figure.facecolor': theme['bg'],
        'axes.facecolor': theme['panel'],
        'axes.edgecolor': theme['grid'],
        'axes.labelcolor': theme['text'],
        'text.color': theme['text'],
        'xtick.color': theme['text'],
        'ytick.color': theme['text'],
        'grid.color': theme['grid'],
        'grid.alpha': 0.4,
        'font.size': 11,
        'font.family': 'DejaVu Sans',
    }


def _style(ax, fig, theme: dict, title: str) -> None:
    ax.set_title(title, fontsize=14, fontweight='bold', color=theme['text'], pad=14)
    sns.despine(fig=fig, ax=ax, left=False, bottom=False)
    ax.xaxis.label.set_color(theme['text'])
    ax.yaxis.label.set_color(theme['text'])


def _watermark(fig, theme: dict) -> None:
    fig.text(0.995, 0.01, 'PesaPilot', ha='right', va='bottom', fontsize=8,
              color=theme['muted'], alpha=0.55, style='italic')


def _resize_for_groups(fig, n_items: int, orientation: str) -> None:
    n = max(int(n_items), 1)
    if orientation == 'h':
        height = min(14.0, max(6.5, 3.2 + 0.32 * n))
        fig.set_size_inches(11.0, height, forward=True)
    else:
        width = min(20.0, max(9.0, 2.6 + 0.9 * n))
        fig.set_size_inches(width, 6.5, forward=True)


def _top_groups(df: pd.DataFrame, key: str, metric: str, top_n: int) -> pd.Series:
    totals = df.groupby(key)[metric].sum().sort_values(ascending=False)
    return totals[totals != 0].head(top_n)


def _pie_like(ax, fig, df, spec, theme, metric, metric_label, title, donut: bool):
    key = spec['group_by'] or 'merchant_category'
    grouped = df.groupby(key)[spec['metric']].sum().sort_values(ascending=False)
    grouped = grouped[grouped > 0]
    if grouped.empty:
        return None, "No positive totals to chart for that grouping."
    top_n = spec.get('top_n', 12)
    if len(grouped) > top_n:
        other = grouped.iloc[top_n:].sum()
        grouped = grouped.iloc[:top_n].copy()
        if other > 0:
            grouped['Other'] = other
    colors = sns.color_palette(_PALETTE_CATEGORICAL, n_colors=len(grouped))
    wedge_kwargs = dict(edgecolor=theme['bg'], linewidth=1.2)
    if donut:
        wedge_kwargs['width'] = 0.42
    wedges, _labels, autotexts = ax.pie(
        grouped.values, labels=grouped.index.astype(str), autopct='%1.1f%%', colors=colors,
        textprops={'color': theme['text'], 'fontsize': 9}, pctdistance=0.8 if not donut else 0.82,
        wedgeprops=wedge_kwargs, startangle=90,
    )
    for wedge, autotext in zip(wedges, autotexts, strict=True):
        r, g, b, _ = wedge.get_facecolor()
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        autotext.set_color('#111111' if luminance > 0.6 else '#ffffff')
    if donut:
        total = grouped.sum()
        ax.text(0, 0.08, f"KES {total:,.0f}", ha='center', va='center',
                fontsize=15, fontweight='bold', color=theme['text'])
        ax.text(0, -0.14, 'total', ha='center', va='center', fontsize=9, color=theme['muted'])
    ax.set_title(title, fontsize=14, fontweight='bold', color=theme['text'], pad=14)
    top_label = grouped.index[0]
    total = grouped.sum()
    summary = f"{top_label} is the largest share at KES {grouped.iloc[0]:,.0f} ({grouped.iloc[0] / total * 100:.0f}%)."
    return summary, None


def build_figure(df: pd.DataFrame, spec: Dict[str, Any], dark: bool = True):
    theme = _DARK if dark else _LIGHT
    metric = spec['metric']
    chart_type = spec['chart_type']
    group_by = spec['group_by']
    title = spec.get('title') or _default_title(spec)
    metric_label = metric.replace('_', ' ').title()

    if df is None or df.empty:
        return None, "No transactions found for that request — try widening the date range."

    base_style = 'darkgrid' if dark else 'whitegrid'

    with sns.axes_style(base_style, rc=_seaborn_rc(theme)), sns.plotting_context('notebook', font_scale=1.0):
        fig, ax = plt.subplots(figsize=(11, 6.5))

        try:
            if chart_type == 'histogram':
                values = df[df[metric] > 0][metric]
                if values.empty or len(values) < 2:
                    plt.close(fig)
                    return None, "Not enough positive amounts to build a distribution from."
                sns.histplot(
                    values, bins=25, kde=True, ax=ax,
                    color=theme['accent'], edgecolor=theme['bg'], linewidth=0.6,
                    line_kws={'color': theme['accent2'], 'linewidth': 2},
                )
                mean_val = values.mean()
                ax.axvline(mean_val, color=theme['accent2'], linestyle='--', linewidth=1.5,
                           label=f"Avg KES {mean_val:,.0f}")
                ax.set_xlabel(f'{metric_label} (KES)')
                ax.set_ylabel('Number of transactions')
                ax.legend(facecolor=theme['panel'], edgecolor=theme['grid'], labelcolor=theme['text'])
                _style(ax, fig, theme, title)
                summary = (f"Average KES {mean_val:,.0f}, median KES {values.median():,.0f}, "
                           f"across {len(values)} transactions.")

            elif chart_type in ('box', 'violin'):
                key = group_by or 'merchant_category'
                totals = _top_groups(df, key, metric, spec.get('top_n', 12) if chart_type == 'box'
                                      else min(spec.get('top_n', 12), 8))
                if totals.empty:
                    plt.close(fig)
                    return None, "No data to chart for that grouping."
                sub = df[df[key].isin(totals.index) & (df[metric] > 0)].copy()
                min_samples = 2 if chart_type == 'box' else 3
                counts = sub[key].value_counts()
                valid_keys = counts[counts >= min_samples].index
                sub = sub[sub[key].isin(valid_keys)]
                if sub.empty:
                    plt.close(fig)
                    return None, "Not enough repeat transactions per group for a spread chart."
                order = sub.groupby(key)[metric].median().sort_values(ascending=False).index
                _resize_for_groups(fig, len(order), orientation='v')
                if chart_type == 'box':
                    sns.boxenplot(data=sub, x=key, y=metric, order=order, hue=key, legend=False,
                                   ax=ax, palette=_PALETTE_DISTRIBUTION, saturation=0.9,
                                   line_kws={'color': theme['text'], 'linewidth': 1})
                else:
                    sns.violinplot(data=sub, x=key, y=metric, order=order, hue=key, legend=False,
                                    ax=ax, palette=_PALETTE_DISTRIBUTION, inner='quartile', cut=0,
                                    density_norm='width', linewidth=1, linecolor=theme['bg'])
                ax.set_xlabel('')
                ax.set_ylabel(f'{metric_label} (KES)')
                ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
                plt.setp(ax.get_xticklabels(), rotation=35, ha='right')
                _style(ax, fig, theme, title)
                widest = sub.groupby(key)[metric].std().idxmax()
                summary = (f"{len(order)} groups compared — {widest} shows the widest spread "
                           f"in {metric_label.lower()}.")

            elif chart_type == 'stacked_bar':
                key = group_by or 'merchant_category'
                pivot = df.pivot_table(values=metric, index=key, columns='weekday',
                                        aggfunc='sum', fill_value=0)
                cols = [d for d in _DAY_ORDER if d in pivot.columns]
                if not cols or pivot.empty or pivot.values.max() == 0:
                    plt.close(fig)
                    return None, "Not enough data yet for a stacked breakdown."
                pivot = pivot[cols]
                totals = pivot.sum(axis=1).sort_values(ascending=False)
                top_n = spec.get('top_n', 12)
                keep = totals.head(top_n).index
                pivot = pivot.loc[keep[::-1]]
                _resize_for_groups(fig, len(pivot.index), orientation='h')
                colors = sns.color_palette(_PALETTE_STACKED, n_colors=len(cols))
                left = pd.Series(0.0, index=pivot.index)
                for day, color in zip(cols, colors):
                    ax.barh(pivot.index.astype(str), pivot[day], left=left, color=color,
                            label=day, edgecolor=theme['bg'], linewidth=0.4)
                    left = left + pivot[day]
                ax.set_xlabel(f'{metric_label} (KES)')
                ax.legend(title='Day', bbox_to_anchor=(1.02, 1), loc='upper left',
                          frameon=False, labelcolor=theme['text'], fontsize=8, title_fontsize=9)
                _style(ax, fig, theme, title)
                top_label = totals.index[0]
                summary = (f"{top_label} leads at KES {totals.iloc[0]:,.0f} across {len(cols)} "
                           f"weekdays — see the breakdown by day in the legend.")

            elif chart_type == 'heatmap':
                pivot = df.pivot_table(values=metric, index='merchant_category', columns='weekday',
                                        aggfunc='sum', fill_value=0)
                cols = [d for d in _DAY_ORDER if d in pivot.columns]
                if not cols or pivot.empty or pivot.values.max() == 0:
                    plt.close(fig)
                    return None, "Not enough data yet for a heatmap."
                pivot = pivot[cols]
                _resize_for_groups(fig, len(pivot.index), orientation='h')
                heat = sns.heatmap(
                    pivot, ax=ax, cmap=_PALETTE_HEATMAP, linewidths=1, linecolor=theme['bg'],
                    cbar_kws={'label': f'{metric_label} (KES)'}, annot=False, square=False,
                )
                quadmesh = heat.collections[0]
                cmap, norm = quadmesh.cmap, quadmesh.norm
                for i in range(len(pivot.index)):
                    for j in range(len(cols)):
                        val = pivot.values[i, j]
                        if val <= 0:
                            continue
                        r, g, b, _ = cmap(norm(val))
                        luminance = 0.299 * r + 0.587 * g + 0.114 * b
                        text_color = '#111111' if luminance > 0.6 else '#ffffff'
                        ax.text(j + 0.5, i + 0.5, f"{val:,.0f}", ha='center', va='center',
                                color=text_color, fontsize=8, fontweight='medium')
                cbar = quadmesh.colorbar
                cbar.ax.yaxis.set_tick_params(color=theme['text'])
                plt.setp(cbar.ax.get_yticklabels(), color=theme['text'])
                cbar.ax.yaxis.label.set_color(theme['text'])
                ax.set_xlabel('')
                ax.set_ylabel('')
                plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
                _style(ax, fig, theme, title)
                summary = f"Heatmap of {metric_label.lower()} across {len(pivot.index)} categories and {len(cols)} weekdays."

            elif chart_type == 'scatter':
                key = group_by or 'recipient'
                grouped = df.groupby(key).agg(total=(metric, 'sum'), tx_count=(metric, 'count')).reset_index()
                grouped = grouped[grouped['total'] != 0]
                if grouped.empty:
                    plt.close(fig)
                    return None, "No data to plot for that grouping."
                sns.scatterplot(
                    data=grouped, x='tx_count', y='total', hue='total', size='total',
                    palette=_PALETTE_SCATTER, sizes=(60, 260), edgecolor=theme['bg'],
                    linewidth=0.8, alpha=0.9, ax=ax, legend=False,
                )
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
                sns.lineplot(x=dates, y=daily[metric], ax=ax, color=theme['accent2'],
                             linewidth=2.2, marker='o', markersize=4)
                ax.set_xlabel('')
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

            elif chart_type in ('pie', 'donut'):
                summary, error = _pie_like(ax, fig, df, spec, theme, metric, metric_label, title,
                                            donut=(chart_type == 'donut'))
                if error:
                    plt.close(fig)
                    return None, error

            else:
                key = group_by or 'merchant_category'
                grouped = df.groupby(key)[metric].sum().sort_values(ascending=True)
                grouped = grouped[grouped != 0]
                if grouped.empty:
                    plt.close(fig)
                    return None, "No data to chart for that grouping."
                top_n = spec.get('top_n', 12)
                grouped = grouped.tail(top_n)
                _resize_for_groups(fig, len(grouped), orientation='h')
                colors = sns.color_palette(_PALETTE_SEQUENTIAL, n_colors=len(grouped))
                bars = ax.barh(grouped.index.astype(str), grouped.values, color=colors,
                                edgecolor=theme['bg'], linewidth=0.6, height=0.65)
                for bar, val in zip(bars, grouped.values, strict=True):
                    ax.plot(val, bar.get_y() + bar.get_height() / 2, marker='o',
                            markersize=4, color=theme['accent2'], zorder=3)
                    ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f" KES {val:,.0f}",
                            va='center', color=theme['text'], fontsize=8)
                ax.set_xlabel(f'{metric_label} (KES)')
                _style(ax, fig, theme, title)
                top_label = grouped.index[-1]
                summary = f"Top: {top_label} at KES {grouped.iloc[-1]:,.0f}, across {len(grouped)} groups."

            fig.patch.set_facecolor(theme['bg'])
            ax.set_facecolor(theme['panel'])
            _watermark(fig, theme)
            plt.tight_layout()
            return fig, summary
        except Exception as e:
            logger.error(f"build_figure failed (chart_type={chart_type}): {e}")
            plt.close(fig)
            return None, f"Couldn't build that chart: {e}"


def generate_dynamic_chart(analyzer, description: str, dark: bool = True) -> Dict[str, Any]:
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
    if fig is None:
        return None
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor=fig.get_facecolor())
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return encoded