FROM python:3.12.0-alpine3.17
WORKDIR /app
ADD src/server.py .
ADD src/config.json .
EXPOSE 8000

ENTRYPOINT ["python", "server.py"]
