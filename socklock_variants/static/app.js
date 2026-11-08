"use strict";

const ELEMENT = { HOOK: "Хук", FIRSTLINE: "Перша фраза", ONSCREEN: "Текст на екрані" };
const ANGLE = {
  pain: "біль", curiosity: "цікавість", humor: "гумор", demo: "демонстрація",
  social_proof: "соцдоказ", contrarian: "проти течії", number: "цифра", question: "питання",
};
const ISSUE = {
  timing: "довше за слот", scope: "змінено зайве",
  duplicate_opening: "той самий початок", near_duplicate: "майже дубль",
};
const SAMPLE = `W12 · Washer thief
HOOK 0-2.5s | VO: "Lost another sock?" | ON-SCREEN: "Your washer eats socks"
PROBLEM 2.5-7s | VO: "Every wash, one goes missing and you never find it"
PRODUCT 7-15s | VO: "SockLock socks have tiny magnets that click pairs together" | ON-SCREEN: "Click. Wash. Still a pair."
CTA 15-20s | VO: "Get your first 5 pairs for $29" | ON-SCREEN: "5 pairs · $29"`;

const $ = (id) => document.getElementById(id);
const state = { count: 20, variants: [], chatFor: null };

// ---------- input ----------
const script = $("script");
$("sample").onclick = (e) => { e.preventDefault(); script.value = SAMPLE; script.focus(); };
$("pick").onclick = (e) => { e.preventDefault(); $("file").click(); };
$("file").onchange = (e) => readFile(e.target.files[0]);

const drop = $("drop");
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => readFile(e.dataTransfer.files[0]));

function readFile(file) {
  if (!file) return;
  if (file.size > 200_000) return toast("Файл завеликий — потрібен лише текст скрипту", true);
  const r = new FileReader();
  r.onload = () => { script.value = String(r.result); toast(`Завантажено ${file.name}`); };
  r.readAsText(file);
}

function setCount(n) { state.count = Math.max(1, Math.min(50, n)); $("count").value = state.count; $("count").textContent = state.count; }
$("minus").onclick = () => setCount(state.count - 1);
$("plus").onclick = () => setCount(state.count + 1);

// ---------- generate ----------
$("generate").onclick = async () => {
  if (!script.value.trim()) { script.focus(); return toast("Встав скрипт переможця", true); }
  const btn = $("generate");
  btn.disabled = true; btn.textContent = "Генерую…";
  closeChat();
  $("results").hidden = false;
  $("rtitle").textContent = `Генерую ${state.count} модифікацій`;
  $("notice").hidden = true;
  $("rows").innerHTML = Array.from({ length: Math.min(state.count, 6) }, () => '<li class="skeleton"></li>').join("");
  try {
    const data = await api("/api/generate", { script: script.value, count: state.count });
    state.variants = data.variants.map((v) => ({ ...v, parent: null }));
    renderAll();
    const flagged = state.variants.filter((v) => v.issues.length).length;
    const notes = [];
    if (!data.parsed) notes.push("Не вдалося розбити скрипт на сегменти з таймінгом — перевірка довжини йде за замовчуванням (хук 2,5 с).");
    if (flagged) notes.push(`${flagged} з ${state.variants.length} мають позначки — перевір їх або попроси поправити в чаті.`);
    $("notice").textContent = notes.join(" ");
    $("notice").hidden = !notes.length;
  } catch (err) {
    $("results").hidden = true;
    toast(err.message, true);
  } finally {
    btn.disabled = false; btn.textContent = "Згенерувати";
  }
};

async function api(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : "Запит не пройшов — перевір кількість (1–50) і скрипт");
  }
  return data;
}

// ---------- render ----------
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function tags(v) {
  const box = el("div", "tags");
  box.append(el("span", "tag", ELEMENT[v.element] || v.element));
  const a = el("span", "tag", ANGLE[v.angle] || v.angle.replace(/_/g, " "));
  a.style.background = `var(--a-${v.angle}, var(--hair))`;
  box.append(a);
  const len = v.seconds != null ? `${v.words} слів, ${String(v.seconds).replace(".", ",")} с` : `${v.words} слів`;
  box.append(el("span", "tag", len));
  if (v.adjacent) box.append(el("span", "tag", "змінена сусідня фраза"));
  v.issues.forEach((i) => {
    const label = i.startsWith("risky:") ? `ризикова обіцянка: ${i.slice(6)}` : ISSUE[i] || i;
    box.append(el("span", "tag issue", label));
  });
  return box;
}

function fullView(v) {
  const box = el("div", "full");
  v.full_script.forEach((s) => {
    const line = el("div");
    const timing = s.start != null ? ` ${s.start}–${s.end}s` : "";
    line.append(el("span", "seg", `${s.name}${timing}  `));
    [["vo", "VO"], ["onscreen", "ON-SCREEN"]].forEach(([f, label]) => {
      if (!s[f]) return;
      line.append(el("span", "field", ` ${label}: `));
      const h = s[`highlight_${f}`];
      line.append(h ? el("mark", h, s[f]) : document.createTextNode(s[f]));
    });
    box.append(line);
  });
  const legend = el("div", "legend");
  legend.append(el("mark", "new", "нове"));
  if (v.adjacent) { legend.append(document.createTextNode("  ")); legend.append(el("mark", "adjacent", "підлаштована сусідня фраза")); }
  box.append(legend);
  if (v.why) box.append(el("div", "legend", `Що перевіряє цей варіант: ${v.why}`));
  return box;
}

