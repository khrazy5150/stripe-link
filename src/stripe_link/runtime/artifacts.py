def artifact_paths(tenant_id: str, page_id: str, slug: str) -> dict[str, str]:
    return {
        "preview": f"preview/{tenant_id}/{page_id}/index.html",
        "test": f"test/{tenant_id}/{slug}/index.html",
        "published": f"published/{tenant_id}/{slug}/index.html",
    }


def cloudfront_path(s3_key: str) -> str:
    return f"/{s3_key.lstrip('/')}"
