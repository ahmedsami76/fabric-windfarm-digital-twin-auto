# Build from the repository root so that the site definition is in the context:
#   docker build -f simulator/Dockerfile -t windfarm-simulator:1.2.0 .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY simulator/pyproject.toml ./
COPY simulator/windfarm_sim ./windfarm_sim
RUN pip install --no-cache-dir .

# The site definition is baked into the image so that the simulator and the
# reference data in the Lakehouse always describe the same site.
COPY data/reference/site.json /app/data/reference/site.json
ENV SITE_FILE=/app/data/reference/site.json

RUN useradd --uid 10001 --create-home sim
USER 10001

ENTRYPOINT ["python", "-m", "windfarm_sim"]
