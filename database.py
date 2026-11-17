"""Art / Pose / Log 구조 생성과 기존 SQLite 데이터의 원자적 이전."""

import json


# 기존 키오스크/API의 필드 이름은 유지하면서 실제 SQL 컬럼을 사용합니다.
ARTWORK_SELECT = """SELECT artwork_index, artist_name, theme, title, description,
    artwork_code, artwork_title AS title_en, artist AS artist_name_en,
    image_path, image_alt, artwork_id, location, x, y, x_min, x_max, y_min, y_max FROM Art"""
SESSION_SELECT = """SELECT *, record_id AS id, route AS course_id,
    created_time AS created_at, end_time AS ended_at FROM TourSession"""
ARTWORK_COLUMNS = {'title_en': 'artwork_title', 'artist_name_en': 'artist'}


def insert_artwork(db, art, replace=False):
    mapped = {ARTWORK_COLUMNS.get(key, key): value for key, value in art.items()}
    if replace:
        updates = {key: value for key, value in mapped.items()
                   if key not in {'artwork_index', 'artwork_id'}}
        db.execute(
            f"UPDATE Art SET {', '.join(field + '=?' for field in updates)} WHERE artwork_id=?",
            [*updates.values(), art['artwork_id']],
        )
    else:
        db.execute(
            f"INSERT OR IGNORE INTO Art ({', '.join(mapped)}) VALUES ({', '.join('?' for _ in mapped)})",
            list(mapped.values()),
        )


