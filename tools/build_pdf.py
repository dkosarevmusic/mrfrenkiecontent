"""Сборка PDF-каталога: трекер Obsidian -> HTML по макету design/mockup.html -> PDF через headless Edge.

Запуск:  python tools/build_pdf.py            # собрать docs/mr-frenkie-content.pdf и проверить
         python tools/build_pdf.py --html     # только HTML (design/out/catalog.html), без печати
Трекер только читается. Стили берутся из <style> макета, шрифты — design/fonts (интернет не нужен).
Разбивку на листы A4, номера страниц оглавления и отчёт для проверок делает JS в самой странице.
Даты для периода «Что нового» — tools/dates.json (нет даты новинки -> сначала python tools/dates.py).
"""
import datetime as dt, html, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
MOCKUP = ROOT / 'design' / 'mockup.html'
OUT_HTML = ROOT / 'design' / 'out' / 'catalog.html'
OUT_PDF = ROOT / 'docs' / 'mr-frenkie-content.pdf'
DATES = ROOT / 'tools' / 'dates.json'
MSK = dt.timezone(dt.timedelta(hours=3))

# Разделы по порядку в трекере: ключевое слово заголовка (для сверки), название, путь в «Что нового», подзаголовок
SECTIONS = [
    ('sound-design', 'Sound Design', 'Sound Design', 'Синтез звука'),
    ('arrangement', 'Arrangement & Genres', 'Arrangement', 'Аранжировка, теория и жанры'),
    ('mixing', 'Mixing & Mastering', 'Mixing', 'Сведение и мастеринг'),
    ('q&a', 'Tips & Q&A', 'Q&A', 'Советы и ответы на вопросы'),
    ('software', 'Software', 'Software', 'Программы и плагины'),
]
MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
MONTHS_NOM = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
LINK = re.compile(r'\[((?:\\.|[^\]\\])*)\]\(([^)\s]+)\)')
NEW = '🆕'


def tracker_path():
    m = json.loads((pathlib.Path.home() / '.claude' / 'machine.json').read_text(encoding='utf-8'))
    return pathlib.Path(m['obsidianVault']) / 'Life Manager' / 'MDs' / 'MrFrenkie Content.md'


def list_start(lines):
    """Список начинается с первого '# ' после блока кнопок (последней строки с INPUT[)."""
    last = max(i for i, l in enumerate(lines) if 'INPUT[' in l)
    return next(i for i in range(last + 1, len(lines)) if lines[i].startswith('# '))


# ---------- текст ----------

def esc(s):
    return html.escape(s, quote=True)


def plural(n, forms):
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return forms[0]
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return forms[1]
    return forms[2]


def materials(n):
    return f'{n} {plural(n, ("материал", "материала", "материалов"))}'


def clean_heading(s):
    s = s.replace(NEW, '').strip()
    return re.sub(r'^[^\w"«]+', '', s).strip()


def clean_title(s):
    s = re.sub(r'\\(.)', r'\1', s)
    s = re.sub(r'\s*-\s*youtube\s*$', '', s, flags=re.I)
    s = re.sub(r'^Mr\.?\s*Frenkie\s*[-:.]\s*', '', s)
    s = re.sub(r'\s*[-.]?\s*Mr\.?\s*Frenkie\s*$', '', s)
    s = re.sub(r'"([^"]*)"', r'«\1»', s)
    s = s.replace(' - ', ' — ')
    return re.sub(r'\s+', ' ', s).strip()


def norm_url(u):
    """Убрать метки отслеживания (si, share…), остальное оставить как есть."""
    p = urllib.parse.urlsplit(u)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
         if k not in ('si', 'is', 'share', 'ab_channel', 'feature')]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), p.fragment))


def is_boosty(u):
    return 'boosty.to' in u


def media_id(u):
    m = re.search(r'boosty\.to/[\w-]+/posts/([0-9a-f-]{36})', u) or \
        re.search(r'(?:youtu\.be/|[?&]v=|/live/|/shorts/)([\w-]{11})', u)
    return m.group(1) if m else None


# ---------- разбор трекера ----------

class Node:
    def __init__(self, kind, title, new=False, **kw):
        self.kind, self.title, self.new = kind, title, new
        self.children = []          # для block/unit: ('list', [items]) | ('unit'|'sub', Node); для module: блоки
        self.items = []             # для sub
        self.__dict__.update(kw)

    def add_item(self, it):
        if self.kind == 'sub':
            self.items.append(it)
        elif self.children and self.children[-1][0] == 'list':
            self.children[-1][1].append(it)
        else:
            self.children.append(('list', [it]))

    def all_items(self):
        if self.kind == 'sub':
            return list(self.items)
        out = []
        for c in self.children:
            if isinstance(c, Node):
                out += c.all_items()
            elif c[0] == 'list':
                out += c[1]
            else:
                out += c[1].all_items()
        return out


