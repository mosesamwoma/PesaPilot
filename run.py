# run.py
import click
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@click.group()
def cli():
    """PesaPilot - M-Pesa Financial Intelligence"""
    pass

@cli.command()
def setup():
    """Test the Supabase connection"""
    from src.database import SupabaseDB
    db = SupabaseDB()
    click.echo("✅ Database connection OK")
    click.echo("Run the SQL in scripts/init_db.sql in your Supabase dashboard to create tables.")

@cli.command()
@click.argument('xml_path')
@click.option('--csv', default='data/processed/mpesa_transactions.csv', help='CSV output path')
def load(xml_path, csv):
    """Parse and load XML backup into database"""
    from src.analyzer import MpesaAnalyzer
    analyzer = MpesaAnalyzer()
    count = analyzer.load_transactions(xml_path, csv_output=csv)
    click.echo(f"✅ Loaded {count} transactions")

@cli.command()
@click.option('--port', default=8501, help='Streamlit port')
def dashboard(port):
    """Launch Streamlit dashboard"""
    import subprocess
    # FIX: was src/streamlit_app.py — dashboard lives at app.py (project root)
    subprocess.run(['streamlit', 'run', 'app.py', f'--server.port={port}'])

@cli.command()
@click.argument('question')
def ask(question):
    """Ask a question about your transactions"""
    from src.analyzer import MpesaAnalyzer
    analyzer = MpesaAnalyzer()
    result = analyzer.ask_question(question)
    click.echo(f"\nSQL: {result['sql']}\n")
    click.echo(f"Analysis:\n{result['analysis']}")

if __name__ == '__main__':
    cli()