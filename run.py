#!/usr/bin/env python
import click
from src.parse_sms import MpesaParser
from src.database import SupabaseDB
from src.analyzer import MpesaAnalyzer
import pandas as pd
import json
import os

@click.group()
def cli():
    """PesaPilot CLI Tool"""
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
    db = SupabaseDB()
    click.echo("✅ Database initialized")
    
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
    os.system("streamlit run src/streamlit_app.py")

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
        
        if click.confirm("Show SQL query?"):
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
    
    # Save to JSON
    df.to_json(output, orient='records', date_format='iso')
    click.echo(f"✅ Backed up {len(df)} transactions")

if __name__ == '__main__':
    cli()