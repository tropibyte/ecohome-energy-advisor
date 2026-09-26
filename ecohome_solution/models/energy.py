"""
Energy data models for EcoHome Energy Advisor
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, func
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

# Anchor relative database paths to the solution folder, not the caller's cwd.
_SOLUTION_ROOT = Path(__file__).resolve().parent.parent


class EnergyUsage(Base):
    """Model for energy consumption data"""
    __tablename__ = "energy_usage"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    consumption_kwh = Column(Float, nullable=False)
    device_type = Column(String(50), nullable=True, index=True)  # e.g., "EV", "HVAC", "appliance"
    device_name = Column(String(100), nullable=True)  # e.g., "Tesla Model 3", "Main AC"
    cost_usd = Column(Float, nullable=True)  # Cost at time of usage

    def __repr__(self):
        return f"<EnergyUsage(timestamp={self.timestamp}, consumption={self.consumption_kwh}kWh, device={self.device_name})>"


class SolarGeneration(Base):
    """Model for solar generation data"""
    __tablename__ = "solar_generation"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    generation_kwh = Column(Float, nullable=False)
    weather_condition = Column(String(50), nullable=True)  # e.g., "sunny", "cloudy", "rainy"
    temperature_c = Column(Float, nullable=True)
    solar_irradiance = Column(Float, nullable=True)  # W/m²

    def __repr__(self):
        return f"<SolarGeneration(timestamp={self.timestamp}, generation={self.generation_kwh}kWh, weather={self.weather_condition})>"


class UserPreference(Base):
    """Household profile and learned preferences used to personalise advice."""
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), nullable=False, unique=True, index=True)
    value_json = Column(Text, nullable=False)
    category = Column(String(50), nullable=True)  # profile | comfort | schedule | goal
    source = Column(String(50), nullable=True)    # seed | user | agent
    updated_at = Column(DateTime, nullable=False, default=datetime.now)

    @property
    def value(self) -> Any:
        return json.loads(self.value_json)

    def __repr__(self):
        return f"<UserPreference({self.key}={self.value_json})>"


class DatabaseManager:
    """Database manager for EcoHome energy data"""

    def __init__(self, db_path: str = "data/energy_data.db"):
        path = Path(db_path)
        if not path.is_absolute():
            path = _SOLUTION_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(path)
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        # expire_on_commit=False keeps returned records readable after the session closes.
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False,
                                         expire_on_commit=False, bind=self.engine)

    def create_tables(self):
        """Create all tables"""
        Base.metadata.create_all(bind=self.engine)
        print(f"Database tables created at {self.db_path}")

    def reset_database(self):
        """Drop and recreate every table so the setup notebook is safely re-runnable."""
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def get_session(self):
        """Get database session"""
        return self.SessionLocal()

    # ----------------------------------------------------------------- writes
    def add_usage_record(self, timestamp: datetime, consumption_kwh: float,
                         device_type: str = None, device_name: str = None, cost_usd: float = None):
        """Add energy usage record"""
        session = self.get_session()
        try:
            record = EnergyUsage(
                timestamp=timestamp,
                consumption_kwh=consumption_kwh,
                device_type=device_type,
                device_name=device_name,
                cost_usd=cost_usd
            )
            session.add(record)
            session.commit()
            return record
        finally:
            session.close()

    def add_generation_record(self, timestamp: datetime, generation_kwh: float,
                              weather_condition: str = None, temperature_c: float = None,
                              solar_irradiance: float = None):
        """Add solar generation record"""
        session = self.get_session()
        try:
            record = SolarGeneration(
                timestamp=timestamp,
                generation_kwh=generation_kwh,
                weather_condition=weather_condition,
                temperature_c=temperature_c,
                solar_irradiance=solar_irradiance
            )
            session.add(record)
            session.commit()
            return record
        finally:
            session.close()

    def bulk_add_usage(self, rows: Iterable[Dict[str, Any]]) -> int:
        """Insert many usage rows in one transaction (one commit instead of one per row)."""
        rows = list(rows)
        session = self.get_session()
        try:
            session.bulk_insert_mappings(EnergyUsage, rows)
            session.commit()
            return len(rows)
        finally:
            session.close()

    def bulk_add_generation(self, rows: Iterable[Dict[str, Any]]) -> int:
        rows = list(rows)
        session = self.get_session()
        try:
            session.bulk_insert_mappings(SolarGeneration, rows)
            session.commit()
            return len(rows)
        finally:
            session.close()

    def set_preference(self, key: str, value: Any, category: str = None, source: str = "user"):
        """Insert or update one preference."""
        session = self.get_session()
        try:
            pref = session.query(UserPreference).filter(UserPreference.key == key).one_or_none()
            if pref is None:
                pref = UserPreference(key=key)
                session.add(pref)
            pref.value_json = json.dumps(value)
            if category:
                pref.category = category
            pref.source = source
            pref.updated_at = datetime.now()
            session.commit()
            return pref
        finally:
            session.close()

    # ------------------------------------------------------------------ reads
    def get_usage_by_date_range(self, start_date: datetime, end_date: datetime):
        """Get energy usage records within [start_date, end_date)"""
        session = self.get_session()
        try:
            return session.query(EnergyUsage).filter(
                EnergyUsage.timestamp >= start_date,
                EnergyUsage.timestamp < end_date
            ).order_by(EnergyUsage.timestamp).all()
        finally:
            session.close()

    def get_generation_by_date_range(self, start_date: datetime, end_date: datetime):
        """Get solar generation records within [start_date, end_date)"""
        session = self.get_session()
        try:
            return session.query(SolarGeneration).filter(
                SolarGeneration.timestamp >= start_date,
                SolarGeneration.timestamp < end_date
            ).order_by(SolarGeneration.timestamp).all()
        finally:
            session.close()

    def get_recent_usage(self, hours: int = 24):
        """Get recent usage records"""
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        return self.get_usage_by_date_range(start_time, end_time)

    def get_recent_generation(self, hours: int = 24):
        """Get recent solar generation records"""
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        return self.get_generation_by_date_range(start_time, end_time)

    def get_preferences(self, category: Optional[str] = None) -> Dict[str, Any]:
        session = self.get_session()
        try:
            q = session.query(UserPreference)
            if category:
                q = q.filter(UserPreference.category == category)
            return {p.key: p.value for p in q.order_by(UserPreference.key).all()}
        finally:
            session.close()

    def get_data_range(self) -> Dict[str, Optional[str]]:
        """First and last usage timestamps held, so tools can explain empty queries."""
        session = self.get_session()
        try:
            lo, hi = session.query(func.min(EnergyUsage.timestamp), func.max(EnergyUsage.timestamp)).one()
            return {"first": lo.isoformat() if lo else None, "last": hi.isoformat() if hi else None}
        finally:
            session.close()

    def table_counts(self) -> Dict[str, int]:
        session = self.get_session()
        try:
            return {
                "energy_usage": session.query(EnergyUsage).count(),
                "solar_generation": session.query(SolarGeneration).count(),
                "user_preferences": session.query(UserPreference).count(),
            }
        finally:
            session.close()

    def device_types(self) -> List[str]:
        session = self.get_session()
        try:
            return sorted(r[0] for r in session.query(EnergyUsage.device_type).distinct().all() if r[0])
        finally:
            session.close()
