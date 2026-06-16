#!/usr/bin/env python
import click
from src.parse_sms import MpesaParser
from src.database import SupabaseDB
from src.analyzer import MpesaAnalyzer
import pandas as pd
import json
import os
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@click.group()
def cli():
    """PesaPilot CLI Tool - AI-Powered Financial Assistant"""
    pass

@cli.command()
@click.option('--force', is_flag=True, help='Force setup even if data exists')
def setup(force):
    """Initialize the database and environment"""
    click.echo("🔧 Setting up PesaPilot...")
    
    # Check environment
    required_vars = ['SUPABASE_URL', 'SUPABASE_KEY', 'GROQ_API_KEY']
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        click.echo(f"❌ Missing environment variables: {', '.join(missing)}")
        click.echo("Please check your .env file")
        return
    
    # Initialize database
    try:
        db = SupabaseDB()
        click.echo("✅ Database initialized")
    except Exception as e:
        click.echo(f"❌ Database initialization failed: {e}")
        return
    
    # Create data directories
    os.makedirs('data/raw', exist_ok=True)
    os.makedirs('data/processed', exist_ok=True)
    click.echo("✅ Data directories created")
    
    click.echo("🎉 Setup complete!")

@cli.command()
@click.argument('xml_path', type=click.Path(exists=True))
def load(xml_path):
    """Load SMS XML data into database"""
    click.echo(f"📂 Loading data from {xml_path}...")
    
    # Parse XML
    parser = MpesaParser()
    df = parser.parse_xml_to_csv(xml_path)
    
    if df.empty:
        click.echo("❌ No transactions found in the XML file")
        return
    
    click.echo(f"✅ Parsed {len(df)} transactions")
    
    # Load into database
    db = SupabaseDB()
    transactions = df.to_dict('records')
    inserted = db.insert_transactions(transactions)
    click.echo(f"✅ Inserted {inserted} transactions into database")

@cli.command()
def dashboard():
    """Start the Streamlit dashboard"""
    click.echo("🚀 Starting PesaPilot dashboard...")
    os.system("streamlit run app.py")

@cli.command()
@click.option('--question', prompt='Ask a question', help='Question about your transactions')
def ask(question):
    """Ask a question about your transactions"""
    click.echo(f"🤔 Question: {question}")
    
    analyzer = MpesaAnalyzer()
    result = analyzer.ask_question(question)
    
    if result.get('success'):
        click.echo("\n📊 Analysis:")
        click.echo(result['analysis'])
        
        if result.get('result_count', 0) > 0:
            click.echo(f"\n📈 Found {result['result_count']} results")
        
        if click.confirm("\nShow SQL query?"):
            click.echo("\n🔍 SQL:")
            click.echo(result['sql'])
    else:
        click.echo(f"❌ Error: {result.get('error', 'Unknown error')}")

@cli.command()
def insights():
    """Generate financial insights"""
    click.echo("💡 Generating insights...")
    
    analyzer = MpesaAnalyzer()
    data = analyzer.get_dashboard_data()
    
    if data.get('success'):
        click.echo("\n📈 Financial Insights:")
        click.echo(data['insights'])
    else:
        click.echo(f"❌ Error: {data.get('error', 'Unknown error')}")

@cli.command()
@click.option('--output', default='data/processed/backup.json', help='Output file')
def backup(output):
    """Backup all transaction data"""
    click.echo(f"💾 Backing up data to {output}...")
    
    db = SupabaseDB()
    df = db.get_transactions(days=365)  # Get all transactions
    
    if df.empty:
        click.echo("❌ No data to backup")
        return
    
    # Save to JSON
    os.makedirs(os.path.dirname(output), exist_ok=True)
    df.to_json(output, orient='records', date_format='iso')
    click.echo(f"✅ Backed up {len(df)} transactions")

@cli.command()
@click.option('--limit', default=10, help='Number of transactions to show')
def recent(limit):
    """Show recent transactions"""
    db = SupabaseDB()
    df = db.get_transactions(days=30, limit=limit)
    
    if df.empty:
        click.echo("❌ No recent transactions found")
        return
    
    click.echo(f"\n📋 Recent {len(df)} transactions:")
    click.echo(df[['timestamp', 'type', 'amount', 'recipient', 'merchant_category']].to_string(index=False))

@cli.command()
def stats():
    """Show transaction statistics"""
    db = SupabaseDB()
    summary = db.get_summary()
    
    click.echo("\n📊 Transaction Statistics:")
    click.echo(f"Total Transactions: {summary.get('total_transactions', 0)}")
    
    categories = pd.DataFrame(summary.get('categories', []))
    if not categories.empty:
        click.echo("\n📈 Spending by Category:")
        for _, row in categories.iterrows():
            click.echo(f"  {row['merchant_category']}: Ksh {row['total_spent']:,.2f} ({row['transaction_count']} transactions)")

if __name__ == '__main__':
    cli()