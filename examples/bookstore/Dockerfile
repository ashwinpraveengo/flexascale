FROM python:3.11-slim
RUN pip install --no-cache-dir prometheus-client==0.21.1
WORKDIR /app
COPY app.py .
USER 65534
EXPOSE 8080
CMD ["python", "app.py"]
