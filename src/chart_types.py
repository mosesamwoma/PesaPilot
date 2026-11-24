from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
from matplotlib.colors import PowerNorm
from matplotlib.patches import Rectangle, Wedge

from src.frames import DAY_ORDER

logger = logging.getLogger(__name__)

DARK = dict(name='dark', bg='#0f1117', panel='#1e2130', grid='#2d3250', text='#c8cdd8', accent='#00d4aa',
            accent2='#ff4b6e', accent3='#ffb454', muted='#8892a4', heat='rocket', good='#00d4aa', bad='#ff4b6e')
LIGHT = dict(name='light', bg='white', panel='#fbfbfd', grid='#e0e0e0', text='#333333', accent='#2E86AB',
             accent2='#e63956', accent3='#f59e0b', muted='#6b7280', heat='rocket_r', good='#2E9E6B', bad='#e63956')

TIME_KEYS = ('date', 'week', 'month', 'weekday', 'hour')
METRIC_LABELS = {'amount': 'Amount (KES)', 'count': 'Transactions', 'transaction_cost': 'Fees (KES)',
                 'average': 'Average amount (KES)'}
_CLEAN_RE = re.compile(r'[\$\x00-\x1f\x7f]+')


class ChartError(Exception):
    pass


def clean_text(value: Any, limit: int = 40) -> str:
    text = _CLEAN_RE.sub(' ', str(value if value is not None else '')).strip()
    return (text[:limit - 1] + '…') if len(text) > limit else text


def seaborn_rc(theme: dict) -> dict:
    return {
        'figure.facecolor': theme['bg'], 'axes.facecolor': theme['panel'], 'axes.edgecolor': theme['grid'],
        'axes.labelcolor': theme['text'], 'text.color': theme['text'], 'xtick.color': theme['text'],
        'ytick.color': theme['text'], 'grid.color': theme['grid'], 'grid.alpha': 0.4, 'font.size': 11,
        'font.family': 'DejaVu Sans', 'legend.facecolor': theme['panel'], 'legend.edgecolor': theme['grid'],
        'legend.labelcolor': theme['text'], 'savefig.facecolor': theme['bg'],
    }


def palette(n: int):
    n = max(int(n), 1)
    if n <= 8:
        return sns.color_palette('Set2', n_colors=n)
    if n <= 20:
        return sns.color_palette('tab20', n_colors=n)
    return sns.color_palette('husl', n_colors=n)


def fmt_value(metric: str, value: float) -> str:
    return f"{value:,.0f}" if metric == 'count' else f"KES {value:,.0f}"


def thousands(ax, axis: str = 'y') -> None:
    formatter = mticker.FuncFormatter(lambda v, _: f"{v:,.0f}")
    (ax.yaxis if axis == 'y' else ax.xaxis).set_major_formatter(formatter)


def aggregate(df: pd.DataFrame, key: str, metric: str) -> pd.Series:
    if metric == 'average':
        series = df.groupby(key)['amount'].mean()
    elif metric == 'count':
        series = df.groupby(key).size().astype(float)
    else:
        series = df.groupby(key)[metric].sum()
    return series


def natural_order(key: str, index) -> list:
    if key == 'weekday':
        return [d for d in DAY_ORDER if d in set(index)]
    return sorted(index)


@dataclass
class Ctx:
    df: pd.DataFrame
    spec: Dict[str, Any]
    theme: dict
    fig: Any = None
    ax: Any = None
    standalone: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def metric(self) -> str:
        return self.spec['metric']

    @property
    def metric_label(self) -> str:
        return METRIC_LABELS.get(self.metric, self.metric)

    @property
    def key(self) -> str:
        return self.spec.get('group_by') or 'merchant_category'

    @property
    def top_n(self) -> int:
        return int(self.spec.get('top_n') or 12)

    @property
    def title(self) -> str:
        return clean_text(self.spec.get('title') or '', 100)

    def new_fig(self, figsize=(11, 6.5), **kwargs):
        if self.fig is not None:
            plt.close(self.fig)
        self.fig, self.ax = plt.subplots(figsize=figsize, **kwargs)
        return self.ax

    def adopt(self, fig, ax=None) -> None:
        if self.fig is not None and self.fig is not fig:
            plt.close(self.fig)
        self.fig, self.ax = fig, ax

    def resize(self, n_items: int, orientation: str) -> None:
        if not self.standalone or self.fig is None:
            return
        n = max(int(n_items), 1)
        if orientation == 'h':
            self.fig.set_size_inches(11.0, min(14.0, max(6.5, 3.2 + 0.32 * n)), forward=True)
        else:
            self.fig.set_size_inches(min(20.0, max(9.0, 2.6 + 0.9 * n)), 6.5, forward=True)

    def style(self, ax=None, title: Optional[str] = None, despine: bool = True) -> None:
        ax = ax or self.ax
        label = self.title if title is None else title
        if label:
            ax.set_title(label, fontsize=14 if self.standalone else 11, fontweight='bold',
                         color=self.theme['text'], pad=14 if self.standalone else 8)
        if despine:
            sns.despine(ax=ax)
        ax.xaxis.label.set_color(self.theme['text'])
        ax.yaxis.label.set_color(self.theme['text'])


def _need(df: pd.DataFrame, minimum: int = 1, message: str = "No transactions to chart.") -> None:
    if df is None or len(df) < minimum:
        raise ChartError(message)


def _top_with_other(series: pd.Series, top_n: int) -> pd.Series:
    series = series[series > 0].sort_values(ascending=False)
    if len(series) > top_n:
        other = series.iloc[top_n:].sum()
        series = series.iloc[:top_n].copy()
        if other > 0:
            series['Other'] = other
    return series


def _daily(df: pd.DataFrame, metric: str, fill: bool = True) -> pd.Series:
    if metric == 'average':
        grouped = df.groupby('date')['amount'].mean()
    elif metric == 'count':
        grouped = df.groupby('date').size().astype(float)
    else:
        grouped = df.groupby('date')[metric].sum()
    if grouped.empty:
        return grouped
    if fill:
        grouped = grouped.reindex(pd.date_range(grouped.index.min(), grouped.index.max(), freq='D'), fill_value=0.0)
    return grouped.astype(float)


def _bucket(span_days: int) -> str:
    return 'D' if span_days <= 45 else 'W-SUN' if span_days <= 400 else 'MS'


def _bucket_label(rule: str) -> str:
    return {'D': 'day', 'W-SUN': 'week', 'MS': 'month'}[rule]


def _skewed(values: pd.Series) -> bool:
    values = values[values > 0]
    return len(values) > 20 and float(values.quantile(0.99)) / max(float(values.median()), 1e-9) > 25


def _log_ticks(ax, axis: str = 'y') -> None:
    formatter = mticker.FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 1 else f"{v:g}")
    (ax.yaxis if axis == 'y' else ax.xaxis).set_major_formatter(formatter)


def _legend_outside(ax, theme: dict, title: Optional[str] = None, **kwargs) -> None:
    ax.legend(title=title, bbox_to_anchor=(1.02, 1), loc='upper left', frameon=False, labelcolor=theme['text'],
              fontsize=8, title_fontsize=9, **kwargs)


def _out(summary: str, *facts: str) -> Dict[str, Any]:
    return {'summary': summary, 'facts': [summary, *facts]}


def render_bar(ctx: Ctx) -> Dict:
    if ctx.key in TIME_KEYS:
        return render_column(ctx)
    series = aggregate(ctx.df, ctx.key, ctx.metric)
    series = series[series != 0].sort_values(ascending=False)
    _need(series, 1, "No data to chart for that grouping.")
    total = float(series.sum())
    top = series.head(ctx.top_n).iloc[::-1]
    ctx.resize(len(top), 'h')
    colors = sns.color_palette('crest', n_colors=len(top))
    labels = [clean_text(i, 34) for i in top.index.astype(str)]
    bars = ctx.ax.barh(labels, top.values, color=colors, edgecolor=ctx.theme['bg'], linewidth=0.6, height=0.65)
    peak = float(top.max())
    for bar, value in zip(bars, top.values):
        share = f" ({value / total * 100:.0f}%)" if ctx.metric != 'average' and total else ''
        ctx.ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f" {fmt_value(ctx.metric, value)}{share}",
                    va='center', color=ctx.theme['text'], fontsize=8)
    ctx.ax.set_xlim(right=peak * 1.25)
    ctx.ax.set_xlabel(ctx.metric_label)
    thousands(ctx.ax, 'x')
    ctx.style()
    name, value = series.index[0], float(series.iloc[0])
    share = f" ({value / total * 100:.0f}% of the total)" if ctx.metric != 'average' and total else ''
    return _out(f"Top: {clean_text(name)} at {fmt_value(ctx.metric, value)}{share}, across {len(series)} groups.")


def render_column(ctx: Ctx) -> Dict:
    key = ctx.key
    series = aggregate(ctx.df, key, ctx.metric)
    series = series[series.index.notna()]
    _need(series, 1, "No data to chart for that grouping.")
    if key in TIME_KEYS:
        if key == 'hour':
            series = series.reindex(range(24), fill_value=0.0)
        elif key == 'weekday':
            series = series.reindex(DAY_ORDER, fill_value=0.0)
        else:
            series = series.sort_index()
            if len(series) > 40:
                series = series.tail(40)
    else:
        series = series[series != 0].sort_values(ascending=False).head(ctx.top_n)
        ctx.resize(len(series), 'v')
    labels = [clean_text(i, 14) if not hasattr(i, 'strftime') else i.strftime('%d %b') for i in series.index]
    peak_pos = int(np.argmax(series.values))
    colors = [ctx.theme['accent2'] if i == peak_pos else ctx.theme['accent'] for i in range(len(series))]
    ctx.ax.bar(range(len(series)), series.values, color=colors, edgecolor=ctx.theme['bg'], linewidth=0.5, width=0.78)
    ctx.ax.set_xticks(range(len(series)))
    ctx.ax.set_xticklabels([f"{l}:00" if key == 'hour' else l for l in labels], rotation=45 if len(series) > 8 else 0,
                           ha='right' if len(series) > 8 else 'center')
    mean_val = float(series.mean())
    ctx.ax.axhline(mean_val, color=ctx.theme['accent3'], linestyle='--', linewidth=1.2,
                   label=f"Average {fmt_value(ctx.metric, mean_val)}")
    if len(series) <= 14:
        for i, v in enumerate(series.values):
            if v > 0:
                ctx.ax.text(i, v, f"{v:,.0f}", ha='center', va='bottom', fontsize=8, color=ctx.theme['text'])
    ctx.ax.set_ylabel(ctx.metric_label)
    thousands(ctx.ax)
    ctx.ax.legend()
    ctx.style()
    peak_label = labels[peak_pos] + (':00' if key == 'hour' else '')
    return _out(f"Highest: {peak_label} at {fmt_value(ctx.metric, series.iloc[peak_pos])}; average "
                f"{fmt_value(ctx.metric, mean_val)} per {key.replace('merchant_', '')}.")


