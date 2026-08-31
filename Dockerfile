# Salón Aziza — app image. One workload, three surfaces: the Telegram webhook, the client's
# join page and the specialist's mini app — docs/PROJECT_DEFINITION.md §14.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# git, because the agent-platform packages are pinned by git tag and pip clones them —
# python:*-slim carries no git.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

# The agent-platform repository is PRIVATE. The PAT arrives as a BuildKit secret, is read out of
# /run/secrets only while pip runs, and is never written into a layer or into git config.
# Build with:  docker build --secret id=ADO_PAT,src=<file-holding-the-PAT> .
COPY requirements.txt ./
RUN --mount=type=secret,id=ADO_PAT \
    git config --global credential.helper \
      '!f() { echo username=pat; echo "password=$(cat /run/secrets/ADO_PAT)"; }; f' \
 && pip install --no-cache-dir -r requirements.txt \
 && git config --global --unset credential.helper

COPY . .

EXPOSE 8080

# Shell form so ${PORT} expands where a platform injects one.
CMD ["sh", "-c", "uvicorn aziza_adk.channel:app --host 0.0.0.0 --port ${PORT:-8080}"]
