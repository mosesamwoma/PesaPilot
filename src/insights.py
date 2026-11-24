import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.frames import DAY_ORDER, daily_spend
from src.security import sanitize_for_prompt
from src.timeutil import today_nairobi

logger = logging.getLogger(__name__)

MICRO_SPEND_KES = 100
MIN_DAYS_FOR_HEALTH = 14


def _kes(value: float) -> str:
    return f"KES {float(value):,.0f}"


def _interp(value: float, xs: List[float], ys: List[float]) -> float:
    return float(np.interp(value, xs, ys))


def _window(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if df.empty:
        return df
    lo, hi = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)
    return df[(df['timestamp'] >= lo) & (df['timestamp'] < hi)]


def latest_balance(df: pd.DataFrame) -> Optional[float]:
    if df.empty or 'balance' not in df.columns:
        return None
    known = df.dropna(subset=['balance'])
    return float(known.iloc[-1]['balance']) if not known.empty else None


def history_days(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    return int((df['date'].max() - df['date'].min()).days) + 1


def cashflow_monthly(df: pd.DataFrame) -> pd.DataFrame:
    columns = ['month', 'income', 'spend', 'fees', 'net', 'savings_rate']
    if df.empty:
        return pd.DataFrame(columns=columns)
    spend = df[df['is_spend']].groupby('month')['amount'].sum()
    fees = df[df['is_spend']].groupby('month')['transaction_cost'].sum()
    income = df[df['is_income']].groupby('month')['amount'].sum()
    months = pd.date_range(df['month'].min(), df['month'].max(), freq='MS')
    out = pd.DataFrame({'month': months})
    out['income'] = out['month'].map(income).fillna(0.0)
    out['spend'] = out['month'].map(spend).fillna(0.0)
    out['fees'] = out['month'].map(fees).fillna(0.0)
    out['net'] = out['income'] - out['spend'] - out['fees']
    out['savings_rate'] = np.where(out['income'] > 0, out['net'] / out['income'].where(out['income'] > 0, 1), np.nan)
    return out[columns]


def financial_health(df: pd.DataFrame, today: Optional[date] = None) -> Dict:
    today = today or today_nairobi()
    if df.empty or history_days(df) < MIN_DAYS_FOR_HEALTH:
        return {
            'sufficient_data': False,
            'message': f"I need at least {MIN_DAYS_FOR_HEALTH} days of M-Pesa history to score your financial health.",
        }

    last90 = _window(df, today - timedelta(days=89), today)
    last30 = _window(df, today - timedelta(days=29), today)
    prior = _window(df, today - timedelta(days=119), today - timedelta(days=30))
    spend90 = float(last90.loc[last90['is_spend'], 'amount'].sum())
    income90 = float(last90.loc[last90['is_income'], 'amount'].sum())
    fees90 = float(last90.loc[last90['is_spend'], 'transaction_cost'].sum())

    components: List[Dict] = []

    net = income90 - spend90 - fees90
    if income90 > 0:
        savings_rate = net / income90
    else:
        savings_rate = -1.0 if spend90 > 0 else 0.0
    components.append({
        'key': 'cashflow', 'name': 'Cash flow', 'weight': 30,
        'score': _interp(savings_rate, [-0.5, 0.0, 0.2], [0, 60, 100]),
        'value': f"{savings_rate * 100:+.0f}% of income kept",
        'detail': (f"Over 90 days you received {_kes(income90)} and spent {_kes(spend90 + fees90)} "
                   f"({'kept' if net >= 0 else 'overspent'} {_kes(abs(net))})."),
    })

    balance = latest_balance(df)
    span30 = max(min(30, history_days(df)), 1)
    daily30 = float(last30.loc[last30['is_spend'], 'amount'].sum()) / span30
    cover = (balance / daily30) if (balance is not None and daily30 > 0) else None
    components.append({
        'key': 'buffer', 'name': 'Cash buffer', 'weight': 20,
        'score': _interp(cover, [0, 3, 7, 14, 30], [0, 20, 45, 70, 100]) if cover is not None else 50.0,
        'value': f"{cover:.0f} days of cover" if cover is not None else 'n/a',
        'detail': (f"Your balance of {_kes(balance)} covers about {cover:.1f} days at your recent pace of "
                   f"{_kes(daily30)}/day." if cover is not None else 'No balance information available.'),
    })

    fee_pct = (fees90 / spend90 * 100) if spend90 > 0 else 0.0
    components.append({
        'key': 'fees', 'name': 'Fee efficiency', 'weight': 15,
        'score': _interp(fee_pct, [0, 0.3, 1, 2, 4], [100, 100, 70, 40, 0]),
        'value': f"{fee_pct:.2f}% lost to fees",
        'detail': f"You paid {_kes(fees90)} in M-Pesa fees over 90 days ({fee_pct:.2f}% of spending).",
    })

    end_week = pd.Timestamp(today).normalize() - pd.Timedelta(days=int(pd.Timestamp(today).dayofweek) + 1)
    weekly = daily_spend(df, end_week - pd.Timedelta(days=12 * 7 - 1), end_week)
    cv = None
    if len(weekly) >= 28:
        totals = weekly.resample('W-SUN').sum()
        if len(totals) >= 4 and totals.mean() > 0:
            cv = float(totals.std() / totals.mean())
    components.append({
        'key': 'stability', 'name': 'Spending stability', 'weight': 15,
        'score': _interp(cv, [0, 0.3, 1.0, 1.5], [100, 100, 40, 0]) if cv is not None else 60.0,
        'value': f"weekly variation {cv * 100:.0f}%" if cv is not None else 'n/a',
        'detail': (f"Your weekly spending swings by about {cv * 100:.0f}% around its average."
                   if cv is not None else 'Not enough weeks of history to judge stability.'),
    })

    recent_daily = float(last30.loc[last30['is_spend'], 'amount'].sum()) / 30
    prior_days = 90
    prior_daily = float(prior.loc[prior['is_spend'], 'amount'].sum()) / prior_days
    ratio = (recent_daily / prior_daily) if prior_daily > 0 else None
    components.append({
        'key': 'trend', 'name': 'Spending trend', 'weight': 10,
        'score': _interp(ratio, [0.0, 0.9, 1.0, 1.3, 1.6], [100, 100, 70, 30, 0]) if ratio is not None else 60.0,
        'value': f"{(ratio - 1) * 100:+.0f}% vs prior 3 months" if ratio is not None else 'n/a',
        'detail': (f"Daily spending over the last 30 days is {_kes(recent_daily)} versus {_kes(prior_daily)} "
                   f"in the 3 months before." if ratio is not None else 'No earlier period to compare with.'),
    })

    saved = float(last90.loc[last90['is_spend'] & (last90['merchant_category'] == 'savings'), 'amount'].sum())
    save_ratio = (saved / income90) if income90 > 0 else 0.0
    components.append({
        'key': 'savings', 'name': 'Saving habit', 'weight': 10,
        'score': _interp(save_ratio, [0, 0.05, 0.1], [25, 70, 100]),
        'value': f"{save_ratio * 100:.1f}% of income to Sacco/MMF",
        'detail': f"Payments to savings vehicles (Sacco, MMF, chama) were {_kes(saved)} in 90 days.",
    })

    for comp in components:
        comp['score'] = round(max(0.0, min(100.0, comp['score'])), 1)
    total_weight = sum(c['weight'] for c in components)
    score = round(sum(c['score'] * c['weight'] for c in components) / total_weight)
    grade = 'A' if score >= 85 else 'B' if score >= 70 else 'C' if score >= 55 else 'D' if score >= 40 else 'F'

    weakest = sorted(components, key=lambda c: (100 - c['score']) * c['weight'], reverse=True)[:3]
    tip_text = {
        'cashflow': "Spend less than you receive: pick one category to trim this week and move the difference to an MMF.",
        'buffer': "Build a buffer: keep at least 7 days of spending (about {daily}) untouched in your wallet or an MMF.",
        'fees': "Cut fees: batch small sends into one larger transfer and use Lipa na M-Pesa where it is free of charge.",
        'stability': "Smooth your spending: set a weekly limit with 'set budget <category> <amount> weekly'.",
        'trend': "Your spending is climbing: ask me for a pie chart of your categories and set a budget for the biggest one.",
        'savings': "Start a small automatic saving (even KES 50/day) into a Sacco or Money Market Fund.",
    }
    tips = [tip_text[c['key']].format(daily=_kes(daily30 * 7)) for c in weakest if c['score'] < 75]

    return {
        'sufficient_data': True,
        'score': int(score),
        'grade': grade,
        'headline': {
            'A': 'Excellent money habits', 'B': 'Healthy, with room to improve', 'C': 'Fair: a few things need attention',
            'D': 'Under pressure: act on the tips below', 'F': 'Critical: your cash is stretched thin',
        }[grade],
        'components': components,
        'tips': tips,
        'window_days': 90,
        'income_90d': round(income90, 2),
        'spend_90d': round(spend90, 2),
        'fees_90d': round(fees90, 2),
        'balance': balance,
        'days_of_cover': None if cover is None else round(cover, 1),
    }


def _cadence(median_gap: float) -> str:
    if median_gap <= 1.5:
        return 'daily'
    if median_gap <= 4.5:
        return 'every few days'
    if median_gap <= 8.5:
        return 'weekly'
    if median_gap <= 16:
        return 'fortnightly'
    if median_gap <= 35:
        return 'monthly'
    return 'occasional'


def detect_recurring(df: pd.DataFrame, today: Optional[date] = None, include_lapsed: bool = False,
                     limit: int = 25) -> List[Dict]:
    if df.empty:
        return []
    spend = df[df['is_spend']]
    if spend.empty:
        return []
    end = pd.Timestamp(today or today_nairobi()).normalize()
    end = max(end, spend['date'].max())
    cutoff90 = end - pd.Timedelta(days=89)
    results: List[Dict] = []

    for key, group in spend.groupby('recipient_key'):
        days = np.sort(group['date'].unique())
        if len(days) < 3 or key == 'unknown':
            continue
        gaps = np.diff(days).astype('timedelta64[D]').astype(float)
        gaps = gaps[gaps > 0]
        if len(gaps) < 2:
            continue
        median_gap = float(np.median(gaps))
        mad = float(np.median(np.abs(gaps - median_gap)))
        gap_cv = (1.4826 * mad / median_gap) if median_gap > 0 else 9.9
        amounts = group['amount'].astype(float)
        mean_amt = float(amounts.mean())
        amount_cv = float(amounts.std() / mean_amt) if mean_amt > 0 and len(amounts) > 1 else 0.0
        span_days = max((pd.Timestamp(days[-1]) - pd.Timestamp(days[0])).days, 1)
        per_week = len(days) / (span_days / 7)

        subscription = len(days) >= 3 and median_gap >= 5 and gap_cv <= 0.35 and amount_cv <= 0.2
        habit = len(days) >= 8 and per_week >= 1.0
        if not (subscription or habit):
            continue

        last_day = pd.Timestamp(days[-1])
        active = (end - last_day).days <= max(median_gap * 2.5, 7)
        if not active and not include_lapsed:
            continue
        recent = group[group['date'] >= cutoff90]
        monthly = float(recent['amount'].sum()) / 3.0 if active else 0.0
        results.append({
            'recipient': str(group['recipient'].mode().iat[0]),
            'category': str(group['merchant_category'].mode().iat[0]),
            'kind': 'subscription' if subscription else 'habit',
            'cadence': _cadence(median_gap),
            'payments': int(len(group)),
            'days_with_payment': int(len(days)),
            'per_week': round(per_week, 1),
            'median_amount': round(float(amounts.median()), 2),
            'total': round(float(amounts.sum()), 2),
            'monthly_estimate': round(monthly, 2),
            'median_gap_days': round(median_gap, 1),
            'last_paid': last_day.date().isoformat(),
            'next_expected': (last_day + pd.Timedelta(days=round(median_gap))).date().isoformat(),
            'active': bool(active),
        })

    results.sort(key=lambda r: (r['monthly_estimate'], r['total']), reverse=True)
    return results[:limit]


def spending_patterns(df: pd.DataFrame) -> Dict:
    spend = df[df['is_spend']] if not df.empty else df
    if spend.empty:
        return {'sufficient_data': False}

    total = float(spend['amount'].sum())
    count = int(len(spend))
    by_hour = spend.groupby('hour')['amount'].agg(['sum', 'count'])
    peak_hour_amount = int(by_hour['sum'].idxmax())
    peak_hour_count = int(by_hour['count'].idxmax())

    span = max(history_days(df), 1)
    series = daily_spend(df)
    by_dow = series.groupby(series.index.dayofweek).mean()
    peak_dow = DAY_ORDER[int(by_dow.idxmax())]
    quiet_dow = DAY_ORDER[int(by_dow.idxmin())]
    weekend_share = float(series[series.index.dayofweek >= 5].sum() / series.sum()) if series.sum() > 0 else 0.0
    weekend_expected = 2 / 7

    micro = spend[spend['amount'] < MICRO_SPEND_KES]
    micro_recipients = (micro.groupby('recipient')['amount'].agg(['sum', 'count'])
                        .sort_values('sum', ascending=False).head(3))
    fees = float(spend['transaction_cost'].sum())
    paid_fee_count = int((spend['transaction_cost'] > 0).sum())

    payday_ratio = None
    income = df[df['is_income']]
    if not income.empty and len(series) > 30:
        threshold = float(income['amount'].quantile(0.75))
        big_days = income[income['amount'] >= threshold]['date'].dt.normalize().unique()
        two_day = series.rolling(2).sum().shift(-1)
        hits = [float(two_day.get(pd.Timestamp(d), np.nan)) for d in big_days]
        hits = [h for h in hits if not np.isnan(h)]
        baseline = float(two_day.mean())
        if len(hits) >= 3 and baseline > 0:
            payday_ratio = float(np.mean(hits) / baseline)

    return {
        'sufficient_data': True,
        'total_spend': round(total, 2),
        'transactions': count,
        'avg_daily_spend': round(total / span, 2),
        'peak_hour_by_amount': peak_hour_amount,
        'peak_hour_by_count': peak_hour_count,
        'peak_weekday': peak_dow,
        'quietest_weekday': quiet_dow,
        'weekend_share_pct': round(weekend_share * 100, 1),
        'weekend_expected_pct': round(weekend_expected * 100, 1),
        'micro_count': int(len(micro)),
        'micro_count_pct': round(len(micro) / count * 100, 1),
        'micro_total': round(float(micro['amount'].sum()), 2),
        'micro_total_pct': round(float(micro['amount'].sum()) / total * 100, 1) if total else 0.0,
        'micro_monthly': round(float(micro['amount'].sum()) / max(span / 30.44, 1), 2),
        'micro_top': [
            {'recipient': str(name), 'total': round(float(row['sum']), 2), 'count': int(row['count'])}
            for name, row in micro_recipients.iterrows()
        ],
        'fees_total': round(fees, 2),
        'fees_pct_of_spend': round(fees / total * 100, 2) if total else 0.0,
        'paid_fee_count': paid_fee_count,
        'payday_spend_ratio': None if payday_ratio is None else round(payday_ratio, 2),
    }


def runway(df: pd.DataFrame, today: Optional[date] = None) -> Dict:
    today = today or today_nairobi()
    balance = latest_balance(df)
    last30 = _window(df, today - timedelta(days=29), today) if not df.empty else df
    span = max(min(30, history_days(df)), 1)
    spend_daily = float(last30.loc[last30['is_spend'], 'amount'].sum()) / span if not last30.empty else 0.0
    income_daily = float(last30.loc[last30['is_income'], 'amount'].sum()) / span if not last30.empty else 0.0
    cover = (balance / spend_daily) if (balance is not None and spend_daily > 0) else None
    net_daily = income_daily - spend_daily
    status = 'unknown'
    if cover is not None:
        status = 'critical' if cover < 1 else 'low' if cover < 3 else 'ok' if cover < 14 else 'strong'
    return {
        'balance': balance,
        'avg_daily_spend': round(spend_daily, 2),
        'avg_daily_income': round(income_daily, 2),
        'net_daily': round(net_daily, 2),
        'days_of_cover': None if cover is None else round(cover, 1),
        'status': status,
    }


def period_comparison(df: pd.DataFrame, days: int = 30, today: Optional[date] = None) -> Dict:
    today = today or today_nairobi()
    if df.empty:
        return {'sufficient_data': False}
    cur = _window(df, today - timedelta(days=days - 1), today)
    prev = _window(df, today - timedelta(days=2 * days - 1), today - timedelta(days=days))
    cur_spend = float(cur.loc[cur['is_spend'], 'amount'].sum())
    prev_spend = float(prev.loc[prev['is_spend'], 'amount'].sum())
    cur_income = float(cur.loc[cur['is_income'], 'amount'].sum())
    prev_income = float(prev.loc[prev['is_income'], 'amount'].sum())

    series = daily_spend(df, df['date'].min(), pd.Timestamp(today))
    percentile = None
    if len(series) >= days * 3:
        rolling = series.rolling(days).sum().dropna().iloc[::7]
        if len(rolling) >= 5:
            percentile = float((rolling <= cur_spend).mean() * 100)

    def pct(a: float, b: float) -> Optional[float]:
        return round((a - b) / b * 100, 1) if b > 0 else None

    return {
        'sufficient_data': True,
        'days': days,
        'spend': round(cur_spend, 2), 'prev_spend': round(prev_spend, 2), 'spend_change_pct': pct(cur_spend, prev_spend),
        'income': round(cur_income, 2), 'prev_income': round(prev_income, 2), 'income_change_pct': pct(cur_income, prev_income),
        'spend_percentile': None if percentile is None else round(percentile),
    }


def smart_alerts(df: pd.DataFrame, today: Optional[date] = None) -> List[Dict]:
    today = today or today_nairobi()
    alerts: List[Dict] = []
    if df.empty:
        return alerts

    run = runway(df, today)
    if run['days_of_cover'] is not None and run['status'] in ('critical', 'low'):
        alerts.append({
            'level': 'warning', 'title': 'Low cash buffer',
            'detail': (f"Your balance of {_kes(run['balance'])} covers only {run['days_of_cover']:.1f} days at your "
                       f"recent spending of {_kes(run['avg_daily_spend'])}/day."),
        })

    series = daily_spend(df, df['date'].min(), pd.Timestamp(today))
    if len(series) >= 56:
        weekly = series.resample('W-SUN').sum()
        completed = weekly.iloc[:-1]
        last7 = float(series.iloc[-7:].sum())
        typical = float(completed.tail(12).median())
        if typical > 0 and last7 > typical * 1.5 and last7 - typical >= 500:
            alerts.append({
                'level': 'warning', 'title': 'Spending spike',
                'detail': f"The last 7 days cost {_kes(last7)}, {last7 / typical:.1f}x your typical week of {_kes(typical)}.",
            })

    pat = spending_patterns(df)
    if pat.get('sufficient_data'):
        if pat['fees_pct_of_spend'] >= 1.5:
            alerts.append({
                'level': 'info', 'title': 'Fees are adding up',
                'detail': f"M-Pesa fees total {_kes(pat['fees_total'])} ({pat['fees_pct_of_spend']:.1f}% of spending).",
            })
        if pat['micro_count_pct'] >= 50 and pat['micro_monthly'] >= 300:
            alerts.append({
                'level': 'info', 'title': 'Small payments add up',
                'detail': (f"{pat['micro_count_pct']:.0f}% of your payments are under KES {MICRO_SPEND_KES}, "
                           f"about {_kes(pat['micro_monthly'])} a month."),
            })

    spend = df[df['is_spend']]
    total = float(spend['amount'].sum())
    if total > 0:
        top = spend.groupby('recipient')['amount'].sum().sort_values(ascending=False)
        name, amount = top.index[0], float(top.iloc[0])
        if amount / total >= 0.25:
            alerts.append({
                'level': 'info', 'title': 'One recipient dominates',
                'detail': f"{amount / total * 100:.0f}% of all spending ({_kes(amount)}) went to {sanitize_for_prompt(name, 40)}.",
            })
    return alerts[:6]


def facts_text(df: pd.DataFrame, today: Optional[date] = None) -> str:
    today = today or today_nairobi()
    if df.empty:
        return ''
    lines: List[str] = []
    health = financial_health(df, today)
    if health.get('sufficient_data'):
        weak = ', '.join(f"{c['name']} {c['score']:.0f}/100" for c in sorted(health['components'], key=lambda c: c['score'])[:2])
        lines.append(f"Financial health score: {health['score']}/100 (grade {health['grade']}); weakest areas: {weak}.")
    run = runway(df, today)
    if run['days_of_cover'] is not None:
        lines.append(f"Cash runway: balance {_kes(run['balance'])} covers {run['days_of_cover']:.1f} days at "
                     f"{_kes(run['avg_daily_spend'])}/day spending (income averages {_kes(run['avg_daily_income'])}/day).")
    cmp30 = period_comparison(df, 30, today)
    if cmp30.get('sufficient_data') and cmp30['spend_change_pct'] is not None:
        extra = f", higher than {cmp30['spend_percentile']}% of your past 30-day periods" if cmp30['spend_percentile'] is not None else ''
        lines.append(f"Last 30 days spending {_kes(cmp30['spend'])} is {cmp30['spend_change_pct']:+.0f}% vs the 30 days before{extra}.")
    pat = spending_patterns(df)
    if pat.get('sufficient_data'):
        lines.append(f"Spending peaks around {pat['peak_hour_by_amount']}:00 and on {pat['peak_weekday']}s; weekends are "
                     f"{pat['weekend_share_pct']:.0f}% of spend. {pat['micro_count_pct']:.0f}% of payments are under "
                     f"KES {MICRO_SPEND_KES} (about {_kes(pat['micro_monthly'])}/month).")
    recurring = detect_recurring(df, today)[:3]
    if recurring:
        parts = [f"{sanitize_for_prompt(r['recipient'], 30)} ({r['cadence']}, ~{_kes(r['monthly_estimate'])}/month)" for r in recurring]
        lines.append("Recurring payments: " + '; '.join(parts) + '.')
    return '\n'.join(lines)
