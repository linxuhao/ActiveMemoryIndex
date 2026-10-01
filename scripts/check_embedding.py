"""One synthetic provider check; run with the academic environment file.

No benchmark source, database, LLM, or AML evaluation request is involved.
This makes embedding API calls and therefore requires a configured provider key.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    import numpy as np
    from app import embed

    identity = embed.embedding_identity()
    if identity['backend'] != 'openai' or identity['model'] != 'text-embedding-v4':
        print(json.dumps({'status': 'not_run', 'reason': 'academic embedding profile required'}))
        return 2
    try:
        documents = embed.encode(['A red notebook is on the kitchen shelf.',
                                  'The blue bicycle is inside the garage.'])
        query = embed.encode(['Where is the red notebook?'], is_query=True)
        assert documents.shape == (2, identity['dimensions'])
        assert query.shape == (1, identity['dimensions'])
        assert np.allclose(np.linalg.norm(documents, axis=1), 1)
        assert np.allclose(np.linalg.norm(query, axis=1), 1)
    except Exception as exc:
        # Provider error strings may echo request details: keep the report bounded.
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}))
        return 1
    print(json.dumps({'status': 'passed', 'embedding_identity': identity,
                      'document_rows': 2, 'query_rows': 1, 'unit_vectors': True,
                      'scope': 'Synthetic embedding connectivity and shape only; not platform Smoke or retrieval quality.'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