def render_lollipop(ctx: Ctx) -> Dict:
    series = aggregate(ctx.df, ctx.key, ctx.metric)
    series = series[series != 0].sort_values(ascending=False).head(ctx.top_n).iloc[::-1]
    _need(series, 1, "No data to chart for that grouping.")
    ctx.resize(len(series), 'h')
    y = np.arange(len(series))
    ctx.ax.hlines(y, 0, series.values, color=ctx.theme['muted'], linewidth=2, alpha=0.7)
    ctx.ax.scatter(series.values, y, s=110, color=ctx.theme['accent'], edgecolor=ctx.theme['bg'], zorder=3)
    ctx.ax.set_yticks(y)
    ctx.ax.set_yticklabels([clean_text(i, 34) for i in series.index.astype(str)])
    for yi, v in zip(y, series.values):
        ctx.ax.text(v, yi, f"   {fmt_value(ctx.metric, v)}", va='center', fontsize=8, color=ctx.theme['text'])
    ctx.ax.set_xlim(right=float(series.max()) * 1.22)
    ctx.ax.set_xlabel(ctx.metric_label)
    thousands(ctx.ax, 'x')
    ctx.style()
    return _out(f"Top: {clean_text(series.index[-1])} at {fmt_value(ctx.metric, series.iloc[-1])} of {len(series)} shown.")


def render_pareto(ctx: Ctx) -> Dict:
    series = aggregate(ctx.df, ctx.key, 'count' if ctx.metric == 'count' else ctx.metric)
    series = series[series > 0].sort_values(ascending=False)
    _need(series, 2, "Need at least two groups for a Pareto chart.")
    shown = series.head(max(ctx.top_n, 6))
    cum = series.cumsum() / series.sum() * 100
    ctx.resize(len(shown), 'v')
    x = np.arange(len(shown))
    ctx.ax.bar(x, shown.values, color=ctx.theme['accent'], edgecolor=ctx.theme['bg'], width=0.75)
    ctx.ax.set_xticks(x)
    ctx.ax.set_xticklabels([clean_text(i, 14) for i in shown.index.astype(str)], rotation=40, ha='right')
    ctx.ax.set_ylabel(ctx.metric_label)
    thousands(ctx.ax)
    twin = ctx.ax.twinx()
    twin.plot(x, cum.iloc[:len(shown)].values, color=ctx.theme['accent2'], marker='o', linewidth=2)
    twin.axhline(80, color=ctx.theme['accent3'], linestyle='--', linewidth=1)
    twin.set_ylim(0, 105)
    twin.set_ylabel('Cumulative share (%)', color=ctx.theme['text'])
    twin.tick_params(colors=ctx.theme['text'])
    twin.grid(False)
    ctx.style()
    n80 = int((cum < 80).sum()) + 1
    return _out(f"{n80} of {len(series)} groups make up 80% of the total; the biggest, {clean_text(series.index[0])}, "
                f"is {series.iloc[0] / series.sum() * 100:.0f}%.")


def render_cashflow(ctx: Ctx) -> Dict:
    df = ctx.df
    _need(df, 1)
    span = int((df['date'].max() - df['date'].min()).days) + 1
    rule = 'MS' if span > 70 else 'W-SUN'
    idx = df.set_index('timestamp')
    income = idx[idx['is_income']]['amount'].resample(rule).sum()
    spend = idx[idx['is_spend']]['amount'].resample(rule).sum()
    frame = pd.DataFrame({'Income': income, 'Spending': spend}).fillna(0.0)
    if rule == 'MS' and len(frame) > 18:
        frame = frame.tail(18)
    frame['Net'] = frame['Income'] - frame['Spending']
    _need(frame, 1)
    ctx.resize(len(frame), 'v')
    x = np.arange(len(frame))
    ctx.ax.bar(x - 0.2, frame['Income'], width=0.4, color=ctx.theme['good'], label='Money in')
    ctx.ax.bar(x + 0.2, frame['Spending'], width=0.4, color=ctx.theme['bad'], label='Money out')
    ctx.ax.plot(x, frame['Net'], color=ctx.theme['accent3'], marker='o', linewidth=2, label='Net')
    ctx.ax.axhline(0, color=ctx.theme['muted'], linewidth=0.8)
    fmt = '%b %y' if rule == 'MS' else '%d %b'
    ctx.ax.set_xticks(x)
    ctx.ax.set_xticklabels([d.strftime(fmt) for d in frame.index], rotation=45 if len(frame) > 8 else 0,
                           ha='right' if len(frame) > 8 else 'center')
    ctx.ax.set_ylabel('KES')
    thousands(ctx.ax)
    ctx.ax.legend(ncol=3)
    ctx.style()
    kept = float(frame['Net'].sum())
    best, worst = frame['Net'].idxmax(), frame['Net'].idxmin()
    unit = 'month' if rule == 'MS' else 'week'
    return _out(
        f"Money in {fmt_value('amount', frame['Income'].sum())}, money out {fmt_value('amount', frame['Spending'].sum())}: "
        f"net {'+' if kept >= 0 else '-'}{fmt_value('amount', abs(kept))} across {len(frame)} {unit}s.",
        f"Best {unit}: {best.strftime(fmt)} (net {frame['Net'].max():+,.0f}); weakest: {worst.strftime(fmt)} (net {frame['Net'].min():+,.0f}).")


def render_waterfall(ctx: Ctx) -> Dict:
    df = ctx.df
    income = float(df.loc[df['is_income'], 'amount'].sum())
    spend = df[df['is_spend']]
    _need(spend, 1, "No spending found for that period.")
    by_cat = spend.groupby('merchant_category')['amount'].sum().sort_values(ascending=False)
    top = by_cat.head(min(ctx.top_n, 7))
    rest = float(by_cat.iloc[len(top):].sum())
    fees = float(spend['transaction_cost'].sum())
    steps = [('Money in', income)] + [(clean_text(k, 14).title(), -float(v)) for k, v in top.items()]
    if rest > 0:
        steps.append(('Other', -rest))
    if fees > 0:
        steps.append(('M-Pesa fees', -fees))
    net = income + sum(v for _, v in steps[1:])
    ctx.resize(len(steps) + 1, 'v')
    running = 0.0
    for i, (name, value) in enumerate(steps):
        bottom = running if value >= 0 else running + value
        color = ctx.theme['good'] if value >= 0 else ctx.theme['bad']
        ctx.ax.bar(i, abs(value), bottom=bottom, color=color, edgecolor=ctx.theme['bg'], width=0.7)
        ctx.ax.text(i, bottom + abs(value), f"{value:+,.0f}", ha='center', va='bottom', fontsize=8, color=ctx.theme['text'])
        running += value
    i = len(steps)
    ctx.ax.bar(i, abs(net), bottom=min(0, net), color=ctx.theme['accent3'], edgecolor=ctx.theme['bg'], width=0.7)
    ctx.ax.text(i, max(net, 0), f"{net:+,.0f}", ha='center', va='bottom', fontsize=8, color=ctx.theme['text'])
    ctx.ax.set_xticks(range(len(steps) + 1))
    ctx.ax.set_xticklabels([s[0] for s in steps] + ['Left over'], rotation=40, ha='right')
    ctx.ax.axhline(0, color=ctx.theme['muted'], linewidth=0.8)
    ctx.ax.set_ylabel('KES')
    thousands(ctx.ax)
    ctx.style()
    return _out(f"Of {fmt_value('amount', income)} received, {clean_text(top.index[0])} took "
                f"{fmt_value('amount', top.iloc[0])}; you ended {'with ' + fmt_value('amount', net) + ' left' if net >= 0 else fmt_value('amount', -net) + ' short'}.")


def _pie_series(ctx: Ctx) -> pd.Series:
    key = ctx.key if ctx.key not in ('date', 'week', 'month', 'hour') else 'merchant_category'
    metric = 'amount' if ctx.metric == 'average' else ctx.metric
    series = aggregate(ctx.df, key, metric)
    series = _top_with_other(series, ctx.top_n)
    if series.empty:
        raise ChartError("No positive totals to chart for that grouping.")
    return series


def render_pie(ctx: Ctx, donut: bool = False) -> Dict:
    series = _pie_series(ctx)
    total = float(series.sum())
    colors = palette(len(series))
    wedge_kwargs = dict(edgecolor=ctx.theme['bg'], linewidth=1.2)
    if donut:
        wedge_kwargs['width'] = 0.42
    wedges, _t, autotexts = ctx.ax.pie(
        series.values, labels=None, colors=colors, startangle=90, counterclock=False, wedgeprops=wedge_kwargs,
        autopct=lambda p: f"{p:.0f}%" if p >= 4 else '', pctdistance=0.8 if donut else 0.72,
        textprops={'fontsize': 9})
    for wedge, text in zip(wedges, autotexts):
        r, g, b, _ = wedge.get_facecolor()
        text.set_color('#111111' if 0.299 * r + 0.587 * g + 0.114 * b > 0.6 else '#ffffff')
    if donut:
        ctx.ax.text(0, 0.08, fmt_value(ctx.metric, total), ha='center', va='center', fontsize=15 if ctx.standalone else 11,
                    fontweight='bold', color=ctx.theme['text'])
        ctx.ax.text(0, -0.14, 'total', ha='center', va='center', fontsize=9, color=ctx.theme['muted'])
    ctx.ax.legend(wedges, [f"{clean_text(k, 22)}  ({v / total * 100:.0f}%)" for k, v in series.items()],
                  loc='center left', bbox_to_anchor=(1.0, 0.5), frameon=False, labelcolor=ctx.theme['text'], fontsize=9)
    ctx.style(despine=False)
    return _out(f"{clean_text(series.index[0])} is the largest share at {fmt_value(ctx.metric, series.iloc[0])} "
                f"({series.iloc[0] / total * 100:.0f}%).")


def render_donut(ctx: Ctx) -> Dict:
    return render_pie(ctx, donut=True)


