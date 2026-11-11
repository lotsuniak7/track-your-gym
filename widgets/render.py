"""HTML-виджеты (Bot API 10.4, sendWidget): интерфейс рисуется прямо в сообщении.

Ограничения Telegram, под которые всё здесь заточено:
  * HTML нельзя заменить после отправки — меняется только chat_data (до 1024 байт);
  * HTML ≤ 32768 байт и ≤ 4096 байт после zlib (уровень 9);
  * высота пузыря ≤ 600 px, прокрутки нет, внешние картинки и шрифты не грузятся;
  * виджет общается с ботом через TelegramWidget.request(строка ≤ 64 байт) → ответ ≤ 1024 байт.

Поэтому данные экрана вшиваются в HTML при отправке, а в chat_data лежит только состояние.
"""

import json
import re
import zlib

MAX_HTML = 32768
MAX_COMPRESSED = 4096

# Общий стиль: тёмный «зал», лаймовый акцент, оранжевый — текущее упражнение
_CSS = """
*{box-sizing:border-box;margin:0}
html,body{background:#0d1016}
body{font-family:system-ui,sans-serif;color:#f2f4f8;padding:14px;font-size:14px;user-select:none;position:relative;overflow:hidden}
.l{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:#8891a3;font-weight:700}
.t{display:flex;justify-content:space-between;align-items:center;gap:8px}
.h{font-weight:800;font-style:italic;text-transform:uppercase;font-size:17px;line-height:1.15}
.a{color:#c5f82a}
.c{background:linear-gradient(160deg,#1d2433,#131822);border:1px solid #283041;border-radius:16px;padding:14px;margin-top:10px}
button{font:inherit;border:0;border-radius:12px;color:#f2f4f8;background:#222a3a;padding:10px 6px;font-weight:700;flex:1;min-width:0}
button:active{opacity:.6}
.r{display:flex;gap:6px;margin-top:8px}
.g{width:100%;margin-top:10px;padding:15px;font-size:15px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;background:linear-gradient(90deg,#c5f82a,#8ee000);color:#0d1016;border-radius:14px;box-shadow:0 6px 18px #c5f82a33}
.g.o{background:#222a3a;color:#f2f4f8;box-shadow:none}
.w{opacity:.45}
.m{position:absolute;left:0;top:0;right:0;bottom:0;background:#0d1016f2;padding:18px;display:flex;flex-direction:column;justify-content:center;gap:10px;text-align:center}
.e{background:#ff6b2c22;color:#ff9a6b;border-radius:10px;padding:8px;margin-top:8px;font-size:12px;text-align:center}
"""

_WORKOUT_CSS = """
.b{display:flex;gap:3px;margin:10px 0 0}
.s{flex:1;height:24px;border-radius:6px;background:#222a3a;font-size:10px;font-weight:800;color:#8891a3;display:flex;align-items:center;justify-content:center}
.s.d{background:#c5f82a;color:#0d1016}.s.n{background:#ff6b2c;color:#fff;box-shadow:0 0 12px #ff6b2c88}
h1{font-size:21px;line-height:1.15;font-weight:800;margin:6px 0 4px}
.k{display:flex;gap:8px;margin-top:12px}
.k div{flex:1;background:#0d1016;border-radius:12px;padding:8px 10px}
.k b{display:block;font-size:24px;font-weight:800;font-style:italic;color:#c5f82a}
.x{color:#8891a3;font-size:12px;margin-top:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.z{font-size:54px}
.q button{padding:9px 2px;font-size:13px}
.q .v{flex:2;color:#c5f82a;font-size:15px}
"""

_HOME_CSS = """
.b{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.s{background:#222a3a;border-radius:10px;padding:8px 12px;font-weight:700;font-size:13px;max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.s.n{background:#ff6b2c;color:#fff;box-shadow:0 0 12px #ff6b2c66}
.i{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px solid #222a3a}
.i span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.i b{color:#c5f82a;font-style:italic;white-space:nowrap}
.q{color:#8891a3;font-size:12px;padding-top:8px}
"""

# Общий JS: состояние из chat_data, запросы к боту, перерисовка
_JS = """
const W=TelegramWidget,D=__DATA__,B=document.body,FIT=596;
let S={},busy=0,err='',M='';
function L(){try{S=JSON.parse(W.chatData)||{}}catch(e){S={}}}
function H(k){try{W.HapticFeedback[k=='ok'?'notificationOccurred':'impactOccurred'](k=='ok'?'success':'light')}catch(e){}}
function Q(a,f){if(busy)return;busy=1;err='';H();R();W.request(a).then(r=>{busy=0;let j={};try{j=JSON.parse(r.result)||{}}catch(e){}
if(j.e)err=j.e;if(j.s)S=j.s;f&&f(j);R()},x=>{busy=0;err=x.code=='TIMEOUT'?'Бот не отвечает — попробуй ещё раз':x.code=='RATE_LIMITED'?'Слишком быстро, секунду…':'Не получилось, попробуй ещё раз';R()})}
function E(s){return String(s).replace(/[&<>"]/g,c=>'&#'+c.charCodeAt(0)+';')}
"""

