import re
from typing import Dict, List, Optional, Tuple

from src.parse_sms import MpesaParser

MIN_QUESTION_LENGTH = 2
MAX_QUESTION_LENGTH = 500
MAX_PERIOD_DAYS = 1000

_DESTRUCTIVE_SQL_RE = re.compile(
    r'\b(?:drop|truncate|alter|create|grant|revoke)\s+(?:table|database|schema|index|view|function|user|role)\b'
    r'|\bdelete\s+from\b'
    r'|\binsert\s+into\b'
    r'|\bupdate\s+\w+\s+set\b',
    re.IGNORECASE,
)

FORECAST_KEYWORDS = [
    'forecast', 'spending prediction', 'predict my spending', 'spending forecast',
    'projected spending', 'predict spending', 'future spending',
]

BUDGET_KEYWORDS = [
    'budget plan', 'budget', 'how should i budget', 'monthly plan', 'allocate my money', 'allocate income',
]

INVEST_KEYWORDS = [
    'invest', 'investment', 'where to invest', 'grow my money', 'grow savings', 'mmf',
    'money market fund', 'treasury bill', 't-bill', 'put my money',
]

ANOMALY_KEYWORDS = [
    'anomaly', 'anomalies', 'unusual spending', 'unusual transaction', 'weird transaction',
    'strange transaction', 'suspicious transaction', 'flagged transaction', 'odd spending',
    'out of pattern', 'is anything unusual',
]

BUDGET_STATUS_KEYWORDS = [
    'my budgets', 'budget status', 'how are my budgets', 'budget check',
    'check my budget', 'am i over budget', 'am i within budget', 'budget progress',
]

CHART_TRIGGER_WORDS = [
    'bar chart', 'pie chart', 'donut chart', 'doughnut chart', 'line chart', 'area chart',
    'scatter chart', 'scatter plot', 'box plot', 'boxplot', 'boxen plot', 'violin plot',
    'stacked bar', 'stacked chart',
    'pie', 'donut', 'doughnut', 'trend', 'heatmap', 'heat map',
    'histogram', 'distribution', 'variability', 'consistency', 'outlier', 'outliers',
    'violin', 'stacked', 'chart', 'graph', 'plot', 'diagram', 'visualize', 'visualise',
    'over days', 'over time', 'spending over', 'daily trend', 'weekly',
    'merchants', 'top merchants', 'top recipients', 'recipients', 'top spending',
    'breakdown of', 'spending by', 'spending per', 'where did i spend', 'where did my money go',
    'how did i spend', 'proportion', 'percentage of my spending', 'compare my spending',
    'show me my spending', 'show my spending', 'transaction costs', 'transaction fees',
]

SET_BUDGET_PATTERN = re.compile(
    r'(?:'
    r'(?:set\s+)?budget(?:\s+limit)?\s+(?:for\s+)?(?P<category>[a-zA-Z ]+?)\s+'
    r'(?:to\s+|of\s+|at\s+)?(?:kes\s*)?(?P<amount>\d[\d,]*(?:\.\d+)?)'
    r'|'
    r'set\s+(?P<category2>[a-zA-Z ]+?)\s+budget\s*'
    r'(?:to\s+|of\s+|at\s+)?(?:kes\s*)?(?P<amount2>\d[\d,]*(?:\.\d+)?)'
    r')\s*(?P<period>weekly|monthly)?',
    re.IGNORECASE,
)
_HAS_DIGIT = re.compile(r'\d')