def _squarify(sizes: List[float], x: float, y: float, w: float, h: float) -> List[tuple]:
    rects: List[tuple] = []
    sizes = list(sizes)

    def worst(row: List[float], side: float) -> float:
        s = sum(row)
        return max(max(side * side * r / (s * s), (s * s) / (side * side * r)) for r in row)

    while sizes:
        side = min(w, h)
        row = [sizes[0]]
        i = 1
        while i < len(sizes) and worst(row + [sizes[i]], side) <= worst(row, side):
            row.append(sizes[i])
            i += 1
        sizes = sizes[i:]
        s = sum(row)
        if w >= h:
            col_w = s / h
            cy = y
            for r in row:
                rects.append((x, cy, col_w, r / col_w))
                cy += r / col_w
            x, w = x + col_w, w - col_w
        else:
            row_h = s / w
            cx = x
            for r in row:
                rects.append((cx, y, r / row_h, row_h))
                cx += r / row_h
            y, h = y + row_h, h - row_h
    return rects


def render_treemap(ctx: Ctx) -> Dict:
    series = _pie_series(ctx)
    series = series.sort_values(ascending=False)
    total = float(series.sum())
    W, H = 100.0, 60.0
    scaled = [float(v) / total * W * H for v in series.values]
    rects = _squarify(scaled, 0, 0, W, H)
    colors = palette(len(series))
    for (rx, ry, rw, rh), name, value, color in zip(rects, series.index, series.values, colors):
        ctx.ax.add_patch(Rectangle((rx, ry), rw, rh, facecolor=color, edgecolor=ctx.theme['bg'], linewidth=2))
        if rw * rh > 90:
            r, g, b = color[:3]
            ink = '#111111' if 0.299 * r + 0.587 * g + 0.114 * b > 0.6 else '#ffffff'
            ctx.ax.text(rx + rw / 2, ry + rh / 2, f"{clean_text(name, 18)}\n{fmt_value(ctx.metric, value)}\n{value / total * 100:.0f}%",
                        ha='center', va='center', fontsize=9 if rw * rh > 300 else 7, color=ink, fontweight='bold')
    ctx.ax.set_xlim(0, W)
    ctx.ax.set_ylim(H, 0)
    ctx.ax.axis('off')
    ctx.style(despine=False)
    return _out(f"{clean_text(series.index[0])} fills the largest block: {series.iloc[0] / total * 100:.0f}% of "
                f"{fmt_value(ctx.metric, total)}.")


def render_waffle(ctx: Ctx) -> Dict:
    series = _pie_series(ctx)
    total = float(series.sum())
    cells = np.floor(series / total * 100).astype(int)
    order = (series / total * 100 - cells).sort_values(ascending=False)
    for k in order.index[:100 - int(cells.sum())]:
        cells[k] += 1
    colors = palette(len(series))
    flat: List[Any] = []
    for color, k in zip(colors, series.index):
        flat += [color] * int(cells[k])
    flat = (flat + [(0.5, 0.5, 0.5)] * 100)[:100]
    for i, color in enumerate(flat):
        row, col = divmod(i, 10)
        ctx.ax.add_patch(Rectangle((col * 1.1, (9 - row) * 1.1), 1, 1, facecolor=color, edgecolor=ctx.theme['bg']))
    ctx.ax.set_xlim(0, 11)
    ctx.ax.set_ylim(0, 11)
    ctx.ax.set_aspect('equal')
    ctx.ax.axis('off')
    handles = [Rectangle((0, 0), 1, 1, facecolor=c) for c in colors]
    ctx.ax.legend(handles, [f"{clean_text(k, 22)} ({v / total * 100:.0f}%)" for k, v in series.items()],
                  loc='center left', bbox_to_anchor=(1.0, 0.5), frameon=False, labelcolor=ctx.theme['text'], fontsize=9)
    ctx.style(despine=False)
    return _out(f"Each square is 1% of {fmt_value(ctx.metric, total)}; {clean_text(series.index[0])} fills "
                f"{int(cells[series.index[0]])} of them.")


