from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

import database
import models


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fk.db'}")
    event.listen(engine, "connect", database.enable_sqlite_foreign_keys)
    database.Base.metadata.create_all(bind=engine)
    return engine


def _add_item(session):
    item = models.Item(
        item_type="found",
        image_path="uploads/a.jpg",
        images=[
            models.ItemImage(image_path="uploads/a.jpg", position=0),
            models.ItemImage(image_path="uploads/b.jpg", position=1),
        ],
    )
    session.add(item)
    session.commit()
    return item.id


def test_foreign_keys_enabled_on_app_engine():
    with database.engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_raw_sql_delete_cascades_to_item_images(tmp_path):
    engine = _engine(tmp_path)
    session = sessionmaker(bind=engine)()
    item_id = _add_item(session)
    assert session.execute(text("SELECT COUNT(*) FROM item_images")).scalar() == 2

    session.execute(text("DELETE FROM items WHERE id = :id"), {"id": item_id})
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM item_images")).scalar() == 0
    session.close()


def test_orm_delete_cascades_to_item_images(tmp_path):
    engine = _engine(tmp_path)
    session = sessionmaker(bind=engine)()
    item_id = _add_item(session)

    session.delete(session.get(models.Item, item_id))
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM item_images")).scalar() == 0
    session.close()


def test_orphan_image_rejected(tmp_path):
    import pytest
    from sqlalchemy.exc import IntegrityError

    engine = _engine(tmp_path)
    session = sessionmaker(bind=engine)()
    session.add(models.ItemImage(item_id=999, image_path="uploads/x.jpg", position=0))
    with pytest.raises(IntegrityError):
        session.commit()
    session.close()
