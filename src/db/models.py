from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SnapshotMeta(Base):
    __tablename__ = "snapshot_meta"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    record_count: Mapped[int]
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contractor(Base):
    __tablename__ = "contractors"

    inn: Mapped[str] = mapped_column(String(12), primary_key=True)
    ogrn: Mapped[str] = mapped_column(String(15), unique=True)
    short_name: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    report_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    risk_level: Mapped[str | None] = mapped_column(Text)
    zsk_risk_level: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    status_reason: Mapped[str | None] = mapped_column(Text)

    registration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    years_from_registration: Mapped[int | None]
    kpp: Mapped[str | None] = mapped_column(String(9))
    okpo: Mapped[str | None] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text, index=True)
    email: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    company_size: Mapped[str | None] = mapped_column(Text)
    staff: Mapped[str | None] = mapped_column(Text)

    share_capital: Mapped[int | None] = mapped_column(BigInteger)
    auth_person_name: Mapped[str | None] = mapped_column(Text)
    auth_person_inn: Mapped[str | None] = mapped_column(String(12))
    auth_person_position: Mapped[str | None] = mapped_column(Text)
    auth_person_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    main_okved_code: Mapped[str | None] = mapped_column(Text)
    main_okved_description: Mapped[str | None] = mapped_column(Text)
    okved_count: Mapped[int] = mapped_column(Integer, default=0)
    tax_systems: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    branches_count: Mapped[int] = mapped_column(Integer, default=0)

    # денормализованные агрегаты, чтобы не джойнить 3873 строки на каждый запрос
    execproc_total: Mapped[int] = mapped_column(Integer, default=0)
    execproc_active: Mapped[int] = mapped_column(Integer, default=0)
    execproc_total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    execproc_active_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    negative_factors_count: Mapped[int] = mapped_column(Integer, default=0)

    arbitration_count: Mapped[int | None]
    arbitration_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    arbitration_by_status: Mapped[dict | None] = mapped_column(JSONB)
    coefficients: Mapped[dict | None] = mapped_column(JSONB)

    raw: Mapped[dict] = mapped_column(JSONB)


class FinReport(Base):
    __tablename__ = "fin_reports"

    inn: Mapped[str] = mapped_column(ForeignKey("contractors.inn", ondelete="CASCADE"), primary_key=True)
    year: Mapped[int] = mapped_column(primary_key=True)

    proceeds: Mapped[int | None] = mapped_column(BigInteger)
    profit: Mapped[int | None] = mapped_column(BigInteger)
    total_assets: Mapped[int | None] = mapped_column(BigInteger)
    current_assets: Mapped[int | None] = mapped_column(BigInteger)
    stocks: Mapped[int | None] = mapped_column(BigInteger)
    receivables: Mapped[int | None] = mapped_column(BigInteger)
    bankroll: Mapped[int | None] = mapped_column(BigInteger)
    uncurrent_assets: Mapped[int | None] = mapped_column(BigInteger)
    fixed_assets: Mapped[int | None] = mapped_column(BigInteger)
    total_liabilities: Mapped[int | None] = mapped_column(BigInteger)
    capitals: Mapped[int | None] = mapped_column(BigInteger)
    long_term_total: Mapped[int | None] = mapped_column(BigInteger)
    long_term_others: Mapped[int | None] = mapped_column(BigInteger)
    short_term_total: Mapped[int | None] = mapped_column(BigInteger)
    borrowed_funds: Mapped[int | None] = mapped_column(BigInteger)
    accounts_payable: Mapped[int | None] = mapped_column(BigInteger)


class ExecutionProceeding(Base):
    __tablename__ = "execution_proceedings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inn: Mapped[str] = mapped_column(ForeignKey("contractors.inn", ondelete="CASCADE"))
    active: Mapped[bool | None] = mapped_column(Boolean)
    number: Mapped[str | None] = mapped_column(Text)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))

    __table_args__ = (Index("ix_execproc_inn_active", "inn", "active"),)


class ArbitrationByYear(Base):
    __tablename__ = "arbitration_by_year"

    inn: Mapped[str] = mapped_column(ForeignKey("contractors.inn", ondelete="CASCADE"), primary_key=True)
    year: Mapped[int] = mapped_column(primary_key=True)
    plaintiff_count: Mapped[int | None]
    plaintiff_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    defendant_count: Mapped[int | None]
    defendant_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))


class ReputationalFactor(Base):
    __tablename__ = "reputational_factors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inn: Mapped[str] = mapped_column(ForeignKey("contractors.inn", ondelete="CASCADE"))
    polarity: Mapped[str] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text)
    chapter: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_factors_inn_polarity_chapter", "inn", "polarity", "chapter"),)


class RelatedCompany(Base):
    __tablename__ = "related_companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inn: Mapped[str] = mapped_column(ForeignKey("contractors.inn", ondelete="CASCADE"))
    related_inn: Mapped[str | None] = mapped_column(String(12))
    related_ogrn: Mapped[str | None] = mapped_column(String(15))
    name: Mapped[str | None] = mapped_column(Text)
    registration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_person_name: Mapped[str | None] = mapped_column(Text)
    auth_person_position: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_related_inn", "inn"),)


class Cofounder(Base):
    __tablename__ = "cofounders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inn: Mapped[str] = mapped_column(ForeignKey("contractors.inn", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(Text)
    founder_inn: Mapped[str | None] = mapped_column(String(12))
    amount: Mapped[int | None] = mapped_column(BigInteger)
    share: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    date_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (Index("ix_cofounders_inn", "inn"),)


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    login: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    tariff: Mapped[str] = mapped_column(Text, default="free")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserQuota(Base):
    __tablename__ = "user_quotas"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    requests_used: Mapped[int] = mapped_column(default=0)
    requests_limit: Mapped[int] = mapped_column(default=100)
    tokens_used: Mapped[int] = mapped_column(BigInteger, default=0)
    reports_generated: Mapped[int] = mapped_column(default=0)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(Text)
    role_preset: Mapped[str] = mapped_column(Text, default="general")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int | None]
    meta: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_messages_session_created", "session_id", "created_at"),)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inn: Mapped[str] = mapped_column(ForeignKey("contractors.inn", ondelete="CASCADE"))
    analysis_type: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    analysis: Mapped[str | None] = mapped_column(Text)
    report: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("inn", "analysis_type", name="uq_analysis_inn_type"),)


class SessionAnalysis(Base):
    __tablename__ = "session_analyses"

    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_session_analyses_recent", "session_id", "created_at"),)
