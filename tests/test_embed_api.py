"""Embedding transport contract tests: every provider client is an in-memory fake."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from app import config, embed


class FakeClient:
    def __init__(self, handler=None):
        self.calls = []
        self.handler = handler or self.valid
        self.embeddings = self

    def valid(self, inputs):
        entries = []
        for index, text in enumerate(inputs):
            vector = [0.0] * config.EMBED_DIMENSIONS
            vector[0 if text.startswith("a") else 1] = 3.0
            entries.append(SimpleNamespace(index=index, embedding=vector))
        return SimpleNamespace(data=list(reversed(entries)))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.handler(kwargs['input'])


class EmbedAPITests(unittest.TestCase):
    def setUp(self):
        self.settings = patch.multiple(
            config, EMBED_BACKEND='openai', EMBED_MODEL='text-embedding-v4',
            EMBED_API_KEY='embedding-test-key', EMBED_BASE_URL='https://embed.example/v1/',
            EMBED_DIMENSIONS=64, EMBED_BATCH=10, EMBED_TIMEOUT=25.0,
            EMBED_RETRIES=1, EMBED_CONCURRENCY=2)
        self.settings.start()
        self.cache = patch.multiple(embed, _client=None, _client_settings=None, _remote_gate=None)
        self.cache.start()
        self.addCleanup(self.settings.stop)
        self.addCleanup(self.cache.stop)

    def use_client(self, fake):
        factory = SimpleNamespace(OpenAI=lambda **kwargs: fake)
        replacement = patch.dict(sys.modules, {'openai': factory})
        replacement.start()
        self.addCleanup(replacement.stop)
        return fake

    def test_batches_restore_provider_index_order_and_normalize(self):
        fake = self.use_client(FakeClient())
        texts = ['a' if index % 2 == 0 else 'b' for index in range(23)]
        vectors = embed.encode(texts)
        # Batches run side by side (rc4), so they may reach the provider in any order.
        self.assertEqual(sorted((len(call['input']) for call in fake.calls), reverse=True), [10, 10, 3])
        self.assertEqual(vectors.shape, (23, 64))
        self.assertEqual(vectors.dtype, np.float32)
        np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0)
        np.testing.assert_array_equal(np.argmax(vectors, axis=1), [index % 2 for index in range(23)])
        for call in fake.calls:
            self.assertEqual(call['model'], 'text-embedding-v4')
            self.assertEqual(call['dimensions'], 64)
            self.assertEqual(call['encoding_format'], 'float')

    def test_bad_dimensions_nan_infinity_and_zero_fail(self):
        for vector in ([1.0] * 63, [float('nan')] * 64,
                       [float('inf')] * 64, [0.0] * 64):
            with self.subTest(vector=vector[0]):
                fake = FakeClient(lambda inputs: SimpleNamespace(
                    data=[SimpleNamespace(index=0, embedding=vector)]))
                with patch.object(embed, '_get_remote_client', return_value=(fake, threading.Semaphore(1))):
                    with self.assertRaises(ValueError):
                        embed.encode(['a'])

    def test_missing_duplicate_and_invalid_indices_fail(self):
        vector = [1.0] * 64
        for indices in ([], [0], [0, 0], [0, 2], [0, None], [0, True]):
            with self.subTest(indices=indices):
                fake = FakeClient(lambda inputs: SimpleNamespace(
                    data=[SimpleNamespace(index=index, embedding=vector) for index in indices]))
                with patch.object(embed, '_get_remote_client', return_value=(fake, threading.Semaphore(1))):
                    with self.assertRaises(ValueError):
                        embed.encode(['a', 'b'])

    def test_credentials_and_endpoint_do_not_inherit_llm_settings(self):
        constructor = unittest.mock.Mock(return_value=FakeClient())
        with patch.dict(sys.modules, {'openai': SimpleNamespace(OpenAI=constructor)}), \
             patch.multiple(config, LLM_API_KEY='llm-only-secret', LLM_BASE_URL='https://llm.example/v1'):
            embed.encode(['a'])
        kwargs = constructor.call_args.kwargs
        self.assertEqual(kwargs['api_key'], 'embedding-test-key')
        self.assertEqual(kwargs['base_url'], 'https://embed.example/v1')
        self.assertEqual(kwargs['timeout'], 25.0)
        # rc4: the SDK makes no retries of its own; deadline.call makes
        # AMI_EMBED_RETRIES of them, each clipped to the request deadline.
        self.assertEqual(kwargs['max_retries'], 0)
        with patch.object(config, 'EMBED_API_KEY', ''):
            with self.assertRaisesRegex(ValueError, 'AMI_EMBED_API_KEY'):
                embed.encode(['a'])
        with patch.object(config, 'EMBED_BASE_URL', ''):
            with self.assertRaisesRegex(ValueError, 'AMI_EMBED_BASE_URL'):
                embed.encode(['a'])

    def test_environment_key_selection_is_separate_and_bge_remains_default(self):
        spec = importlib.util.spec_from_file_location('isolated_config', Path(config.__file__))
        for values, expected in (
            ({'OPENAI_API_KEY': 'llm-only'}, ''),
            ({'DASHSCOPE_API_KEY': 'dashscope-key', 'OPENAI_API_KEY': 'llm-only'}, 'dashscope-key'),
            ({'AMI_EMBED_API_KEY': 'explicit', 'DASHSCOPE_API_KEY': 'other'}, 'explicit')):
            with patch.dict(os.environ, values, clear=True):
                fresh = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(fresh)
            self.assertEqual(fresh.EMBED_API_KEY, expected)
            self.assertEqual(fresh.EMBED_BASE_URL, '')
            self.assertEqual(fresh.EMBED_BACKEND, 'bge')
            self.assertEqual(fresh.EMBED_MODEL, 'BAAI/bge-small-en-v1.5')
            self.assertEqual(fresh.EMBED_BATCH, 64)
        with patch.dict(os.environ, {'AMI_EMBED_BACKEND': 'openai'}, clear=True):
            fresh = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(fresh)
        self.assertEqual(fresh.EMBED_MODEL, 'text-embedding-v4')
        self.assertEqual(fresh.EMBED_DIMENSIONS, 1024)
        self.assertEqual(fresh.EMBED_BATCH, 10)
        self.assertEqual(fresh.EMBED_API_KEY, '')

    def test_query_prefix_local_only(self):
        fake = self.use_client(FakeClient())
        embed.encode(['a question'], is_query=True)
        self.assertEqual(fake.calls[0]['input'], ['a question'])
        model = unittest.mock.Mock()
        model.encode.return_value = np.ones((1, 4), dtype=np.float32)
        with patch.object(config, 'EMBED_BACKEND', 'bge'), patch.object(embed, '_get_model', return_value=model):
            embed.encode(['a question'], is_query=True)
            self.assertEqual(model.encode.call_args.args[0], [embed.QUERY_PREFIX + 'a question'])

    def test_provider_failure_propagates_without_local_fallback(self):
        def fail(inputs):
            raise RuntimeError('provider rejection')
        fake = self.use_client(FakeClient(fail))
        with patch.object(embed, '_get_model', side_effect=AssertionError('local fallback')):
            with self.assertRaisesRegex(RuntimeError, 'provider rejection'):
                embed.encode(['a'])
        self.assertEqual(len(fake.calls), 1)

    def test_no_items_dim_and_identity_do_not_initialize_any_client(self):
        with patch.object(embed, '_get_remote_client', side_effect=AssertionError('client initialized')), \
             patch.object(embed, '_get_model', side_effect=AssertionError('model initialized')):
            empty = embed.encode([])
            self.assertEqual(empty.shape, (0, 64))
            self.assertEqual(empty.dtype, np.float32)
            self.assertEqual(embed.dim(), 64)
            identity = embed.embedding_identity()
            self.assertEqual(identity['query_preprocess'], 'identity')
            self.assertNotIn('embedding-test-key', json.dumps(identity))
            with patch.object(config, 'EMBED_BACKEND', 'bge'):
                embed.embedding_identity()

    def test_long_unicode_text_is_lossless_and_pooling_uses_byte_lengths(self):
        text = 'a' * 2048 + '汉字🙂  \n' * 300
        parts = embed._chunks(text)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(0 < len(part.encode('utf-8')) <= 2048 for part in parts))
        fake = self.use_client(FakeClient())
        vector = embed.encode([text])[0]
        self.assertEqual([part for call in fake.calls for part in call['input']], parts)
        expected = np.zeros(64)
        expected[0] = len(parts[0].encode('utf-8'))
        expected[1] = sum(len(part.encode('utf-8')) for part in parts[1:])
        expected /= np.linalg.norm(expected)
        np.testing.assert_allclose(vector, expected, rtol=1e-6)

    def test_invalid_input_validated_before_any_request(self):
        fake = self.use_client(FakeClient())
        for texts in (['a', ''], ['a', None], ['a', '\ud800']):
            with self.subTest(texts=texts):
                with self.assertRaises((ValueError, UnicodeEncodeError)):
                    embed.encode(texts)
        self.assertEqual(fake.calls, [])

    def test_identity_changes_with_space_not_secrets_and_normalizes_url(self):
        original = embed.embedding_identity()
        with patch.object(config, 'EMBED_API_KEY', 'another-secret'):
            self.assertEqual(embed.embedding_identity(), original)
        with patch.object(config, 'EMBED_BASE_URL', 'HTTPS://EMBED.EXAMPLE:443/v1///'):
            self.assertEqual(embed.embedding_identity(), original)
        with patch.object(config, 'EMBED_DIMENSIONS', 128):
            self.assertNotEqual(embed.embedding_identity(), original)
        with patch.object(config, 'EMBED_BASE_URL', 'https://elsewhere.example/v1'):
            self.assertNotEqual(embed.embedding_identity(), original)

    def test_remote_settings_are_bounded(self):
        invalid = {'EMBED_BATCH': 11, 'EMBED_DIMENSIONS': 3, 'EMBED_TIMEOUT': float('nan'),
                   'EMBED_RETRIES': 4, 'EMBED_CONCURRENCY': 0, 'EMBED_MODEL': 'unregistered-model'}
        for field, value in invalid.items():
            with self.subTest(field=field), patch.object(config, field, value):
                with self.assertRaises(ValueError):
                    embed.encode([])

    def test_endpoint_cannot_leak_credentials_into_public_identity(self):
        for endpoint in ('https://secret@example/v1', 'https://example/v1?api_key=secret',
                         'https://example/v1#secret', 'ftp://example/v1'):
            with self.subTest(endpoint=endpoint), patch.object(config, 'EMBED_BASE_URL', endpoint):
                with self.assertRaises(ValueError):
                    embed.embedding_identity()

    def test_finite_extreme_vectors_normalize_and_cancelled_pool_fails(self):
        fake = self.use_client(FakeClient(lambda inputs: SimpleNamespace(data=[
            SimpleNamespace(index=index, embedding=[1e308 if index == 0 else -1e308] * 64)
            for index in range(len(inputs))])))
        result = embed.encode(['a'])
        np.testing.assert_allclose(np.linalg.norm(result, axis=1), 1.0)
        with self.assertRaisesRegex(ValueError, 'nonzero'):
            embed.encode(['a' * (2 * embed.REMOTE_CHUNK_BYTES)])

    def test_concurrent_calls_share_bounded_provider_gate(self):
        active, maximum = 0, 0
        lock = threading.Lock()
        fake = FakeClient()
        def handler(inputs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.01)
            result = fake.valid(inputs)
            with lock:
                active -= 1
            return result
        fake.handler = handler
        self.use_client(fake)
        threads = [threading.Thread(target=embed.encode, args=(['a'],)) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(fake.calls), 8)
        self.assertLessEqual(maximum, 2)


if __name__ == '__main__':
    unittest.main()
