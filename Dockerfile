ARG PYTHON_VERSION=3.9.16-slim-buster

FROM python:${PYTHON_VERSION}

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN mkdir -p /code

WORKDIR /code

RUN set -ex && \
    pip install --upgrade pip poetry && \
    rm -rf /root/.cache/

COPY poetry.lock pyproject.toml ./

RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-root --no-dev && \
    rm -rf ~/.cache/pypoetry && \
    rm -rf ~/.config/pypoetry

COPY . /code/

# Ignored for now as there are no static files
# RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "--bind", ":8000", "--workers", "2", "config.wsgi"]