def parse_item(s, lineno):
    body = s[2:].strip()
    body = re.sub(r'^\[[ xX]\]\s*', '', body)
    links = list(LINK.finditer(body))
    if not links:
        raise SystemExit(f'Строка {lineno}: пункт списка без ссылки: {s}')
    pre = body[:links[0].start()]
    new = NEW in pre
    if pre.replace(NEW, '').strip():
        raise SystemExit(f'Строка {lineno}: текст перед ссылкой: {s}')
    rest = body[links[0].end():]
    rels = [(m.group(1), m.group(2)) for m in links[1:]]
    note = re.sub(r'\(\s*' + LINK.pattern + r'\s*\)', '', rest)
    note = LINK.sub('', note).replace(NEW, '').strip()
    url = links[0].group(2)
    return dict(raw=links[0].group(1), title=clean_title(links[0].group(1)), url=norm_url(url), new=new,
                note=note, line=lineno,
                rels=[dict(label=clean_title(l), raw=l, url=norm_url(u)) for l, u in rels])


def parse(text):
    lines = text.split('\n')
    start = list_start(lines)
    sections = []
    sec = mod = blk = unit = sub = None
    for i in range(start, len(lines)):
        lineno = i + 1
        m = re.match(r'^((?:>\s?)*)(.*)$', lines[i])
        depth = m.group(1).count('>')
        s = m.group(2).strip()
        if not s or s == '---':
            continue
        if depth == 0:
            if s.startswith('# '):
                sec = Node('section', clean_heading(s[2:]), NEW in s, modules=[], raw=s)
                sections.append(sec)
                mod = blk = unit = sub = None
            elif s.startswith('## '):
                mod = Node('module', clean_heading(s[3:]), NEW in s, implicit=False)
                sec.modules.append(mod)
                blk = unit = sub = None
            else:
                raise SystemExit(f'Строка {lineno}: непонятная строка вне выноски: {s}')
            continue
        if s.startswith('[!info]'):
            title = clean_heading(s[7:])
            if mod is None or mod.implicit:   # раздел без ## (Q&A): блок сам становится подразделом
                mod = Node('module', title, NEW in s, implicit=True)
                sec.modules.append(mod)
            blk = Node('block', title, NEW in s)
            mod.children.append(blk)
            unit = sub = None
        elif s.startswith('[!example]'):
            unit = Node('unit', clean_heading(s[10:]), NEW in s, depth=2)
            blk.children.append(('unit', unit))
            sub = None
        elif re.match(r'#{3,6} ', s):
            title = clean_heading(s.lstrip('#'))
            if depth >= 2:            # подгруппа внутри группы [!example]
                sub = Node('sub', title, NEW in s)
                unit.children.append(('sub', sub))
            else:                     # #### прямо в блоке — это группа
                unit = Node('unit', title, NEW in s, depth=1)
                blk.children.append(('unit', unit))
                sub = None
        elif s.startswith('- '):
            it = parse_item(s, lineno)
            if depth >= 2 or (unit is not None and unit.depth == 1):
                (sub or unit).add_item(it)
            else:
                unit = sub = None
                blk.add_item(it)
        else:
            raise SystemExit(f'Строка {lineno}: непонятная строка: {s}')
    return sections, start


def raw_link_count(text):
    """Независимый счёт: все ссылки в пунктах списка трекера (основные + связанные)."""
    lines = text.split('\n')
    main = rel = 0
    for l in lines[list_start(lines):]:
        s = re.sub(r'^[>\s]*', '', l)
        if s.startswith('- '):
            n = len(LINK.findall(s))
            main += n > 0
            rel += max(n - 1, 0)
    return main, rel


# ---------- HTML ----------

def badge(url):
    if is_boosty(url):
        return f'<a class="src b" href="{esc(url)}"><svg><use href="#i-b"/></svg>Boosty</a>'
    return f'<a class="src yt" href="{esc(url)}"><svg><use href="#i-yt"/></svg>YouTube</a>'


NEW_HTML = '<span class="new">NEW</span>'


def episode(raw):
    m = re.search(r'(?:част[ьи]|ч\.)\s*(\d+(?:\.\d+)?)', raw, re.I) or re.search(r'#\s?(\d+(?:\.\d+)?)', raw)
    return m.group(1) if m else ''


def item_html(it, tag, series):
    ep = f'<span class="ep">{esc(episode(it["raw"]))}</span>' if series else ''
    note = f' <span class="note">{esc(it["note"])}</span>' if it['note'] else ''
    new = NEW_HTML + ' ' if it['new'] else ''
    tg = f'<span class="tag">{tag}</span>' if tag else ''
    out = [f'<li>{ep}<a href="{esc(it["url"])}">{new}{esc(it["title"])}{note}</a>{tg}{badge(it["url"])}</li>']
    for r in it['rels']:
        label = r['label']
        if r['raw'].strip().lower() == 'youtube' and is_boosty(it['url']) and not is_boosty(r['url']):
            label = 'Это же видео на YouTube'
        out.append(f'<li class="rel"><span class="arrow">↳</span><a href="{esc(r["url"])}">{esc(label)}</a>{badge(r["url"])}</li>')
    return ''.join(out)


