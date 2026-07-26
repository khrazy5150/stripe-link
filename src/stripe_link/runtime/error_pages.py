from html import escape


def render_error_page(
    status_code: int = 404,
    message: str = "This page is no longer available.",
    *,
    title: str = "",
    badge: str = "",
) -> str:
    """A styled full-page error, ported from stripe-cart's test page server. Server-rendered HTML shared by
    every server-side 404/403 path (the test viewer today; other served-page errors later). Dark gradient
    backdrop, a big gradient status number, the message, and an optional pill badge (e.g. "Test Environment").
    """
    sc = escape(str(status_code))
    msg = escape(str(message))
    ttl = escape(str(title) or f"{status_code} — Not found")
    badge_html = f'        <span class="badge">{escape(str(badge))}</span>\n' if badge else ""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '    <meta charset="UTF-8">\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '    <meta name="robots" content="noindex, nofollow">\n'
        f"    <title>{ttl}</title>\n"
        "    <style>\n"
        "        * { margin: 0; padding: 0; box-sizing: border-box; }\n"
        "        body {\n"
        "            font-family: system-ui, -apple-system, sans-serif;\n"
        "            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);\n"
        "            color: #f1f5f9;\n"
        "            min-height: 100vh;\n"
        "            display: flex;\n"
        "            align-items: center;\n"
        "            justify-content: center;\n"
        "            padding: 20px;\n"
        "        }\n"
        "        .container { text-align: center; max-width: 500px; }\n"
        "        h1 {\n"
        "            font-size: 4rem;\n"
        "            margin-bottom: 1rem;\n"
        "            background: linear-gradient(135deg, #f59e0b, #ef4444);\n"
        "            -webkit-background-clip: text;\n"
        "            background-clip: text;\n"
        "            -webkit-text-fill-color: transparent;\n"
        "        }\n"
        "        p { font-size: 1.25rem; color: #94a3b8; margin-bottom: 2rem; }\n"
        "        .badge {\n"
        "            display: inline-block;\n"
        "            background: rgba(245, 158, 11, 0.1);\n"
        "            border: 1px solid rgba(245, 158, 11, 0.3);\n"
        "            color: #f59e0b;\n"
        "            padding: 0.5rem 1rem;\n"
        "            border-radius: 9999px;\n"
        "            font-size: 0.875rem;\n"
        "        }\n"
        "    </style>\n"
        "</head>\n"
        "<body>\n"
        '    <div class="container">\n'
        f"        <h1>{sc}</h1>\n"
        f"        <p>{msg}</p>\n"
        f"{badge_html}"
        "    </div>\n"
        "</body>\n"
        "</html>"
    )
