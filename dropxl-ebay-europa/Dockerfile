FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 bridge
WORKDIR /app
COPY --chown=bridge:bridge bridge.py demo.py ./
RUN mkdir /app/state && chown bridge:bridge /app/state
USER bridge
CMD ["python", "bridge.py", "worker"]
