FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python -m compileall -b -q . && find . -name "*.py" -not -name "*.pyc" -type f -delete
RUN useradd -m agentuser
USER agentuser
CMD ["python", "run_agent.pyc"]