def initialize_database(db, root):
    catalog = json.loads((root / 'data/catalog.json').read_text(encoding='utf-8'))
    db.execute('PRAGMA journal_mode = WAL')
    with db:
        db.execute('BEGIN IMMEDIATE')
        old_tables = {row['name'] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'artworks' in old_tables:
            columns = {row['name'] for row in db.execute('PRAGMA table_info(artworks)')}
            if 'data' in columns:
                db.execute('ALTER TABLE artworks RENAME TO artworks_legacy_v1')
                old_tables.remove('artworks')
        if 'Log' in old_tables:
            log_columns = {row['name'] for row in db.execute('PRAGMA table_info(Log)')}
            if 'record_id' in log_columns:
                # 기존 관람 상태는 키오스크 내부 동작을 위해 보존합니다.
                db.execute('ALTER TABLE Log RENAME TO TourSession')
                db.execute('DROP INDEX IF EXISTS log_created_time')
        rebuild_art = 'Art' in old_tables and db.execute('PRAGMA user_version').fetchone()[0] < 5
        if rebuild_art:
            db.execute('ALTER TABLE Art RENAME TO Art_previous_v4')
        for statement in (root / 'schema.sql').read_text(encoding='utf-8').split(';'):
            if statement.strip():
                db.execute(statement)

        for column in ('year', 'medium', 'curator_notes'):
            if column in {row['name'] for row in db.execute('PRAGMA table_info(Art)')}:
                db.execute(f'ALTER TABLE Art DROP COLUMN {column}')
        if rebuild_art:
            columns = ', '.join(row['name'] for row in db.execute('PRAGMA table_info(Art_previous_v4)') if row['name'] not in ('year', 'medium', 'curator_notes'))
            db.execute(f'INSERT INTO Art ({columns}) SELECT {columns} FROM Art_previous_v4')
            db.execute('DROP TABLE Art_previous_v4')

        # 이전과 테이블 교체를 하나의 트랜잭션으로 처리하여 실패하면 원래 상태로 되돌립니다.
        if 'artworks' in old_tables:
            for row in db.execute('SELECT * FROM artworks').fetchall():
                old = dict(row)
                art = next(dict(item) for item in catalog['artworks']
                           if item['artwork_index'] == old['artwork_index'])
                art.update({key: value for key, value in old.items() if key in art})
                art['theme'] = {'자연': 'nature', '색채': 'color', '추상': 'abstract'}.get(art['theme'], art['theme'])
                insert_artwork(db, art)
            db.execute('DROP TABLE artworks')
        if 'robots' in old_tables:
            db.execute('''INSERT INTO Pose (robot_id, x, y, theta, active, frame_id, pose_updated_at)
                SELECT robot_id, pose_x, pose_y, pose_theta, active, frame_id, pose_updated_at FROM robots''')
            db.execute('DROP TABLE robots')
        if 'sessions' in old_tables:
            columns = {row['name'] for row in db.execute('PRAGMA table_info(sessions)')}
            optional = ', '.join(key if key in columns else 'NULL'
                                 for key in ('robot_id', 'robot_namespace', 'visitor_id'))
            db.execute(f'''INSERT INTO TourSession (record_id, mode, route, artwork_ids, visited_ids,
                status, created_time, started_at, end_time, robot_id, robot_namespace, visitor_id)
                SELECT id, mode, course_id, artwork_ids, visited_ids, status, created_at,
                started_at, ended_at, {optional} FROM sessions''')
            db.execute('DROP TABLE sessions')

        for art in catalog['artworks']:
            insert_artwork(db, art)
        # 예전 임시 작품만 한 번 갱신하며, 이미 수정한 실제 작품은 보존합니다.
        artwork_version = catalog.get('artwork_version')
        if artwork_version and not db.execute(
            'SELECT 1 FROM catalog_migrations WHERE version=?', (artwork_version,)
        ).fetchone():
            for art in catalog['artworks']:
                insert_artwork(db, art, replace=True)
            db.execute('INSERT INTO catalog_migrations (version) VALUES (?)', (artwork_version,))
        # 요청한 임시 표 내용은 한 번만 적용합니다. 이후 SQL/관리 화면 편집은 보존합니다.
        content_version = catalog.get('artwork_content_version')
        if content_version and not db.execute(
            'SELECT 1 FROM catalog_migrations WHERE version=?', (content_version,)
        ).fetchone():
            content_fields = ('title', 'title_en', 'artist_name', 'artist_name_en', 'location', 'theme', 'description')
            for art in catalog['artworks']:
                assignments = ', '.join(ARTWORK_COLUMNS.get(field, field) + '=?' for field in content_fields)
                db.execute(f'UPDATE Art SET {assignments} WHERE artwork_id=?',
                           [art[field] for field in content_fields] + [art['artwork_id']])
            db.execute('INSERT INTO catalog_migrations (version) VALUES (?)', (content_version,))
        for course in catalog['courses']:
            db.execute('INSERT OR IGNORE INTO courses (id, data) VALUES (?, ?)',
                       (course['id'], json.dumps(course, ensure_ascii=False)))
        version = catalog.get('version')
        if version and not db.execute(
            'SELECT 1 FROM catalog_migrations WHERE version=?', (version,)
        ).fetchone():
            for course in catalog['courses']:
                db.execute('UPDATE courses SET data=? WHERE id=?',
                           (json.dumps(course, ensure_ascii=False), course['id']))
            db.execute('INSERT INTO catalog_migrations (version) VALUES (?)', (version,))
        for row in db.execute('SELECT id, data FROM courses').fetchall():
            old = json.loads(row['data'])
            if any(item not in {'art-01', 'art-02', 'art-03'} for item in old['ids']):
                old.update(ids=['art-03', 'art-02', 'art-01'], minutes=15, theme='추상 · 색채 · 자연')
                db.execute('UPDATE courses SET data=? WHERE id=?',
                           (json.dumps(old, ensure_ascii=False), row['id']))

        # 위치 미수신 상태는 NULL입니다. robot-02는 수신/활성화 전까지 비활성입니다.
        db.execute("INSERT OR IGNORE INTO Pose (robot_id, active) VALUES ('robot-01', 1)")
        db.execute("INSERT OR IGNORE INTO Pose (robot_id, active) VALUES ('robot-02', 0)")
        if "x_min" not in {row["name"] for row in db.execute("PRAGMA table_info(Art)")}:
            for field in ("x_min", "x_max", "y_min", "y_max"):
                db.execute(f"ALTER TABLE Art ADD COLUMN {field} REAL")
            ranges = [(-2.56,-2.51,1.02,1.45), (-2.52,3.51,2.5,4.01),
                      (-1.51,-1.02,5.14,5.15), (0.06,0.43,3.51,3.96)]
            for index, (left,right,bottom,top) in enumerate(ranges, 1):
                db.execute("UPDATE Art SET x_min=?,x_max=?,y_min=?,y_max=?,x=?,y=? WHERE artwork_index=?",
                           (left,right,bottom,top,round((left+right)/2,4),round((bottom+top)/2,4),index))
        db.execute('PRAGMA user_version = 6')