def list_html(items, tag, series=False):
    return '<ul class="list">' + ''.join(item_html(it, tag, series) for it in items) + '</ul>'


def tag_for(*titles):
    t = [x.lower() for x in titles if x]
    if 'presets' in t:
        return 'Пресет'
    if 'scripts' in t:
        return 'Скрипт'
    return ''


def series_title(title):
    m = re.match(r'^[«"](.+)[»"]\s+Series$', title)
    return (f'«{m.group(1)}»', True) if m else (title, False)


def unit_html(u, ctx):
    name, series = series_title(u.title)
    tag = tag_for(*ctx, u.title)
    parts = []
    for kind, c in u.children:
        if kind == 'list':
            parts.append(list_html(c, tag, series))
        else:
            n = len(c.items)
            parts.append(f'<div class="sub"><h5>{esc(c.title)} <em>{n}</em>{" " + NEW_HTML if c.new else ""}</h5>'
                         + list_html(c.items, tag_for(*ctx, u.title, c.title), series) + '</div>')
    head = (f'<h4>{esc(name)}{" " + NEW_HTML if u.new else ""}{" <span class=\"tag\">Серия</span>" if series else ""}'
            f' <span class="cnt">{len(u.all_items())}</span></h4>')
    return f'<div class="unit" id="{u.id}" data-name="{esc(name)}">{head}<div class="in">{"".join(parts)}</div></div>'


def block_html(b, mod):
    ctx = (mod.title, b.title)
    parts = []
    for kind, c in b.children:
        parts.append(list_html(c, tag_for(*ctx)) if kind == 'list' else unit_html(c, ctx))
    title = 'Videos' if mod.implicit else b.title
    h3 = f'<h3>{esc(title)}{NEW_HTML if b.new and not mod.implicit else ""} <span class="cnt">{len(b.all_items())}</span></h3>'
    return f'<section class="block" id="{b.id}">{h3}{"".join(parts)}</section>'


def module_html(m):
    n = len(m.all_items())
    head = (f'<header><span class="led"></span><h2>{esc(m.title)}</h2>{NEW_HTML if m.new else ""}'
            f'<span class="cnt">{materials(n)}</span></header>')
    return f'<article class="module" id="{m.id}">{head}<div class="body">{"".join(block_html(b, m) for b in m.children)}</div></article>'


def assign_ids(sections):
    for si, sec in enumerate(sections, 1):
        sec.id = f's{si:02d}'
        for mi, m in enumerate(sec.modules, 1):
            m.id = f'm{si}-{mi}'
            for bi, b in enumerate(m.children, 1):
                b.id = f'b{si}-{mi}-{bi}'
                ui = 0
                for kind, c in b.children:
                    if kind == 'unit':
                        ui += 1
                        c.id = f'u{si}-{mi}-{bi}-{ui}'


def whats_new(sections):
    """Новинки по порядку трекера: (раздел, путь, якорь, пункт)."""
    out = []
    for si, sec in enumerate(sections):
        short = SECTIONS[si][2]
        for m in sec.modules:
            for b in m.children:
                def add(items, unit=None, sub=None):
                    for it in items:
                        if it['new']:
                            path = [short, m.title]
                            if not m.implicit and b.title.lower() != 'videos':
                                path.append(b.title)
                            if unit:
                                path.append(series_title(unit.title)[0])
                            anchor = unit.id if unit else b.id
                            out.append((si, ' · '.join(path), anchor, it))
                for kind, c in b.children:
                    if kind == 'list':
                        add(c)
                    else:
                        for k2, c2 in c.children:
                            add(c2 if k2 == 'list' else c2.items, c)
    return out


def period(news, dates):
    whens, missing = [], []
    for *_, it in news:
        mid = media_id(it['url'])
        if mid in dates:
            whens.append(dt.datetime.fromisoformat(dates[mid]).astimezone(MSK).date())
        else:
            missing.append(f'{it["title"]} ({it["url"]})')
    if missing:
        raise SystemExit('Нет даты публикации у новинок (запусти python tools/dates.py, дату не угадывать):\n  '
                         + '\n  '.join(missing))
    if not whens:
        return ''
    a, b = min(whens), max(whens)
    f = lambda d, y: f'{d.day} {MONTHS_GEN[d.month - 1]}' + (f' {d.year}' if y else '')
    if a == b:
        return f(a, True)
    return f'{f(a, a.year != b.year)} — {f(b, True)}'


def tab_html(idx):
    return '<div class="tab">' + ''.join(
        f'<i style="background:var(--c{k});opacity:1"></i>' if k == idx else '<i></i>' for k in range(1, 6)) + '</div>'


