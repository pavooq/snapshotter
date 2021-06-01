FROM python:3.9-alpine AS base

ENV PYTHONUNBUFFERED true

RUN adduser -D --home /runtime runtime runtime

WORKDIR /tmp/package

# install dependencies

COPY setup.py setup.cfg *requirements*.txt /tmp/package

RUN apk add --quiet --virtual .build build-base gcc && \

    pip install --upgrade pip && pip install /tmp/package && \

    apk del --quiet .build


COPY . /tmp/package

RUN pip install --no-deps /tmp/package


USER runtime:runtime

WORKDIR /runtime


FROM base AS auth

ARG DOMAIN

ENV DOMAIN ${DOMAIN}

CMD ["sh", "-c", "snapshotter auth 0.0.0.0 8080 ${DOMAIN}"]

EXPOSE 8080


FROM base AS collect

CMD ["snapshotter", "collect"]
