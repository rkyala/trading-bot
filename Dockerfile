FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all necessary Python modules and data files
COPY bot.py rl_policy.py rl_q_table.json finrl_integration.py finrl_agent.zip ./

CMD ["python", "-u", "bot.py"]