CATEGORY_SYNONYMS: Dict[str, List[str]] = {
    'food': ['food', 'groceries', 'grocery', 'eating', 'restaurant', 'eats', 'lunch', 'dinner', 'kibanda', 'mama mboga'],
    'transport': ['transport', 'fare', 'matatu', 'uber', 'bolt', 'taxi', 'fuel', 'petrol', 'boda'],
    'utilities': ['utilities', 'utility', 'kplc', 'electricity', 'power', 'water bill', 'wifi', 'internet', 'airtime', 'data', 'bundles'],
    'banking': ['banking', 'bank charges', 'bank charge', 'withdrawal', 'withdraw', 'deposit', 'transaction charges'],
    'shopping': ['shopping', 'shop', 'clothes', 'clothing', 'retail'],
    'health': ['health', 'medical', 'hospital', 'clinic', 'pharmacy', 'medicine', 'nhif', 'sha'],
    'education': ['education', 'school fees', 'fees', 'tuition', 'school'],
    'entertainment': ['entertainment', 'movies', 'netflix', 'showmax', 'fun', 'leisure', 'games'],
    'savings': ['savings', 'saving', 'sacco', 'mmf', 'chama'],
    'business': ['business', 'stock', 'supplies', 'wholesale'],
    'personal': ['personal', 'family', 'friends', 'people', 'send money', 'p2p'],
    'other': ['other', 'miscellaneous', 'misc'],
}

HELP_SECTIONS = """🤖 **PesaPilot v1.2 - Your AI Financial Assistant**

**CHARTS** (Describe what you want, in your own words):
  • "Pie chart of my spending by category last month"
  • "Donut chart of my spending by category"
  • "Bar chart of my top 5 recipients in August"
  • "Show my transport spending as a line chart this year"
  • "How much has M-Pesa charged me in fees this month?"
  • "Heatmap of my spending by day of the week"
  • "Stacked bar of my spending by category and day"
  • "Distribution of my transaction amounts last 90 days"
  • "Spread of my food spending" or "Violin plot of my spending by category"
  • Any chart type (bar/pie/donut/line/area/scatter/histogram/heatmap/
    box/violin/stacked bar) + any date range (a specific month, "last
    week", "Q1", exact dates, "all time")

**QUESTIONS** (Ask naturally):
  • "What did I spend on food?"
  • "Top 5 expenses?"
  • "How much to Safaricom?"

**ADVICE**:
  • "Give me a budget plan" → Personalized KES budget split
  • "What should I invest in?" → Sacco / MMF / T-Bill guidance

**REPORTS**:
  • "Summary" → Last 30 days
  • "Daily summary" / "Today" → Today's overview
  • "90 days" / "All time" → Extended periods
{manual_sms}
**FORECASTING**:
  • "Forecast" / "Forecast 7 days" → Next 7-day spending prediction
  • "Forecast 30 days" → Next 30-day spending prediction
  • "Spending prediction" → Same as "forecast"
  • Returns predicted amount, trend, risk level + AI summary

**ANOMALY DETECTION**:
  • "Anomalies" / "Unusual spending" → ML-flagged unusual transactions
  • Learns YOUR normal pattern per category, not a generic threshold
{anomaly_page}
**BUDGET GOALS**:
  • "Set budget food 5000" → Monthly food budget of KES 5,000
  • "Set budget transport 3000 weekly" → Weekly transport budget
  • "My budgets" / "Budget status" → Current spend vs each limit
{budget_tail}
Just ask naturally! Charts & analysis are smart."""


def help_text(dashboard: bool = False) -> str:
    if dashboard:
        return HELP_SECTIONS.format(
            manual_sms="",
            anomaly_page="  • Also browsable on the Anomalies page in the sidebar\n",
            budget_tail="  • Manage budgets anytime on the Budgets page in the sidebar\n",
        )
    return HELP_SECTIONS.format(
        manual_sms=(
            "\n**MANUAL SMS**:\n"
            "  • PIN-PASTE_SMS_HERE (e.g., 1234-UFMD8OKA...)\n"
        ),
        anomaly_page="",
        budget_tail="  • I'll proactively ping you here if you get close to or go over\n",
    )


def is_valid_question_length(question: str) -> bool:
    return MIN_QUESTION_LENGTH <= len(question or '') <= MAX_QUESTION_LENGTH


def is_safe_question(question: str) -> bool:
    return not _DESTRUCTIVE_SQL_RE.search(question or '')


