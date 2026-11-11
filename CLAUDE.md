# mrfrenkiecontent — список обучающих видео Mr. Frenkie
Публичный список ссылок на контент Mr. Frenkie (Boosty по подписке, YouTube), читается на GitHub по ссылке из README. Ведёт Дмитрий; код не пишет — правки делает Claude. Стек: только Markdown, без сборки.
План (решено 2026-11-11):
- Claude собирает PDF из трекера Obsidian `MrFrenkie Content.md` — без чекбоксов, счётчиков и кнопок.
- PDF лежит в `docs/mr-frenkie-content.pdf`, читателям — прямая ссылка через GitHub Pages: `https://dkosarevmusic.github.io/mrfrenkiecontent/mr-frenkie-content.pdf`. Pages включить (источник `main` / `docs`), когда появится первая PDF.
- `Mr. Frenkie Export.md` удалить в том же коммите, где появится первая PDF, и поменять ссылку в README.
- В репо остаются только PDF, то, чем она собирается, и настройки Claude.
- Видео добавляются раз в месяц пачкой прямо в трекер — навык `add-video`.
- Дизайн PDF утверждён — макет `design/mockup.html`; следующий шаг (скрипт сборки) описан в `design/HANDOFF.md`. В PDF кликабельно всё, что выглядит кликабельным: названия видео и бейджи площадок → видео; разделы на обложке, оглавление, полоса долей, путь в «Что нового» → нужная страница внутри PDF.

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
- `Mr. Frenkie Export.md` — старый публичный список (устарел, удаляется с первой PDF).
- `README.md` — описание и ссылка на список.
- `design/mockup.html` — утверждаемый макет PDF (4 листа на настоящих данных); `design/fonts/` — шрифты Unbounded, Montserrat, Inter (OFL), макет берёт их локально; `design/out/` — собранные PDF и копия старого каталога (не в git).
- Сборка PDF из HTML: headless Edge (`--print-to-pdf`, отдельный `--user-data-dir`); файл дописывается уже после выхода команды — проверяй время изменения.
- Хранилище Obsidian, `Life Manager/MDs/`: `MrFrenkie Content.md` — исходный трекер с чекбоксами, из него собирается список; ссылка на трекер есть в `Music Sound-Design Sources.md`. Копия экспорта в хранилище удалена в `.trash` 2026-11-11.

## Own rules
You maintain this file and the skills: guard → here, procedure → skill, knowledge → docs. Each rule once. New skill → add a line to `.claude/menu.md`. Tell the user in 1–2 lines what changed.
