import datetime as dt

from sqlalchemy.orm import Session

from app.models import UserStats, UnlockedAchievement, JournalEntry, Person
from app.services import gamification


def test_initial_stats_created(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        stats = gamification._get_or_create_stats(db, user)
        assert stats.id == 1
        assert stats.total_xp == 0
        assert stats.current_level == 1
        assert stats.streak_days == 0
    finally:
        db.close()


def test_xp_awards_and_levels(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        db.add(JournalEntry(author_user_id=1, title="Test", body="Test entry", entry_date=dt.date.today()))
        db.commit()

        result = gamification.award_xp(db, user, "NOTE_ADDED")
        assert result["xp_gained"] == 15
        assert result["total_xp"] == 15
        assert result["current_level"] == 1
        assert not result["level_up"]
        assert "first_step" in result["unlocked_badges"]

        for _ in range(19):
            result = gamification.award_xp(db, user, "NOTE_ADDED")

        assert result["total_xp"] >= 300
        stats = gamification._get_or_create_stats(db, user)
        assert stats.current_level >= 3
    finally:
        db.close()


def test_level_calculation():
    assert gamification.calculate_level(0) == 1
    assert gamification.calculate_level(50) == 1
    assert gamification.calculate_level(99) == 1
    assert gamification.calculate_level(100) == 2
    assert gamification.calculate_level(281) == 2
    assert gamification.calculate_level(282) == 3
    assert gamification.calculate_level(500) == 3
    assert gamification.calculate_level(1000) == 5


def test_streak_tracking(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        # First day
        result = gamification.award_xp(db, user, "NOTE_ADDED")
        assert result["streak_days"] == 1

        # Same day — no streak change (this is a fresh DB, award_xp won't be called twice same day)
        stats = gamification._get_or_create_stats(db, user)
        assert stats.streak_days == 1
        assert stats.last_active_date == dt.date.today().isoformat()

        # Simulate yesterday's date for streak continuation test
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        stats.last_active_date = yesterday
        stats.streak_days = 3
        db.commit()

        result = gamification.award_xp(db, user, "NOTE_ADDED")
        assert result["streak_days"] == 4  # continued

        # Gap detected — reset streak
        stats.last_active_date = (dt.date.today() - dt.timedelta(days=2)).isoformat()
        stats.streak_days = 7
        db.commit()

        result = gamification.award_xp(db, user, "NOTE_ADDED")
        assert result["streak_days"] == 1  # Reset
    finally:
        db.close()


def test_achievement_first_step(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        db.add(JournalEntry(author_user_id=1, title="First", body="My first entry", entry_date=dt.date.today()))
        db.commit()

        assert not db.query(UnlockedAchievement).count()

        result = gamification.award_xp(db, user, "NOTE_ADDED")
        assert "first_step" in result["unlocked_badges"]
        unlocked = {r.slug for r in db.query(UnlockedAchievement).all()}
        assert "first_step" in unlocked
    finally:
        db.close()


def test_achievement_circle_builder(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        stats = gamification._get_or_create_stats(db, user)
        # Need context with people count
        gamification.award_xp(db, user, "NOTE_ADDED")
        assert not db.query(UnlockedAchievement).filter_by(slug="circle_builder").first()

        # Add 3 people
        for name in ["Alice", "Bob", "Charlie"]:
            db.add(Person(user_id=1, name=name))
        db.commit()

        result = gamification.award_xp(db, user, "NOTE_ADDED")
        assert "circle_builder" in result["unlocked_badges"]
    finally:
        db.close()


def test_achievement_party_planner(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_people_count": 4})
        assert "party_planner" in result["unlocked_badges"]

        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_people_count": 2})
        assert "party_planner" not in result["unlocked_badges"]
    finally:
        db.close()


def test_achievement_deep_listener(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_word_count": 150})
        assert "deep_listener" in result["unlocked_badges"]

        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_word_count": 50})
        assert "deep_listener" not in result["unlocked_badges"]
    finally:
        db.close()


def test_achievement_night_owl(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_hour": 3})
        assert "night_owl" in result["unlocked_badges"]

        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_hour": 14})
        assert "night_owl" not in result["unlocked_badges"]
    finally:
        db.close()


def test_achievement_time_traveler(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_years_back": 10})
        assert "time_traveler" in result["unlocked_badges"]

        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_years_back": 2})
        assert "time_traveler" not in result["unlocked_badges"]
    finally:
        db.close()


def test_achievement_new_year(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_is_new_year": True})
        assert "new_years_toast" in result["unlocked_badges"]
    finally:
        db.close()


def test_achievement_birthday_hero(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_matches_birthday": True})
        assert "birthday_hero" in result["unlocked_badges"]
    finally:
        db.close()


def test_achievement_scratchpad_clearer(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"scratchpad_cleared": True})
        assert "scratchpad_clearer" in result["unlocked_badges"]
    finally:
        db.close()


def test_achievement_one_time_unlock(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_hour": 3})
        assert "night_owl" in result["unlocked_badges"]

        # Second call should not re-unlock
        result2 = gamification.award_xp(db, user, "NOTE_ADDED", context={"entry_hour": 3})
        assert "night_owl" not in result2["unlocked_badges"]
    finally:
        db.close()


def test_get_stats_and_achievements(app, user):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        progress = gamification.get_stats_and_achievements(db, user)
        assert "stats" in progress
        assert "achievements" in progress
        assert "unlocked_count" in progress
        assert "total_count" in progress
        assert progress["total_count"] == len(gamification.ACHIEVEMENTS)
        assert progress["stats"].total_xp == 0
    finally:
        db.close()
