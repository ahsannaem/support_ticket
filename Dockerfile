FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -c constraints.txt '.[live]'
ENTRYPOINT ["python", "-m", "agent.runtime"]
CMD ["--help"]