HOWTO = '''<div class="howto">
    <h3>Как пользоваться</h3>
    <ul>
      <li><span>Названия</span>Все названия кликабельны — открывают видео или пост.</li>
      <li><span><span class="src b"><svg><use href="#i-b"/></svg>Boosty</span></span>Пост по подписке на автора. Без подписки откроется только заголовок.</li>
      <li><span><span class="src yt"><svg><use href="#i-yt"/></svg>YouTube</span></span>Открыт всем.</li>
      <li><span><span class="tag">Пресет</span><span class="tag">Скрипт</span></span>Тип материала, если это не видео.</li>
      <li><span><span class="new">NEW</span></span>Добавлено в последнем обновлении. У раздела — внутри есть новое.</li>
      <li><span class="arrow">↳</span>Связанная ссылка: копия видео, проект, пресеты.</li>
    </ul>
  </div>'''

CABLES = '''<svg class="cables" viewBox="0 0 400 700" fill="none" stroke-linecap="round">
    <path d="M400 40 C 250 40, 260 200, 120 210 S -20 420, 40 560 S 90 660, 70 700" stroke="var(--c1)" stroke-width="3" opacity=".9"/>
    <path d="M400 110 C 300 120, 330 260, 210 300 S 120 470, 170 580 S 200 670, 180 700" stroke="var(--c2)" stroke-width="3" opacity=".85"/>
    <path d="M400 190 C 340 210, 360 330, 290 360 S 240 500, 280 600 S 280 680, 270 700" stroke="var(--c3)" stroke-width="3" opacity=".8"/>
    <path d="M400 260 C 370 280, 330 300, 330 380 S 390 520, 350 620 S 340 690, 345 700" stroke="var(--c5)" stroke-width="3" opacity=".75"/>
    <path d="M400 330 C 360 340, 250 330, 240 400 S 300 520, 230 640 S 220 690, 225 700" stroke="var(--new)" stroke-width="2" opacity=".7" stroke-dasharray="1 7"/>
    <g fill="var(--bg)" stroke-width="2.5">
      <circle cx="120" cy="210" r="6" stroke="var(--c1)"/><circle cx="210" cy="300" r="6" stroke="var(--c2)"/>
      <circle cx="290" cy="360" r="6" stroke="var(--c3)"/><circle cx="330" cy="380" r="6" stroke="var(--c5)"/>
    </g>
  </svg>'''

# Дополнения к стилям макета, нужные только сборке
EXTRA_CSS = '''
/* ---------- сборка: экран считается как печать, чтобы замеры совпали с PDF ---------- */
.page { margin: 0 auto 24px; }
.module > .body { padding-top: 4mm; }
.module > .body > .block:first-child { margin-top: 0; }
.page > .tab + .module { margin-top: 0; }               /* модуль первым на листе — без лишнего отступа */
.block.cont-down::after, .block.cont-up::after { height: 300mm; }  /* пунктир до края листа (лист обрезает) */
.list .note { color: var(--muted); font-size: 8.8px; }
.page.last { break-after: auto; }
#src, #report { display: none; }
'''

