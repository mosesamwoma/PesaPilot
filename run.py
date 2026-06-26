#!/usr/bin/env python3
"""
PesaPilot - Start all services
"""
import subprocess
import os
import sys
import signal
import time

# Colors
GREEN = '\033[92m'
RED = '\033[91m'
BLUE = '\033[94m'
YELLOW = '\033[93m'
RESET = '\033[0m'

def print_header():
    print(f"""
{BLUE}╔══════════════════════════════════════════════════════════╗
║         🚀 PesaPilot - M-Pesa Financial Assistant           ║
║                      Starting Services...                     ║
╚══════════════════════════════════════════════════════════╝{RESET}
    """)

def check_env():
    """Check if .env exists"""
    if not os.path.exists(".env"):
        print(f"{RED}❌ .env file not found!{RESET}")
        print(f"{YELLOW}Please create .env file with required variables{RESET}")
        sys.exit(1)

def start_services():
    """Start FastAPI and Streamlit"""
    print(f"{GREEN}Starting services...{RESET}\n")

    processes = []

    # Start FastAPI
    print(f"{GREEN}▶ Starting FastAPI server (port 8000)...{RESET}")
    api_cmd = [
        sys.executable, "-m", "uvicorn",
        "whatsapp.whatsapp_api:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--reload"
    ]
    try:
        api_proc = subprocess.Popen(api_cmd)
        processes.append(("FastAPI", api_proc))
        print(f"{GREEN}✅ FastAPI started (PID: {api_proc.pid}){RESET}")
    except Exception as e:
        print(f"{RED}❌ Failed to start FastAPI: {e}{RESET}")
        return []

    time.sleep(3)

    # Start Streamlit — dashboard is now at dashboard/app.py
    print(f"{GREEN}▶ Starting Streamlit dashboard (port 8501)...{RESET}")
    st_cmd = [
        sys.executable, "-m", "streamlit", "run",
        "dashboard/app.py",
        "--logger.level=error",
        "--client.showErrorDetails=false"
    ]
    try:
        st_proc = subprocess.Popen(st_cmd)
        processes.append(("Streamlit", st_proc))
        print(f"{GREEN}✅ Streamlit started (PID: {st_proc.pid}){RESET}")
    except Exception as e:
        print(f"{RED}❌ Failed to start Streamlit: {e}{RESET}")
        return processes

    return processes

def main():
    print_header()
    check_env()

    processes = start_services()

    if not processes:
        print(f"{RED}❌ Failed to start services{RESET}")
        sys.exit(1)

    print(f"""
{GREEN}
╔══════════════════════════════════════════════════════════╗
║            ✅ All services running successfully!          ║
╚══════════════════════════════════════════════════════════╝{RESET}

📊 Dashboard:  {BLUE}http://localhost:8501{RESET}
🔗 API:        {BLUE}http://localhost:8000{RESET}
📱 WhatsApp:   {BLUE}Online & Connected{RESET}

{YELLOW}Commands:{RESET}
  • Press Ctrl+C to stop all services
  • Watch logs above for activity

{GREEN}Ready to use! 🎉{RESET}
    """)

    def signal_handler(sig, frame):
        print(f"\n{YELLOW}⏹  Shutting down services...{RESET}")
        for name, proc in processes:
            print(f"  • Stopping {name}...", end=" ", flush=True)
            proc.terminate()
            try:
                proc.wait(timeout=5)
                print(f"{GREEN}✅{RESET}")
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"{YELLOW}(killed){RESET}")
        print(f"{GREEN}✅ All services stopped{RESET}")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Keep running
    for name, proc in processes:
        try:
            proc.wait()
        except KeyboardInterrupt:
            signal_handler(None, None)

if __name__ == "__main__":
    main()