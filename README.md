# Arcade Store (Python + Flask + SQLite)

A transactional key-value store with nested transactions, a Flask REST API, and tests.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
ENABLE_STORE_DUMP=1 python api.py
```

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

## Sample usage of the key-value store 

**Tip**: install jq to pretty-print JSON (brew install jq on macOS). It’s optional 

### 0) Start the API server in one terminal
```bash
ENABLE_STORE_DUMP=1 python api.py
# ENABLE_STORE_DUMP env var allows client side to print the entire committed db
```

### 1) Create a client Session in another terminal window and begin a transaction
```bash
SID=$(curl -s -X POST http://localhost:8000/session | jq -r .session_id)
echo "SID=$SID"

# begin tx (depth=1)
curl -s -X POST http://localhost:8000/session/$SID/begin | jq
```

### 2) Stage some writes (not visible globally yet)
```bash
# set two keys inside the open transaction
curl -s -X PUT "http://localhost:8000/store/user:1" \
  -H "Content-Type: application/json" -H "X-Session-ID: $SID" \
  -d '{"value":{"name":"Ava","age":19}}' | jq

curl -s -X PUT "http://localhost:8000/store/user:2" \
  -H "Content-Type: application/json" -H "X-Session-ID: $SID" \
  -d '{"value":{"name":"Ben","age":21}}' | jq

# read inside the session (visible)
curl -s -X GET "http://localhost:8000/store/user:1" -H "X-Session-ID: $SID" | jq
curl -s -X GET "http://localhost:8000/store/user:2" -H "X-Session-ID: $SID" | jq

# read without the session (NOT visible yet)
curl -s -X GET "http://localhost:8000/store/user:1" | jq -r .
curl -s -X GET "http://localhost:8000/store" | jq   # full dump = still empty
```

### 3) Commit (flush staged changes atomically)
```bash
curl -s -X POST http://localhost:8000/session/$SID/commit | jq

# now visible to everyone
curl -s -X GET "http://localhost:8000/store/user:1" | jq
curl -s -X GET "http://localhost:8000/store" | jq    # full dump shows both keys
```

### 4) Open another tx, modify, then rollback
```bash
# begin nested work
curl -s -X POST http://localhost:8000/session/$SID/begin | jq

# update user:1 and delete user:2 (staged only)
curl -s -X PUT "http://localhost:8000/store/user:1" \
  -H "Content-Type: application/json" -H "X-Session-ID: $SID" \
  -d '{"value":{"name":"Ava","age":20,"city":"NYC"}}' | jq

curl -s -X DELETE "http://localhost:8000/store/user:2" -H "X-Session-ID: $SID" | jq

# inside the session: see the staged state
curl -s -X GET "http://localhost:8000/store/user:1" -H "X-Session-ID: $SID" | jq
curl -s -X GET "http://localhost:8000/store/user:2" -H "X-Session-ID: $SID" | jq -r .

# outside the session: still the committed state
curl -s -X GET "http://localhost:8000/store" | jq

# roll back the staged changes (discard)
curl -s -X POST http://localhost:8000/session/$SID/rollback | jq

# verify nothing changed globally
curl -s -X GET "http://localhost:8000/store" | jq
```

### 5) Autocommit path (no sessions)
```bash
# write without X-Session-ID → immediate commit
curl -s -X PUT "http://localhost:8000/store/config:theme" \
  -H "Content-Type: application/json" \
  -d '{"value":"dark"}' | jq

curl -s -X GET "http://localhost:8000/store/config:theme" | jq
curl -s -X GET "http://localhost:8000/store" | jq
```
