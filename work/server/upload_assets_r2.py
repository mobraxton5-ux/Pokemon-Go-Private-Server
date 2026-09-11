"""
Upload the Pokemon asset bundles to a Cloudflare R2 bucket, keyed by their genuine
Niantic asset_id (<guid>/<version>) -- the exact path the client requests. After this,
point the game server at the bucket:

    ASSET_BASE_URL = https://<your-r2-public-url>          (no trailing /asset)

and GET_DOWNLOAD_URLS will hand clients `https://<r2>/<guid>/<version>`, which R2 serves
directly (free egress, global CDN). The game server no longer serves the 65 MB itself.

R2 is S3-compatible, so this uses boto3.
    pip install boto3
Set these env vars (from Cloudflare > R2 > Manage API Tokens, and your account id):
    R2_ACCOUNT_ID          e.g. a1b2c3...            (R2 dashboard URL / account id)
    R2_ACCESS_KEY_ID       the Access Key ID
    R2_SECRET_ACCESS_KEY   the Secret Access Key
    R2_BUCKET              the bucket name you created (e.g. pogo-assets)
Then:
    py upload_assets_r2.py            # upload android + ios, skip ones already there
    py upload_assets_r2.py --force    # re-upload everything

Bundles are immutable, so they're sent with a long-cache header for the CDN.
"""
import os
import sys
import protocol as P

CACHE = "public, max-age=31536000, immutable"


def _client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        sys.exit("boto3 not installed. Run:  pip install boto3")
    acct = os.environ.get("R2_ACCOUNT_ID")
    key = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (acct and key and secret):
        sys.exit("Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY (see header).")
    endpoint = f"https://{acct}.r2.cloudflarestorage.com"
    return boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=key,
                        aws_secret_access_key=secret,
                        config=Config(signature_version="s3v4", region_name="auto"))


def _exists(cli, bucket, key):
    try:
        cli.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def main():
    force = "--force" in sys.argv
    bucket = os.environ.get("R2_BUCKET")
    if not bucket:
        sys.exit("Set R2_BUCKET to your bucket name.")
    cli = _client()

    total = up = skip = miss = 0
    for platform in ("android", "ios"):
        adir = P.assets_dir(platform)
        try:
            digest = P._load_real_digest(platform)
        except Exception as e:
            print(f"[{platform}] no digest ({e}) -- skipping"); continue
        print(f"[{platform}] {len(digest)} bundles -> r2://{bucket}/")
        for bn, m in digest.items():
            total += 1
            key = m["asset_id"]                       # '<guid>/<version>'
            src = os.path.join(adir, bn)
            if not os.path.isfile(src):
                print(f"   MISSING local bundle {bn}"); miss += 1; continue
            if not force and _exists(cli, bucket, key):
                skip += 1; continue
            with open(src, "rb") as fh:
                cli.put_object(Bucket=bucket, Key=key, Body=fh.read(),
                               ContentType="application/octet-stream",
                               CacheControl=CACHE)
            up += 1
            if up % 25 == 0:
                print(f"   ...{up} uploaded")
    print(f"\nDone. uploaded={up} skipped(existing)={skip} missing={miss} of {total}")
    print("Next: make the bucket public (r2.dev URL or a custom domain), then set the")
    print("game server's ASSET_BASE_URL to that base URL.")


if __name__ == "__main__":
    main()
