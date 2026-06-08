@echo off
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Starting H2GV UX Questionnaire web app...
echo Open your browser at: http://localhost:5000
echo.
python app.py
pause
