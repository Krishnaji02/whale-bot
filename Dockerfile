# Use a compatible Python version (3.10)
FROM python:3.10-slim

# Working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --upgrade pip setuptools && pip install -r requirements.txt

# Copy bot code
COPY bot.py .

# Start the bot
CMD ["python", "bot.py"]
