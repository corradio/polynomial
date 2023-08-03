ARG PYTHON_VERSION=3.9.16-slim-buster

FROM python:${PYTHON_VERSION}

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN mkdir -p /code

WORKDIR /code

# Install poetry
RUN set -ex && \
    pip install --upgrade pip poetry && \
    rm -rf /root/.cache/

# Install node+yarn
RUN apt update && apt install -y curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_16.x | bash - && \
    apt install nodejs && \
    curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add - && \
    echo "deb https://dl.yarnpkg.com/debian/ stable main" | tee /etc/apt/sources.list.d/yarn.list && \
    apt update && apt install -y yarn

# Install poetry packages
COPY poetry.lock pyproject.toml ./
RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-root --no-dev && \
    rm -rf ~/.cache/pypoetry && \
    rm -rf ~/.config/pypoetry

# Install javascript packages
COPY package.json yarn.lock ./
RUN yarn

# Copy source files
COPY . /code/

# Generate static files
RUN yarn build && \
    python manage.py collectstatic --noinput && \
    python manage.py compress

EXPOSE 8000
ENV NEW_RELIC_CONFIG_FILE=newrelic.ini

CMD ["poetry", "run", "newrelic-admin", "run-program", "gunicorn", "--bind", ":8000", "--workers", "2", "config.wsgi"]