def render_radar(ctx: Ctx) -> Dict:
    series = aggregate(ctx.df, ctx.key, 'amount' if ctx.metric == 'average' else ctx.metric)
    if ctx.key == 'weekday':
        series = series.reindex(DAY_ORDER, fill_value=0.0)
    elif ctx.key == 'hour':
        series = series.groupby(series.index // 3 * 3).sum()
    else:
        series = series[series > 0].sort_values(ascending=False).head(max(min(ctx.top_n, 10), 3))
    if len(series) < 3:
        raise ChartError("Need at least three groups for a radar chart.")
    ax = ctx.new_fig(figsize=(8.5, 8), subplot_kw={'projection': 'polar'})
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)
    values = (series / series.sum() * 100).values
    angles = np.linspace(0, 2 * np.pi, len(series), endpoint=False)
    ax.plot(np.r_[angles, angles[0]], np.r_[values, values[0]], color=ctx.theme['accent'], linewidth=2)
    ax.fill(np.r_[angles, angles[0]], np.r_[values, values[0]], color=ctx.theme['accent'], alpha=0.25)
    ax.set_xticks(angles)
    labels = [f"{i}:00" if ctx.key == 'hour' else clean_text(i, 14) for i in series.index.astype(str)]
    ax.set_xticklabels(labels, color=ctx.theme['text'], fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.tick_params(axis='y', colors=ctx.theme['muted'], labelsize=7)
    ax.set_facecolor(ctx.theme['panel'])
    ax.grid(color=ctx.theme['grid'])
    ctx.style(ax, despine=False)
    top = series.idxmax()
    return _out(f"{clean_text(top)} takes the biggest slice ({values.max():.0f}% of the total).")


def render_stacked_bar(ctx: Ctx) -> Dict:
    key = ctx.key if ctx.key not in TIME_KEYS else 'merchant_category'
    pivot = ctx.df.pivot_table(values='amount' if ctx.metric == 'average' else ctx.metric, index=key, columns='weekday',
                               aggfunc='mean' if ctx.metric == 'average' else 'sum', fill_value=0)
    cols = [d for d in DAY_ORDER if d in pivot.columns]
    if not cols or pivot.empty or pivot.values.max() == 0:
        raise ChartError("Not enough data yet for a stacked breakdown.")
    pivot = pivot[cols]
    totals = pivot.sum(axis=1).sort_values(ascending=False)
    pivot = pivot.loc[totals.head(ctx.top_n).index[::-1]]
    ctx.resize(len(pivot.index), 'h')
    colors = sns.color_palette('viridis', n_colors=len(cols))
    left = np.zeros(len(pivot))
    labels = [clean_text(i, 30) for i in pivot.index.astype(str)]
    for day, color in zip(cols, colors):
        ctx.ax.barh(labels, pivot[day].values, left=left, color=color, label=day, edgecolor=ctx.theme['bg'], linewidth=0.4)
        left = left + pivot[day].values
    ctx.ax.set_xlabel(ctx.metric_label)
    thousands(ctx.ax, 'x')
    _legend_outside(ctx.ax, ctx.theme, 'Day')
    ctx.style()
    best_day = pivot.sum(axis=0).idxmax()
    return _out(f"{clean_text(totals.index[0])} leads at {fmt_value(ctx.metric, totals.iloc[0])}; {best_day} is the heaviest day overall.")


def _month_category_pivot(ctx: Ctx, top: int = 7) -> pd.DataFrame:
    spend = ctx.df
    cats = spend.groupby('merchant_category')['amount'].sum().sort_values(ascending=False)
    keep = list(cats.head(top).index)
    data = spend.assign(group=np.where(spend['merchant_category'].isin(keep), spend['merchant_category'], 'other'))
    span = int((data['date'].max() - data['date'].min()).days) + 1
    rule = 'MS' if span > 70 else 'W-SUN'
    pivot = data.set_index('timestamp').groupby([pd.Grouper(freq=rule), 'group'])['amount'].sum().unstack(fill_value=0.0)
    pivot.attrs['rule'] = rule
    return pivot


def render_monthly_stack(ctx: Ctx) -> Dict:
    _need(ctx.df, 1)
    pivot = _month_category_pivot(ctx)
    if len(pivot) > 18:
        pivot = pivot.tail(18)
    rule = pivot.attrs.get('rule', 'MS')
    ctx.resize(len(pivot), 'v')
    colors = palette(len(pivot.columns))
    bottom = np.zeros(len(pivot))
    for color, col in zip(colors, pivot.columns):
        ctx.ax.bar(range(len(pivot)), pivot[col].values, bottom=bottom, color=color, label=clean_text(col, 18),
                   edgecolor=ctx.theme['bg'], linewidth=0.4, width=0.78)
        bottom += pivot[col].values
    for i, total in enumerate(bottom):
        ctx.ax.text(i, total, f"{total:,.0f}", ha='center', va='bottom', fontsize=7, color=ctx.theme['text'])
    fmt = '%b %y' if rule == 'MS' else '%d %b'
    ctx.ax.set_xticks(range(len(pivot)))
    ctx.ax.set_xticklabels([d.strftime(fmt) for d in pivot.index], rotation=45, ha='right')
    ctx.ax.set_ylabel('KES')
    thousands(ctx.ax)
    _legend_outside(ctx.ax, ctx.theme)
    ctx.style()
    top_period = pivot.sum(axis=1).idxmax()
    return _out(f"Heaviest {'month' if rule == 'MS' else 'week'}: {top_period.strftime(fmt)} at {fmt_value('amount', pivot.sum(axis=1).max())}; "
                f"{clean_text(pivot.sum().idxmax())} is the biggest category overall.")


def render_stacked_area(ctx: Ctx) -> Dict:
    _need(ctx.df, 5, "Not enough transactions for a stacked area chart.")
    pivot = _month_category_pivot(ctx)
    if len(pivot) < 3:
        raise ChartError("Need at least three time periods for a stacked area chart.")
    colors = palette(len(pivot.columns))
    ctx.ax.stackplot(pivot.index, pivot.T.values, labels=[clean_text(c, 18) for c in pivot.columns], colors=colors, alpha=0.9)
    ctx.ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %y'))
    ctx.ax.set_ylabel('KES')
    thousands(ctx.ax)
    _legend_outside(ctx.ax, ctx.theme)
    ctx.fig.autofmt_xdate(rotation=45) if ctx.standalone else None
    ctx.style()
    return _out(f"{clean_text(pivot.sum().idxmax())} is the largest layer ({pivot.sum().max() / pivot.values.sum() * 100:.0f}% of all spending).")


def _positive(ctx: Ctx, minimum: int = 2) -> pd.Series:
    metric = 'amount' if ctx.metric in ('count', 'average') else ctx.metric
    values = ctx.df.loc[ctx.df[metric] > 0, metric]
    if len(values) < minimum:
        raise ChartError("Not enough positive amounts to build a distribution from.")
    return values


def _group_frame(ctx: Ctx, max_groups: int, min_samples: int):
    key = ctx.key if ctx.key not in ('date', 'week', 'month') else 'merchant_category'
    metric = 'amount' if ctx.metric in ('count', 'average') else ctx.metric
    totals = ctx.df.groupby(key)[metric].sum().sort_values(ascending=False)
    top_groups = totals.index[:max(int(max_groups), 1)]
    sub = ctx.df[ctx.df[key].isin(top_groups) & (ctx.df[metric] > 0)].copy()
    counts = sub[key].value_counts()
    sub = sub[sub[key].isin(counts[counts >= min_samples].index)]
    if sub.empty:
        raise ChartError("Not enough repeat transactions per group for a spread chart.")
    pretty = {'merchant_category': 'Category', 'recipient': 'Recipient', 'type': 'Type', 'weekday': 'Weekday', 'hour': 'Hour'}.get(key, 'Group')
    sub[pretty] = sub[key].astype(str).map(lambda v: clean_text(v, 16))
    order = sub.groupby(pretty)[metric].median().sort_values(ascending=False).index.tolist()
    return sub, pretty, metric, order


def render_histogram(ctx: Ctx) -> Dict:
    values = _positive(ctx)
    skew = _skewed(values)
    sns.histplot(values, bins=30, kde=True, ax=ctx.ax, color=ctx.theme['accent'], edgecolor=ctx.theme['bg'],
                 linewidth=0.6, log_scale=skew, line_kws={'color': ctx.theme['accent2'], 'linewidth': 2})
    mean_val, median_val = float(values.mean()), float(values.median())
    ctx.ax.axvline(mean_val, color=ctx.theme['accent2'], linestyle='--', linewidth=1.5, label=f"Average KES {mean_val:,.0f}")
    ctx.ax.axvline(median_val, color=ctx.theme['accent3'], linestyle=':', linewidth=1.8, label=f"Median KES {median_val:,.0f}")
    ctx.ax.set_xlabel(f"{ctx.metric_label}" + (' (log scale)' if skew else ''))
    ctx.ax.set_ylabel('Number of transactions')
    if skew:
        _log_ticks(ctx.ax, 'x')
    ctx.ax.legend()
    ctx.style()
    return _out(f"Average KES {mean_val:,.0f}, median KES {median_val:,.0f}, across {len(values)} transactions"
                + ("; a few large payments pull the average well above the typical one." if mean_val > 2 * median_val else "."))


def render_kde(ctx: Ctx) -> Dict:
    values = _positive(ctx, 5)
    if ctx.spec.get('group_by') in (None, 'date', 'week', 'month', 'weekday', 'hour'):
        sns.kdeplot(x=values, ax=ctx.ax, fill=True, color=ctx.theme['accent'], log_scale=True, linewidth=2, alpha=0.4)
        hue_note = ''
    else:
        sub, label, metric, order = _group_frame(ctx, 5, 8)
        sns.kdeplot(data=sub, x=metric, hue=label, hue_order=order, fill=True, common_norm=False, log_scale=True,
                    ax=ctx.ax, palette=palette(len(order)), alpha=0.28, linewidth=1.8, warn_singular=False)
        hue_note = f" compared across {len(order)} groups"
    ctx.ax.set_xlabel(f"{ctx.metric_label} (log scale)")
    ctx.ax.set_ylabel('Density')
    _log_ticks(ctx.ax, 'x')
    ctx.style()
    mode = float(np.exp(np.log(values).median()))
    return _out(f"Most payments cluster around KES {mode:,.0f} (typical size on a log scale){hue_note}.")


def render_ecdf(ctx: Ctx) -> Dict:
    values = _positive(ctx, 5)
    if ctx.spec.get('group_by') in (None, 'date', 'week', 'month', 'weekday', 'hour'):
        sns.ecdfplot(x=values, ax=ctx.ax, color=ctx.theme['accent'], linewidth=2.4, log_scale=True)
    else:
        sub, label, metric, order = _group_frame(ctx, 6, 8)
        sns.ecdfplot(data=sub, x=metric, hue=label, hue_order=order, ax=ctx.ax, palette=palette(len(order)),
                     linewidth=2, log_scale=True)
    p50, p80, p95 = (float(values.quantile(q)) for q in (0.5, 0.8, 0.95))
    for q, v, color in ((0.5, p50, ctx.theme['accent3']), (0.8, p80, ctx.theme['accent2'])):
        ctx.ax.axvline(v, color=color, linestyle=':', linewidth=1.2)
        ctx.ax.text(v, q, f" {int(q * 100)}% under KES {v:,.0f}", color=color, fontsize=8, va='bottom')
    ctx.ax.set_xlabel(f"{ctx.metric_label} (log scale)")
    ctx.ax.set_ylabel('Share of transactions at or below')
    ctx.ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    _log_ticks(ctx.ax, 'x')
    ctx.style()
    return _out(f"Half of your payments are under KES {p50:,.0f}, 80% under KES {p80:,.0f}, 95% under KES {p95:,.0f}.")


def _spread_chart(ctx: Ctx, kind: str) -> Dict:
    min_samples = 3 if kind in ('violin', 'strip', 'swarm') else 2
    sub, label, metric, order = _group_frame(ctx, 8 if kind in ('violin', 'swarm') else 12, min_samples)
    if kind == 'swarm' and len(sub) > 700:
        sub = sub.groupby(label, group_keys=False).apply(lambda g: g.sample(min(len(g), 90), random_state=1))
    ctx.resize(len(order), 'v')
    skew = _skewed(sub[metric])
    pal = sns.color_palette('viridis', n_colors=len(order))
    common = dict(data=sub, x=label, y=metric, order=order, ax=ctx.ax)
    if kind == 'box':
        sns.boxplot(**common, hue=label, hue_order=order, legend=False, palette=pal, linewidth=1.1, fliersize=2.5,
                    flierprops={'markerfacecolor': ctx.theme['accent2'], 'markeredgecolor': 'none'})
    elif kind == 'boxen':
        sns.boxenplot(**common, hue=label, hue_order=order, legend=False, palette=pal, saturation=0.9,
                      line_kws={'color': ctx.theme['text'], 'linewidth': 1})
    elif kind == 'violin':
        sub = sub.assign(_log=np.log10(sub[metric]))
        sns.violinplot(data=sub, x=label, y='_log', order=order, hue=label, hue_order=order, legend=False, ax=ctx.ax,
                       palette=pal, inner='quartile', cut=0, density_norm='width', linewidth=1, linecolor=ctx.theme['bg'])
        ctx.ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{10 ** v:,.0f}"))
        skew = False
    elif kind == 'strip':
        sns.stripplot(**common, hue=label, hue_order=order, legend=False, palette=pal, size=4, alpha=0.7, jitter=0.28)
    else:
        sns.swarmplot(**common, hue=label, hue_order=order, legend=False, palette=pal, size=3.6, warn_thresh=1.0)
    if skew and kind != 'violin':
        ctx.ax.set_yscale('log')
        _log_ticks(ctx.ax)
    elif kind != 'violin':
        thousands(ctx.ax)
    ctx.ax.set_xlabel('')
    ctx.ax.set_ylabel(ctx.metric_label + (' (log scale)' if skew or kind == 'violin' else ''))
    plt.setp(ctx.ax.get_xticklabels(), rotation=35, ha='right')
    ctx.style()
    spread = sub.groupby(label)[metric].std().idxmax()
    return _out(f"{len(order)} groups compared; {spread} shows the widest spread in {ctx.metric_label.split(' (')[0].lower()}.")


def render_box(ctx: Ctx) -> Dict:
    return _spread_chart(ctx, 'box')


def render_boxen(ctx: Ctx) -> Dict:
    return _spread_chart(ctx, 'boxen')


def render_violin(ctx: Ctx) -> Dict:
    return _spread_chart(ctx, 'violin')


def render_strip(ctx: Ctx) -> Dict:
    return _spread_chart(ctx, 'strip')


def render_swarm(ctx: Ctx) -> Dict:
    return _spread_chart(ctx, 'swarm')


def render_ridge(ctx: Ctx) -> Dict:
    sub, label, metric, order = _group_frame(ctx, 7, 12)
    n = len(order)
    if n < 2:
        raise ChartError("Need at least two groups with enough repeat payments for a ridge plot.")
    if ctx.fig is not None:
        plt.close(ctx.fig)
    fig, axes = plt.subplots(n, 1, figsize=(10.5, max(5.5, 1.0 * n + 2)), sharex=True)
    ctx.fig, ctx.ax = fig, axes[0]
    colors = palette(n)
    lo, hi = float(sub[metric].min()), float(sub[metric].max())
    for ax, name, color in zip(axes, order, colors):
        data = sub.loc[sub[label] == name, metric]
        sns.kdeplot(x=data, ax=ax, fill=True, color=color, alpha=0.75, linewidth=1.4, log_scale=True,
                    bw_adjust=0.9, warn_singular=False)
        ax.set_facecolor('none')
        ax.set_yticks([])
        ax.set_ylabel(clean_text(name, 16), rotation=0, ha='right', va='center', color=ctx.theme['text'], fontsize=9)
        ax.axvline(float(data.median()), color=ctx.theme['text'], linewidth=0.8, linestyle=':')
        for side in ('top', 'right', 'left'):
            ax.spines[side].set_visible(False)
        ax.grid(False)
        if ax is not axes[-1]:
            ax.set_xlabel('')
            ax.tick_params(axis='x', length=0, labelbottom=False)
    axes[-1].set_xlim(lo * 0.7, hi * 1.5)
    axes[-1].set_xlabel(f"{ctx.metric_label} (log scale)")
    _log_ticks(axes[-1], 'x')
    fig.subplots_adjust(hspace=-0.35, left=0.18)
    fig.suptitle(ctx.title, fontsize=14, fontweight='bold', color=ctx.theme['text'])
    medians = sub.groupby(label)[metric].median()
    return _out(f"{clean_text(medians.idxmax())} has the highest typical payment (median KES {medians.max():,.0f}); "
                f"{clean_text(medians.idxmin())} the lowest (KES {medians.min():,.0f}).")


def render_scatter(ctx: Ctx) -> Dict:
    key = ctx.key if ctx.key not in ('date', 'week', 'month', 'weekday', 'hour') else 'recipient'
    metric = 'amount' if ctx.metric in ('average', 'count') else ctx.metric
    grouped = ctx.df.groupby(key).agg(total=(metric, 'sum'), tx_count=('amount', 'size')).reset_index()
    grouped = grouped[grouped['total'] != 0]
    _need(grouped, 2, "Not enough groups to plot.")
    sns.scatterplot(data=grouped, x='tx_count', y='total', hue='total', size='total', palette='viridis',
                    sizes=(60, 300), edgecolor=ctx.theme['bg'], linewidth=0.8, alpha=0.9, ax=ctx.ax, legend=False)
    if _skewed(grouped['total']):
        ctx.ax.set_yscale('log')
        _log_ticks(ctx.ax)
    for _, row in grouped.nlargest(min(8, len(grouped)), 'total').iterrows():
        ctx.ax.annotate(clean_text(row[key], 18), (row['tx_count'], row['total']), color=ctx.theme['text'], fontsize=8,
                        xytext=(5, 5), textcoords='offset points')
    ctx.ax.set_xlabel('Number of transactions')
    ctx.ax.set_ylabel(f"Total {ctx.metric_label}")
    ctx.style()
    return _out(f"{len(grouped)} {key.replace('_', ' ')} groups plotted by count versus total.")


def render_bubble(ctx: Ctx) -> Dict:
    key = ctx.key if ctx.key not in ('date', 'week', 'month', 'weekday', 'hour') else 'merchant_category'
    grouped = ctx.df.groupby(key).agg(total=('amount', 'sum'), n=('amount', 'size'), avg=('amount', 'mean')).reset_index()
    grouped = grouped[grouped['total'] > 0].nlargest(max(ctx.top_n, 6), 'total')
    _need(grouped, 2, "Not enough groups for a bubble chart.")
    sizes = 200 + grouped['total'] / grouped['total'].max() * 2600
    colors = palette(len(grouped))
    ctx.ax.scatter(grouped['n'], grouped['avg'], s=sizes, c=colors, alpha=0.78, edgecolor=ctx.theme['bg'], linewidth=1.2)
    for _, row in grouped.iterrows():
        ctx.ax.annotate(clean_text(row[key], 16), (row['n'], row['avg']), ha='center', va='center', fontsize=8,
                        color=ctx.theme['text'])
    if _skewed(grouped['avg']) or grouped['avg'].max() / max(grouped['avg'].min(), 1) > 30:
        ctx.ax.set_yscale('log')
        _log_ticks(ctx.ax)
    ctx.ax.set_xscale('log' if grouped['n'].max() / max(grouped['n'].min(), 1) > 30 else 'linear')
    ctx.ax.set_xlabel('How often (transactions)')
    ctx.ax.set_ylabel('Typical size (average KES)')
    ctx.style()
    big = grouped.iloc[0]
    return _out(f"Bubble size is total spend: {clean_text(big[key])} is biggest at KES {big['total']:,.0f} "
                f"({int(big['n'])} payments averaging KES {big['avg']:,.0f}).")


def render_regression(ctx: Ctx) -> Dict:
    daily = ctx.df.groupby('date').agg(spend=('amount', 'sum'), n=('amount', 'size'))
    daily = daily[daily['n'] > 0]
    _need(daily, 8, "Need at least 8 active days for a regression.")
    x, y = daily['n'].astype(float), daily['spend'].astype(float)
    sns.regplot(x=x, y=y, ax=ctx.ax, n_boot=300, ci=90, scatter_kws={'alpha': 0.55, 's': 28, 'color': ctx.theme['accent']},
                line_kws={'color': ctx.theme['accent2'], 'linewidth': 2.4})
    r = float(np.corrcoef(x, y)[0, 1]) if x.std() > 0 and y.std() > 0 else 0.0
    slope = float(np.polyfit(x, y, 1)[0]) if x.std() > 0 else 0.0
    ctx.ax.set_xlabel('Payments made that day')
    ctx.ax.set_ylabel('Spent that day (KES)')
    thousands(ctx.ax)
    ctx.ax.text(0.02, 0.95, f"R² = {r * r:.2f}\n~KES {slope:,.0f} per extra payment", transform=ctx.ax.transAxes,
                va='top', fontsize=9, color=ctx.theme['text'])
    ctx.style()
    strength = 'strongly' if r * r > 0.5 else 'moderately' if r * r > 0.2 else 'weakly'
    return _out(f"Daily spending is {strength} tied to how many payments you make (R² {r * r:.2f}); each extra payment adds about KES {slope:,.0f}.")


def _amount_hour(df: pd.DataFrame) -> pd.DataFrame:
    positive = df[df['amount'] > 0]
    rng = np.random.default_rng(7)
    return pd.DataFrame({
        'hour': positive['timestamp'].dt.hour + positive['timestamp'].dt.minute / 60.0 + rng.uniform(-0.02, 0.02, len(positive)),
        'log_amount': np.log10(positive['amount'].values),
    })


def render_hexbin(ctx: Ctx) -> Dict:
    _need(ctx.df, 30, "Need at least 30 transactions for a hexbin chart.")
    data = _amount_hour(ctx.df)
    hb = ctx.ax.hexbin(data['hour'], data['log_amount'], gridsize=(24, 16), cmap='viridis', mincnt=1,
                       linewidths=0.2, edgecolors=ctx.theme['bg'])
    cbar = ctx.fig.colorbar(hb, ax=ctx.ax)
    cbar.set_label('Transactions', color=ctx.theme['text'])
    cbar.ax.yaxis.set_tick_params(color=ctx.theme['text'])
    plt.setp(cbar.ax.get_yticklabels(), color=ctx.theme['text'])
    ctx.ax.set_xticks(range(0, 25, 3))
    ctx.ax.set_xlim(0, 24)
    ctx.ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{10 ** v:,.0f}"))
    ctx.ax.set_xlabel('Hour of day')
    ctx.ax.set_ylabel('Amount (KES, log scale)')
    ctx.style()
    busiest = int(np.floor(data['hour']).mode().iat[0])
    return _out(f"Payments cluster at {busiest}:00; darker hexagons show where most transactions land by hour and size.")


def render_joint(ctx: Ctx) -> Dict:
    _need(ctx.df, 30, "Need at least 30 transactions for a joint plot.")
    data = _amount_hour(ctx.df)
    with sns.axes_style('darkgrid' if ctx.theme['name'] == 'dark' else 'whitegrid', rc=seaborn_rc(ctx.theme)):
        g = sns.JointGrid(data=data, x='hour', y='log_amount', height=7.5, ratio=5, space=0.15)
        g.plot_joint(sns.histplot, bins=(24, 22), cmap='viridis', cbar=False, thresh=0)
        g.plot_marginals(sns.histplot, bins=24, kde=True, color=ctx.theme['accent'], edgecolor=ctx.theme['bg'])
    g.ax_joint.set_xlim(0, 24)
    g.ax_joint.set_xticks(range(0, 25, 3))
    g.ax_joint.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{10 ** v:,.0f}"))
    g.ax_joint.set_xlabel('Hour of day')
    g.ax_joint.set_ylabel('Amount (KES, log scale)')
    g.figure.suptitle(ctx.title, y=1.02, fontsize=14, fontweight='bold', color=ctx.theme['text'])
    ctx.adopt(g.figure, g.ax_joint)
    peak = int(np.floor(data['hour']).mode().iat[0])
    return _out(f"Edge histograms show the hour and size distributions separately; the busiest hour is {peak}:00.")


def render_pair(ctx: Ctx) -> Dict:
    _need(ctx.df, 40, "Need at least 40 transactions for a pair plot.")
    sample = ctx.df[ctx.df['amount'] > 0].copy()
    if len(sample) > 700:
        sample = sample.sample(700, random_state=3)
    top = sample['merchant_category'].value_counts().head(5).index
    sample['category'] = np.where(sample['merchant_category'].isin(top), sample['merchant_category'], 'other')
    sample['log10 amount'] = np.log10(sample['amount'])
    sample['hour of day'] = sample['hour']
    sample['weekday no.'] = sample['dow']
    sample['fee (KES)'] = sample['transaction_cost']
    cols = ['log10 amount', 'hour of day', 'weekday no.']
    if sample['fee (KES)'].nunique() > 2:
        cols.append('fee (KES)')
    order = sample['category'].value_counts().index.tolist()
    with sns.axes_style('darkgrid' if ctx.theme['name'] == 'dark' else 'whitegrid', rc=seaborn_rc(ctx.theme)):
        g = sns.pairplot(sample, vars=cols, hue='category', hue_order=order, palette=palette(len(order)), corner=True,
                         diag_kind='hist', height=2.1, plot_kws={'alpha': 0.55, 's': 16, 'edgecolor': 'none'},
                         diag_kws={'alpha': 0.7})
    if g._legend is not None:
        g._legend.set_title('Category')
    g.figure.suptitle(ctx.title, y=1.02, fontsize=14, fontweight='bold', color=ctx.theme['text'])
    ctx.adopt(g.figure)
    corr = sample[cols].corr().abs().where(~np.eye(len(cols), dtype=bool)).stack().sort_values(ascending=False)
    pair = corr.index[0]
    return _out(f"Every pair of {len(cols)} features at once; the strongest link is {pair[0]} with {pair[1]} (|r| = {corr.iloc[0]:.2f}).")


def render_correlation(ctx: Ctx) -> Dict:
    spend = ctx.df
    top = spend.groupby('merchant_category')['amount'].sum().sort_values(ascending=False).head(8).index
    daily = spend[spend['merchant_category'].isin(top)].pivot_table(
        index='date', columns='merchant_category', values='amount', aggfunc='sum', fill_value=0.0)
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max(), freq='D'), fill_value=0.0)
    daily = daily.loc[:, daily.std() > 0]
    if daily.shape[1] < 3 or len(daily) < 14:
        raise ChartError("Need at least 3 categories and 14 days of data for a correlation chart.")
    corr = daily.corr()
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)
    sns.heatmap(corr, mask=mask, ax=ctx.ax, cmap='vlag', center=0, vmin=-1, vmax=1, annot=True, fmt='.2f',
                annot_kws={'fontsize': 8}, linewidths=1, linecolor=ctx.theme['bg'], cbar_kws={'label': 'Correlation'})
    cbar = ctx.ax.collections[0].colorbar
    cbar.ax.yaxis.set_tick_params(color=ctx.theme['text'])
    plt.setp(cbar.ax.get_yticklabels(), color=ctx.theme['text'])
    cbar.ax.yaxis.label.set_color(ctx.theme['text'])
    ctx.ax.set_xlabel('')
    ctx.ax.set_ylabel('')
    plt.setp(ctx.ax.get_xticklabels(), rotation=40, ha='right')
    ctx.style(despine=False)
    pairs = corr.where(~np.eye(len(corr), dtype=bool)).stack()
    pairs = pairs[[a < b for a, b in pairs.index]].sort_values(ascending=False)
    a, b = pairs.index[0]
    return _out(f"{clean_text(a)} and {clean_text(b)} tend to rise on the same days (correlation {pairs.iloc[0]:.2f}).")


