"""Что нового у Mr. Frenkie: свежие посты Boosty и видео/стримы YouTube, которых ещё нет в трекере.

Запуск:  python tools/find_new.py                 # за последние 45 дней (служебные посты скрыты; --show-service — показать)
         python tools/find_new.py --since 2026-10-01
         python tools/find_new.py --all           # весь Boosty + первые ~30 видео и стримов YouTube
Трекер:  ~/.claude/machine.json -> obsidianVault + "Life Manager/MDs/MrFrenkie Content.md" (или --tracker PATH).
Ничего не меняет: только печатает список. Без входа: Boosty отдаёт и платные посты (название, дата, ссылка).
"""
import argparse, datetime as dt, difflib, json, pathlib, re, sys, urllib.request

BOOSTY_BLOG = 'mrfrenkie'
YT_CHANNEL = 'UC8pd3tMzamnMlQ-xLEgyxwQ'
MSK = dt.timezone(dt.timedelta(hours=3))
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ru-RU,ru;q=0.9'}
# посты Boosty без контента: сборы треков, объявления
SERVICE = re.compile(r'^(сбор\b|внимание|анонс|опрос|объявление|встреча|сходка|завтра сходка|благодарност|переезд|чат\b)', re.I)
SERVICE_TAG = re.compile(r'^\[(сбор[^\]]*|объявление|встреча|анонс)\]', re.I)


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def tracker_path(arg):
    if arg:
        return pathlib.Path(arg)
    m = json.loads((pathlib.Path.home() / '.claude' / 'machine.json').read_text(encoding='utf-8'))
    return pathlib.Path(m['obsidianVault']) / 'Life Manager' / 'MDs' / 'MrFrenkie Content.md'


def known_ids(text):
    boosty = set(re.findall(r'boosty\.to/[\w-]+/posts/([0-9a-f-]{36})', text))
    yt = set(re.findall(r'(?:youtu\.be/|[?&]v=|/live/|/shorts/)([\w-]{11})', text))
    return boosty, yt


def boosty_posts(since):
    """Посты новее since (или все, если since=None), от новых к старым."""
    out, offset = [], None
    while True:
        url = f'https://api.boosty.to/v1/blog/{BOOSTY_BLOG}/post/?limit=50' + (f'&offset={offset}' if offset else '')
        j = json.loads(get(url))
        for p in j['data']:
            when = dt.datetime.fromtimestamp(p['publishTime'], MSK)
            if since and when < since:
                return out
            out.append({'id': p['id'], 'title': p['title'].strip(), 'when': when, 'access': p.get('hasAccess')})
        if j['extra'].get('isLast') or not j['data']:
            return out
        offset = j['extra']['offset']


def yt_tab(tab):
    html = get(f'https://www.youtube.com/channel/{YT_CHANNEL}/{tab}?hl=ru')
    m = re.search(r'var ytInitialData = (\{.*?\});</script>', html, re.S)
    if not m:
        raise RuntimeError(f'YouTube /{tab}: страница не разобралась (ytInitialData не найден)')
    out = []

    def walk(v):
        if isinstance(v, dict):
            if 'richItemRenderer' in v:
                c = v['richItemRenderer'].get('content', {})
                if 'lockupViewModel' in c:
                    lk = c['lockupViewModel']
                    out.append((lk.get('contentId'), lk.get('metadata', {}).get('lockupMetadataViewModel', {}).get('title', {}).get('content')))
                elif 'videoRenderer' in c:
                    vr = c['videoRenderer']
                    out.append((vr['videoId'], vr['title']['runs'][0]['text']))
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(json.loads(m.group(1)))
    return [x for x in out if x[0]]


def yt_details(vid):
    html = get(f'https://www.youtube.com/watch?v={vid}&hl=ru')
    start = re.search(r'"startTimestamp":"([^"]+)"', html)
    pub = re.search(r'"publishDate":"([^"]+)"', html)
    title = re.search(r'"title":"((?:[^"\\]|\\.)*)","lengthSeconds"', html)
    raw = (start or pub).group(1) if (start or pub) else None
    when = dt.datetime.fromisoformat(raw).astimezone(MSK) if raw else None
    t = json.loads(f'"{title.group(1)}"') if title else None
    return when, t


