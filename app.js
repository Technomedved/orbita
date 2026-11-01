"use strict";
(() => {
  const form = document.getElementById("planner-form");
  const repeat = document.getElementById("repeat");
  const weekdays = document.getElementById("weekdays");
  const error = document.getElementById("error");
  const submit = document.getElementById("submit");
  const app = window.Telegram && window.Telegram.WebApp;
  const inTelegram = !!(app && typeof app.sendData === "function" && app.platform && app.platform !== "unknown");
  let sent = false;
  if (inTelegram) { app.ready(); app.expand(); }
  else { document.getElementById("connection").hidden = false; submit.disabled = true; }
  try {
    const zones = Intl.supportedValuesOf("timeZone");
    const list = document.getElementById("timezones");
    for (const zone of zones) { const option = document.createElement("option"); option.value = zone; list.append(option); }
  } catch (_) { /* UTC remains available; a user may enter any valid IANA name. */ }
  repeat.addEventListener("change", () => { weekdays.hidden = repeat.value !== "weekly"; });
  const showError = (message) => { error.textContent = message; error.hidden = false; };
  function payload() {
    const title = document.getElementById("title").value.trim();
    const day = document.getElementById("date").value || null;
    const time = document.getElementById("time").value || null;
    const timezone = document.getElementById("timezone").value.trim();
    const notes = document.getElementById("notes").value.trim();
    const notify = document.getElementById("notify").checked;
    const days = repeat.value === "weekly" ? [...form.querySelectorAll("input[name=days]:checked")].map(input => Number(input.value)) : [];
    if (!title || [...title].length > 200) throw new Error("Укажи название длиной до 200 символов.");
    if (time && !day) throw new Error("Для времени сначала выбери дату.");
    if (repeat.value !== "none" && !day) throw new Error("Для повторения выбери дату начала.");
    if (repeat.value === "weekly" && !days.length) throw new Error("Выбери хотя бы один день недели.");
    if (notify && (!day || !time)) throw new Error("Для уведомления выбери дату и время.");
    if (!timezone) throw new Error("Проверь часовой пояс дела.");
    try { new Intl.DateTimeFormat("ru", {timeZone: timezone}).format(); }
    catch (_) { throw new Error("Укажи действительный IANA-пояс, например Europe/Berlin."); }
    const value = {version: 1, action: "planner.create", values: {title, notes, date: day, time, timezone, repeat: repeat.value, days, notify}};
    const encoded = JSON.stringify(value);
    if (new TextEncoder().encode(encoded).length > 4096) throw new Error("Форма длиннее лимита Telegram. Сократи заметку; её можно дополнить в приложении.");
    return encoded;
  }
  form.addEventListener("submit", event => {
    event.preventDefault(); if (sent) return;
    error.hidden = true;
    try {
      const encoded = payload();
      if (!inTelegram) throw new Error("Открой форму из кнопки в личном чате с ботом.");
      app.sendData(encoded); sent = true; submit.disabled = true;
      submit.textContent = "Черновик отправлен";
    } catch (failure) { showError(failure.message || "Не удалось передать черновик. Поля сохранены в открытой форме."); }
  });
})();
