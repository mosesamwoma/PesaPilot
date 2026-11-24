from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.frames import DAY_ORDER
from src.security import sanitize_for_prompt

BG = 'rgba(0,0,0,0)'
GRID = '#2d3250'
TEXT = '#8892a4'
ACCENT, ACCENT2, ACCENT3 = '#00d4aa', '#ff4b6e', '#ffb454'
SEQ = ['#1e2130', '#3b2a5c', '#8b2f6b', '#e0475b', '#ffb454', '#fff3cf']


def _layout(fig: go.Figure, height: int = 380, **kwargs) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=BG, plot_bgcolor=BG, font_color=TEXT, height=height, margin=dict(l=0, r=0, t=36, b=0),
        legend=dict(bgcolor=BG), **kwargs,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def _label(value: Any, limit: int = 28) -> str:
    return sanitize_for_prompt(str(value), limit)


def _spend(df: pd.DataFrame) -> pd.DataFrame:
    return df[df['is_spend']] if not df.empty else df


def daily_series(df: pd.DataFrame, spend: bool = True) -> pd.Series:
    sub = df[df['is_spend']] if spend else df[df['is_income']]
    if sub.empty:
        return pd.Series(dtype=float)
    s = sub.groupby('date')['amount'].sum()
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq='D'), fill_value=0.0)