function row(v) {
  const li = el("li", "row" + (v.parent ? " child" : ""));
  li.dataset.name = v.name;
  const main = el("div");
  main.append(el("div", "name", v.name), el("div", "text", v.text), tags(v));
  const acts = el("div", "row-actions");
  const exp = el("button", "icon", "⌄");
  exp.title = "Повний скрипт"; exp.setAttribute("aria-label", "Показати повний скрипт"); exp.setAttribute("aria-expanded", "false");
  exp.onclick = () => {
    const open = li.classList.toggle("open");
    exp.setAttribute("aria-expanded", String(open));
    exp.textContent = open ? "⌃" : "⌄";
    const existing = li.querySelector(".full");
    if (open && !existing) li.append(fullView(v));
    if (!open && existing) existing.remove();
  };
  const chat = el("button", "icon", "💬");
  chat.title = "Поправити в чаті"; chat.setAttribute("aria-label", "Відкрити чат з модифікацією");
  chat.onclick = () => openChat(v.name);
  const copy = el("button", "icon", "⧉");
  copy.title = "Копіювати"; copy.setAttribute("aria-label", "Копіювати текст");
  copy.onclick = () => copyText(asText(v), "Скопійовано");
  acts.append(exp, chat, copy);
  li.append(main, acts);
  return li;
}

function renderAll() {
  const list = $("rows");
  list.innerHTML = "";
  state.variants.forEach((v) => list.append(row(v)));
  $("rtitle").textContent = `${state.variants.length} модифікацій`;
}

function asText(v) {
  let t = `${v.name}\t${v.text}`;
  if (v.adjacent) t += `\t(${v.adjacent.segment}: ${v.adjacent.text})`;
  return t;
}

$("copyAll").onclick = () => copyText(state.variants.map(asText).join("\n"), `Скопійовано ${state.variants.length}`);

async function copyText(text, msg) {
  try { await navigator.clipboard.writeText(text); toast(msg); }
  catch { toast("Браузер не дав доступ до буфера — виділи текст вручну", true); }
}

// ---------- chat ----------
function byName(name) { return state.variants.find((v) => v.name === name); }

function openChat(name) {
  const v = byName(name);
  state.chatFor = name;
  $("chatName").textContent = name;
  const msgs = $("msgs");
  msgs.innerHTML = "";
  msgs.append(aiBubble(v, "Поточна версія"));
  (v.history || []).forEach((m) => msgs.append(m.role === "designer" ? el("div", "me", m.text) : el("div", "ai", m.text)));
  $("sheet").hidden = false;
  document.body.classList.add("chat-open");
  $("msg").focus();
}

function closeChat() {
  $("sheet").hidden = true;
  document.body.classList.remove("chat-open");
  state.chatFor = null;
}
$("closeChat").onclick = closeChat;
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("sheet").hidden) closeChat(); });

function aiBubble(v, lead) {
  const b = el("div", "ai");
  if (lead) b.append(el("span", "meta", lead));
  b.append(el("div", null, `“${v.text}”`));
  const ok = v.issues.length ? `позначки: ${v.issues.join(", ")}` : "перевірки пройдено";
  b.append(el("span", "meta", `${v.name}, ${v.words} слів, ${ok}`));
  return b;
}

$("compose").onsubmit = async (e) => {
  e.preventDefault();
  const input = $("msg");
  const text = input.value.trim();
  if (!text || !state.chatFor) return;
  const msgs = $("msgs");
  msgs.append(el("div", "me", text));
  const typing = el("div", "ai typing", "Переписую…");
  msgs.append(typing);
  msgs.scrollTop = msgs.scrollHeight;
  input.value = ""; input.disabled = true;
  const base = byName(state.chatFor);
  try {
    const data = await api(`/api/variants/${encodeURIComponent(state.chatFor)}/chat`, { message: text });
    typing.remove();
    const nv = { ...data.variant, parent: base.parent || base.name, history: data.history };
    const r = el("div", "ai", data.reply);
    msgs.append(r, aiBubble(nv));
    insertAfterFamily(nv);
    state.chatFor = nv.name;
    $("chatName").textContent = nv.name;
  } catch (err) {
    typing.remove();
    msgs.append(el("div", "ai", `Не вийшло: ${err.message}`));
  } finally {
    input.disabled = false; input.focus();
    msgs.scrollTop = msgs.scrollHeight;
  }
};

function insertAfterFamily(nv) {
  const root = nv.parent;
  let idx = state.variants.findIndex((v) => v.name === root);
  while (idx + 1 < state.variants.length && state.variants[idx + 1].parent === root) idx++;
  state.variants.splice(idx + 1, 0, nv);
  renderAll();
  const li = document.querySelector(`.row[data-name="${CSS.escape(nv.name)}"]`);
  if (li) { li.classList.add("fresh"); li.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
}

// ---------- toast ----------
let toastTimer;
function toast(msg, error = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (error ? " error" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), error ? 6000 : 2200);
}
