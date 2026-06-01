import unittest

from stripe_link.repositories.documents import ResourceIsolationError, DynamoDocumentRepository, TenantRangeRepository


class PaginatedTable:
    def __init__(self):
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        if "ExclusiveStartKey" not in kwargs:
            return {
                "Items": [
                    {
                        "PK": "TENANT#tenant-1",
                        "SK": "PRODUCT#product-1",
                        "GSI1PK": "PRODUCT#product-1",
                        "GSI1SK": "TENANT#tenant-1",
                        "tenant_id": "tenant-1",
                        "product_id": "product-1",
                    }
                ],
                "LastEvaluatedKey": {"PK": "TENANT#tenant-1", "SK": "PRODUCT#product-1"},
            }
        return {
            "Items": [
                {
                    "PK": "TENANT#tenant-1",
                    "SK": "PRODUCT#product-2",
                    "GSI1PK": "PRODUCT#product-2",
                    "GSI1SK": "TENANT#tenant-1",
                    "tenant_id": "tenant-1",
                    "product_id": "product-2",
                }
            ]
        }


class PaginatedTenantRangeTable:
    def __init__(self):
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        if "ExclusiveStartKey" not in kwargs:
            return {
                "Items": [{"tenant_id": "tenant-1", "customer_id": "customer-1"}],
                "LastEvaluatedKey": {"tenant_id": "tenant-1", "customer_id": "customer-1"},
            }
        return {"Items": [{"tenant_id": "tenant-1", "customer_id": "customer-2"}]}


class RepositoryGuardTests(unittest.TestCase):
    def test_repository_rejects_non_jb_table(self):
        with self.assertRaises(ResourceIsolationError):
            DynamoDocumentRepository("products-dev", document_type="product", id_field="product_id", table=object())

    def test_repository_accepts_jb_table(self):
        repository = DynamoDocumentRepository("jb-products-dev", document_type="product", id_field="product_id", table=object())

        self.assertEqual(repository.table_name, "jb-products-dev")

    def test_document_repository_lists_all_query_pages(self):
        table = PaginatedTable()
        repository = DynamoDocumentRepository(
            "jb-products-dev",
            document_type="product",
            id_field="product_id",
            table=table,
        )

        documents = repository.list_for_tenant("tenant-1")

        self.assertEqual(
            documents,
            [
                {"tenant_id": "tenant-1", "product_id": "product-1"},
                {"tenant_id": "tenant-1", "product_id": "product-2"},
            ],
        )
        self.assertEqual(len(table.calls), 2)
        self.assertEqual(table.calls[1]["ExclusiveStartKey"], {"PK": "TENANT#tenant-1", "SK": "PRODUCT#product-1"})

    def test_tenant_range_repository_lists_all_query_pages(self):
        table = PaginatedTenantRangeTable()
        repository = TenantRangeRepository("jb-customers-dev", id_field="customer_id", table=table)

        documents = repository.list_for_tenant("tenant-1")

        self.assertEqual(
            documents,
            [
                {"tenant_id": "tenant-1", "customer_id": "customer-1"},
                {"tenant_id": "tenant-1", "customer_id": "customer-2"},
            ],
        )
        self.assertEqual(len(table.calls), 2)
        self.assertEqual(table.calls[1]["ExclusiveStartKey"], {"tenant_id": "tenant-1", "customer_id": "customer-1"})


if __name__ == "__main__":
    unittest.main()