def calendar_heatmap(df: pd.DataFrame) -> Optional[go.Figure]:
    s = daily_series(df)
    if len(s) < 7:
        return None
    end = s.index.max()
    start = max(s.index.min(), end - pd.Timedelta(weeks=52))
    start -= pd.Timedelta(days=int(start.dayofweek))
    full = s.reindex(pd.date_range(start, end, freq='D'), fill_value=0.0)
    weeks = len(full) // 7 + (1 if len(full) % 7 else 0)
    z = np.full((7, weeks), np.nan)
    text = np.full((7, weeks), '', dtype=object)
    for i, (day, value) in enumerate(full.items()):
        z[i % 7, i // 7] = value
        text[i % 7, i // 7] = f"{day:%a %d %b %Y}: KES {value:,.0f}"
    cap = float(full[full > 0].quantile(0.98)) if (full > 0).any() else 1.0
    fig = go.Figure(go.Heatmap(
        z=np.minimum(z, cap), text=text, hoverinfo='text', colorscale=SEQ, showscale=True, xgap=2, ygap=2,
        colorbar=dict(title='KES'),
    ))
    month_ticks = [(w, (start + pd.Timedelta(weeks=w)).strftime('%b')) for w in range(weeks)
                   if (start + pd.Timedelta(weeks=w)).day <= 7]
    fig.update_xaxes(tickvals=[w for w, _ in month_ticks], ticktext=[m for _, m in month_ticks], showgrid=False)
    fig.update_yaxes(tickvals=list(range(7)), ticktext=[d[:3] for d in DAY_ORDER], autorange='reversed', showgrid=False)
    return _layout(fig, 300)


def hour_weekday_heatmap(df: pd.DataFrame) -> Optional[go.Figure]:
    sp = _spend(df)
    if len(sp) < 10:
        return None
    pivot = sp.pivot_table(index='weekday', columns='hour', values='amount', aggfunc='sum', fill_value=0)
    pivot = pivot.reindex(index=DAY_ORDER, columns=range(24), fill_value=0)
    fig = px.imshow(pivot, aspect='auto', color_continuous_scale=SEQ, labels=dict(x='Hour of day', y='', color='KES'))
    return _layout(fig, 330)


def treemap(df: pd.DataFrame) -> Optional[go.Figure]:
    sp = _spend(df)
    if sp.empty:
        return None
    top_rec = sp.groupby('recipient')['amount'].sum().nlargest(40).index
    data = sp.assign(recipient_short=np.where(sp['recipient'].isin(top_rec), sp['recipient'], 'Other recipients'))
    agg = data.groupby(['merchant_category', 'recipient_short'], as_index=False)['amount'].sum()
    agg['merchant_category'] = agg['merchant_category'].map(_label)
    agg['recipient_short'] = agg['recipient_short'].map(_label)
    fig = px.treemap(agg, path=[px.Constant('All spending'), 'merchant_category', 'recipient_short'], values='amount',
                     color='amount', color_continuous_scale='Tealgrn')
    fig.update_traces(textinfo='label+value+percent root', hovertemplate='%{label}: KES %{value:,.0f}<extra></extra>')
    return _layout(fig, 460, coloraxis_showscale=False)


def sunburst(df: pd.DataFrame) -> Optional[go.Figure]:
    sp = _spend(df)
    if sp.empty:
        return None
    top_rec = sp.groupby('recipient')['amount'].sum().nlargest(30).index
    data = sp[sp['recipient'].isin(top_rec)]
    agg = data.groupby(['merchant_category', 'recipient'], as_index=False)['amount'].sum()
    agg['merchant_category'] = agg['merchant_category'].map(_label)
    agg['recipient'] = agg['recipient'].map(_label)
    fig = px.sunburst(agg, path=['merchant_category', 'recipient'], values='amount',
                      color_discrete_sequence=px.colors.qualitative.Bold)
    fig.update_traces(hovertemplate='%{label}: KES %{value:,.0f}<extra></extra>')
    return _layout(fig, 460)


def sankey(df: pd.DataFrame, top_sources: int = 5, top_cats: int = 7) -> Optional[go.Figure]:
    income, sp = df[df['is_income']], _spend(df)
    if income.empty or sp.empty:
        return None
    src = income.groupby('recipient')['amount'].sum().sort_values(ascending=False)
    top_src = src.head(top_sources)
    if len(src) > top_sources:
        top_src['Other senders'] = src.iloc[top_sources:].sum()
    cats = sp.groupby('merchant_category')['amount'].sum().sort_values(ascending=False)
    top_c = cats.head(top_cats)
    if len(cats) > top_cats:
        top_c['other categories'] = cats.iloc[top_cats:].sum()
    fees = float(sp['transaction_cost'].sum())
    labels = [f"{_label(s, 22)}" for s in top_src.index] + ['M-Pesa wallet'] + [_label(c, 22).title() for c in top_c.index]
    if fees > 0:
        labels.append('M-Pesa fees')
    wallet = len(top_src)
    sources, targets, values = [], [], []
    for i, v in enumerate(top_src.values):
        sources.append(i)
        targets.append(wallet)
        values.append(float(v))
    for j, v in enumerate(top_c.values):
        sources.append(wallet)
        targets.append(wallet + 1 + j)
        values.append(float(v))
    if fees > 0:
        sources.append(wallet)
        targets.append(len(labels) - 1)
        values.append(fees)
    palette = px.colors.qualitative.Bold
    fig = go.Figure(go.Sankey(
        node=dict(label=labels, pad=18, thickness=16, color=[palette[i % len(palette)] for i in range(len(labels))]),
        link=dict(source=sources, target=targets, value=values, color='rgba(136,146,164,0.25)'),
    ))
    return _layout(fig, 460)


def category_distribution(df: pd.DataFrame, kind: str = 'violin') -> Optional[go.Figure]:
    sp = _spend(df)
    sp = sp[sp['amount'] > 0]
    counts = sp['merchant_category'].value_counts()
    keep = counts[counts >= 5].index
    sp = sp[sp['merchant_category'].isin(keep)]
    if len(keep) < 1:
        return None
    order = sp.groupby('merchant_category')['amount'].median().sort_values(ascending=False).index.tolist()
    fn = px.violin if kind == 'violin' else px.box
    kwargs = dict(box=True, points=False) if kind == 'violin' else dict(points='outliers')
    fig = fn(sp, x='merchant_category', y='amount', color='merchant_category', log_y=True,
             category_orders={'merchant_category': order}, labels={'amount': 'Amount (KES, log scale)', 'merchant_category': ''},
             color_discrete_sequence=px.colors.qualitative.Bold, **kwargs)
    return _layout(fig, 380, showlegend=False)


def ecdf(df: pd.DataFrame) -> Optional[go.Figure]:
    sp = _spend(df)
    sp = sp[sp['amount'] > 0]
    if len(sp) < 10:
        return None
    fig = px.ecdf(sp, x='amount', log_x=True, labels={'amount': 'Amount (KES, log scale)'}, color_discrete_sequence=[ACCENT])
    for q, color in ((0.5, ACCENT3), (0.9, ACCENT2)):
        v = float(sp['amount'].quantile(q))
        fig.add_vline(x=v, line_dash='dot', line_color=color, annotation_text=f"{int(q * 100)}% under KES {v:,.0f}",
                      annotation_position='top left')
    fig.update_yaxes(title='Share of payments', tickformat='.0%')
    return _layout(fig, 380)


def cashflow(df: pd.DataFrame) -> Optional[go.Figure]:
    if df.empty:
        return None
    span = (df['date'].max() - df['date'].min()).days + 1
    rule = 'MS' if span > 70 else 'W-SUN'
    idx = df.set_index('timestamp')
    inc = idx[idx['is_income']]['amount'].resample(rule).sum()
    out = idx[idx['is_spend']]['amount'].resample(rule).sum()
    frame = pd.DataFrame({'Money in': inc, 'Money out': out}).fillna(0.0)
    frame['Net'] = frame['Money in'] - frame['Money out']
    if frame.empty:
        return None
    fig = go.Figure()
    fig.add_bar(x=frame.index, y=frame['Money in'], name='Money in', marker_color=ACCENT)
    fig.add_bar(x=frame.index, y=frame['Money out'], name='Money out', marker_color=ACCENT2)
    fig.add_scatter(x=frame.index, y=frame['Net'], name='Net', mode='lines+markers', line=dict(color=ACCENT3, width=3))
    fig.update_layout(barmode='group')
    return _layout(fig, 380)


def cumulative(df: pd.DataFrame) -> Optional[go.Figure]:
    if df.empty:
        return None
    days = pd.date_range(df['date'].min(), df['date'].max(), freq='D')
    spend = df[df['is_spend']].groupby('date')['amount'].sum().reindex(days, fill_value=0.0).cumsum()
    inc = df[df['is_income']].groupby('date')['amount'].sum().reindex(days, fill_value=0.0).cumsum()
    fig = go.Figure()
    fig.add_scatter(x=days, y=inc, name='Money in', line=dict(color=ACCENT, width=3))
    fig.add_scatter(x=days, y=spend, name='Money out', line=dict(color=ACCENT2, width=3), fill='tonexty',
                    fillcolor='rgba(255,75,110,0.12)')
    return _layout(fig, 380)


def rolling(df: pd.DataFrame) -> Optional[go.Figure]:
    s = daily_series(df)
    if len(s) < 14:
        return None
    fig = go.Figure()
    fig.add_bar(x=s.index, y=s.values, name='Daily', marker_color='rgba(136,146,164,0.35)')
    fig.add_scatter(x=s.index, y=s.rolling(7, min_periods=4).mean(), name='7-day average', line=dict(color=ACCENT3, width=2))
    fig.add_scatter(x=s.index, y=s.rolling(30, min_periods=10).mean(), name='30-day average', line=dict(color=ACCENT, width=3))
    cap = float(s.quantile(0.995)) * 1.3
    if s.max() > 12 * max(float(s.median()), 1.0):
        fig.update_yaxes(range=[0, cap])
    return _layout(fig, 380)


def weekday_bars(df: pd.DataFrame) -> Optional[go.Figure]:
    s = daily_series(df)
    if len(s) < 7:
        return None
    avg = s.groupby(s.index.dayofweek).mean().reindex(range(7)).fillna(0.0)
    colors = [ACCENT2 if i == int(avg.values.argmax()) else ACCENT for i in range(7)]
    fig = go.Figure(go.Bar(x=DAY_ORDER, y=avg.values, marker_color=colors, text=[f"{v:,.0f}" for v in avg.values], textposition='outside'))
    fig.update_yaxes(title='Average spend per day (KES)')
    return _layout(fig, 340)


def correlation(df: pd.DataFrame) -> Optional[go.Figure]:
    sp = _spend(df)
    top = sp.groupby('merchant_category')['amount'].sum().nlargest(8).index
    daily = sp[sp['merchant_category'].isin(top)].pivot_table(index='date', columns='merchant_category', values='amount',
                                                             aggfunc='sum', fill_value=0.0)
    if daily.empty:
        return None
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max(), freq='D'), fill_value=0.0)
    daily = daily.loc[:, daily.std() > 0]
    if daily.shape[1] < 3 or len(daily) < 14:
        return None
    fig = px.imshow(daily.corr(), text_auto='.2f', color_continuous_scale='RdBu_r', zmin=-1, zmax=1, aspect='auto')
    return _layout(fig, 420)