def clean_response(text: str) -> str:
    jargon = ['postgresql', 'postgres', 'schema', 'database', 'query', 'sql', 'rpc']
    for word in jargon:
        text = re.sub(rf'\b{re.escape(word)}\b', '', text or '', flags=re.IGNORECASE)
    return re.sub(r' +', ' ', text).strip()


def keyword_pattern(word: str) -> re.Pattern:
    if ' ' in word:
        return re.compile(re.escape(word), re.IGNORECASE)
    return re.compile(rf'\b{re.escape(word)}\b', re.IGNORECASE)


def matches_any_keyword(text: str, keywords) -> bool:
    return any(keyword_pattern(k).search(text) for k in keywords)


def is_set_budget_command(question_lower: str) -> bool:
    return (
        question_lower.startswith('set budget')
        or question_lower.startswith('budget limit')
        or (question_lower.startswith('set ') and 'budget' in question_lower
            and bool(_HAS_DIGIT.search(question_lower)))
    )


def normalize_category(text: str) -> Optional[str]:
    cleaned = re.sub(r'\s+', ' ', (text or '').strip().lower())
    if not cleaned:
        return None
    if cleaned in MpesaParser.CATEGORIES:
        return cleaned
    for category, words in CATEGORY_SYNONYMS.items():
        if cleaned in words:
            return category
    for category, words in CATEGORY_SYNONYMS.items():
        if any(re.search(rf'\b{re.escape(w)}\b', cleaned) for w in words):
            return category
    return None


def parse_set_budget(question: str) -> Tuple[Optional[Dict], Optional[str]]:
    match = SET_BUDGET_PATTERN.search(question)
    if not match:
        return None, 'Couldn\'t read that. Try: "set budget food 5000" or "set budget transport 3000 weekly"'
    raw_category = (match.group('category') or match.group('category2') or '').strip()
    category = normalize_category(raw_category)
    if category is None:
        names = ', '.join(MpesaParser.CATEGORIES)
        return None, f'I don\'t know the category "{raw_category}". Pick one of: {names}.'
    amount = float((match.group('amount') or match.group('amount2')).replace(',', ''))
    if amount <= 0:
        return None, 'The budget limit must be greater than 0.'
    period = (match.group('period') or 'monthly').lower()
    return {'category': category, 'amount': amount, 'period': period}, None


def parse_days_from_question(question_lower: str, default: Optional[int] = 30) -> Optional[int]:
    q = question_lower or ''
    if re.search(r'all[\s-]?time|\bever\b|full history|since the beginning|overall', q):
        return None
    m = re.search(r'(\d{1,4})\s*-?\s*days?\b', q)
    if m:
        return max(1, min(int(m.group(1)), MAX_PERIOD_DAYS))
    m = re.search(r'(\d{1,3})\s*-?\s*weeks?\b', q)
    if m:
        return max(1, min(int(m.group(1)) * 7, MAX_PERIOD_DAYS))
    m = re.search(r'(\d{1,2})\s*-?\s*months?\b', q)
    if m:
        return max(1, min(int(m.group(1)) * 30, MAX_PERIOD_DAYS))
    m = re.search(r'(?:last|past)\s+(\d{1,4})\b', q)
    if m:
        return max(1, min(int(m.group(1)), MAX_PERIOD_DAYS))
    if re.search(r'two weeks|fortnight', q):
        return 14
    if 'year' in q:
        return 365
    if 'quarter' in q:
        return 90
    if 'month' in q:
        return 30
    if re.search(r'\bweek\b', q):
        return 7
    return default


def parse_forecast_horizon(question_lower: str, default: int = 7) -> int:
    if 'month' in question_lower or re.search(r'\b30\b', question_lower):
        return 30
    if 'week' in question_lower or re.search(r'\b7\b', question_lower):
        return 7
    return default


def period_label(days: Optional[int]) -> str:
    return 'All-Time' if days is None else f'{days}-Day'