PAGINATE_JS = r'''
(async function () {
  const fonts = ['900 66px Unbounded', '500 14px Unbounded', '400 19px Montserrat', '400 10px Inter', '600 10px Inter'];
  await Promise.all(fonts.map(f => document.fonts.load(f)));
  await document.fonts.ready;
  const MM = 96 / 25.4, LIMIT = 281 * MM, TOL = 0.5;
  const src = document.getElementById('src');
  const isCont = el => el.matches('.module, .module > .body, .block, .unit, .unit > .in, .sub, ul.list');
  const isHead = el => el.matches('.sec-head, .module > header, .block > h3, .unit > h4, .sub > h5');
  const esc = s => s.replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const report = {pages: [], wires: [], errors: []};
  const flowBottom = p => {
    const top = p.getBoundingClientRect().top; let b = 0;
    for (const c of p.children) {
      if (getComputedStyle(c).position === 'absolute') continue;
      b = Math.max(b, c.getBoundingClientRect().bottom - top);
    }
    return b;
  };

  for (const sec of [...src.querySelectorAll(':scope > .sec-src')]) {
    // листья: шапки и строки (строка + её ↳-строки — одно целое); путь — цепочка контейнеров
    const leaves = [];
    (function rec(el, path) {
      for (const ch of [...el.children]) {
        if (isCont(ch)) rec(ch, path.concat([ch]));
        else if (ch.matches('li.rel') && leaves.length) leaves[leaves.length - 1].nodes.push(ch);
        else leaves.push({nodes: [ch], path, head: isHead(ch)});
      }
    })(sec, []);
    // кусок = шапки подряд + первая строка после них (шапка не отрывается от строки)
    const chunks = []; let cur = [];
    for (const lf of leaves) { cur.push(lf); if (!lf.head) { chunks.push(cur); cur = []; } }
    if (cur.length) chunks.push(cur);

    const started = new Set(), lastClone = new Map();
    const newPage = first => {
      const p = document.createElement('section');
      p.className = 'page';
      p.style.setProperty('--acc', sec.dataset.acc);
      if (first) p.id = sec.dataset.id;
      p.dataset.foot = sec.dataset.foot;
      p.innerHTML = sec.dataset.tab;
      document.body.insertBefore(p, src);
      return {el: p, open: [], filled: false};
    };
    const ensure = (pg, path, undo) => {
      let k = 0;
      while (k < pg.open.length && k < path.length && pg.open[k].src === path[k]) k++;
      pg.open.length = k;
      for (let i = k; i < path.length; i++) {
        const s = path[i], c = s.cloneNode(false), parent = i ? pg.open[i - 1].clone : pg.el;
        const cont = started.has(s);
        if (cont) {
          c.removeAttribute('id');
          if (s.matches('.module')) c.classList.add('cont');
          if (s.matches('.block')) {
            c.classList.add('cont-up');
            const prev = lastClone.get(s);
            if (!prev.classList.contains('cont-down')) { prev.classList.add('cont-down'); undo.push(() => prev.classList.remove('cont-down')); }
          }
        } else { started.add(s); undo.push(() => started.delete(s)); }
        const prevClone = lastClone.get(s);
        lastClone.set(s, c);
        undo.push(() => prevClone ? lastClone.set(s, prevClone) : lastClone.delete(s));
        parent.appendChild(c); undo.push(() => c.remove());
        if (cont && s.matches('.unit')) {
          const h = document.createElement('h4'); h.className = 'cont-h';
          h.innerHTML = esc(s.dataset.name) + ' <span>· продолжение</span>'; c.appendChild(h);
        }
        if (cont && s.matches('.sub')) {
          const h = document.createElement('h5');
          h.innerHTML = esc(s.dataset.name) + ' <em>продолжение</em>'; c.appendChild(h);
        }
        pg.open.push({src: s, clone: c});
      }
    };
    const placeChunk = (pg, chunk, undo) => {
      for (const lf of chunk) {
        ensure(pg, lf.path, undo);
        const parent = lf.path.length ? pg.open[pg.open.length - 1].clone : pg.el;
        for (const n of lf.nodes) { parent.appendChild(n); undo.push(() => n.remove()); }
      }
    };

    let page = newPage(true);
    for (const ch of chunks) {
      const snap = page.open.slice(), undo = [];
      placeChunk(page, ch, undo);
      if (flowBottom(page.el) > LIMIT + TOL && page.filled) {
        for (const f of undo.reverse()) f();
        page.open = snap;
        page = newPage(false);
        placeChunk(page, ch, []);
        if (flowBottom(page.el) > LIMIT + TOL) report.errors.push('кусок не влезает на пустой лист: ' + ch[0].nodes[0].textContent.slice(0, 60));
      }
      page.filled = true;
    }
  }

  // подвалы, номера страниц, оглавление
  const pages = [...document.querySelectorAll('body > .page')];
  pages.forEach((p, i) => {
    const n = String(i + 1).padStart(2, '0');
    if (p.dataset.foot) p.insertAdjacentHTML('beforeend', `<div class="foot"><span>${p.dataset.foot}</span><span>${n}</span></div>`);
    p.dataset.n = n;
  });
  pages[pages.length - 1].classList.add('last');
  for (const el of document.querySelectorAll('[data-pg]')) {
    const t = document.getElementById(el.dataset.pg);
    if (!t) { report.errors.push('нет якоря для номера страницы: ' + el.dataset.pg); continue; }
    el.textContent = t.closest('.page').dataset.n;
  }

  // отчёт для проверок сборки
  pages.forEach((p, i) => report.pages.push(+(flowBottom(p) / MM).toFixed(2)));
  for (const b of document.querySelectorAll('.page .block.cont-down')) {
    const m = b.closest('.module'), mr = m.getBoundingClientRect(), br = b.getBoundingClientRect();
    report.wires.push({kind: 'down', page: +b.closest('.page').dataset.n, last: b.parentElement.lastElementChild === b,
      delta: +((mr.bottom - 1) - (br.bottom + 4 * MM)).toFixed(2)});
  }
  for (const b of document.querySelectorAll('.page .block.cont-up')) {
    const m = b.closest('.module'), mr = m.getBoundingClientRect(), br = b.getBoundingClientRect();
    report.wires.push({kind: 'up', page: +b.closest('.page').dataset.n, last: b.parentElement.firstElementChild === b,
      delta: +((br.top - 4 * MM) - (mr.top + 1)).toFixed(2)});
  }
  report.rows = document.querySelectorAll('.page .list li:not(.rel)').length;
  report.rels = document.querySelectorAll('.page .list li.rel').length;
  report.leftover = src.querySelectorAll('li, header, h3, h4, h5, .sec-head').length;
  report.broken = [...document.querySelectorAll('a[href^="#"]')].map(a => a.getAttribute('href')).filter(h => !document.getElementById(h.slice(1)));
  report.internal = document.querySelectorAll('a[href^="#"]').length;
  report.fonts = ['12px Unbounded', '12px Montserrat', '12px Inter'].every(f => document.fonts.check(f));
  document.getElementById('report').textContent = JSON.stringify(report);
  document.documentElement.dataset.ready = '1';
  console.log('BUILD-REPORT ' + JSON.stringify(report));  // сборка читает отчёт из лога Edge
})();
'''