def health_gauge(health: Dict) -> Optional[go.Figure]:
    if not health.get('sufficient_data'):
        return None
    score = health['score']
    color = ACCENT2 if score < 40 else ACCENT3 if score < 70 else ACCENT
    fig = go.Figure(go.Indicator(
        mode='gauge+number', value=score, number=dict(suffix=f"  ({health['grade']})", font=dict(color=color)),
        gauge=dict(axis=dict(range=[0, 100]), bar=dict(color=color), bgcolor='rgba(255,255,255,0.04)', borderwidth=0,
                   steps=[dict(range=[0, 40], color='rgba(255,75,110,0.15)'),
                          dict(range=[40, 70], color='rgba(255,180,84,0.15)'),
                          dict(range=[70, 100], color='rgba(0,212,170,0.15)')]),
    ))
    return _layout(fig, 300)


def health_components(health: Dict) -> Optional[go.Figure]:
    if not health.get('sufficient_data'):
        return None
    comps = sorted(health['components'], key=lambda c: c['score'])
    colors = [ACCENT2 if c['score'] < 40 else ACCENT3 if c['score'] < 70 else ACCENT for c in comps]
    fig = go.Figure(go.Bar(
        x=[c['score'] for c in comps], y=[f"{c['name']} ({c['weight']}%)" for c in comps], orientation='h',
        marker_color=colors, text=[f"{c['score']:.0f} · {c['value']}" for c in comps], textposition='inside',
        insidetextanchor='start', hovertext=[c['detail'] for c in comps], hoverinfo='text',
    ))
    fig.update_xaxes(range=[0, 100], title='Score')
    return _layout(fig, 340)