_STATE_EVENTS = """
W.onEvent('chatDataChanged',()=>{if(!busy){L();R()}});
"""

_WORKOUT_JS = """
let Wt={},lv=0;
function G(c){return Wt[c.i]!=null?Wt[c.i]:c.w||0}
function K(i,v){const c=D.x.find(e=>e.i==i);Wt[i]=Math.max(0,Math.round((G(c)+v)*2)/2);H();R()}
function N(){const x=D.x,d=S.d||[],k=x.findIndex(e=>e.i==S.c);for(let j=1;j<x.length;j++){const e=x[(k+j)%x.length];if(!d.includes(e.i))return e}}
function T(i){Q('t:'+i,j=>{if(j.t)M='<div class=l>Техника</div><div style="font-size:15px;line-height:1.4">'+E(j.t)+'</div><button class=g onclick="M=\\'\\';R()">Понятно</button>'})}
function F(){M='<div class=h>Закончить тренировку?</div><div class=l>Выполнено '+(S.d||[]).length+' из '+D.x.length+'</div><button class=g onclick="M=\\'\\';Q(\\'f\\')">Да, закончить</button><button class="g o" onclick="M=\\'\\';R()">Продолжить</button>';R()}
function R0(){const f=S.f,x=D.x,d=S.d||[];let h;
if(f){h='<div class=m style="position:static;background:none"><div class=z>'+(f.a?'🏆':'💪')+'</div><div class=h>Тренировка завершена</div><div style="font-size:16px">'+E(f.p)+'</div><div class=k><div><b>'+f.d+'/'+f.t+'</b><span class=l>упражнений</span></div>'+(f.m?'<div><b>'+f.m+'</b><span class=l>минут</span></div>':'')+(f.n?'<div><b>'+f.n+'</b><span class=l>тренировка</span></div>':'')+'</div><button class=g onclick="Q(\\'h\\')">На главную</button></div>'}
else{const c=x.find(e=>e.i==S.c)||x[0],k=x.indexOf(c),o=d.includes(c.i),n=N(),g=G(c);
h='<div class=t><div class=h>'+E(D.t)+'</div><div class="h a">'+d.length+'/'+x.length+'</div></div><div class=b>'+x.map((e,j)=>'<div class="s'+(e.i==c.i?' n':d.includes(e.i)?' d':'')+'" onclick="Q(\\'g:'+e.i+'\\')">'+(d.includes(e.i)&&e.i!=c.i?'✓':j+1)+'</div>').join('')+'</div>'
+'<div class=c><div class=l>Упражнение '+(k+1)+(c.m?' · '+E(c.m):'')+'</div><h1>'+E(c.n)+'</h1>'+(c.o?'<div class=l style="color:#ff9a6b">Замена · было: '+E(c.o)+'</div>':'')
+'<div class=k><div><b>'+c.s+'</b><span class=l>подходы</span></div><div><b>'+E(c.r)+'</b><span class=l>повторения</span></div></div>'
+'<div class="r q"><button onclick="K('+c.i+',-10)">−10</button><button onclick="K('+c.i+',-2.5)">−2.5</button><button class=v>'+(g?g+' кг':'без веса')+'</button><button onclick="K('+c.i+',2.5)">+2.5</button><button onclick="K('+c.i+',10)">+10</button></div>'
+'<div class=r><button onclick="Q(\\'p:'+c.i+'\\')">📷 Фото</button>'+(c.h?'<button onclick="T('+c.i+')">📝 Техника</button>':'')+'<button onclick="Q(\\'w:'+c.i+'\\')">🔄 Замена</button></div></div>'
+(o?'<button class="g o" onclick="Q(\\'u:'+c.i+'\\')">↩ Снять отметку</button>':'<button class=g onclick="H(\\'ok\\');Q(\\'d:'+c.i+':'+Math.round(g*10)+'\\')">✓ Выполнено</button>')
+(err?'<div class=e>'+E(err)+'</div>':'')
+'<div class=r><button onclick="Q(\\'k\\')">'+(o?'Дальше →':'Пропустить →')+'</button><button onclick="Q(\\'a\\')">🎲 Заменить всё</button></div>'
+'<div class=r>'+(D.w?'<button onclick="Q(\\'r\\')">↩ Как в программе</button>':'')+'<button onclick="F()">🏁 Закончить</button></div>'
+(lv?'':n?'<div class=x>Далее: '+E(n.n)+'</div>':'<div class=x>Последнее упражнение — дожимай 🔥</div>')}
B.innerHTML=h+(M?'<div class=m>'+M+'</div>':'');B.className=busy?'w':''}
function R(){lv=0;R0();try{if(B.scrollHeight>FIT){lv=1;R0()}}catch(e){}}
L();R();
"""