def render_cluster(ctx: Ctx) -> Dict:
    pivot = ctx.df.pivot_table(values='amount', index='merchant_category', columns='weekday', aggfunc='sum', fill_value=0)
    cols = [d for d in DAY_ORDER if d in pivot.columns]
    pivot = pivot[cols]
    pivot = pivot[pivot.sum(axis=1) > 0]
    if len(pivot) < 3 or len(cols) < 3:
        raise ChartError("Need at least 3 categories and 3 weekdays for a cluster map.")
    share = pivot.div(pivot.sum(axis=1), axis=0)
    with sns.axes_style('darkgrid' if ctx.theme['name'] == 'dark' else 'whitegrid', rc=seaborn_rc(ctx.theme)):
        g = sns.clustermap(share, cmap=ctx.theme['heat'], linewidths=1, linecolor=ctx.theme['bg'], figsize=(9.5, 7.5),
                           col_cluster=False, dendrogram_ratio=(0.16, 0.02), cbar_pos=(0.02, 0.86, 0.025, 0.12),
                           cbar_kws={'label': 'Share of category'})
    g.figure.set_facecolor(ctx.theme['bg'])
    for line in g.ax_row_dendrogram.collections:
        line.set_color(ctx.theme['muted'])
    plt.setp(g.ax_heatmap.get_xticklabels(), rotation=40, ha='right', color=ctx.theme['text'])
    plt.setp(g.ax_heatmap.get_yticklabels(), rotation=0, color=ctx.theme['text'])
    g.ax_heatmap.set_xlabel('')
    g.ax_heatmap.set_ylabel('')
    plt.setp(g.ax_cbar.get_yticklabels(), color=ctx.theme['text'])
    g.ax_cbar.yaxis.label.set_color(ctx.theme['text'])
    g.figure.suptitle(ctx.title, y=1.0, fontsize=14, fontweight='bold', color=ctx.theme['text'])
    ctx.adopt(g.figure, g.ax_heatmap)
    return _out("Categories with similar weekday habits are grouped together; brighter cells are the days each category is usually paid.")