def ignored_ids():
    f = pathlib.Path(__file__).with_name('ignore.txt')
    if not f.exists():
        return set()
    return {ln.split('#')[0].strip() for ln in f.read_text(encoding='utf-8').splitlines() if ln.split('#')[0].strip()}


def norm(t):
    t = re.sub(r'\[[^\]]*\]|mr\.? ?frenkie|youtube', ' ', t.lower())
    return re.sub(r'[^\w]+', ' ', t).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', help='YYYY-MM-DD, по Москве')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--tracker')
    ap.add_argument('--show-service', action='store_true', help='показать и служебные посты (сборы, встречи, объявления)')
    a = ap.parse_args()
    since = None if a.all else (dt.datetime.fromisoformat(a.since).replace(tzinfo=MSK) if a.since
                                else dt.datetime.now(MSK) - dt.timedelta(days=45))

    path = tracker_path(a.tracker)
    kb, ky = known_ids(path.read_text(encoding='utf-8'))
    ign = ignored_ids()
    kb |= ign
    ky |= ign
    print(f'Трекер: {len(kb - ign)} постов Boosty, {len(ky - ign)} видео YouTube; исключений (tools/ignore.txt): {len(ign)}')

    items = []
    posts = boosty_posts(since)
    for p in posts:
        if p['id'] in kb:
            continue
        kind = 'стрим' if '[СТРИМ]' in p['title'].upper() else 'видео' if '[ВИДЕО]' in p['title'].upper() else 'пост'
        bare = re.sub(r'^\[[^\]]*\]\s*', '', p['title'])  # без ведущей метки [..]
        service = kind == 'пост' and bool(SERVICE_TAG.search(p['title']) or SERVICE.search(bare) or SERVICE.search(p['title']))
        items.append({'when': p['when'], 'src': 'Boosty', 'kind': kind, 'title': p['title'],
                      'url': f'https://boosty.to/{BOOSTY_BLOG}/posts/{p["id"]}', 'service': service})
    print(f'Boosty: прочитано {len(posts)} постов' + (f' с {since:%d.%m.%Y}' if since else ' (все)') + f', новых {sum(i["src"] == "Boosty" for i in items)}')

    for tab, kind in (('videos', 'видео'), ('streams', 'стрим')):
        lst = yt_tab(tab)
        new = [x for x in lst if x[0] not in ky]
        added = 0
        for vid, title in new:
            when, t = yt_details(vid)
            if since and when and when < since:
                continue
            items.append({'when': when, 'src': 'YouTube', 'kind': kind, 'title': t or title,
                          'url': f'https://youtu.be/{vid}', 'service': False})
            added += 1
        print(f'YouTube /{tab}: на странице {len(lst)}, нет в трекере {len(new)}, из них в периоде {added}')

    # одно и то же видео на обеих площадках: похожее название, разница до 3 дней
    for y in (i for i in items if i['src'] == 'YouTube'):
        for b in (i for i in items if i['src'] == 'Boosty'):
            close = y['when'] and abs((y['when'] - b['when']).days) <= 3
            if close and difflib.SequenceMatcher(None, norm(y['title']), norm(b['title'])).ratio() > 0.6:
                y['pair'] = b['title']

    # служебные посты не добавляются и не показываются (решение Дмитрия, 2026-11-11); список — по --show-service
    n_service = sum(i['service'] for i in items)
    if not a.show_service:
        items = [i for i in items if not i['service']]
    items.sort(key=lambda i: i['when'] or dt.datetime.min.replace(tzinfo=MSK))
    hidden = f' (скрыто служебных постов Boosty: {n_service})' if n_service and not a.show_service else ''
    print(f'\nНовых: {len(items)}{hidden}\n')
    for n, i in enumerate(items, 1):
        when = f'{i["when"]:%d.%m.%Y %H:%M}' if i['when'] else 'дата ?'
        flag = '  [служебный?]' if i['service'] else ''
        pair = f'\n      ↳ похоже на Boosty: «{i["pair"]}»' if i.get('pair') else ''
        print(f'{n:>2}. {when} МСК  {i["src"]:<7} {i["kind"]:<5} {i["title"]}{flag}\n      {i["url"]}{pair}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
