"""Даты публикации всех ссылок трекера -> tools/dates.json (только для порядка строк; в трекер и PDF не пишутся).

Запуск:  python tools/dates.py            # дополнить: скачать даты только для новых id
         python tools/dates.py --refresh  # перекачать всё
         python tools/dates.py ID [ID ...] # ещё и эти id (ещё не в трекере), например перед вставкой
Формат:  {"<id>": "2026-11-04T00:17:49+03:00", ...}, время по Москве. Boosty — publishTime из API,
         YouTube — startTimestamp стрима, иначе publishDate со страницы видео.
"""
import json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import find_new as F

OUT = pathlib.Path(__file__).with_name('dates.json')


def main():
    args = sys.argv[1:]
    refresh = '--refresh' in args
    extra = [a for a in args if not a.startswith('--')]
    cache = {} if refresh or not OUT.exists() else json.loads(OUT.read_text(encoding='utf-8'))

    kb, ky = F.known_ids(F.tracker_path(None).read_text(encoding='utf-8'))
    for e in extra:
        (kb if re.fullmatch(r'[0-9a-f-]{36}', e) else ky).add(e)

    need_b = [i for i in kb if i not in cache]
    if need_b:
        for p in F.boosty_posts(None):
            if p['id'] in kb:
                cache[p['id']] = p['when'].isoformat()
    miss_b = [i for i in kb if i not in cache]

    miss_y = []
    for vid in sorted(i for i in ky if i not in cache):
        try:
            when, _ = F.yt_details(vid)
        except Exception as ex:  # видео удалено или недоступно
            when = None
            print(f'YouTube {vid}: ошибка {ex}')
        if when:
            cache[vid] = when.isoformat()
        else:
            miss_y.append(vid)

    OUT.write_text(json.dumps(dict(sorted(cache.items())), ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'Boosty: {len(kb)} id, дат {len(kb) - len(miss_b)}; YouTube: {len(ky)} id, дат {len(ky) - len(miss_y)}; в файле {len(cache)}')
    for i in miss_b:
        print('нет даты Boosty:', i)
    for i in miss_y:
        print('нет даты YouTube:', i)
    return 0


if __name__ == '__main__':
    sys.exit(main())
