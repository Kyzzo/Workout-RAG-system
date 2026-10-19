from typing import Literal

import pydantic

# The four dosage categories each back a generated field and are hard
# retrieval filters for it. 'recovery' (muscle damage, fatigue, time between
# sessions, deloads) and 'exercise-selection' (varying exercises, regional
# growth) back no generated field, so generation never searches them - it
# keeps those papers out of dosing evidence while chat (which searches the
# whole corpus) can still cite them. The same holds for the topics chat
# answers but no field is generated for: rest between sets, nutrition,
# technique (rep tempo, range of motion), stretching, cardio alongside
# lifting, and who is training (sex, age).
Category = Literal[
    "volume", "frequency", "intensity", "progression", "recovery", "exercise-selection",
    "rest-intervals", "nutrition", "technique", "stretching", "concurrent-training", "population",
]


class ChunksAndMeta(pydantic.BaseModel):
    chunks: list[str]
    sections: list[str]  # 'body' or 'references', one per chunk
    source_id: str  # its tags come from corpus/papers.json


class UpsertResult(pydantic.BaseModel):
    ingested: int
