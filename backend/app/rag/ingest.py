import datetime
import logging

import inngest

from .corpus import paper
from .data_loader import embed_texts, load_and_chunk_pdf
from .qdrant_storage import QdrantStorage, chunk_point_id
from .types import ChunksAndMeta, UpsertResult

inngest_client = inngest.Inngest(
    app_id="workout_rag",
    logger=logging.getLogger("uvicorn"),
    is_production=False,
    serializer=inngest.PydanticSerializer(),
)


@inngest_client.create_function(
    fn_id="RAG: Ingest Literature PDF",
    trigger=inngest.TriggerEvent(event="rag/ingest_literature"),
    throttle=inngest.Throttle(limit=4, period=datetime.timedelta(minutes=1)),
)
async def ingest_literature_pdf(ctx: inngest.Context):
    def _load(ctx: inngest.Context) -> ChunksAndMeta:
        # The paper must be in corpus/papers.json: its PDF and tags come from there.
        source_id = ctx.event.data["source_id"]
        entry = paper(source_id)
        sectioned = load_and_chunk_pdf(str(entry.pdf_path), entry.text_fixes)
        return ChunksAndMeta(
            chunks=[text for text, _ in sectioned], sections=[section for _, section in sectioned], source_id=source_id,
        )

    def _upsert(data: ChunksAndMeta) -> UpsertResult:
        vecs = embed_texts(data.chunks)
        ids = [chunk_point_id(data.source_id, i, text) for i, text in enumerate(data.chunks)]
        tags = paper(data.source_id).payload()
        payloads = [{**tags, "text": text, "section": section} for text, section in zip(data.chunks, data.sections)]
        QdrantStorage(collection="literature").upsert(ids, vecs, payloads)
        return UpsertResult(ingested=len(data.chunks))

    chunks_and_meta = await ctx.step.run(
        "load-and-chunk", lambda: _load(ctx), output_type=ChunksAndMeta
    )
    result = await ctx.step.run(
        "embed-and-upsert", lambda: _upsert(chunks_and_meta), output_type=UpsertResult
    )
    return result.model_dump()
