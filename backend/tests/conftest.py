import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app import models
from app.database import engine


@pytest.fixture()
def db_session():
    # Standard SQLAlchemy "join an external transaction" pattern: everything
    # the test (and the code it calls, including db.commit()) does happens
    # inside one outer transaction that gets rolled back at the end, so
    # tests never leave data behind in the real dev database.
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(bind=connection)

    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    session.close()
    outer_transaction.rollback()
    connection.close()


@pytest.fixture()
def owner_and_prescription(db_session):
    user = models.User(clerk_user_id="test-clerk-id-owner")
    db_session.add(user)
    db_session.flush()

    program = models.Program(user_id=user.id, goal="hypertrophy")
    db_session.add(program)
    db_session.flush()

    mesocycle = models.Mesocycle(program_id=program.id, name="Test Block", start_week=1, end_week=6)
    db_session.add(mesocycle)
    db_session.flush()

    day_template = models.DayTemplate(mesocycle_id=mesocycle.id, name="Push", order=1)
    db_session.add(day_template)
    db_session.flush()

    exercise_slot = models.ExerciseSlot(
        day_template_id=day_template.id,
        exercise_name="Barbell Bench Press",
        muscle_group="chest",
        order=1,
    )
    db_session.add(exercise_slot)
    db_session.flush()

    prescription = models.WeeklyPrescription(
        exercise_slot_id=exercise_slot.id, week_number=1, sets=0, reps="8-10", load="70% 1RM"
    )
    db_session.add(prescription)
    db_session.flush()

    return user, prescription


@pytest.fixture()
def other_user(db_session):
    user = models.User(clerk_user_id="test-clerk-id-other")
    db_session.add(user)
    db_session.flush()
    return user
