import datetime as dt
import logging

from sqlalchemy.orm import Session

from ..models import Person, InstagramPost, ReviewStatus
from .instagram_client import InstagramClient, InstagramError
from ..settings_store import get_setting

logger = logging.getLogger(__name__)


def poll_all(db: Session) -> dict:
    """Poll Instagram for every person with instagram_enabled + a username set.
    New posts are inserted as pending InstagramPost rows for human review -
    never auto-imported. Returns a summary dict for logging/telemetry."""
    username = get_setting(db, "instagram_username")
    password = get_setting(db, "instagram_password")
    summary = {"checked": 0, "new_posts": 0, "errors": []}

    if not username or not password:
        summary["errors"].append("Instagram credentials not configured")
        return summary

    people = (
        db.query(Person)
        .filter(Person.instagram_enabled.is_(True))
        .filter(Person.instagram_username.isnot(None))
        .filter(Person.archived.is_(False))
        .all()
    )
    if not people:
        return summary

    try:
        client = InstagramClient(username, password)
    except InstagramError as e:
        summary["errors"].append(str(e))
        return summary

    for person in people:
        summary["checked"] += 1
        try:
            posts = client.get_recent_posts(person.instagram_username, count=12)
            person.instagram_last_error = None
        except InstagramError as e:
            logger.warning("Instagram check failed for %s: %s", person.instagram_username, e)
            person.instagram_last_error = str(e)
            summary["errors"].append(f"@{person.instagram_username}: {e}")
            continue
        finally:
            person.instagram_last_checked = dt.datetime.utcnow()
            db.add(person)

        for post in posts:
            exists = (
                db.query(InstagramPost)
                .filter_by(person_id=person.id, ig_post_id=post["ig_post_id"])
                .first()
            )
            if exists:
                continue
            row = InstagramPost(
                person_id=person.id,
                ig_post_id=post["ig_post_id"],
                caption=post.get("caption"),
                media_url=post.get("media_url"),
                permalink=post.get("permalink"),
                post_type=post.get("post_type"),
                posted_at=post.get("posted_at"),
                status=ReviewStatus.pending,
            )
            db.add(row)
            summary["new_posts"] += 1

        db.commit()

    return summary
