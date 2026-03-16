"""
aws_gcp_tool — Interact with AWS and Google Cloud Platform cloud services.

AWS (requires: pip install boto3)
Env vars: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION

GCP (requires: pip install google-cloud-storage google-cloud-compute)
Env vars: GOOGLE_APPLICATION_CREDENTIALS (path to service-account JSON),
          GCP_PROJECT_ID

Actions — AWS S3
───────────────────────────────────────────────────────────────────
  s3_list_buckets    : List all S3 buckets in the account.
  s3_list_objects    : List objects in a bucket (optionally under a prefix).
  s3_upload          : Upload a local file to S3 (sandboxed local path).
  s3_download        : Download an S3 object to agent_output/cloud/.
  s3_delete          : Delete a single S3 object (requires confirm="yes").

Actions — AWS EC2
───────────────────────────────────────────────────────────────────
  ec2_list_instances : List EC2 instances with state, type, and public IP.
  ec2_start          : Start a stopped instance.
  ec2_stop           : Stop a running instance (requires confirm="yes").
  ec2_reboot         : Reboot an instance (requires confirm="yes").

Actions — GCP Storage
───────────────────────────────────────────────────────────────────
  gcs_list_buckets   : List GCS buckets in the project.
  gcs_list_objects   : List objects in a GCS bucket.
  gcs_upload         : Upload a local file to GCS.
  gcs_download       : Download a GCS object to agent_output/cloud/.
  gcs_delete         : Delete a GCS object (requires confirm="yes").
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
_CLOUD_DIR    = Path(__file__).parent.parent / "agent_output" / "cloud"

_MAX_ITEMS = 50


def aws_gcp_tool(
    action: str,
    bucket: str = "",
    key: str = "",
    local_path: str = "",
    prefix: str = "",
    instance_id: str = "",
    region: str = "",
    confirm: str = "",
    project: str = "",
) -> str:
    """
    Interact with AWS and GCP cloud services.

    action      : One of the actions listed in the module docstring.
    bucket      : S3 / GCS bucket name.
    key         : S3 / GCS object key (filename in the bucket).
    local_path  : Local file path for upload/download (sandboxed to project dir).
    prefix      : Object prefix filter for list operations.
    instance_id : EC2 instance ID (e.g. 'i-0abc123def').
    region      : AWS region override (defaults to AWS_DEFAULT_REGION).
    confirm     : Pass 'yes' for destructive operations (delete, stop, reboot).
    project     : GCP project ID (defaults to GCP_PROJECT_ID env var).
    """
    action = (action or "").strip().lower()
    if not action:
        return "Error: 'action' is required."

    if action.startswith("s3_") or action.startswith("ec2_"):
        return _aws_dispatch(action, bucket, key, local_path, prefix,
                             instance_id, region, confirm)

    if action.startswith("gcs_"):
        return _gcs_dispatch(action, bucket, key, local_path, prefix,
                             confirm, project)

    return f"Unknown action '{action}'. See module docstring for valid actions."


# ──────────────────────────────────────────────────────────────────────────────
# AWS
# ──────────────────────────────────────────────────────────────────────────────

def _aws_dispatch(
    action: str, bucket: str, key: str, local_path: str, prefix: str,
    instance_id: str, region: str, confirm: str,
) -> str:
    try:
        import boto3  # type: ignore
        from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
    except ImportError:
        return "Error: boto3 is not installed.\nInstall with: pip install boto3"

    # Validate credentials exist
    if not os.environ.get("AWS_ACCESS_KEY_ID") or not os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return (
            "Error: AWS credentials not set.\n"
            "Add AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY to your .env file."
        )

    region = region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    try:
        if action == "s3_list_buckets":
            s3 = boto3.client("s3")
            resp = s3.list_buckets()
            buckets = resp.get("Buckets", [])
            if not buckets:
                return "No S3 buckets found."
            lines = ["S3 Buckets:"]
            for b in buckets[:_MAX_ITEMS]:
                lines.append(f"  • {b['Name']}  (created: {b['CreationDate'].strftime('%Y-%m-%d')})")
            return "\n".join(lines)

        if action == "s3_list_objects":
            if not bucket:
                return "Error: 'bucket' is required."
            s3 = boto3.client("s3")
            kwargs = {"Bucket": bucket, "MaxKeys": _MAX_ITEMS}
            if prefix:
                kwargs["Prefix"] = prefix
            resp = s3.list_objects_v2(**kwargs)
            objects = resp.get("Contents", [])
            if not objects:
                return f"No objects in s3://{bucket}/{prefix or ''}"
            lines = [f"Objects in s3://{bucket}/{prefix or ''}:"]
            for obj in objects:
                size = _human_size(obj["Size"])
                lines.append(f"  • {obj['Key']}  ({size}, {obj['LastModified'].strftime('%Y-%m-%d')})")
            return "\n".join(lines)

        if action == "s3_upload":
            if not bucket or not local_path:
                return "Error: 'bucket' and 'local_path' are required."
            src = _safe_path(local_path)
            if src is None:
                return "❌ Security: local_path is outside the project directory."
            if not src.exists():
                return f"Error: File not found — {src}"
            obj_key = key or src.name
            s3 = boto3.client("s3", region_name=region)
            s3.upload_file(str(src), bucket, obj_key)
            return f"Uploaded: {src.name} → s3://{bucket}/{obj_key}"

        if action == "s3_download":
            if not bucket or not key:
                return "Error: 'bucket' and 'key' are required."
            _CLOUD_DIR.mkdir(parents=True, exist_ok=True)
            fname = key.split("/")[-1] or "download"
            dest  = _CLOUD_DIR / fname
            s3 = boto3.client("s3", region_name=region)
            s3.download_file(bucket, key, str(dest))
            return f"Downloaded: s3://{bucket}/{key} → {dest}"

        if action == "s3_delete":
            if not bucket or not key:
                return "Error: 'bucket' and 'key' are required."
            if confirm.strip().lower() != "yes":
                return f"⚠ Pass confirm='yes' to permanently delete s3://{bucket}/{key}."
            s3 = boto3.client("s3", region_name=region)
            s3.delete_object(Bucket=bucket, Key=key)
            return f"Deleted: s3://{bucket}/{key}"

        if action == "ec2_list_instances":
            ec2 = boto3.client("ec2", region_name=region)
            resp = ec2.describe_instances()
            lines = [f"EC2 Instances ({region}):"]
            for res in resp["Reservations"]:
                for inst in res["Instances"]:
                    name = next(
                        (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                        "(unnamed)",
                    )
                    lines.append(
                        f"  • {inst['InstanceId']}  [{inst['State']['Name']}]  "
                        f"{inst['InstanceType']}  {inst.get('PublicIpAddress', 'no-ip')}  "
                        f"Name: {name}"
                    )
            return "\n".join(lines) if len(lines) > 1 else "No EC2 instances found."

        if action in ("ec2_start", "ec2_stop", "ec2_reboot"):
            if not instance_id:
                return f"Error: 'instance_id' is required for {action}."
            if action != "ec2_start" and confirm.strip().lower() != "yes":
                return f"⚠ Pass confirm='yes' to {action.split('_')[1]} instance {instance_id}."
            ec2 = boto3.client("ec2", region_name=region)
            verb = action.split("_")[1]
            if verb == "start":
                ec2.start_instances(InstanceIds=[instance_id])
            elif verb == "stop":
                ec2.stop_instances(InstanceIds=[instance_id])
            else:
                ec2.reboot_instances(InstanceIds=[instance_id])
            return f"EC2 instance {instance_id}: {verb} command sent."

        return f"Unknown AWS action '{action}'."

    except ClientError as exc:  # type: ignore[possibly-undefined]
        return f"AWS error ({exc.response['Error']['Code']}): {exc.response['Error']['Message']}"
    except Exception as exc:
        logger.error("aws_gcp_tool: %s", exc)
        return f"Error: {exc}"


# ──────────────────────────────────────────────────────────────────────────────
# GCP
# ──────────────────────────────────────────────────────────────────────────────

def _gcs_dispatch(
    action: str, bucket: str, key: str, local_path: str, prefix: str,
    confirm: str, project: str,
) -> str:
    try:
        from google.cloud import storage as gcs  # type: ignore
    except ImportError:
        return (
            "Error: google-cloud-storage not installed.\n"
            "Install with: pip install google-cloud-storage"
        )

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    project_id = project or os.environ.get("GCP_PROJECT_ID", "").strip()

    if not creds_path:
        return (
            "Error: GOOGLE_APPLICATION_CREDENTIALS is not set.\n"
            "Set it to the path of your GCP service account JSON key file."
        )

    try:
        client = gcs.Client(project=project_id) if project_id else gcs.Client()

        if action == "gcs_list_buckets":
            buckets = list(client.list_buckets())[:_MAX_ITEMS]
            if not buckets:
                return "No GCS buckets found."
            return "GCS Buckets:\n" + "\n".join(f"  • {b.name}" for b in buckets)

        if action == "gcs_list_objects":
            if not bucket:
                return "Error: 'bucket' is required."
            blobs = list(client.list_blobs(bucket, prefix=prefix or None, max_results=_MAX_ITEMS))
            if not blobs:
                return f"No objects in gs://{bucket}/{prefix or ''}"
            lines = [f"Objects in gs://{bucket}/{prefix or ''}:"]
            for blob in blobs:
                lines.append(f"  • {blob.name}  ({_human_size(blob.size)})")
            return "\n".join(lines)

        if action == "gcs_upload":
            if not bucket or not local_path:
                return "Error: 'bucket' and 'local_path' are required."
            src = _safe_path(local_path)
            if src is None:
                return "❌ Security: local_path is outside the project directory."
            if not src.exists():
                return f"Error: File not found — {src}"
            blob_name = key or src.name
            b = client.bucket(bucket)
            blob = b.blob(blob_name)
            blob.upload_from_filename(str(src))
            return f"Uploaded: {src.name} → gs://{bucket}/{blob_name}"

        if action == "gcs_download":
            if not bucket or not key:
                return "Error: 'bucket' and 'key' are required."
            _CLOUD_DIR.mkdir(parents=True, exist_ok=True)
            fname = key.split("/")[-1] or "download"
            dest  = _CLOUD_DIR / fname
            b    = client.bucket(bucket)
            blob = b.blob(key)
            blob.download_to_filename(str(dest))
            return f"Downloaded: gs://{bucket}/{key} → {dest}"

        if action == "gcs_delete":
            if not bucket or not key:
                return "Error: 'bucket' and 'key' are required."
            if confirm.strip().lower() != "yes":
                return f"⚠ Pass confirm='yes' to permanently delete gs://{bucket}/{key}."
            b    = client.bucket(bucket)
            blob = b.blob(key)
            blob.delete()
            return f"Deleted: gs://{bucket}/{key}"

        return f"Unknown GCP action '{action}'."

    except Exception as exc:
        logger.error("aws_gcp_tool (GCP): %s", exc)
        return f"GCP error: {exc}"


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def _safe_path(p: str) -> Path | None:
    path = Path(p)
    if not path.is_absolute():
        path = (_PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    pr = str(_PROJECT_ROOT)
    if str(path) == pr or str(path).startswith(pr + os.sep):
        return path
    return None


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
