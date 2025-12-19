import unittest
from core.providers.utils.normalization import MessageNormalizer

class TestMessageNormalizer(unittest.TestCase):
    def test_merge_contents_strings(self):
        res = MessageNormalizer._merge_contents("Hello", "World")
        self.assertEqual(res, "Hello\nWorld")

    def test_merge_contents_mixed(self):
        res = MessageNormalizer._merge_contents("Hello", [{"type": "image_url", "url": "..."}])
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["text"], "Hello")
        self.assertEqual(res[1]["type"], "image_url")

    def test_merge_contents_lists_optimization(self):
        # Test merging two lists where boundary is text
        list_a = [{"type": "text", "text": "Part A"}]
        list_b = [{"type": "text", "text": "Part B"}]
        res = MessageNormalizer._merge_contents(list_a, list_b)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["text"], "Part A\nPart B")

    def test_normalize_for_openai_basic(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "user", "content": "There"},
            {"role": "assistant", "content": "Hello"}
        ]
        norm = MessageNormalizer.normalize_for_openai(msgs)
        self.assertEqual(len(norm), 2)
        self.assertEqual(norm[0]["content"], "Hi\nThere")
        self.assertEqual(norm[0]["role"], "user")
        self.assertEqual(norm[1]["content"], "Hello")

    def test_normalize_for_openai_empty_cleanup(self):
        msgs = [
            {"role": "user", "content": "Valid"},
            {"role": "assistant", "content": ""},  # Empty string -> Removed
            {"role": "assistant", "content": "   "}, # Whitespace -> Removed
            {"role": "user", "content": None},     # None -> Removed
            {"role": "user", "content": "Also Valid"}
        ]
        norm = MessageNormalizer.normalize_for_openai(msgs)
        # Cleaned: User(Valid), User(Also Valid).
        # Merged: User(Valid\nAlso Valid)
        self.assertEqual(len(norm), 1)
        self.assertEqual(norm[0]["content"], "Valid\nAlso Valid")

    def test_normalize_for_gemini_start_with_assistant(self):
        msgs = [
            {"role": "system", "content": "Sys"},
            {"role": "assistant", "content": "Prefill"}
        ]
        norm = MessageNormalizer.normalize_for_gemini(msgs)
        # Should be System -> User (Dummy) -> Assistant
        self.assertEqual(len(norm), 3)
        self.assertEqual(norm[0]["role"], "system")
        self.assertEqual(norm[1]["role"], "user")
        self.assertEqual(norm[1]["content"], "...")
        self.assertEqual(norm[2]["role"], "assistant")

    def test_normalize_for_gemini_consecutive_users(self):
        msgs = [
            {"role": "user", "content": "1"},
            {"role": "user", "content": "2"},
            {"role": "assistant", "content": "A"},
            {"role": "assistant", "content": "B"}
        ]
        norm = MessageNormalizer.normalize_for_gemini(msgs)
        self.assertEqual(len(norm), 2)
        self.assertEqual(norm[0]["role"], "user")
        self.assertEqual(norm[0]["content"], "1\n2")
        self.assertEqual(norm[1]["role"], "assistant")
        self.assertEqual(norm[1]["content"], "A\nB")

if __name__ == "__main__":
    unittest.main()
