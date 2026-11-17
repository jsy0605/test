"""내부 관람 세션 조회·검색. 값은 모두 SQL 매개변수로 전달합니다."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import abort
from database import SESSION_SELECT


def session_page(db, args, serialize):
    def integer(name, default, minimum, maximum):
        value = args.get(name, str(default))
        if not re.fullmatch(r'[0-9]{1,7}', value) or not minimum <= int(value) <= maximum:
            abort(400, description=f'{name}은 {minimum}~{maximum} 사이 정수여야 합니다.')
        return int(value)

    limit = integer('limit', 100, 1, 500)
    offset = integer('offset', 0, 0, 1000000)
    clauses, values = [], []
    filters = {name: args.get(name, '').strip() for name in ('q', 'status', 'mode', 'from', 'to')}
    if len(filters['q']) > 200:
        abort(400, description='검색어는 200자 이내로 입력해 주세요.')
    for key, allowed in (('status', {'calling', 'active', 'completed', 'cancelled'}), ('mode', {'course', 'free'})):
        if filters[key]:
            if filters[key] not in allowed:
                abort(400, description='올바른 관람 상태와 방식을 선택해 주세요.')
            clauses.append(f'{key}=?')
            values.append(filters[key])
    dates = {}
    for key, column, operator in (('from', 'created_time', '>='), ('to', 'created_time', '<')):
        if filters[key]:
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', filters[key]):
                    raise ValueError()
                date = datetime.strptime(filters[key], '%Y-%m-%d').replace(tzinfo=ZoneInfo('Asia/Seoul'))
                dates[key] = date
                boundary = date + timedelta(days=1) if key == 'to' else date
                value = int(boundary.timestamp() * 1000)
            except (ValueError, OverflowError, OSError):
                abort(400, description='검색 날짜는 YYYY-MM-DD 형식의 올바른 날짜여야 합니다.')
            clauses.append(column + operator + '?')
            values.append(value)
    if dates.get('from') and dates.get('to') and dates['from'] > dates['to']:
        abort(400, description='시작 날짜는 종료 날짜보다 늦을 수 없습니다.')
    if filters['q']:
        escaped = filters['q'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        columns = ('record_id', 'robot_id', 'visitor_id', 'route', 'artwork_ids')
        clauses.append('(' + ' OR '.join(f"{column} LIKE ? ESCAPE '\\'" for column in columns) + ')')
        values.extend(['%' + escaped + '%'] * len(columns))
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    total = db.execute('SELECT COUNT(*) FROM TourSession' + where, values).fetchone()[0]
    rows = db.execute(SESSION_SELECT + where + ' ORDER BY created_time DESC, record_id DESC LIMIT ? OFFSET ?',
                      [*values, limit, offset]).fetchall()
    return {'sessions': [serialize(row) for row in rows], 'total': total, 'limit': limit,
            'offset': offset, 'has_more': offset + len(rows) < total, 'filters': filters}
