from pathlib import Path

META = {
    "tool_id": "oss_upload",
    "name": "对象存储上传",
    "description": "上传本地文件到 MinIO 对象存储",
    "type": "tool",
    "params_schema": {
        "local_path": {"type": "string", "required": True, "description": "本地文件路径"},
        "remote_key": {"type": "string", "required": True, "description": "远程对象键（路径）"},
    },
}


def execute(local_path: str, remote_key: str) -> dict:
    """上传文件到 MinIO。"""
    p = Path(local_path)
    if not p.exists():
        return {"success": False, "error": f"本地文件不存在: {local_path}"}

    try:
        from minio import Minio
        from agent.config import config

        endpoint = config.get("minio.endpoint", "")
        access_key = config.get("minio.access_key", "")
        secret_key = config.get("minio.secret_key", "")
        bucket = config.get("minio.bucket", "")

        if not all([endpoint, access_key, secret_key, bucket]):
            return {"success": False, "error": "MinIO 配置不完整，请检查 config.yaml"}

        # 解析 endpoint，去掉 scheme
        endpoint_clean = endpoint.replace("http://", "").replace("https://", "")
        secure = endpoint.startswith("https://")

        client = Minio(
            endpoint_clean,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

        # 确保 bucket 存在
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        client.fput_object(bucket, remote_key, str(p.absolute()))

        return {
            "success": True,
            "local_path": str(p.absolute()),
            "remote_key": remote_key,
            "bucket": bucket,
        }
    except ImportError:
        return {"success": False, "error": "minio 库未安装，请执行: pip install minio"}
    except Exception as e:
        return {"success": False, "error": str(e)}