def _series_for_time(ctx: Ctx):
    df = ctx.df
    _need(df, 2, "Not enough transactions for a time chart.")
    span = int((df['date'].max() - df['date'].min()).days) + 1
    return span


def render_line(ctx: Ctx, area: bool = False) -> Dict:
    span = _series_for_time(ctx)
    key = ctx.spec.get('group_by')
    metric = ctx.metric
    if key in ('weekday', 'hour'):
        return render_column(ctx)
    if key in ('merchant_category', 'recipient', 'type'):
        rule = _bucket(span)
        top = ctx.df.groupby(key)['amount'].sum().sort_values(ascending=False).head(min(ctx.top_n, 6)).index
        sub = ctx.df[ctx.df[key].isin(top)].copy()
        sub['bucket'] = sub['timestamp'].dt.to_period(rule.split('-')[0] if rule != 'W-SUN' else 'W-SUN').dt.start_time
        value = 'amount' if metric == 'average' else metric
        agg = 'mean' if metric == 'average' else ('size' if metric == 'count' else 'sum')
        long = sub.groupby(['bucket', key])[value].agg(agg).unstack(fill_value=0.0)
        if rule != 'D':
            long = long.reindex(pd.date_range(long.index.min(), long.index.max(), freq='W-MON' if rule == 'W-SUN' else 'MS'), fill_value=0.0)
        long = long.stack().rename('value').reset_index()
        long.columns = ['bucket', key, 'value']
        long[key] = long[key].map(lambda v: clean_text(v, 18))
        sns.lineplot(data=long, x='bucket', y='value', hue=key, ax=ctx.ax, palette=palette(long[key].nunique()),
                     linewidth=2, marker='o' if len(long) < 80 else None)
        _legend_outside(ctx.ax, ctx.theme)
        ctx.ax.set_ylabel(f"{ctx.metric_label} per {_bucket_label(rule)}")
        leader = long.groupby(key)['value'].sum().idxmax()
        summary = f"{clean_text(leader)} leads across {long[key].nunique()} groups, shown per {_bucket_label(rule)}."
    else:
        daily = _daily(ctx.df, metric)
        rule = 'D'
        if key == 'week':
            daily = daily.resample('W-SUN').sum() if metric != 'average' else daily.resample('W-SUN').mean()
            rule = 'W-SUN'
        elif key == 'month':
            daily = daily.resample('MS').sum() if metric != 'average' else daily.resample('MS').mean()
            rule = 'MS'
        color = ctx.theme['accent2']
        ctx.ax.plot(daily.index, daily.values, color=color, linewidth=2.0, marker='o' if len(daily) <= 60 else None, markersize=4)
        if area:
            ctx.ax.fill_between(daily.index, daily.values, color=color, alpha=0.18)
        if rule == 'D' and len(daily) >= 14:
            ma = daily.rolling(7, min_periods=3).mean()
            ctx.ax.plot(daily.index, ma.values, color=ctx.theme['accent3'], linewidth=1.8, linestyle='-', alpha=0.9, label='7-day average')
        avg = float(daily.mean())
        unit = {'D': 'day', 'W-SUN': 'week', 'MS': 'month'}[rule]
        ctx.ax.axhline(avg, color=ctx.theme['accent'], linestyle='--', linewidth=1.2,
                       label=f"Average {fmt_value(metric, avg)}/{unit} (incl. quiet {unit}s)")
        peak_idx = daily.idxmax()
        ctx.ax.annotate(f"Peak {fmt_value(metric, daily.max())}\n{peak_idx.strftime('%d %b %Y')}", (peak_idx, daily.max()),
                        xytext=(12, -6), textcoords='offset points', fontsize=8, color=ctx.theme['text'],
                        arrowprops={'arrowstyle': '-', 'color': ctx.theme['muted']})
        ctx.ax.legend(loc='upper left')
        ctx.ax.set_ylabel(f"{ctx.metric_label}")
        summary = (f"Peak: {peak_idx.strftime('%d %b %Y')} at {fmt_value(metric, daily.max())}. "
                   f"Average {fmt_value(metric, avg)} per {unit} across {len(daily)} {unit}s (quiet {unit}s included).")
    ctx.ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b' if span <= 400 else '%b %y'))
    ctx.ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
    if ctx.standalone:
        ctx.fig.autofmt_xdate(rotation=45)
    ctx.ax.set_xlabel('')
    thousands(ctx.ax)
    ctx.style()
    return _out(summary)


def render_area(ctx: Ctx) -> Dict:
    return render_line(ctx, area=True)


def render_rolling(ctx: Ctx) -> Dict:
    _series_for_time(ctx)
    daily = _daily(ctx.df, ctx.metric if ctx.metric != 'average' else 'amount')
    if len(daily) < 14:
        raise ChartError("Need at least 14 days of data for a rolling average.")
    ma7, ma30 = daily.rolling(7, min_periods=4).mean(), daily.rolling(30, min_periods=10).mean()
    sd30 = daily.rolling(30, min_periods=10).std()
    ctx.ax.bar(daily.index, daily.values, color=ctx.theme['muted'], alpha=0.35, width=0.9, label='Daily')
    ctx.ax.plot(ma7.index, ma7.values, color=ctx.theme['accent3'], linewidth=2, label='7-day average')
    ctx.ax.plot(ma30.index, ma30.values, color=ctx.theme['accent'], linewidth=2.6, label='30-day average')
    ctx.ax.fill_between(ma30.index, (ma30 - sd30).clip(lower=0), ma30 + sd30, color=ctx.theme['accent'], alpha=0.12, label='±1 std dev (30d)')
    spikes = daily[daily > daily.quantile(0.985)].nlargest(4)
    for day, value in spikes.items():
        ctx.ax.annotate(f"{value:,.0f}", (day, value), xytext=(0, 6), textcoords='offset points', ha='center', fontsize=8,
                        color=ctx.theme['accent2'])
    if daily.max() > 12 * max(float(daily.median()), 1.0):
        ctx.ax.set_ylim(0, float(daily.quantile(0.995)) * 1.35)
    ctx.ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %y'))
    ctx.ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
    ctx.ax.set_ylabel(ctx.metric_label)
    thousands(ctx.ax)
    ctx.ax.legend(loc='upper left', ncol=2)
    if ctx.standalone:
        ctx.fig.autofmt_xdate(rotation=45)
    ctx.style()
    now, before = float(ma30.dropna().iloc[-1]), float(ma30.dropna().iloc[max(-len(ma30.dropna()), -31)])
    change = (now - before) / before * 100 if before > 0 else 0.0
    return _out(f"30-day average is KES {now:,.0f}/day, {'up' if change >= 0 else 'down'} {abs(change):.0f}% from a month earlier; "
                f"spikes are the labelled days.")


def render_cumulative(ctx: Ctx) -> Dict:
    df = ctx.df
    _need(df, 2, "Not enough transactions for a cumulative chart.")
    days = pd.date_range(df['date'].min(), df['date'].max(), freq='D')
    spend = df[df['is_spend']].groupby('date')['amount'].sum().reindex(days, fill_value=0.0).cumsum()
    income = df[df['is_income']].groupby('date')['amount'].sum().reindex(days, fill_value=0.0).cumsum()
    ctx.ax.plot(days, income.values, color=ctx.theme['good'], linewidth=2.4, label='Money in')
    ctx.ax.plot(days, spend.values, color=ctx.theme['bad'], linewidth=2.4, label='Money out')
    ctx.ax.fill_between(days, income.values, spend.values, where=income.values >= spend.values, color=ctx.theme['good'], alpha=0.14)
    ctx.ax.fill_between(days, income.values, spend.values, where=income.values < spend.values, color=ctx.theme['bad'], alpha=0.18)
    ctx.ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %y'))
    ctx.ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
    ctx.ax.set_ylabel('Cumulative KES')
    thousands(ctx.ax)
    ctx.ax.legend(loc='upper left')
    if ctx.standalone:
        ctx.fig.autofmt_xdate(rotation=45)
    ctx.style()
    gap = float(income.iloc[-1] - spend.iloc[-1])
    return _out(f"Running totals: {fmt_value('amount', income.iloc[-1])} in versus {fmt_value('amount', spend.iloc[-1])} out; "
                f"you are {'ahead by ' if gap >= 0 else 'behind by '}{fmt_value('amount', abs(gap))}.")


