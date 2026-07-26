# Sale / Flash-Sale context views publish as sibling artifacts of the base page (plans/SALES_FUNNELS.md P1c),
# so a Site can route /sale and /flash-sale to distinct HTML rendered in that price context.
_CONTEXT_SUBPATH = {"sale": "sale", "flash_sale": "flash-sale"}


def artifact_paths(tenant_id: str, page_id: str, slug: str = "", context: str = "") -> dict[str, str]:
    sub = _CONTEXT_SUBPATH.get(str(context or ""), "")
    key = f"{page_id}/{sub}/index.html" if sub else f"{page_id}/index.html"
    preview_key = (
        f"preview/{tenant_id}/{page_id}/{sub}/index.html" if sub
        else f"preview/{tenant_id}/{page_id}/index.html"
    )
    return {
        "preview": preview_key,
        "test": key,
        "published": key,
    }


def cloudfront_path(s3_key: str) -> str:
    return f"/{s3_key.lstrip('/')}"
