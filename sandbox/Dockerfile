# Course execution image: what every student submission runs in.
# Students develop locally against the same deps (agent-starter/requirements.txt).
FROM python:3.12-slim

# course_kit (and its deps) baked in so submissions can `from course_kit import ...`
RUN pip install --no-cache-dir \
    "course-kit @ https://github.com/agents4science/agent-starter/archive/refs/heads/master.tar.gz" \
    numpy pandas

RUN useradd -m runner
USER runner
WORKDIR /submission
