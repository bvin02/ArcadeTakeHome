# Arcade Store (Python + Flask + SQLite)

A transactional key-value store with nested transactions, a Flask REST API, and tests.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
ENABLE_STORE_DUMP=1 ENABLE_STORE_LOG=1 python api.py
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

---
## Sample usage of the key-value store (via API with curl) 
---

**Tip**: install jq to pretty-print JSON (brew install jq on macOS). It’s optional 

### 0) Start the API server in one terminal
```bash
ENABLE_STORE_DUMP=1 ENABLE_STORE_LOG=1 python api.py
# ENABLE_STORE_DUMP enables GET /store (full committed DB dump)
# ENABLE_STORE_LOG enables GET /_debug/commit_log.txt (commit log view)
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

### 6) Nested transactions
Begin outer tx:
```bash
curl -s -X POST http://localhost:8000/session/$SID/begin | jq
# → {"ok":true,"depth":1}

# stage a change in outer tx
curl -s -X PUT "http://localhost:8000/store/nested:key" \
  -H "Content-Type: application/json" -H "X-Session-ID: $SID" \
  -d '{"value":"outer"}' | jq

# Read WITHIN the session (sees staged "outer")
curl -s -X GET "http://localhost:8000/store/nested:key" -H "X-Session-ID: $SID" | jq

# Read WITHOUT the session (404)
curl -s -X GET "http://localhost:8000/store/nested:key" | jq
```
Begin inner transaction:
```bash
# override key
curl -s -X POST http://localhost:8000/session/$SID/begin | jq # → {"ok":true,"depth":2}

curl -s -X PUT "http://localhost:8000/store/nested:key" \
  -H "Content-Type: application/json" -H "X-Session-ID: $SID" \
  -d '{"value":"inner"}' | jq

# Inside session → shows inner value
curl -s -X GET "http://localhost:8000/store/nested:key" -H "X-Session-ID: $SID" | jq
# → {"key":"nested:key","value":"inner","found":true}
```
Merge inner transaction:
```bash
curl -s -X POST http://localhost:8000/session/$SID/commit | jq
# → {"ok":true,"depth":1}

# Still only visible IN session
curl -s -X GET "http://localhost:8000/store/nested:key" -H "X-Session-ID: $SID" | jq # → {"key":"nested:key","value":"inner","found":true}
curl -s -X GET "http://localhost:8000/store/nested:key" | jq # 404
```
Rollback outer transaction:
```bash
curl -s -X POST http://localhost:8000/session/$SID/rollback | jq
# → {"ok":true,"depth":0}

# Gone everywhere
curl -s -X GET "http://localhost:8000/store/nested:key" -H "X-Session-ID: $SID" | jq
curl -s -X GET "http://localhost:8000/store/nested:key" | jq
```

### 7) View commit log (if logging enabled)
```bash
curl -s http://localhost:8000/_debug/commit_log.txt
```