def render_calendar(ctx: Ctx) -> Dict:
    df = ctx.df
    _need(df, 5, "Not enough transactions for a calendar chart.")
    daily = _daily(df, ctx.metric if ctx.metric != 'average' else 'amount')
    end = daily.index.max()
    start = max(daily.index.min(), end - pd.Timedelta(weeks=52))
    start = start - pd.Timedelta(days=int(start.dayofweek))
    full = daily.reindex(pd.date_range(start, end, freq='D'), fill_value=0.0)
    weeks = (np.arange(len(full)) // 7)
    grid = np.full((7, weeks.max() + 1), np.nan)
    for i, v in enumerate(full.values):
        grid[i % 7, i // 7] = v
    if ctx.standalone:
        ctx.fig.set_size_inches(14.0, 4.4, forward=True)
    positive = full[full > 0]
    norm = PowerNorm(0.5, vmin=0, vmax=float(positive.quantile(0.98)) if len(positive) else 1.0)
    sns.heatmap(grid, ax=ctx.ax, cmap=ctx.theme['heat'], norm=norm, linewidths=1.5, linecolor=ctx.theme['bg'],
                square=False, cbar_kws={'label': ctx.metric_label, 'shrink': 0.8})
    cbar = ctx.ax.collections[0].colorbar
    cbar.ax.yaxis.set_tick_params(color=ctx.theme['text'])
    plt.setp(cbar.ax.get_yticklabels(), color=ctx.theme['text'])
    cbar.ax.yaxis.label.set_color(ctx.theme['text'])
    ctx.ax.set_yticks(np.arange(7) + 0.5)
    ctx.ax.set_yticklabels([d[:3] for d in DAY_ORDER], rotation=0)
    ticks, labels, last_month = [], [], None
    for w in range(grid.shape[1]):
        month = (start + pd.Timedelta(weeks=w)).strftime('%b')
        if month != last_month:
            ticks.append(w + 0.5)
            labels.append(month)
            last_month = month
    ctx.ax.set_xticks(ticks)
    ctx.ax.set_xticklabels(labels, rotation=0)
    ctx.ax.set_xlabel('')
    ctx.ax.set_ylabel('')
    ctx.style(despine=False)
    busiest = full.idxmax()
    active = int((full > 0).sum())
    return _out(f"Busiest day: {busiest.strftime('%a %d %b %Y')} at {fmt_value(ctx.metric, full.max())}; "
                f"you transacted on {active} of {len(full)} days shown.")


def render_hour_heatmap(ctx: Ctx) -> Dict:
    df = ctx.df
    _need(df, 10, "Not enough transactions for an hour-by-weekday heatmap.")
    metric = 'amount' if ctx.metric == 'average' else ctx.metric
    if ctx.metric == 'count':
        pivot = df.pivot_table(index='weekday', columns='hour', values='amount', aggfunc='size', fill_value=0)
    else:
        pivot = df.pivot_table(index='weekday', columns='hour', values=metric, aggfunc='sum', fill_value=0)
    pivot = pivot.reindex(index=DAY_ORDER, columns=range(24), fill_value=0)
    norm = PowerNorm(0.5, vmin=0, vmax=max(float(pivot.values.max()), 1.0))
    sns.heatmap(pivot, ax=ctx.ax, cmap=ctx.theme['heat'], norm=norm, linewidths=0.8, linecolor=ctx.theme['bg'],
                cbar_kws={'label': ctx.metric_label})
    cbar = ctx.ax.collections[0].colorbar
    cbar.ax.yaxis.set_tick_params(color=ctx.theme['text'])
    plt.setp(cbar.ax.get_yticklabels(), color=ctx.theme['text'])
    cbar.ax.yaxis.label.set_color(ctx.theme['text'])
    ctx.ax.set_xticks(np.arange(24) + 0.5)
    ctx.ax.set_xticklabels([str(h) if (ctx.standalone or h % 3 == 0) else '' for h in range(24)], rotation=0, fontsize=8)
    ctx.ax.set_yticks(np.arange(7) + 0.5)
    ctx.ax.set_yticklabels([d[:3] for d in DAY_ORDER], rotation=0)
    ctx.ax.set_xlabel('Hour of day')
    ctx.ax.set_ylabel('')
    ctx.style(despine=False)
    day, hour = np.unravel_index(int(np.argmax(pivot.values)), pivot.shape)
    return _out(f"Hottest slot: {DAY_ORDER[day]} around {hour}:00 ({fmt_value(ctx.metric, pivot.values.max())}).")


def render_heatmap(ctx: Ctx) -> Dict:
    metric = 'amount' if ctx.metric == 'average' else ctx.metric
    if ctx.metric == 'count':
        pivot = ctx.df.pivot_table(index='merchant_category', columns='weekday', values='amount', aggfunc='size', fill_value=0)
    else:
        pivot = ctx.df.pivot_table(index='merchant_category', columns='weekday', values=metric, aggfunc='sum', fill_value=0)
    cols = [d for d in DAY_ORDER if d in pivot.columns]
    if not cols or pivot.empty or pivot.values.max() == 0:
        raise ChartError("Not enough data yet for a heatmap.")
    pivot = pivot[cols]
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
    ctx.resize(len(pivot.index), 'h')
    norm = PowerNorm(0.6, vmin=0, vmax=float(pivot.values.max()))
    heat = sns.heatmap(pivot, ax=ctx.ax, cmap=ctx.theme['heat'], norm=norm, linewidths=1, linecolor=ctx.theme['bg'],
                       cbar_kws={'label': ctx.metric_label}, annot=False)
    quad = heat.collections[0]
    cmap = quad.cmap
    for i in range(len(pivot.index)):
        for j in range(len(cols)):
            val = pivot.values[i, j]
            if val <= 0:
                continue
            r, g, b, _ = cmap(norm(val))
            ctx.ax.text(j + 0.5, i + 0.5, f"{val:,.0f}", ha='center', va='center', fontsize=8,
                        color='#111111' if 0.299 * r + 0.587 * g + 0.114 * b > 0.6 else '#ffffff')
    cbar = quad.colorbar
    cbar.ax.yaxis.set_tick_params(color=ctx.theme['text'])
    plt.setp(cbar.ax.get_yticklabels(), color=ctx.theme['text'])
    cbar.ax.yaxis.label.set_color(ctx.theme['text'])
    ctx.ax.set_xlabel('')
    ctx.ax.set_ylabel('')
    ctx.ax.set_yticklabels([clean_text(t.get_text(), 20) for t in ctx.ax.get_yticklabels()], rotation=0)
    plt.setp(ctx.ax.get_xticklabels(), rotation=45, ha='right')
    ctx.style(despine=False)
    i, j = np.unravel_index(int(np.argmax(pivot.values)), pivot.shape)
    return _out(f"Hottest cell: {clean_text(pivot.index[i])} on {cols[j]}s ({fmt_value(ctx.metric, pivot.values.max())}).")


def render_forecast(ctx: Ctx) -> Dict:
    forecast = ctx.extra.get('forecast')
    if not forecast or not forecast.get('sufficient_data'):
        raise ChartError((forecast or {}).get('message') or "Not enough history to forecast yet (need 14+ days).")
    hist = pd.DataFrame(forecast['historical']).tail(60)
    fut = pd.DataFrame(forecast['forecast'])
    hist['date'], fut['date'] = pd.to_datetime(hist['date']), pd.to_datetime(fut['date'])
    ctx.ax.bar(hist['date'], hist['amount'], color=ctx.theme['muted'], alpha=0.35, width=0.9, label='Actual daily')
    ma = hist['amount'].rolling(7, min_periods=3).mean()
    ctx.ax.plot(hist['date'], ma, color=ctx.theme['accent'], linewidth=2.4, label='7-day average')
    ctx.ax.plot(fut['date'], fut['predicted'], color=ctx.theme['accent2'], linewidth=2.4, marker='o', markersize=4, linestyle='--', label='Forecast')
    ctx.ax.fill_between(fut['date'], fut['lower'], fut['upper'], color=ctx.theme['accent2'], alpha=0.16, label='Likely range')
    ctx.ax.axvline(fut['date'].iloc[0] - pd.Timedelta(hours=12), color=ctx.theme['muted'], linestyle=':')
    cap = max(float(hist['amount'].quantile(0.97)) * 1.4, float(fut['upper'].max()) * 1.05)
    ctx.ax.set_ylim(0, cap)
    ctx.ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
    ctx.ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=12))
    ctx.ax.set_ylabel('KES per day')
    thousands(ctx.ax)
    ctx.ax.legend(loc='upper left', ncol=2)
    if ctx.standalone:
        ctx.fig.autofmt_xdate(rotation=45)
    ctx.style()
    h = forecast['horizon_days']
    return _out(
        f"Next {h} days: about KES {forecast['total_predicted']:,.0f} (likely KES {forecast['total_lower']:,.0f} to "
        f"{forecast['total_upper']:,.0f}); trend {forecast['trend'].lower()}, risk {forecast['risk_level'].lower()}, "
        f"confidence {forecast['confidence'].lower()}.")


