@echo off
cd /d "C:\Users\User\Documents\stock_agent"
python -m streamlit run dashboard.py --server.port 8501 --server.headless false
pause
