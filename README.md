# Arcade Store (Python + Flask + SQLite)

A transactional key-value store with nested transactions, a Flask REST API, and tests.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
python api.py  # http://localhost:8000
````

## API

* `POST /session` → `{ "session_id": "<uuid>" }`
* `POST /session/<id>/begin` → start nested transaction
* `POST /session/<id>/commit` → commit one level (outermost flushes to DB)
* `POST /session/<id>/rollback` → rollback one level
* `PUT /store/<key>` body `{ "value": ... }` (optional `X-Session-ID`)
* `GET /store/<key>` (optional `X-Session-ID`)
* `DELETE /store/<key>` (optional `X-Session-ID`)

## Description of the project

* A tiny **database** that stores **key → value** pairs.
* Values can be any **JSON** (numbers, strings, lists, dicts).
* It supports **transactions** so you can stage multiple changes and then **commit** (save) or **rollback** (undo).
* A **web API** (HTTP endpoints) exposes `GET`, `PUT`, `DELETE`, and transaction controls.
* Backed by **SQLite** (a local .sqlite file). Values are serialized as JSON text.
