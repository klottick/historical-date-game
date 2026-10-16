"""Empty-state transition tests on the exact owned migration disposable DB."""

import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CalledProcessError
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.core.config import settings
from tests.api.routes.test_game_daily import release
from tests.browser import guest_test_environment as environment

DATABASE = "historical_date_game_lives_migration_test"


def setUpModule() -> None:
    Path("/tmp/opencode").mkdir(mode=0o700, parents=True, exist_ok=True)


class ThreeLivesMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        environment.require_guest_test_target(DATABASE, settings.POSTGRES_SERVER, settings.ENVIRONMENT)
        environment.require_owned_guest_database(DATABASE)
        with environment._maintenance_connection() as connection:
            active = connection.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (DATABASE,)).fetchone()[0]
            if active:
                raise RuntimeError(f"Unexpected foreign consumers: {active}")
        cls.url = str(settings.SQLALCHEMY_DATABASE_URI).rsplit("/", 1)[0] + "/" + DATABASE
        cls.engine = create_engine(cls.url)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.created_users = []
        self.created_releases = []
        with Session(self.engine) as session:
            self.original_selection = session.execute(text("SELECT release_id FROM catalogselection WHERE id=1")).scalar_one()

    def tearDown(self) -> None:
        # Only IDs created by this proof are removed; keep the synthetic baseline
        # and all pre-existing retained rows, even when an assertion fails.
        with Session(self.engine) as session:
            for owner in self.created_users:
                for table in ("gameoperation", "gamerun", "item", "guestsession"):
                    session.execute(text(f'DELETE FROM "{table}" WHERE owner_id=:owner'), {"owner": owner})
                session.execute(text('DELETE FROM "user" WHERE id=:owner'), {"owner": owner})
            session.execute(text("UPDATE catalogselection SET release_id=:release WHERE id=1"), {"release": self.original_selection})
            for release_id in self.created_releases:
                session.execute(text("DELETE FROM dailydefinition WHERE catalog_release_id=:release"), {"release": release_id})
                for table in ("eventrevision", "catalogcategory", "mediaasset"):
                    session.execute(text(f'DELETE FROM "{table}" WHERE release_id=:release'), {"release": release_id})
                session.execute(text("DELETE FROM catalogrelease WHERE id=:release"), {"release": release_id})
            session.commit()
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        self.engine.dispose()
        if revision == "20261013_01":
            environment.run_migration(DATABASE, "upgrade", "20261015_01")

    def test_nonempty_upgrade_refuses_without_mutation(self) -> None:
        with Session(self.engine) as session:
            current = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if current == "20261015_01":
            environment.run_migration(DATABASE, "downgrade", "20261013_01")
        with tempfile.TemporaryDirectory(prefix="hdg-lives-migration-", dir="/tmp/opencode") as temp:
            with Session(self.engine) as session:
                release_id = release(session, Path(temp) / "fixture")
                self.created_releases.append(release_id)
                owner_id, run_id, op_id = uuid4(), uuid4(), uuid4()
                guest_owner, guest_public = uuid4(), uuid4()
                self.created_users.extend((owner_id, guest_owner))
                stamp = datetime.now(UTC)
                event_ids = session.execute(text("SELECT event_id FROM eventrevision WHERE release_id=:release ORDER BY event_id LIMIT 2"), {"release": release_id}).scalars().all()
                self.assertEqual(len(event_ids), 2)
                event_ids = [str(value) for value in event_ids]
                session.execute(text('INSERT INTO "user" (id,email,hashed_password,full_name,is_active,is_superuser) VALUES (:id,:email,:hash,:name,true,false)'), {"id": owner_id, "email": f"migration-{owner_id}@example.com", "hash": "historical-fixture", "name": "Migration fixture"})
                session.execute(text('INSERT INTO "user" (id,email,hashed_password,full_name,is_active,is_superuser,is_guest) VALUES (:id,:email,:hash,:name,true,false,true)'), {"id": guest_owner, "email": f"guest-{guest_owner}@example.com", "hash": "guest-fixture", "name": "Guest migration fixture"})
                session.execute(text("INSERT INTO guestsession (token_digest,owner_id,public_id,created_at,expires_at) VALUES (:digest,:owner,:public,:created,:expires)"), {"digest": hashlib.sha256(b"guest migration sentinel" + guest_owner.bytes).hexdigest(), "owner": guest_owner, "public": guest_public, "created": stamp, "expires": stamp.replace(year=stamp.year + 1)})
                session.execute(text("INSERT INTO item (id,title,description,owner_id) VALUES (:id,'retained sentinel','unrelated row',:owner)"), {"id": uuid4(), "owner": owner_id})
                session.execute(text("""INSERT INTO gamerun
                    (id,owner_id,mode,daily_definition_id,catalog_release_id,seed,generation_version,rules,pool,"order",timeline,pending_event_id,status,streak,revision,created_at,updated_at)
                    VALUES (:id,:owner,'freeplay',NULL,:release,:seed,1,:rules,:pool,:order,:timeline,:pending,'active',0,0,now(),now())"""), {"id": run_id, "owner": owner_id, "release": release_id, "seed": bytes(range(32)), "rules": json.dumps({"category_ids":["battles"],"start_year_index":-500,"end_year_index":3000,"min_gap":1}), "pool": json.dumps(event_ids), "order": json.dumps(event_ids), "timeline": json.dumps(event_ids[:1]), "pending": event_ids[1]})
                session.execute(text("""INSERT INTO gameoperation (id,owner_id,operation_id,scope,run_id,payload_digest,outcome,created_at)
                    VALUES (:id,:owner,:op,'freeplay',:run,:digest,'{}'::jsonb,now())"""), {"id": uuid4(), "owner": owner_id, "op": op_id, "run": run_id, "digest": hashlib.sha256(b"fixture").hexdigest()})
                session.commit()
                before = environment._private_row_digests(session)
                guest_before = session.execute(text("SELECT to_jsonb(g)::text FROM guestsession g")).scalars().all()
                session.commit()
            with self.assertRaises(CalledProcessError):
                environment.run_migration(DATABASE, "upgrade", "20261015_01")
            with Session(self.engine) as session:
                after = environment._private_row_digests(session)
                guest_after = session.execute(text("SELECT to_jsonb(g)::text FROM guestsession g")).scalars().all()
                revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                self.assertEqual(revision, "20261013_01")
                self.assertEqual(after, before)
                self.assertEqual(guest_after, guest_before)
                session.execute(text("DELETE FROM gameoperation WHERE run_id=:run"), {"run": run_id})
                session.execute(text("DELETE FROM gamerun WHERE id=:run"), {"run": run_id})
                daily_id = uuid4()
                session.execute(
                    text("""INSERT INTO dailydefinition
                        (id,day,catalog_release_id,seed,generation_version,rules,pool,"order",anchor_event_id,created_at)
                        VALUES (:id,'2402-01-01',:release,:seed,1,:rules,:pool,:order,:anchor,now())"""),
                    {
                        "id": daily_id,
                        "release": release_id,
                        "seed": b"d" * 32,
                        "rules": json.dumps({
                            "category_ids": ["battles"],
                            "start_year_index": -500,
                            "end_year_index": 3000,
                            "min_gap": 1,
                        }),
                        "pool": json.dumps(event_ids),
                        "order": json.dumps(event_ids),
                        "anchor": event_ids[0],
                    },
                )
                session.commit()
                daily_before = environment._private_row_digests(session)["dailydefinition"]
                self.assertGreater(daily_before["count"], 0)
            # DailyDefinition alone is a protected gameplay row: refusal must
            # preserve it, even after every run and operation has been removed.
            with self.assertRaises(CalledProcessError):
                environment.run_migration(DATABASE, "upgrade", "20261015_01")
            with Session(self.engine) as session:
                self.assertEqual(
                    session.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one(),
                    "20261013_01",
                )
                self.assertEqual(
                    environment._private_row_digests(session)["dailydefinition"],
                    daily_before,
                )
                session.execute(
                    text("DELETE FROM dailydefinition WHERE day='2402-01-01'")
                )
                session.commit()
        with Session(self.engine) as session:
            unrelated_before = environment._private_row_digests(session)
            guest_before = session.execute(text("SELECT to_jsonb(g)::text FROM guestsession g")).scalars().all()
        environment.run_migration(DATABASE, "upgrade", "20261015_01")
        with Session(self.engine) as session:
            unrelated_after = environment._private_row_digests(session)
            guest_after = session.execute(text("SELECT to_jsonb(g)::text FROM guestsession g")).scalars().all()
            retained = {name: unrelated_before[name] for name in unrelated_before if name not in {"gamerun", "gameoperation", "dailydefinition"}}
            self.assertEqual(retained, {name: unrelated_after[name] for name in retained})
            self.assertEqual(guest_before, guest_after)
        with tempfile.TemporaryDirectory(prefix="hdg-lives-migration-", dir="/tmp/opencode") as temp:
            with Session(self.engine) as session:
                release_id = release(session, Path(temp) / "fixture")
                self.created_releases.append(release_id)
                run_id, owner_id, event_ids = self._insert_current_run(session, release_id)
                session.commit()
            with self.assertRaises(CalledProcessError):
                environment.run_migration(DATABASE, "downgrade", "20261013_01")
            with Session(self.engine) as session:
                self.assertEqual(session.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "20261015_01")
                self._assert_counter_constraints(run_id, event_ids)
                session.execute(text("DELETE FROM gameoperation WHERE run_id=:run"), {"run": run_id})
                session.execute(text("DELETE FROM gamerun WHERE id=:run"), {"run": run_id})
                session.commit()
        with Session(self.engine) as session:
            downgrade_before = environment._private_row_digests(session)
            guest_before = session.execute(text("SELECT to_jsonb(g)::text FROM guestsession g")).scalars().all()
        environment.run_migration(DATABASE, "downgrade", "20261013_01")
        with Session(self.engine) as session:
            downgrade_after = environment._private_row_digests(session)
            guest_after = session.execute(text("SELECT to_jsonb(g)::text FROM guestsession g")).scalars().all()
            self.assertEqual(downgrade_after, downgrade_before)
            self.assertEqual(guest_after, guest_before)
        environment.run_migration(DATABASE, "upgrade", "20261015_01")

    def _insert_current_run(self, session: Session, release_id: str):
        owner_id, run_id = uuid4(), uuid4()
        self.created_users.append(owner_id)
        event_ids = [str(value) for value in session.execute(text("SELECT event_id FROM eventrevision WHERE release_id=:release ORDER BY event_id LIMIT 8"), {"release": release_id}).scalars().all()]
        session.execute(text('INSERT INTO "user" (id,email,hashed_password,full_name,is_active,is_superuser) VALUES (:id,:email,:hash,:name,true,false)'), {"id": owner_id, "email": f"migration-{owner_id}@example.com", "hash": "current-fixture", "name": "Current migration fixture"})
        session.execute(text("""INSERT INTO gamerun
            (id,owner_id,mode,daily_definition_id,catalog_release_id,seed,generation_version,rules,pool,"order",timeline,pending_event_id,status,streak,revision,mistakes,correct_count,created_at,updated_at)
            VALUES (:id,:owner,'freeplay',NULL,:release,:seed,1,:rules,:pool,:order,:timeline,:pending,'active',0,0,0,0,now(),now())"""), {"id": run_id, "owner": owner_id, "release": release_id, "seed": bytes(range(32)), "rules": json.dumps({"category_ids":["battles"],"start_year_index":-500,"end_year_index":3000,"min_gap":1}), "pool": json.dumps(event_ids), "order": json.dumps(event_ids), "timeline": json.dumps(event_ids[:1]), "pending": event_ids[1]})
        return run_id, owner_id, event_ids

    def _assert_counter_constraints(self, run_id, event_ids) -> None:
        invalid_updates = [
            {"correct_count": -1},
            {"mistakes": -1},
            {"mistakes": 4},
            {"revision": 1},
            {"timeline": json.dumps(event_ids[:2])},
            {"status": "lost", "mistakes": 3, "correct_count": 0, "revision": 3, "streak": 1, "pending_event_id": None, "timeline": json.dumps(event_ids[:3])},
            {"mistakes": 3, "correct_count": 0, "revision": 3, "timeline": json.dumps(event_ids[:4])},
        ]
        for changes in invalid_updates:
            assigns = ",".join(f'"{key}"=:{key}' for key in changes)
            params = dict(changes.items())
            params["run"] = run_id
            with self.assertRaises(IntegrityError, msg=f"constraint accepted {changes}"):
                with self.engine.begin() as connection:
                    connection.execute(text(f"UPDATE gamerun SET {assigns} WHERE id=:run"), params)