def recurring_bars(items: List[Dict]) -> Optional[go.Figure]:
    items = [r for r in items if r['monthly_estimate'] > 0][:12][::-1]
    if not items:
        return None
    fig = go.Figure(go.Bar(
        x=[r['monthly_estimate'] for r in items], y=[_label(r['recipient']) for r in items], orientation='h',
        marker_color=[ACCENT2 if r['kind'] == 'subscription' else ACCENT for r in items],
        text=[f"KES {r['monthly_estimate']:,.0f}/mo · {r['cadence']}" for r in items], textposition='auto',
    ))
    fig.update_xaxes(title='Estimated KES per month')
    return _layout(fig, max(300, 60 + 34 * len(items)))


def forecast_figure(forecast: Dict) -> Optional[go.Figure]:
    hist, fut = forecast.get('historical', [])[-60:], forecast.get('forecast', [])
    if not hist and not fut:
        return None
    fig = go.Figure()
    if hist:
        h = pd.DataFrame(hist)
        fig.add_bar(x=h['date'], y=h['amount'], name='Actual daily', marker_color='rgba(136,146,164,0.35)')
        fig.add_scatter(x=h['date'], y=h['amount'].rolling(7, min_periods=3).mean(), name='7-day average',
                        line=dict(color=ACCENT, width=3))
    if fut:
        f = pd.DataFrame(fut)
        fig.add_scatter(x=list(f['date']) + list(f['date'])[::-1], y=list(f['upper']) + list(f['lower'])[::-1], fill='toself',
                        fillcolor='rgba(255,75,110,0.15)', line=dict(color='rgba(0,0,0,0)'), name='Likely range', hoverinfo='skip')
        fig.add_scatter(x=f['date'], y=f['predicted'], name='Forecast', mode='lines+markers',
                        line=dict(color=ACCENT2, width=3, dash='dash'))
    if hist:
        cap = max(float(pd.DataFrame(hist)['amount'].quantile(0.97)) * 1.4, max((p['upper'] for p in fut), default=0) * 1.05)
        fig.update_yaxes(range=[0, cap])
    return _layout(fig, 400)


def anomaly_scatter(df: pd.DataFrame, flagged: List[Dict]) -> Optional[go.Figure]:
    sp = _spend(df)
    sp = sp[sp['amount'] > 0]
    if sp.empty:
        return None
    fig = go.Figure()
    fig.add_scatter(x=sp['timestamp'], y=sp['amount'], mode='markers', name='Payments',
                    marker=dict(color='rgba(136,146,164,0.45)', size=5), hovertemplate='%{x}<br>KES %{y:,.0f}<extra></extra>')
    if flagged:
        f = pd.DataFrame(flagged)
        f['timestamp'] = pd.to_datetime(f['timestamp'], format='ISO8601', errors='coerce')
        reasons = [(r[0] if r else '') for r in f.get('reasons', [[]] * len(f))]
        fig.add_scatter(x=f['timestamp'], y=f['amount'], mode='markers', name='Flagged',
                        marker=dict(color=ACCENT2, size=11, line=dict(color='white', width=1)),
                        text=[_label(f"{r}", 90) for r in reasons], hovertemplate='%{x}<br>KES %{y:,.0f}<br>%{text}<extra></extra>')
    fig.update_yaxes(type='log', title='Amount (KES, log scale)')
    return _layout(fig, 420)
