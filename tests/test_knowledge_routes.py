import unittest
from unittest.mock import patch

import routes.knowledge as knowledge_routes
from routes.knowledge import LocalHashEmbedding, _public_doc, _public_kb


class KnowledgeRouteTestCase(unittest.TestCase):
    def test_public_kb_uses_frontend_contract(self):
        result = _public_kb({
            "kb_id": "kb_1",
            "name": "审核规范",
            "doc_count": 2,
            "chunk_count": 8,
        })
        self.assertEqual(result["kbId"], "kb_1")
        self.assertEqual(result["docCount"], 2)
        self.assertEqual(result["chunkCount"], 8)

    def test_public_doc_uses_frontend_contract(self):
        result = _public_doc({
            "doc_id": "doc_1",
            "filename": "rules.md",
            "chunk_count": 4,
        })
        self.assertEqual(result["docId"], "doc_1")
        self.assertEqual(result["name"], "rules.md")
        self.assertEqual(result["vectorStatus"], "indexed")

    def test_offline_embedding_has_minilm_dimension(self):
        model = LocalHashEmbedding()
        vector = model.encode("高光剪辑规则与标准")
        self.assertEqual(vector.shape, (384,))
        self.assertGreater(float(vector.sum()), 0)

    @patch("routes.knowledge.MODEL_PATH", "")
    @patch("routes.knowledge.SentenceTransformer")
    def test_embedding_falls_back_without_network(self, sentence_transformer):
        original = knowledge_routes.embedding_model
        self.addCleanup(setattr, knowledge_routes, "embedding_model", original)
        knowledge_routes.embedding_model = None
        model = knowledge_routes.get_embedding_model()
        self.assertIsInstance(model, LocalHashEmbedding)
        sentence_transformer.assert_not_called()

    @patch("routes.knowledge.chroma_client")
    def test_chroma_collection_names_are_supported(self, chroma_client):
        chroma_client.list_collections.return_value = ["kb_1"]
        knowledge_routes.get_or_create_collection("kb_1")
        chroma_client.get_collection.assert_called_once_with("kb_1")


if __name__ == "__main__":
    unittest.main()
