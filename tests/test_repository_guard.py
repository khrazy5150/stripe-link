import unittest

from stripe_link.repositories.documents import ResourceIsolationError, DynamoDocumentRepository


class RepositoryGuardTests(unittest.TestCase):
    def test_repository_rejects_non_jb_table(self):
        with self.assertRaises(ResourceIsolationError):
            DynamoDocumentRepository("products-dev", document_type="product", id_field="product_id", table=object())

    def test_repository_accepts_jb_table(self):
        repository = DynamoDocumentRepository("jb-products-dev", document_type="product", id_field="product_id", table=object())

        self.assertEqual(repository.table_name, "jb-products-dev")


if __name__ == "__main__":
    unittest.main()
