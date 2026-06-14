FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py rl_policy.py rl_q_table.json ./

CMD ["python", "-u", "bot.py"]
