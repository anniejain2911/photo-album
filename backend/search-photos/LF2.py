
import os
import json
import re
import uuid
import logging
from urllib.parse import quote as url_quote

import boto3
from botocore.session import Session
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth
import urllib3

log = logging.getLogger()
log.setLevel(logging.INFO)

OS_HOST   = os.environ.get("OS_HOST")                 
OS_REGION = os.environ.get("OS_REGION", "us-west-2")
OS_INDEX  = os.environ.get("OS_INDEX", "photos")

AWS_REGION = os.environ.get("AWS_REGION", OS_REGION)

LEX_BOT_ID   = os.environ.get("LEX_BOT_ID", "")
LEX_ALIAS_ID = os.environ.get("LEX_ALIAS_ID", "")
LEX_LOCALE   = os.environ.get("LEX_LOCALE", "en_US")

http = urllib3.PoolManager()
lex  = boto3.client("lexv2-runtime") if (LEX_BOT_ID and LEX_ALIAS_ID) else None

# --- Helpers ------------------------------------------------------------------
def _ok(body: dict, status: int = 200):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "x-api-key,Content-Type",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
        },
        "body": json.dumps(body),
    }

def _err(msg: str, status: int = 500):
    log.error(msg)
    return _ok({"error": msg}, status)

STOP = {
    "a","an","the","and","or","of","to","in","on","with","for","from","by",
    "is","are","this","that","these","those","me","my","our","your","their",
    "photo","photos","image","images","pic","pics","show","find","search"
}

def _normalize_tokens(text: str):
    tokens = re.sub(r"[^a-z0-9\s]+", " ", (text or "").lower()).split()
    tokens = [t for t in tokens if t and t not in STOP]
    seen = {}
    return [seen.setdefault(t, t) for t in tokens if t not in seen]

def _tokens_from_lex_or_text(q: str):
    q = (q or "").strip()
    if not q:
        return []
    if lex:
        try:
            resp = lex.recognize_text(
                botId=LEX_BOT_ID,
                botAliasId=LEX_ALIAS_ID,
                localeId=LEX_LOCALE,
                sessionId=str(uuid.uuid4()),
                text=q,
            )
            slots = (resp.get("sessionState", {}).get("intent", {}) or {}).get("slots", {}) or {}
            values = []
            for s in slots.values():
                v = (s or {}).get("value", {})
                if "interpretedValue" in v and v["interpretedValue"]:
                    values.append(v["interpretedValue"])
            if values:
                return _normalize_tokens(" ".join(values))
        except Exception:
            log.exception("Lex recognize_text failed; fallback to text parsing")
    return _normalize_tokens(q)

def _signed_es_request(method: str, path: str, body: dict | None):
    """
    Send a SigV4-signed HTTP request to OpenSearch.
    path like '/photos/_search'
    """
    if not OS_HOST:
        raise RuntimeError("OS_HOST env var is required")

    url = f"https://{OS_HOST}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None

    session = Session()
    creds = session.get_credentials().get_frozen_credentials()
    req = AWSRequest(method=method, url=url, data=data, headers={"Content-Type": "application/json"})
    SigV4Auth(creds, "es", OS_REGION).add_auth(req)

    headers = {k: v for k, v in req.headers.items()}

    return http.request(method, url, body=data, headers=headers, timeout=urllib3.Timeout(connect=3.0, read=8.0))

def _search_opensearch(tokens: list[str], size: int = 30):
    """
    Query OpenSearch 'photos' index.
    We match tokens against analyzed 'labels' text, exact 'labels.raw', and 'objectKey'.
    """
    if not tokens:
        return []

    should = [{"match": {"labels": t}} for t in tokens]
    should.append({"terms": {"labels.raw": tokens}})
    should.append({"terms": {"objectKey": tokens}})

    body = {
        "size": size,
        "_source": ["objectKey", "bucket"],
        "query": {
            "bool": {
                "should": should,
                "minimum_should_match": 1
            }
        }
    }