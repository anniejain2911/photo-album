import os, json, logging, urllib3, boto3
from datetime import datetime, timezone
from urllib.parse import unquote_plus, quote as url_quote
from botocore.session import Session
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth

log = logging.getLogger()
log.setLevel(logging.INFO)

s3  = boto3.client("s3")
rek = boto3.client("rekognition")

# --------- ENV ----------
OS_HOST     = os.environ["OS_HOST"]            # e.g. search-photos-domain-…us-west-2.es.amazonaws.com
OS_REGION   = os.environ.get("OS_REGION", "us-west-2")
OS_INDEX    = os.environ.get("OS_INDEX", "photos")
MAX_LABELS  = int(os.environ.get("MAX_LABELS", "10"))
MIN_CONF    = int(os.environ.get("MIN_CONFIDENCE", "80"))

http = urllib3.PoolManager()
_creds = Session().get_credentials().get_frozen_credentials()

def _os(method: str, path: str, payload: dict | None):
    """Signed call to OpenSearch."""
    url = f"https://{OS_HOST}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"host": OS_HOST, "content-type": "application/json"}
    req = AWSRequest(method=method, url=url, data=data, headers=headers)
    SigV4Auth(_creds, "es", OS_REGION).add_auth(req)
    r = http.request(method, url, body=data, headers=dict(req.headers))
    if r.status >= 300:
        log.error("OS %s %s -> %s %s", method, path, r.status, r.data)
    else:
        log.info("OS %s %s -> %s", method, path, r.status)
    return r

def _custom_labels(bucket: str, key: str) -> list[str]:
    """From S3 object metadata (x-amz-meta-customlabels)."""
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
        meta = head.get("Metadata") or {}
        raw = meta.get("customlabels") or meta.get("x-amz-meta-customlabels")
        if not raw:
            return []
        return [w.strip().lower() for w in raw.split(",") if w.strip()]
    except Exception:
        log.exception("head_object failed")
        return []

def _rek_labels(bucket: str, key: str) -> list[str]:
    try:
        out = rek.detect_labels(
            Image={"S3Object": {"Bucket": bucket, "Name": key}},
            MaxLabels=MAX_LABELS,
            MinConfidence=MIN_CONF,
        )
        return [l["Name"].lower() for l in out.get("Labels", [])]
    except Exception:
        log.exception("rekognition failed")
        return []

def lambda_handler(event, context):
    log.info("event=%s", json.dumps(event)[:1000])
    for rec in event.get("Records", []):
        bucket = rec["s3"]["bucket"]["name"]
        key    = unquote_plus(rec["s3"]["object"]["key"])

        labels = _rek_labels(bucket, key) + _custom_labels(bucket, key)
        # de-dupe, keep order
        seen = set()
        labels = [x for x in labels if not (x in seen or seen.add(x))]

        doc = {
            "objectKey": key,
            "bucket": bucket,
            # index a single text field so match queries work
            "labels": " ".join(labels),
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }

        # put document (use key as id) and refresh for immediate searchability
        path = f"/{OS_INDEX}/_doc/{url_quote(key, safe='')}"
        _os("PUT", path + "?refresh=true", doc)

    return {"statusCode": 200, "body": json.dumps({"ok": True})}