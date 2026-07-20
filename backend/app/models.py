from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    clerk_user_id: Mapped[str] = mapped_column(String, unique=True)
    programs: Mapped[list["Program"]] = relationship(back_populates="user")


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    goal: Mapped[str] = mapped_column(String)

    user: Mapped["User"] = relationship(back_populates="programs") #one ForeignKey so auto-detected, no need to specify
    mesocycles: Mapped[list["Mesocycle"]] = relationship(back_populates="program")

class Mesocycle(Base):
    __tablename__ = "mesocycles"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"))
    name: Mapped[str] = mapped_column(String)
    start_week: Mapped[int] = mapped_column()
    end_week: Mapped[int] = mapped_column()

    program: Mapped["Program"] = relationship(back_populates="mesocycles")
    day_templates: Mapped[list["DayTemplate"]] = relationship(back_populates="mesocycle")

class DayTemplate(Base):
    __tablename__ = "day_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    mesocycle_id: Mapped[int] = mapped_column(ForeignKey("mesocycles.id"))
    name: Mapped[str] = mapped_column(String)
    order: Mapped[int] = mapped_column()
    rest_days_before: Mapped[int | None] = mapped_column(nullable=True)

    mesocycle: Mapped["Mesocycle"] = relationship(back_populates="day_templates")
    exercise_slots: Mapped[list["ExerciseSlot"]] = relationship(back_populates="day_template")

class ExerciseSlot(Base):
    __tablename__ = "exercise_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    day_template_id: Mapped[int] = mapped_column(ForeignKey("day_templates.id"))
    exercise_name: Mapped[str] = mapped_column(String)
    order: Mapped[int] = mapped_column()

    day_template: Mapped["DayTemplate"] = relationship(back_populates="exercise_slots")
    weekly_prescriptions: Mapped[list["WeeklyPrescription"]] = relationship(back_populates="exercise_slot")

class WeeklyPrescription(Base):
    __tablename__ = "weekly_prescriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    exercise_slot_id: Mapped[int] = mapped_column(ForeignKey("exercise_slots.id"))
    week_number: Mapped[int] = mapped_column()
    sets: Mapped[int] = mapped_column()
    reps: Mapped[str] = mapped_column(String)
    load: Mapped[str] = mapped_column(String)

    exercise_slot: Mapped["ExerciseSlot"] = relationship(back_populates="weekly_prescriptions")