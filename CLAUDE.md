# mrfrenkiecontent — список обучающих видео Mr. Frenkie
Публичный список ссылок на контент Mr. Frenkie (Boosty по подписке, YouTube), читается как PDF по ссылке из README. Ведёт Дмитрий; код не пишет — правки делает Claude. Стек: Markdown + Python-скрипт сборки PDF (headless Edge).
План (решено 2026-11-11):
- Claude собирает PDF из трекера Obsidian `MrFrenkie Content.md` — без чекбоксов, счётчиков и кнопок.
- PDF лежит в `docs/mr-frenkie-content.pdf`, читателям — прямая ссылка через GitHub Pages: `https://dkosarevmusic.github.io/mrfrenkiecontent/mr-frenkie-content.pdf`. Pages включить (источник `main` / `docs`) после первого пуша с PDF.
- В репо остаются только PDF, то, чем она собирается, и настройки Claude.
- Видео добавляются раз в месяц пачкой прямо в трекер — навык `add-video`.
- Дизайн PDF утверждён — макет `design/mockup.html`; собирает его `tools/build_pdf.py` по правилам `design/HANDOFF.md`. В PDF кликабельно всё, что выглядит кликабельным: названия видео и бейджи площадок → видео; разделы на обложке, оглавление, полоса долей, путь в «Что нового» → нужная страница внутри PDF.

## Work order — skills `.claude/skills/`
| When | Skill |
|---|---|
| Добавить видео (пачку) в трекер, обновить метки 🆕 | `add-video` |

## Guards — always
- Раздел для нового видео выбирает Дмитрий: всегда спроси и дождись ответа, сам не решай.
- В хранилище Obsidian (`~/.claude/machine.json` → `obsidianVault`) правь только трекер `MrFrenkie Content.md` и только по задаче Дмитрия; другие заметки — нет. У хранилища нет git: перед правкой копия трекера в scratchpad.
- Разметку списка не ломай: уровни `>`, выноски `[!info]`/`[!example]`, формат строк видео — как у соседей.

## Context economy
- Трекер (~38 КБ) читай по частям: `Grep "^(#|>)"` даёт карту разделов с номерами строк → `Read offset/limit` нужного раздела.

## Where things are
- `README.md` — описание и ссылка на PDF (GitHub Pages).
- `tools/find_new.py` — что нового на Boosty и YouTube и чего нет в трекере (только читает; навык `add-video`, шаг 0); `tools/ignore.txt` — что решено не добавлять.
- `tools/dates.py` → `tools/dates.json` — даты публикации всех ссылок трекера, для порядка строк и периода «Что нового» (сами даты в трекер и PDF не пишутся).
- `design/mockup.html` — утверждаемый макет PDF (4 листа на настоящих данных); `design/fonts/` — шрифты Unbounded, Montserrat, Inter (OFL), макет берёт их локально; `design/out/` — собранные PDF и копия старого каталога (не в git).
- `tools/build_pdf.py` — сборка PDF одной командой (`python tools/build_pdf.py`): трекер → `design/out/catalog.html` (стили из макета, разбивка на листы JS в странице) → `docs/mr-frenkie-content.pdf` → проверки (ссылки = трекер, якоря, листы ≤ 281 мм, провода у рамок); код возврата 0 = пройдены.
- Сборка PDF из HTML: headless Edge (`--print-to-pdf`, отдельный `--user-data-dir`); файл дописывается уже после выхода команды — проверяй время изменения. `--dump-dom` на Windows молчит — отчёт страницы идёт через `console.log` в `chrome_debug.log` профиля (`--enable-logging`).
- Хранилище Obsidian, `Life Manager/MDs/`: `MrFrenkie Content.md` — исходный трекер с чекбоксами, из него собирается список; ссылка на трекер есть в `Music Sound-Design Sources.md`. Копия экспорта в хранилище удалена в `.trash` 2026-11-11.

## Own rules
You maintain this file and the skills: guard → here, procedure → skill, knowledge → docs. Each rule once. New skill → add a line to `.claude/menu.md`. Tell the user in 1–2 lines what changed.