def render_health(ctx: Ctx) -> Dict:
    health = ctx.extra.get('health')
    if not health or not health.get('sufficient_data'):
        raise ChartError((health or {}).get('message') or "Need at least 14 days of history to score your financial health.")
    if ctx.fig is not None:
        plt.close(ctx.fig)
    fig = plt.figure(figsize=(11.5, 6.2))
    ctx.fig = fig
    gauge = fig.add_axes([0.02, 0.12, 0.38, 0.72])
    bars = fig.add_axes([0.50, 0.14, 0.46, 0.70])
    score = health['score']
    color = ctx.theme['bad'] if score < 40 else ctx.theme['accent3'] if score < 70 else ctx.theme['good']
    gauge.add_patch(Wedge((0, 0), 1.0, 0, 180, width=0.28, facecolor=ctx.theme['grid']))
    gauge.add_patch(Wedge((0, 0), 1.0, 180 - 1.8 * score, 180, width=0.28, facecolor=color))
    gauge.text(0, 0.12, f"{score}", ha='center', va='center', fontsize=44, fontweight='bold', color=ctx.theme['text'])
    gauge.text(0, -0.12, f"Grade {health['grade']}", ha='center', va='center', fontsize=15, color=color, fontweight='bold')
    gauge.text(0, -0.36, health['headline'], ha='center', va='center', fontsize=9.5, color=ctx.theme['muted'], wrap=True)
    gauge.set_xlim(-1.15, 1.15)
    gauge.set_ylim(-0.5, 1.15)
    gauge.set_aspect('equal')
    gauge.axis('off')
    comps = sorted(health['components'], key=lambda c: c['score'])
    y = np.arange(len(comps))
    cols = [ctx.theme['bad'] if c['score'] < 40 else ctx.theme['accent3'] if c['score'] < 70 else ctx.theme['good'] for c in comps]
    bars.barh(y, [c['score'] for c in comps], color=cols, height=0.58, edgecolor=ctx.theme['bg'])
    bars.barh(y, [100 - c['score'] for c in comps], left=[c['score'] for c in comps], color=ctx.theme['grid'], height=0.58, alpha=0.6)
    bars.set_yticks(y)
    bars.set_yticklabels([f"{c['name']} ({c['weight']}%)" for c in comps], color=ctx.theme['text'])
    for yi, c in zip(y, comps):
        bars.text(2, yi, f"{c['score']:.0f}  ·  {clean_text(c['value'], 34)}", va='center', fontsize=8,
                  color='#111111' if c['score'] > 25 else ctx.theme['text'])
    bars.set_xlim(0, 100)
    bars.set_xlabel('Component score (0-100)')
    bars.set_facecolor(ctx.theme['panel'])
    sns.despine(ax=bars)
    fig.suptitle(ctx.title, fontsize=14, fontweight='bold', color=ctx.theme['text'], y=0.97)
    ctx.ax = bars
    weakest = comps[0]
    return _out(f"Financial health {score}/100 (grade {health['grade']}): {health['headline'].lower()}. "
                f"Weakest area: {weakest['name'].lower()} ({weakest['score']:.0f}/100). " + (health['tips'][0] if health['tips'] else ''))


def render_recurring(ctx: Ctx) -> Dict:
    items = [r for r in (ctx.extra.get('recurring') or []) if r['monthly_estimate'] > 0][:12]
    if not items:
        raise ChartError("No recurring payments or habits detected yet (need repeated payments to the same recipient).")
    items = items[::-1]
    ctx.resize(len(items), 'h')
    colors = [ctx.theme['accent2'] if r['kind'] == 'subscription' else ctx.theme['accent'] for r in items]
    ctx.ax.barh([clean_text(r['recipient'], 28) for r in items], [r['monthly_estimate'] for r in items], color=colors,
                edgecolor=ctx.theme['bg'], height=0.62)
    peak = max(r['monthly_estimate'] for r in items)
    for i, r in enumerate(items):
        ctx.ax.text(r['monthly_estimate'], i, f"  KES {r['monthly_estimate']:,.0f}/mo · {r['cadence']} · {r['payments']}x",
                    va='center', fontsize=8, color=ctx.theme['text'])
    ctx.ax.set_xlim(0, peak * 1.6)
    ctx.ax.set_xlabel('Estimated KES per month (last 90 days)')
    thousands(ctx.ax, 'x')
    handles = [Rectangle((0, 0), 1, 1, facecolor=ctx.theme['accent2']), Rectangle((0, 0), 1, 1, facecolor=ctx.theme['accent'])]
    ctx.ax.legend(handles, ['Subscription-like (regular, same amount)', 'Habit (frequent payments)'], loc='lower right')
    ctx.style()
    total = sum(r['monthly_estimate'] for r in items)
    return _out(f"{len(items)} recurring payments cost about KES {total:,.0f} a month; the biggest is "
                f"{clean_text(items[-1]['recipient'])} (KES {items[-1]['monthly_estimate']:,.0f}/month).")


def render_overview(ctx: Ctx) -> Dict:
    df = ctx.df
    _need(df, 10, "Not enough transactions for an overview.")
    if ctx.fig is not None:
        plt.close(ctx.fig)
    fig, axes = plt.subplots(2, 3, figsize=(20, 10.5))
    ctx.fig = fig
    spend = df[df['is_spend']]
    panels: List[tuple] = [
        (axes[0, 0], 'Spending trend', 'rolling', df[df['is_spend']], {}),
        (axes[0, 1], 'Where the money goes', 'donut', spend, {'group_by': 'merchant_category', 'top_n': 6}),
        (axes[0, 2], 'When you spend', 'hour_heatmap', spend, {}),
        (axes[1, 0], 'Top recipients', 'bar', spend, {'group_by': 'recipient', 'top_n': 7}),
        (axes[1, 1], 'Money in vs out', 'cashflow', df, {}),
        (axes[1, 2], 'Payment sizes', 'histogram', spend, {}),
    ]
    facts: List[str] = []
    for ax, title, kind, data, overrides in panels:
        spec = dict(ctx.spec, metric='amount', title=title, **overrides)
        panel_ctx = Ctx(df=data, spec=spec, theme=ctx.theme, fig=fig, ax=ax, standalone=False, extra=ctx.extra)
        try:
            result = RENDERERS[kind].fn(panel_ctx)
            facts.append(result['summary'])
        except Exception as e:
            logger.warning(f"overview panel {kind} failed: {e}")
            ax.text(0.5, 0.5, 'Not enough data', ha='center', va='center', color=ctx.theme['muted'], transform=ax.transAxes)
            ax.set_title(title, color=ctx.theme['text'], fontsize=11, fontweight='bold')
            ax.axis('off')
    for ax in axes.flat:
        ax.tick_params(labelsize=8)
    fig.suptitle(ctx.title, fontsize=17, fontweight='bold', color=ctx.theme['text'])
    ctx.ax = axes[0, 0]
    return {'summary': facts[0] if facts else 'Overview of your M-Pesa activity.', 'facts': facts}


@dataclass(frozen=True)
class Renderer:
    fn: Callable[[Ctx], Dict]
    label: str
    all_types: bool = False
    needs: Optional[str] = None
    multi_fig: bool = False


RENDERERS: Dict[str, Renderer] = {
    'bar': Renderer(render_bar, 'Bar chart'),
    'column': Renderer(render_column, 'Column chart'),
    'lollipop': Renderer(render_lollipop, 'Lollipop chart'),
    'pareto': Renderer(render_pareto, 'Pareto chart'),
    'cashflow': Renderer(render_cashflow, 'Cash-flow chart', all_types=True),
    'waterfall': Renderer(render_waterfall, 'Waterfall chart', all_types=True),
    'pie': Renderer(render_pie, 'Pie chart'),
    'donut': Renderer(render_donut, 'Donut chart'),
    'treemap': Renderer(render_treemap, 'Treemap'),
    'waffle': Renderer(render_waffle, 'Waffle chart'),
    'radar': Renderer(render_radar, 'Radar chart', multi_fig=True),
    'stacked_bar': Renderer(render_stacked_bar, 'Stacked bar chart'),
    'monthly_stack': Renderer(render_monthly_stack, 'Stacked column chart'),
    'stacked_area': Renderer(render_stacked_area, 'Stacked area chart'),
    'histogram': Renderer(render_histogram, 'Histogram'),
    'kde': Renderer(render_kde, 'Density plot'),
    'ecdf': Renderer(render_ecdf, 'ECDF plot'),
    'box': Renderer(render_box, 'Box plot'),
    'boxen': Renderer(render_boxen, 'Boxen plot'),
    'violin': Renderer(render_violin, 'Violin plot'),
    'strip': Renderer(render_strip, 'Strip plot'),
    'swarm': Renderer(render_swarm, 'Swarm plot'),
    'ridge': Renderer(render_ridge, 'Ridge plot', multi_fig=True),
    'scatter': Renderer(render_scatter, 'Scatter plot'),
    'bubble': Renderer(render_bubble, 'Bubble chart'),
    'regression': Renderer(render_regression, 'Regression plot'),
    'hexbin': Renderer(render_hexbin, 'Hexbin plot'),
    'joint': Renderer(render_joint, 'Joint plot', multi_fig=True),
    'pair': Renderer(render_pair, 'Pair plot', multi_fig=True),
    'correlation': Renderer(render_correlation, 'Correlation heatmap'),
    'cluster': Renderer(render_cluster, 'Cluster map', multi_fig=True),
    'line': Renderer(render_line, 'Line chart'),
    'area': Renderer(render_area, 'Area chart'),
    'rolling': Renderer(render_rolling, 'Rolling-average chart'),
    'cumulative': Renderer(render_cumulative, 'Cumulative chart', all_types=True),
    'calendar': Renderer(render_calendar, 'Calendar heatmap'),
    'hour_heatmap': Renderer(render_hour_heatmap, 'Hour-by-weekday heatmap'),
    'heatmap': Renderer(render_heatmap, 'Heatmap'),
    'forecast': Renderer(render_forecast, 'Forecast chart', all_types=True, needs='forecast'),
    'health': Renderer(render_health, 'Financial health scorecard', all_types=True, needs='health', multi_fig=True),
    'recurring': Renderer(render_recurring, 'Recurring payments chart', all_types=True, needs='recurring'),
    'overview': Renderer(render_overview, 'Overview', all_types=True, multi_fig=True),
}
CHART_TYPES = tuple(RENDERERS)


def draw_anomaly_figure(anomalies: List[Dict[str, Any]], theme: dict, title: str):
    rows = [a for a in anomalies if a.get('amount')][:12]
    if not rows:
        raise ChartError("No unusual transactions to chart.")
    rows = rows[::-1]
    fig, ax = plt.subplots(figsize=(11, max(4.5, 1.4 + 0.5 * len(rows))))
    scores = np.array([float(a.get('score') or 0) for a in rows])
    top = max(float(scores.max()), 1.0)
    cmap = sns.color_palette('YlOrRd', as_cmap=True)
    colors = [cmap(0.35 + 0.65 * s / top) for s in scores]
    amounts = [float(a['amount']) for a in rows]
    labels = [f"{str(a.get('timestamp', ''))[:10]} · {clean_text(a.get('recipient', 'Unknown'), 24)}" for a in rows]
    ax.barh(labels, amounts, color=colors, edgecolor=theme['bg'], height=0.65)
    peak = max(amounts)
    for i, (a, amount) in enumerate(zip(rows, amounts)):
        reason = clean_text((a.get('reasons') or [''])[0], 70)
        ax.text(amount, i, f"  KES {amount:,.0f}  ·  {reason}", va='center', fontsize=8, color=theme['text'])
    ax.set_xlim(0, peak * 2.2)
    ax.set_xlabel('Amount (KES); colour = unusualness (darker is more unusual)')
    thousands(ax, 'x')
    ax.set_title(clean_text(title, 100), fontsize=14, fontweight='bold', color=theme['text'], pad=14)
    sns.despine(ax=ax)
    return fig
