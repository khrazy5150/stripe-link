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

    def find_by_id(self, document_id):
        for document in self.documents.values():
            if document.get(self.id_field) == document_id:
                return dict(document)
        return None


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