def daily_summary_text(summary: Dict, manual_sms_hint: bool = True) -> str:
    if not summary or summary.get('total_transactions', 0) == 0:
        hint = (
            "Start tracking by sending M-Pesa SMS or manual entry: PIN-SMS_CONTENT"
            if manual_sms_hint else "Start tracking by adding M-Pesa transactions."
        )
        return f"No transactions recorded today.\n\n{hint}"

    spent = summary.get('total_spent', 0)
    received = summary.get('total_received', 0)
    balance = summary.get('balance', 0)
    transactions = summary.get('total_transactions', 0)
    debit_count = summary.get('debit_count', 0)
    fees = summary.get('total_transaction_cost', 0)

    return f"""**Today's Financial Summary**

Total Transactions: {transactions}
Total Spent: KES {spent:,.0f}
Total Received: KES {received:,.0f}
Net Flow: KES {received - spent:,.0f}
M-Pesa Fees: KES {fees:,.0f}
Current Balance: KES {balance:,.0f}

**Insights:**
- Average per payment: KES {spent / max(debit_count, 1):,.0f}
- Spending velocity: {'High' if spent > 5000 else 'Moderate' if spent > 1000 else 'Low'}
"""


def range_summary_text(summary: Dict, days: Optional[int]) -> str:
    if not summary or summary.get('total_transactions', 0) == 0:
        return "No transactions in this period. Start tracking now!"

    spent = summary.get('total_spent', 0)
    received = summary.get('total_received', 0)
    balance = summary.get('balance', 0)
    transactions = summary.get('total_transactions', 0)
    debit_count = summary.get('debit_count', 0)
    fees = summary.get('total_transaction_cost', 0)
    span = days if days is not None else max(int(summary.get('span_days') or 1), 1)
    position = (
        'Deficit (spent more than received)' if spent > received
        else 'Surplus (received more than spent)'
    )

    return f"""**{period_label(days)} Financial Summary**

Transactions: {transactions}
Total Spent: KES {spent:,.0f}
Total Received: KES {received:,.0f}
Net: KES {received - spent:,.0f}
M-Pesa Fees: KES {fees:,.0f}
Balance: KES {balance:,.0f}

**Analytics:**
- Daily Average: KES {spent / span:,.0f}
- Per Payment: KES {spent / max(debit_count, 1):,.0f}
- Net Position: {position}"""


def budget_status_text(rows: List[Dict], dashboard: bool = False) -> str:
    if not rows:
        tail = ' to create one, or use the Budgets page.' if dashboard else ' to create one.'
        return f'No budgets set yet. Try: "set budget food 5000"{tail}'
    lines = ["**Your Budgets**\n"]
    for row in rows:
        limit = float(row.get('limit_amount') or 0)
        spent = float(row.get('spent_this_period') or 0)
        pct = (spent / limit * 100) if limit else 0
        threshold = float(row.get('alert_threshold_pct') or 80)
        icon = "🔴" if pct >= 100 else "🟡" if pct >= threshold else "🟢"
        lines.append(
            f"{icon} {str(row.get('category', '')).title()} ({row.get('period', 'monthly')}): "
            f"KES {spent:,.0f} / {limit:,.0f} ({pct:.0f}%)"
        )
    return "\n".join(lines)


def forecast_header(forecast_data: Dict, horizon: int) -> str:
    trend = forecast_data.get('trend', 'Stable')
    risk = forecast_data.get('risk_level', 'Low')
    trend_icon = {'Increasing': '📈', 'Decreasing': '📉', 'Stable': '➡️'}.get(trend, '')
    risk_icon = {'Low': '🟢', 'Moderate': '🟡', 'High': '🔴'}.get(risk, '')
    return (
        f"**{horizon}-Day Spending Forecast**\n\n"
        f"Predicted Spend: KES {forecast_data.get('total_predicted', 0):,.0f}\n"
        f"Avg per Day: KES {forecast_data.get('avg_predicted_daily', 0):,.0f}\n"
        f"{trend_icon} Trend: {trend}\n"
        f"{risk_icon} Risk Level: {risk}\n"
    )
