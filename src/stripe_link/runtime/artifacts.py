# Sale / Flash-Sale context views publish as sibling artifacts of the base page (plans/SALES_FUNNELS.md P1c),
# so a Site can route /sale and /flash-sale to distinct HTML rendered in that price context.
_CONTEXT_SUBPATH = {"sale": "sale", "flash_sale": "flash-sale"}


def artifact_paths(tenant_id: str, page_id: str, slug: str = "", context: str = "", mode: str = "live") -> dict[str, str]:
    # Stripe-mode partitioning (plans/STRIPE_MODE_DECOUPLING.md P5): live pages keep the root key (byte-identical
    # to before — the critical serving path is untouched); test pages get a `test/` prefix so a test page and its
    # live promotion (same page_id) don't collide in the one bucket. Default "live" keeps every un-updated caller
    # on the root key (a forgotten reader fail-safes to a 404, never a cross-mode serve).
    prefix = "test/" if str(mode or "").strip().lower() == "test" else ""
    sub = _CONTEXT_SUBPATH.get(str(context or ""), "")
    key = f"{prefix}{page_id}/{sub}/index.html" if sub else f"{prefix}{page_id}/index.html"
    preview_key = (
        f"preview/{prefix}{tenant_id}/{page_id}/{sub}/index.html" if sub
        else f"preview/{prefix}{tenant_id}/{page_id}/index.html"
    )
    return {
        "preview": preview_key,
        "test": key,
        "published": key,
    }


def cloudfront_path(s3_key: str) -> str:
    return f"/{s3_key.lstrip('/')}"
