# Renaming programs, blocks and days; saved chat history (per user, with
# each change's current status so a reload shows the right buttons).
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app import models, schemas
from app.routers.changes import undo_change
from app.routers.chat import clear_chat_history, get_chat_history, send_chat_message
from app.routers.programs import rename_program
from app.routers.structure import rename_day_template, rename_mesocycle


def test_program_block_and_day_can_be_renamed(db_session, owner_and_prescription):
    user, prescription = owner_and_prescription
    day = prescription.exercise_slot.day_template
    mesocycle = day.mesocycle

    assert rename_program(mesocycle.program_id, schemas.Rename(name="  Summer cut  "), db_session, user).name == "Summer cut"
    assert rename_mesocycle(mesocycle.id, schemas.Rename(name="Block 1"), db_session, user).name == "Block 1"
    assert rename_day_template(day.id, schemas.Rename(name="Push"), db_session, user).name == "Push"


def test_renaming_someone_elses_program_is_refused(db_session, owner_and_prescription, other_user):
    _, prescription = owner_and_prescription
    program_id = prescription.exercise_slot.day_template.mesocycle.program_id
    with pytest.raises(HTTPException) as exc_info:
        rename_program(program_id, schemas.Rename(name="mine now"), db_session, other_user)
    assert exc_info.value.status_code == 404


def _make_it_4_sets(db_session, user, prescription):
    route = SimpleNamespace(
        tool="adjust_prescription", field_id=prescription.id, target_field="sets",
        adjustment_kind="set_value", requested_value="4", requested_change="make it 4 sets",
        question=None, topic=None,
    )
    generate = MagicMock(return_value=(SimpleNamespace(sets=4, chunk_ids=[], grounding="general_knowledge"), []))
    with patch("app.routers.chat.route_chat_message", return_value=route), \
         patch("app.routers.generation.verify_citation", return_value="contradicted"), \
         patch.dict("app.routers.chat._ADJUST_FIELDS", {"sets": (generate, lambda m, g: "q")}):
        return send_chat_message(
            request=schemas.ChatMessageRequest(
                message="make it 4 sets", field_id=prescription.id, anchor_label="Bench Press, week 1",
            ),
            db=db_session, current_user=user,
        )


def test_history_is_saved_with_each_changes_current_status(db_session, owner_and_prescription, other_user):
    user, prescription = owner_and_prescription
    db_session.query(models.ChatMessage).filter_by(user_id=user.id).delete()
    response = _make_it_4_sets(db_session, user, prescription)

    turns = get_chat_history(db=db_session, current_user=user)
    assert [t.role for t in turns] == ["user", "assistant"]
    assert turns[0].content == {"text": "make it 4 sets", "anchor": "Bench Press, week 1"}
    assert turns[1].content["change_id"] == response.change_id
    assert turns[1].change_status == "applied"
    assert get_chat_history(db=db_session, current_user=other_user) == []  # per user

    undo_change(change_id=response.change_id, db=db_session, current_user=user)
    assert get_chat_history(db=db_session, current_user=user)[1].change_status == "undone"

    clear_chat_history(db=db_session, current_user=user)
    assert get_chat_history(db=db_session, current_user=user) == []