_HOME_JS = """
let P=0;try{P=+localStorage.getItem('d')||0}catch(e){}
function G(i){P=i;try{localStorage.setItem('d',i)}catch(e){}H();R()}
let mx=99;
function R0(){const y=D.y,u=S.u||D.u;let h='<div class=t><div class=l>Track your gym</div>'+(D.n?'<div class=l>🔥 '+D.n+' '+E(D.nw)+'</div>':'')+'</div><div class=h style="font-size:22px;margin-top:4px">'+E(D.p)+'</div>';
if(!y.length)h+='<div class=c><div class=q>В программе пока нет дней.</div></div><button class=g onclick="Q(\\'E\\')">Добавить день</button>';
else{let a=y.findIndex(e=>e.i==P);if(a<0)a=u?Math.max(0,y.findIndex(e=>e.i==u.i)):0;const c=y[a],r=u&&u.i==c.i;
h+='<div class=b>'+y.map(e=>'<div class="s'+(e.i==c.i?' n':'')+'" onclick="G('+e.i+')">'+E(e.t)+'</div>').join('')+'</div>'
+'<div class=c><div class=l>'+(c.c?c.c+' '+E(c.cw)+' · '+c.s+' '+E(c.sw):'Пусто')+'</div>'+c.x.slice(0,mx).map(e=>'<div class=i><span>'+E(e[0])+'</span><b>'+E(e[1])+'</b></div>').join('')+(c.c>Math.min(mx,c.x.length)?'<div class=q>…и ещё '+(c.c-Math.min(mx,c.x.length))+'</div>':'')+(c.c?'':'<div class=q>Добавь упражнения, чтобы начать.</div>')+'</div>'
+(c.c?(r?'<button class=g onclick="Q(\\'C\\')">Продолжить · '+u.d+'/'+u.t+'</button>':'<button class=g onclick="Q(\\'S:'+c.i+'\\')">Начать тренировку</button>'):'<button class=g onclick="Q(\\'D:'+c.i+'\\')">Добавить упражнения</button>')
+(err?'<div class=e>'+E(err)+'</div>':'')
+'<div class=r>'+(r?'<button onclick="Q(\\'S:'+c.i+'\\')">🔁 Заново</button>':'')+'<button onclick="Q(\\'D:'+c.i+'\\')">✏️ Изменить день</button></div>'}
h+='<div class=r><button onclick="Q(\\'E\\')">⚙️ Правка</button><button onclick="Q(\\'P\\')">🔀 Программы</button><button onclick="Q(\\'R\\')">📊 Прогресс</button></div>';
B.innerHTML=h;B.className=busy?'w':''}
function R(){mx=99;R0();try{let g=0;while(B.scrollHeight>FIT&&mx>1&&g++<12){mx=Math.min(mx,6)-1;R0()}}catch(e){}}
L();R();
"""


def _minify(code: str) -> str:
    return re.sub(r"\n\s*", "", code.strip())


