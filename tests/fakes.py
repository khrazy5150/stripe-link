class FakeDocumentRepository:
    def __init__(self, id_field):
        self.id_field = id_field
        self.documents = {}

    def put(self, document):
        key = (document["tenant_id"], document[self.id_field])
        self.documents[key] = dict(document)
        return self.documents[key]

    def get(self, tenant_id, document_id):
        document = self.documents.get((tenant_id, document_id))
        return dict(document) if document else None

    def delete(self, tenant_id, document_id):
        document = self.documents.pop((tenant_id, document_id), None)
        return dict(document) if document else None

    def list_for_tenant(self, tenant_id):
        return [
            dict(document)
            for (doc_tenant_id, _), document in self.documents.items()
            if doc_tenant_id == tenant_id
        ]

    def list_page_for_tenant(self, tenant_id, *, limit=None, cursor=""):
        """Mirrors DynamoDocumentRepository: one page plus an opaque cursor ("" when exhausted).
        The fake's cursor is just the offset, base64'd, so tests exercise the same round trip."""
        import base64

        rows = self.list_for_tenant(tenant_id)
        start = 0
        if cursor:
            try:
                start = int(base64.urlsafe_b64decode(cursor.encode()).decode())
            except Exception:  # noqa: BLE001 - a bad bookmark means "from the beginning", as in the real repo
                start = 0
        page = rows[start:] if limit is None else rows[start:start + limit]
        end = start + len(page)
        next_cursor = base64.urlsafe_b64encode(str(end).encode()).decode() if end < len(rows) else ""
        return page, next_cursor

    def find_by_id(self, document_id):
        for document in self.documents.values():
            if document.get(self.id_field) == document_id:
                return dict(document)
        return None

    def scan_type(self):
        return [dict(document) for document in self.documents.values()]

    def find_by_payment_intent(self, payment_intent_id):
        for document in self.documents.values():
            if document.get("payment_intent_id") == payment_intent_id:
                return dict(document)
        return None

    def find_by_stripe_refund(self, stripe_refund_id):
        for document in self.documents.values():
            if document.get("stripe_refund_id") == stripe_refund_id:
                return dict(document)
        return None

    def list_for_order(self, order_id):
        return [dict(document) for document in self.documents.values() if document.get("order_id") == order_id]

    def increment_view(self, tenant_id, document_id, page_id, amount=1):
        document = self.documents.get((tenant_id, document_id))
        if not document:
            return
        stats = document.setdefault("stats", {})
        views = stats.setdefault("views_by_page", {})
        views[page_id] = int(views.get(page_id, 0)) + amount


class FakeSubdomainRegistry:
    """In-memory stand-in for the global subdomain reservation (first-claim-wins, idempotent per site)."""

    def __init__(self):
        self.reservations = {}  # label -> {site_id, tenant_id}

    def owner_of(self, label):
        item = self.reservations.get(str(label or "").strip().lower())
        return item["site_id"] if item else None

    def reservation_of(self, label):
        item = self.reservations.get(str(label or "").strip().lower())
        return dict(item) if item else None

    def reserve(self, label, *, site_id, tenant_id, now):
        label = str(label or "").strip().lower()
        owner = self.reservations.get(label)
        if owner and owner["site_id"] != site_id:
            return False
        self.reservations[label] = {"site_id": site_id, "tenant_id": tenant_id}
        return True


class FakeSimpleRepository:
    def __init__(self, key_field):
        self.key_field = key_field
        self.documents = {}

    def put(self, document):
        self.documents[document[self.key_field]] = dict(document)
        return self.documents[document[self.key_field]]

    def get(self, key_value):
        document = self.documents.get(key_value)
        return dict(document) if document else None


class FakeAppConfigRepository:
    def __init__(self):
        self.documents = {}

    def put(self, document):
        key = (document["config_key"], document["environment"])
        self.documents[key] = dict(document)
        return self.documents[key]

    def get(self, config_key, environment):
        document = self.documents.get((config_key, environment))
        return dict(document) if document else None
