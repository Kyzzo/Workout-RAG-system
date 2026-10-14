from typing import Literal

import pydantic

# The four dosage categories each back a generated field and are hard
# retrieval filters for it. 'recovery' (muscle damage, fatigue, time between
# sessions, deloads) and 'exercise-selection' (varying exercises, regional
# growth) back no generated field, so generation never searches them - it
# keeps those papers out of dosing evidence while chat (which searches the
# whole corpus) can still cite them.
Category = Literal["volume", "frequency", "intensity", "progression", "recovery", "exercise-selection"]


class ChunksAndMeta(pydantic.BaseModel):
    chunks: list[str]
    source_id: str  # its tags come from corpus/papers.json


class UpsertResult(pydantic.BaseModel):
    ingested: int