def _build(css: str, js: str, data: dict) -> str | None:
    """Собирает HTML. Возвращает None, если виджет не влезает в лимиты Telegram."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (
        "<!doctype html><html><head><meta charset=utf-8><style>"
        + _minify(_CSS + css)
        + "</style></head><body><script>"
        + (_JS + js).strip().replace("__DATA__", payload)
        + "</script></body></html>"
    )
    raw = html.encode()
    if len(raw) > MAX_HTML or len(zlib.compress(raw, 9)) > MAX_COMPRESSED:
        return None
    return html


def workout_html(title: str, exercises: list[dict], has_swaps: bool) -> str | None:
    """exercises: {i: id, n: название, s: подходы, r: повторения, m: мышца, o: что было до замены, h: есть техника,
    w: вес с прошлого раза, кг}."""
    data = {"t": title, "x": exercises, "w": int(has_swaps)}
    html = _build(_WORKOUT_CSS, _STATE_EVENTS + _WORKOUT_JS, data)
    if html is None:  # не влезло — убираем подписи мышц
        data["x"] = [{k: v for k, v in e.items() if k != "m"} for e in exercises]
        html = _build(_WORKOUT_CSS, _STATE_EVENTS + _WORKOUT_JS, data)
    return html


def home_html(program: str, workouts: int, workouts_word: str, days: list[dict], session: dict | None) -> str | None:
    """days: {i, t, c: упражнений, cw, s: подходов, sw, x: [[название, '3×8–12'], …]}; session: {i: day_id, d, t}."""
    for limit in (6, 4, 0):  # если не влезает — показываем меньше строк в списке
        trimmed = [{**d, "x": d["x"][:limit]} for d in days]
        html = _build(_HOME_CSS, _STATE_EVENTS + _HOME_JS, {"p": program, "n": workouts, "nw": workouts_word, "y": trimmed, "u": session})
        if html is not None:
            return html
    return None


# --- универсальный экран: любой «текст + кнопки» в том же стиле ---

_MENU_CSS = """
.d{color:#c3cad8;line-height:1.45;margin-top:8px}
.d b{color:#fff}.d i{color:#8891a3}
.d code{background:#222a3a;border-radius:6px;padding:1px 5px;color:#c5f82a;font-family:monospace}
.o{display:flex;justify-content:space-between;align-items:center;gap:8px;text-align:left;width:100%;padding:10px 14px;margin-top:5px;background:#19202e;border:1px solid #283041}
.o span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.o i{font-style:normal;color:#8891a3;font-weight:800}
.s,.s i{border-color:#c5f82a;color:#c5f82a}
button.s{background:#c5f82a;color:#0d1016}
.o.s{background:#c5f82a14;color:#c5f82a}
.v{background:none;color:#8891a3}
.z{color:#ff7a6b}
.y{background:#c5f82a22;color:#c5f82a;border-radius:10px;padding:8px;margin-top:8px;font-size:12px;text-align:center}
"""

# V — текущий экран: {k: ключ, x: текст (HTML), r: ряды кнопок [[подпись, действие, стиль]], p: строк списка на странице}
# Стили кнопок: p — главная, n — навигация, s — выбрано, a — добавить, z — опасное, b — действие, '' — строка списка
# Bv — экран-основа (вшитый в HTML или присланный целиком), V = основа + точечные правки {b: ключ основы, x: текст, u: [[ряд, кнопка, новая]]}
_MENU_JS = """
let Bv=D,V=D,pg=0,ts='';
function P(u){if(u.b!=Bv.k)return;V=JSON.parse(JSON.stringify(Bv));if(u.x)V.x=u.x;(u.u||[]).forEach(a=>{V.r[a[0]][a[1]]=a[2]})}
function LV(){L();if(S&&S.r){Bv=V=S}else if(S&&S.b)P(S)}
function A(a){Q('~'+a,j=>{if(j.v){Bv=V=j.v;pg=0}if(j.u)P(j.u);if(j.t){ts=j.t;try{setTimeout(()=>{ts='';R()},2600)}catch(e){}}})}
function U(b,c){return '<button class="'+c+'" onclick="A(\\''+b[1]+'\\')">'+b[0]+'</button>'}
function R0(){const x=V.x.split('\\n'),r=V.r,p=V.p||99,li=b=>b.length==1&&!'pnzb'.includes(b[0][2]||'-');
const n=r.filter(li).length,pc=Math.ceil(n/p)||1;if(pg>=pc)pg=pc-1;let k=0,last=-1;r.forEach((b,j)=>{if(li(b))last=j});
let h='<div class=l>Track your gym</div><div class=h style="font-size:19px;margin-top:4px">'+x[0]+'</div>'+(x.length>1?'<div class=d>'+x.slice(1).join('<br>')+'</div>':'');
r.forEach((b,j)=>{if(li(b)){const q=k++,c=b[0];if(q>=pg*p&&q<pg*p+p)h+='<button class="o'+(c[2]=='s'?' s':'')+'" onclick="A(\\''+c[1]+'\\')"><span>'+c[0]+'</span><i>'+(c[2]=='s'?'✓':c[2]=='a'?'+':'›')+'</i></button>';
if(j==last&&pc>1)h+='<div class=r><button onclick="pg=(pg+'+(pc-1)+')%'+pc+';H();R()">‹</button><button class=v>'+(pg+1)+' / '+pc+'</button><button onclick="pg=(pg+1)%'+pc+';H();R()">›</button></div>'}
else if(b.length==1){const c=b[0];h+=c[2]=='p'?U(c,'g'):'<div class=r>'+U(c,c[2]=='z'?'z':c[2]=='b'?'':'v')+'</div>'}
else h+='<div class=r>'+b.map(c=>U(c,c[2]=='s'||c[2]=='p'?'s':c[2]=='z'?'z':c[2]=='n'?'v':'')).join('')+'</div>'});
h+=(err?'<div class=e>'+E(err)+'</div>':'')+(ts?'<div class=y>'+E(ts)+'</div>':'');
B.innerHTML=h;B.className=busy?'w':''}
function R(){R0();try{const n=V.r.filter(b=>b.length==1&&!'pnzb'.includes(b[0][2]||'-')).length;let g=0;while(B.scrollHeight>FIT&&g++<12){const p=Math.min(V.p||n,n);if(p<=2)break;V.p=p-1;R0()}}catch(e){}}
W.onEvent('chatDataChanged',()=>{if(!busy){LV();R()}});
LV();R();
"""

_NAV = ("⬅️", "🏠", "❌", "✖️", "👤", "🔀")
_PRIMARY = ("▶️", "✅ Готово", "✅ Сохранить", "✅ Заниматься", "✅ Да", "➕ Создать программу", "🏁 Да", "💪 Продолжить")
_ACTION = ("➕ Добавить", "📝", "✍️", "📷", "⏭")
_TAG = re.compile(r"<[^>]+>")


def _button(text: str, action: str) -> list[str]:
    """[подпись, действие, стиль] — стиль угадываем по подписи и действию."""
    label, style = text, ""
    if action.startswith("pk:"):  # выбор упражнений: уже добавлено / добавить
        style = "s" if text.startswith("✅") else "a"
        label = text[2:]
    elif text.startswith("· ") and text.endswith(" ·"):  # выбранные повторения
        label, style = text[2:-2], "s"
    elif action.startswith("p:switch") and text.startswith("✅ "):  # активная программа
        label, style = text[2:], "s"
    elif text.startswith(_PRIMARY):
        style = "p"
    elif text.startswith(_NAV):
        style = "n"
    elif text.startswith("🗑"):
        style = "z"
    elif text.startswith(_ACTION):
        style = "b"
    label = label.strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "’")
    return [label, action, style] if style else [label, action]


def screen_view(text: str, rows: list[list[tuple[str, str]]], image: str | None = None) -> dict:
    """Обычный экран (текст + ряды кнопок (подпись, callback_data)) → описание для универсального виджета."""
    text = text.strip("\n").replace("'", "’")
    view_rows = [[_button(t, a) for t, a in row] for row in rows if row]
    if image:  # картинку в виджет не вставить — даём кнопку, которая пришлёт её отдельным сообщением
        view_rows.insert(0, [["📷 Показать фото", f"ph:{image}", "b"]])

    # Сколько строк списка влезает в 600 px: оцениваем высоту текста и остальных кнопок
    lines = text.split("\n")
    def wrapped(line: str, per_line: int) -> int:
        return max(1, -(-len(_TAG.sub("", line)) // per_line))

    # отступы и надпись сверху + заголовок (крупный, ~20 знаков в строке) + текст (~36 знаков в строке)
    text_height = 50 + 23 * wrapped(lines[0], 20) + sum(21 * wrapped(line, 36) if line else 21 for line in lines[1:])
    is_list = [len(r) == 1 and (r[0][2] if len(r[0]) > 2 else "") not in ("p", "n", "z", "b") for r in view_rows]
    other_height = sum(50 for flag in is_list if not flag)
    per_page = max(2, (580 - text_height - other_height) // 46)
    view = {"k": f"{zlib.crc32(text.encode()) & 0xFFFF:x}", "x": text, "r": view_rows}
    if sum(is_list) > per_page:
        view["p"] = max(2, (580 - text_height - other_height - 50) // 46)  # минус ряд листалки
    return view


def view_patch(base: dict, view: dict) -> dict | None:
    """Точечные правки, превращающие экран base в view. None — экраны слишком разные, нужен новый."""
    rows_a, rows_b = base["r"], view["r"]
    if base.get("p") != view.get("p") or [len(r) for r in rows_a] != [len(r) for r in rows_b]:
        return None
    patch: dict = {"b": base["k"], "u": [
        [i, j, new] for i, (ra, rb) in enumerate(zip(rows_a, rows_b)) for j, (old, new) in enumerate(zip(ra, rb))
        if old != new
    ]}
    if base["x"] != view["x"]:
        patch["x"] = view["x"]
    return patch


def menu_html(view: dict) -> str | None:
    return _build(_MENU_CSS, _MENU_JS, view)
