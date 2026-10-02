from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base
import datetime

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    clerk_user_id: Mapped[str] = mapped_column(String, unique=True)
    programs: Mapped[list["Program"]] = relationship(back_populates="user")
    documents: Mapped[list["UserDocument"]] = relationship(back_populates="user")

class Program(Base):
    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    goal: Mapped[str] = mapped_column(String)

    user: Mapped["User"] = relationship(back_populates="programs") #one ForeignKey so auto-detected, no need to specify
    mesocycles: Mapped[list["Mesocycle"]] = relationship(back_populates="program", order_by="Mesocycle.start_week")

class Mesocycle(Base):
    __tablename__ = "mesocycles"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"))
    name: Mapped[str] = mapped_column(String)
    start_week: Mapped[int] = mapped_column()
    end_week: Mapped[int] = mapped_column()

    program: Mapped["Program"] = relationship(back_populates="mesocycles")
    day_templates: Mapped[list["DayTemplate"]] = relationship(back_populates="mesocycle", order_by="DayTemplate.order")
    muscle_group_frequencies: Mapped[list["MuscleGroupFrequency"]] = relationship(back_populates="mesocycle")
    progression_schemes: Mapped[list["ProgressionScheme"]] = relationship(back_populates="mesocycle")

class DayTemplate(Base):
    __tablename__ = "day_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    mesocycle_id: Mapped[int] = mapped_column(ForeignKey("mesocycles.id"))
    name: Mapped[str] = mapped_column(String)
    order: Mapped[int] = mapped_column()
    rest_days_before: Mapped[int | None] = mapped_column(nullable=True)

    mesocycle: Mapped["Mesocycle"] = relationship(back_populates="day_templates")
    exercise_slots: Mapped[list["ExerciseSlot"]] = relationship(back_populates="day_template", order_by="ExerciseSlot.order", cascade="all, delete-orphan")

class ExerciseSlot(Base):
    __tablename__ = "exercise_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    day_template_id: Mapped[int] = mapped_column(ForeignKey("day_templates.id"))
    exercise_name: Mapped[str] = mapped_column(String)
    muscle_group: Mapped[str] = mapped_column(String)
    order: Mapped[int] = mapped_column()

    day_template: Mapped["DayTemplate"] = relationship(back_populates="exercise_slots")
    weekly_prescriptions: Mapped[list["WeeklyPrescription"]] = relationship(back_populates="exercise_slot", order_by="WeeklyPrescription.week_number", cascade="all, delete-orphan")

class WeeklyPrescription(Base):
    __tablename__ = "weekly_prescriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_slot_id: Mapped[int] = mapped_column(ForeignKey("exercise_slots.id"))
    week_number: Mapped[int] = mapped_column()
    sets: Mapped[int] = mapped_column()
    reps: Mapped[str] = mapped_column(String)
    load: Mapped[str] = mapped_column(String)
    grounding_note: Mapped[str | None] = mapped_column(String, nullable=True)

    exercise_slot: Mapped["ExerciseSlot"] = relationship(back_populates="weekly_prescriptions")
    prescription_citations: Mapped[list["PrescriptionCitation"]] = relationship(back_populates="prescription", cascade="all, delete-orphan")

class UserDocument(Base):
    __tablename__ = "user_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String)
    uploaded_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="documents")

class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String)
    snippet: Mapped[str] = mapped_column(String)
    qdrant_point_id: Mapped[str] = mapped_column(String)

    prescription_citations: Mapped[list["PrescriptionCitation"]] = relationship(back_populates="citation")
    frequency_citations: Mapped[list["FrequencyCitation"]] = relationship(back_populates="citation")
    progression_scheme_citations: Mapped[list["ProgressionSchemeCitation"]] = relationship(back_populates="citation")

class PrescriptionCitation(Base):
    __tablename__ = "prescription_citations"

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey("weekly_prescriptions.id"))
    citation_id: Mapped[int] = mapped_column(ForeignKey("citations.id"))
    verification_status: Mapped[str] = mapped_column(String)

    prescription: Mapped["WeeklyPrescription"] = relationship(back_populates="prescription_citations")
    citation: Mapped["Citation"] = relationship(back_populates="prescription_citations")

class MuscleGroupFrequency(Base):
    __tablename__ = "muscle_group_frequencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    mesocycle_id: Mapped[int] = mapped_column(ForeignKey("mesocycles.id"))
    muscle_group: Mapped[str] = mapped_column(String)
    frequency: Mapped[int] = mapped_column()
    grounding_note: Mapped[str | None] = mapped_column(String, nullable=True)

    mesocycle: Mapped["Mesocycle"] = relationship(back_populates="muscle_group_frequencies")
    frequency_citations: Mapped[list["FrequencyCitation"]] = relationship(back_populates="frequency")

class FrequencyCitation(Base):
    __tablename__ = "frequency_citations"

    id: Mapped[int] = mapped_column(primary_key=True)
    frequency_id: Mapped[int] = mapped_column(ForeignKey("muscle_group_frequencies.id"))
    citation_id: Mapped[int] = mapped_column(ForeignKey("citations.id"))
    verification_status: Mapped[str] = mapped_column(String)

    frequency: Mapped["MuscleGroupFrequency"] = relationship(back_populates="frequency_citations")
    citation: Mapped["Citation"] = relationship(back_populates="frequency_citations")

class ProgressionScheme(Base):
    __tablename__ = "progression_schemes"

    id: Mapped[int] = mapped_column(primary_key=True)
    mesocycle_id: Mapped[int] = mapped_column(ForeignKey("mesocycles.id"))
    muscle_group: Mapped[str] = mapped_column(String)
    scheme: Mapped[str] = mapped_column(String)  # "linear" or "undulating"
    grounding_note: Mapped[str | None] = mapped_column(String, nullable=True)

    mesocycle: Mapped["Mesocycle"] = relationship(back_populates="progression_schemes")
    progression_scheme_citations: Mapped[list["ProgressionSchemeCitation"]] = relationship(back_populates="scheme")

class ProgressionSchemeCitation(Base):
    __tablename__ = "progression_scheme_citations"

    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("progression_schemes.id"))
    citation_id: Mapped[int] = mapped_column(ForeignKey("citations.id"))
    verification_status: Mapped[str] = mapped_column(String)

    scheme: Mapped["ProgressionScheme"] = relationship(back_populates="progression_scheme_citations")
    citation: Mapped["Citation"] = relationship(back_populates="progression_scheme_citations")