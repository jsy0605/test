"""로봇이 보낸 로그의 관리자 조회·검색."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import abort


def log_page(db, args):
    def integer(name, default, minimum, maximum):
        value = args.get(name, str(default))
        if not re.fullmatch(r'[0-9]{1,7}', value) or not minimum <= int(value) <= maximum:
            abort(400, description=f'{name}은 {minimum}~{maximum} 사이 정수여야 합니다.')
        return int(value)
    limit, offset = integer('limit', 100, 1, 500), integer('offset', 0, 0, 1000000)
    clauses, values = [], []
    filters = {name: args.get(name, '').strip() for name in ('q','robot_id','date','from','to')}
    if len(filters['q']) > 200 or len(filters['robot_id']) > 64:
        abort(400, description='검색어는 200자, 로봇 ID는 64자 이내로 입력해 주세요.')
    if filters['robot_id']:
        clauses.append('robot_id=?'); values.append(filters['robot_id'])
    if filters["date"]:
        filters["from"] = filters["to"] = filters["date"]
    dates = {}
    for key, operator in (('from','>='),('to','<')):
        if not filters[key]: continue
        try:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', filters[key]): raise ValueError()
            date = datetime.strptime(filters[key], '%Y-%m-%d').replace(tzinfo=ZoneInfo('Asia/Seoul'))
            dates[key] = date
            boundary = date + timedelta(days=1) if key == 'to' else date
            value = int(boundary.timestamp() * 1000)
        except (ValueError, OverflowError, OSError):
            abort(400, description='검색 날짜는 YYYY-MM-DD 형식의 올바른 날짜여야 합니다.')
        clauses.append('sent_at'+operator+'?'); values.append(value)
    if dates.get('from') and dates.get('to') and dates['from'] > dates['to']:
        abort(400, description='시작 날짜는 종료 날짜보다 늦을 수 없습니다.')
    if filters['q']:
        escaped = filters['q'].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        clauses.append("(CAST(log_id AS TEXT) LIKE ? ESCAPE '\\' OR message LIKE ? ESCAPE '\\')")
        values.extend(['%'+escaped+'%'] * 2)
    where = ' WHERE '+' AND '.join(clauses) if clauses else ''
    total = db.execute('SELECT COUNT(*) FROM Log'+where, values).fetchone()[0]
    rows = db.execute('SELECT log_id,robot_id,sent_at,message FROM Log'+where+' ORDER BY sent_at DESC,log_id DESC LIMIT ? OFFSET ?', [*values,limit,offset]).fetchall()
    return {'logs':[dict(row) for row in rows], 'total':total, 'limit':limit, 'offset':offset,
            'has_more':offset+len(rows)<total, 'filters':filters}
