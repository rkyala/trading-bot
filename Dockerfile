FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py backtest_v2.py ./

CMD ["python", "-u", "bot.py"]
