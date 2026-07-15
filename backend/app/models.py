from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class User(Base):
    __tablename__ = "users" 
    id: Mapped[int] = mapped_column(primary_key=True) 

    programs: Mapped[list["Program"]] = relationship(back_populates="user")


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id")) 
    goal: Mapped[str] = mapped_column(String)

    user: Mapped["User"] = relationship(back_populates="programs")

   