def build_html(sections, dates, today):
    assign_ids(sections)
    style = re.search(r'<style>(.*?)</style>', MOCKUP.read_text(encoding='utf-8'), re.S).group(1)
    style = style.replace('url("fonts/', 'url("../fonts/')

    counts = [len([it for m in s.modules for it in m.all_items()]) for s in sections]
    items = [it for s in sections for m in s.modules for it in m.all_items()]
    total, nb = len(items), sum(is_boosty(it['url']) for it in items)
    news = whats_new(sections)
    per = period(news, dates)

    # обложка
    cover_secs = ''.join(f'<li style="color:var(--c{i})"><a href="#{s.id}"><b>{i:02d}</b>{esc(SECTIONS[i - 1][1])}</a></li>'
                         for i, s in enumerate(sections, 1))
    cover = f'''<section class="page cover">
  <div class="eyebrow">Boosty + YouTube</div>
  <h1>Mr.<span>Frenkie</span></h1>
  <div class="subtitle">Все видео</div>
  <ul class="sections">{cover_secs}</ul>
  {HOWTO}
  {CABLES}
  <div class="stats">
    <div class="stat"><div class="n">{total}</div><div class="l">{plural(total, ("материал", "материала", "материалов"))}</div></div>
    <div class="stat"><div class="n" style="color:var(--boosty)">{nb}</div><div class="l">Boosty</div></div>
    <div class="stat"><div class="n" style="color:var(--yt)">{total - nb}</div><div class="l">YouTube</div></div>
    <div class="stat"><div class="n" style="color:var(--new)">{len(news)}</div><div class="l">{plural(len(news), ("новый", "новых", "новых"))}</div></div>
  </div>
  <div class="date">Обновлено<br><span style="color:var(--text)">{MONTHS_NOM[today.month - 1]} {today.year}</span></div>
</section>'''

    # содержание
    wn = ''.join(f'<li><a class="path" href="#{a}" style="color:var(--c{si + 1})">{esc(path)}</a>'
                 f'<a href="{esc(it["url"])}">{esc(it["title"])}</a>{badge(it["url"])}</li>' for si, path, a, it in news)
    whatsnew = (f'<div class="whatsnew"><h3>{NEW_HTML} Что нового <small>{esc(per)}</small></h3><ul>{wn}</ul></div>'
                if news else '')
    bar = ''.join(f'<a href="#{s.id}" style="flex:{c};background:var(--c{i})"></a>' for i, (s, c) in enumerate(zip(sections, counts), 1))
    legend = ''.join(f'<a href="#{s.id}"><i style="background:var(--c{i})"></i>{esc(SECTIONS[i - 1][1])} <b>{c}</b></a>'
                     for i, (s, c) in enumerate(zip(sections, counts), 1))
    toc = ''
    for i, s in enumerate(sections, 1):
        subs = ''.join(f'<a href="#{m.id}"><span>{esc(m.title)}</span>{" " + NEW_HTML if m.new else ""}<em>{len(m.all_items())}</em>'
                       f'<i class="dots"></i><b data-pg="{m.id}">00</b></a>' for m in s.modules)
        toc += (f'<li style="color:var(--c{i})"><a class="row" href="#{s.id}"><span class="num">{i:02d}</span>'
                f'<span class="t">{esc(SECTIONS[i - 1][1])}{" " + NEW_HTML if s.new else ""}<small>{esc(SECTIONS[i - 1][3])}</small></span>'
                f'<i class="dots"></i><span class="pg" data-pg="{s.id}">00</span></a><div class="subs">{subs}</div></li>')
    contents = f'''<section class="page" data-foot="Mr. Frenkie — все видео">
  <div class="kicker">Mr. Frenkie · все видео</div>
  <div class="h-page">Содержание</div>
  {whatsnew}
  <div class="bar">{bar}</div>
  <div class="legend">{legend}</div>
  <ul class="toc">{toc}</ul>
</section>'''

    # разделы — сплошным потоком, JS разложит по листам
    srcs = ''
    for i, s in enumerate(sections, 1):
        n_new = sum(it['new'] for m in s.modules for it in m.all_items())
        meta = f'{SECTIONS[i - 1][3]} · {materials(counts[i - 1])}' + (f' · {n_new} {plural(n_new, ("новый", "новых", "новых"))}' if n_new else '')
        chips = ''.join(f'<a href="#{m.id}">{esc(m.title)} <em>{len(m.all_items())}</em>{" " + NEW_HTML if m.new else ""}</a>' for m in s.modules)
        head = (f'<div class="sec-head"><div class="sec-num">{i:02d}</div><div>'
                f'<div class="kicker" style="margin-bottom:3mm">Раздел</div>'
                f'<div class="h-page" style="color:var(--c{i})">{esc(SECTIONS[i - 1][1])}</div>'
                f'<div class="meta">{esc(meta)}</div><nav class="chips">{chips}</nav></div></div>')
        srcs += (f'<div class="sec-src" data-id="{s.id}" data-acc="var(--c{i})" data-foot="{i:02d} · {esc(SECTIONS[i - 1][1])}"'
                 f' data-tab="{esc(tab_html(i))}">{head}{"".join(module_html(m) for m in s.modules)}</div>')
    # подгруппам — имя для шапки продолжения
    srcs = re.sub(r'<div class="sub"><h5>([^<]*?) <em>', lambda m: f'<div class="sub" data-name="{m.group(1)}"><h5>{m.group(1)} <em>', srcs)

    return f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mr. Frenkie — все видео</title>
