from typing import Literal

import pydantic

# The four dosage categories each back a generated field and are hard
# retrieval filters for it. 'recovery' (muscle damage, fatigue, time between
# sessions, deloads) backs no generated field, so generation never searches
# it - it keeps those papers out of dosing evidence while chat (which
# searches the whole corpus) can still cite them.
Category = Literal["volume", "frequency", "intensity", "progression", "recovery"]


class ChunksAndMeta(pydantic.BaseModel):
    chunks: list[str]
    source_id: str
    category: Category


class UpsertResult(pydantic.BaseModel):
    ingested: int