<style>{style}{EXTRA_CSS}</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute">
  <symbol id="i-yt" viewBox="0 0 10 10"><path d="M2 1.2 L9 5 L2 8.8 Z" fill="currentColor"/></symbol>
  <symbol id="i-b" viewBox="0 0 10 10"><circle cx="5" cy="5" r="3.6" fill="currentColor"/></symbol>
</svg>
{cover}
{contents}
<div id="src">{srcs}</div>
<pre id="report"></pre>
<script>{PAGINATE_JS}</script>
</body>
</html>
'''


# ---------- Edge ----------

def edge_path():
    for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), os.environ.get('LOCALAPPDATA')):
        if base:
            p = pathlib.Path(base) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe'
            if p.exists():
                return str(p)
    p = shutil.which('msedge')
    if not p:
        raise SystemExit('Не найден Microsoft Edge (msedge.exe)')
    return p


def edge(args, profile):
    cmd = [edge_path(), '--headless=new', '--disable-gpu', f'--user-data-dir={profile}', '--no-first-run',
           '--enable-logging', '--v=0', '--virtual-time-budget=10000'] + args
    return subprocess.run(cmd, capture_output=True, timeout=180)


def print_pdf(url, out, profile):
    """Печать в PDF; отчёт разбивки — из console.log страницы (msedge.exe на Windows не пишет в stdout,
    поэтому --dump-dom не годится; лог Edge кладёт в chrome_debug.log папки профиля)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    before = out.stat().st_mtime if out.exists() else 0
    t0 = time.time()
    edge(['--no-pdf-header-footer', f'--print-to-pdf={out}', url], profile)
    # Edge дописывает файл уже после выхода команды: ждём новый файл с устоявшимся размером
    last = -1
    while True:
        if time.time() - t0 > 120:
            raise SystemExit('PDF не появился за 2 минуты')
        if out.exists() and out.stat().st_mtime > before:
            size = out.stat().st_size
            if size == last and size > 0:
                break
            last = size
        time.sleep(1)
    log = pathlib.Path(profile) / 'chrome_debug.log'
    text = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
    m = re.search(r'BUILD-REPORT (\{.*?\})", source', text)
    if not m:
        raise SystemExit('Edge не вернул отчёт разбивки (JS не отработал?)')
    return json.loads(m.group(1))


def direct_links(pdf):
    """Edge пишет внутренние ссылки по имени метки (/Dest /s01 + таблица /Dests). Компьютерный Chrome это
    понимает, а мобильные программы для PDF часто нет. Меняем каждую на прямую: [страница /XYZ x y 0]."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, NameObject, FloatObject, NumberObject
    rd = PdfReader(str(pdf))
    target = {}
    for name, d in rd.named_destinations.items():
        target[str(name)] = (rd.get_destination_page_number(d), float(d.left or 0), float(d.top or 0))
    w = PdfWriter(clone_from=rd)
    for page in w.pages:
        for a in page.get('/Annots') or []:
            a = a.get_object()
            d = a.get('/Dest')
            if a.get('/Subtype') != '/Link' or d is None:
                continue
            d = str(d.get_object() if hasattr(d, 'get_object') else d)
            if d not in target:
                raise SystemExit(f'Внутренняя ссылка на несуществующую метку: {d}')
            n, left, top = target[d]
            a[NameObject('/Dest')] = ArrayObject([w.pages[n].indirect_reference, NameObject('/XYZ'),
                                                  FloatObject(left), FloatObject(top), NumberObject(0)])
    tmp = pdf.with_suffix('.tmp.pdf')
    with open(tmp, 'wb') as f:
        w.write(f)
    tmp.replace(pdf)


# ---------- проверки ----------

def check(report, pdf, sections, raw_counts):
    from pypdf import PdfReader
    errs = []
    items = [it for s in sections for m in s.modules for it in m.all_items()]
    n_rels = sum(len(it['rels']) for it in items)
    if (len(items), n_rels) != raw_counts:
        errs.append(f'разбор трекера: {len(items)}+{n_rels} ссылок, прямой счёт {raw_counts[0]}+{raw_counts[1]}')
    if report['rows'] != len(items) or report['rels'] != n_rels:
        errs.append(f'в вёрстке строк {report["rows"]}+{report["rels"]}, в трекере {len(items)}+{n_rels}')
    if report['leftover']:
        errs.append(f'не разложено по листам: {report["leftover"]} элементов')
    errs += report['errors']
    if report['broken']:
        errs.append('внутренние ссылки без цели: ' + ', '.join(report['broken']))
    if not report['fonts']:
        errs.append('шрифты не загрузились')
    tall = [(i + 1, h) for i, h in enumerate(report['pages']) if h > 281.02]
    if tall:
        errs.append('листы выше 281 мм: ' + ', '.join(f'{p} ({h} мм)' for p, h in tall))
    bad_w = [w for w in report['wires'] if abs(w['delta']) > 0.6 or not w['last']]
    if bad_w:
        errs.append(f'провода не у рамки: {bad_w}')

    rd = PdfReader(str(pdf))
    if len(rd.pages) != len(report['pages']):
        errs.append(f'страниц в PDF {len(rd.pages)}, свёрстано {len(report["pages"])}')
    uris, internal, dead = [], 0, []
    page_objs = [p.get_object() for p in rd.pages]
    for pg in rd.pages:
        w, h = float(pg.mediabox.width), float(pg.mediabox.height)
        if abs(w - 595.28) > 1.5 or abs(h - 841.89) > 1.5:
            errs.append(f'размер листа не A4: {w:.1f}×{h:.1f}')
            break
    for pg in rd.pages:
        for a in pg.get('/Annots') or []:
            a = a.get_object()
            if a.get('/Subtype') != '/Link':
                continue
            act = a.get('/A')
            act = act.get_object() if act is not None else None
            if act is not None and act.get('/S') == '/URI':
                uris.append(str(act['/URI']))
                continue
            internal += 1
            d = a.get('/Dest') if a.get('/Dest') is not None else (act.get('/D') if act is not None else None)
            d = d.get_object() if hasattr(d, 'get_object') else d
            if isinstance(d, str):   # ссылка по имени метки — мобильные программы её не понимают
                dead.append(f'{d} (по имени, не прямая)')
            elif not (isinstance(d, list) and d and d[0].get_object() in page_objs):
                dead.append(str(d))
    want = {it['url'] for it in items} | {r['url'] for it in items for r in it['rels']}
    if set(uris) != want:
        errs.append(f'ссылки PDF ≠ трекер: лишние {sorted(set(uris) - want)[:5]}, нет {sorted(want - set(uris))[:5]}')
    n_new = sum(it['new'] for it in items)
    exp = 2 * (len(items) + n_rels) + 2 * n_new
    if len(uris) != exp:
        errs.append(f'внешних ссылок в PDF {len(uris)}, ожидалось {exp}')
    if internal < report['internal']:
        errs.append(f'внутренних ссылок в PDF {internal}, в вёрстке {report["internal"]}')
    if dead:
        errs.append(f'внутренние ссылки PDF без цели: {dead[:5]}')
    stats = dict(pages=len(rd.pages), rows=len(items), rels=n_rels, boosty=sum(is_boosty(it['url']) for it in items),
                 new=n_new, uris=len(uris), internal=internal, max_mm=max(report['pages']), wires=len(report['wires']))
    return errs, stats


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    only_html = '--html' in sys.argv
    text = tracker_path().read_text(encoding='utf-8')
    sections, _ = parse(text)
    if len(sections) != len(SECTIONS) or any(k not in s.raw.lower() for (k, *_), s in zip(SECTIONS, sections)):
        raise SystemExit('Разделы трекера не совпадают с ожидаемыми: ' + ' | '.join(s.title for s in sections)
                         + '\nПоправь SECTIONS в tools/build_pdf.py')
    dates = json.loads(DATES.read_text(encoding='utf-8'))
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(build_html(sections, dates, dt.datetime.now(MSK).date()), encoding='utf-8')
    print('HTML:', OUT_HTML.relative_to(ROOT))
    if only_html:
        return 0
    url = OUT_HTML.as_uri()
    # фоновый процесс Edge иногда держит файлы профиля после выхода — не падать на уборке
    with tempfile.TemporaryDirectory(prefix='edge-pdf-', ignore_cleanup_errors=True) as profile:
        report = print_pdf(url, OUT_PDF, profile)
    direct_links(OUT_PDF)
    print('PDF: ', OUT_PDF.relative_to(ROOT))
    errs, st = check(report, OUT_PDF, sections, raw_link_count(text))
    print(f"Листов {st['pages']}; строк {st['rows']} (Boosty {st['boosty']}, YouTube {st['rows'] - st['boosty']}) + ↳ {st['rels']}; "
          f"новых {st['new']}; внешних ссылок {st['uris']}, внутренних {st['internal']}; самый высокий лист {st['max_mm']} мм; "
          f"переходов провода {st['wires']}")
    if errs:
        print('ПРОВЕРКИ НЕ ПРОЙДЕНЫ:')
        for e in errs:
            print(' -', e)
        return 1
    print('Проверки пройдены.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
