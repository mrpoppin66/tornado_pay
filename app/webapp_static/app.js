// TornadoPay Mini App — простой SPA без сборки, работает поверх REST API /api/*.
// Тот же бэкенд и та же бизнес-логика, что и у чат-бота: пополнение, вывод,
// заявки, эскроу, чат, споры, рефералка — просто другой интерфейс.
(function () {
  "use strict";

  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  // ---------- Фирменная тёмная палитра TornadoPay ----------
  // Цвета зашиты в style.css (:root) намеренно — бренд-стиль (чёрный + неоново-
  // мятный зелёный) важнее автоподстройки под системную тему пользователя,
  // поэтому здесь мы не тянем цвета из tg.themeParams, а только просим сам
  // Telegram (шапку/системный фон вокруг WebView) покрасить в тон приложения.
  function applyBrandChrome() {
    if (!tg) return;
    try { tg.setHeaderColor && tg.setHeaderColor("#060b09"); } catch (e) {}
    try { tg.setBackgroundColor && tg.setBackgroundColor("#050a08"); } catch (e) {}
    try { tg.setBottomBarColor && tg.setBottomBarColor("#060b09"); } catch (e) {}
  }
  applyBrandChrome();

  // ---------- API-клиент ----------
  function apiCall(path, opts) {
    opts = opts || {};
    var headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    headers["X-Telegram-Init-Data"] = (tg && tg.initData) || "";
    return fetch("/api" + path, Object.assign({}, opts, { headers: headers }))
      .then(function (res) {
        return res.text().then(function (text) {
          var data = null;
          try { data = text ? JSON.parse(text) : null; } catch (e) {}
          if (!res.ok) {
            var msg = (data && data.error) || ("Ошибка " + res.status);
            throw new Error(msg);
          }
          return data;
        });
      });
  }
  var apiGet = function (path) { return apiCall(path); };
  var apiPost = function (path, body) { return apiCall(path, { method: "POST", body: JSON.stringify(body || {}) }); };

  // ---------- Утилиты ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  // ---------- Premium SVG icon set (Mini-App only) ----------
  var ICONS = {
    services: '<path d="M4 9h16l-1.2 10.5H5.2z"/><path d="M8 9a4 4 0 0 1 8 0"/><path d="M8 13h.01M12 13h.01M16 13h.01"/>',
    orders: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    executor: '<circle cx="9" cy="8" r="3"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0M16 5v6M13 8h6"/>',
    referrals: '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="10" r="2.3"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0M15 19a4.5 4.5 0 0 1 5 0"/>',
    bell: '<path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
    telegram: '<path d="m21 4-3.1 15.2c-.2 1.1-.8 1.4-1.7.9l-4.8-3.6-2.3 2.2c-.3.3-.5.5-1 .5l.3-4.9L17.8 7c.4-.4-.1-.6-.6-.2L6.5 13.6l-4.7-1.5c-1-.3-1-1 .2-1.5L20.4 3c.8-.3 1.1.2.6 1z"/>',
    youtube: '<rect x="3" y="6" width="18" height="12" rx="4"/><path d="m10 9 5 3-5 3z"/>',
    tiktok: '<path d="M14 4v10.3a4.7 4.7 0 1 1-3.5-4.5"/><path d="M14 4c1.1 2.1 2.7 3.3 5 3.5"/>',
    vk: '<path d="M5 7c.2 5.7 3.2 9 8.5 9h.3v-3.3c1.9.2 3.4 1.5 4 3.3H21c-.7-2.7-2.3-4.1-3.6-4.7 1.3-.7 2.6-2.1 3.1-5.3h-3c-.5 1.9-1.8 3.8-3.7 4.1V7h-2.8v7.2C9.1 13.7 8 11.6 7.8 7z"/>',
    instagram: '<rect x="3.5" y="3.5" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.4" cy="6.7" r=".8" fill="currentColor" stroke="none"/>',
    wallet: '<rect x="3" y="6" width="18" height="13" rx="3"/><path d="M16 10h5v5h-5a2.5 2.5 0 0 1 0-5zM7 10h.01"/>',
    star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>',
    toggle: '<rect x="3" y="7" width="18" height="10" rx="5"/><circle cx="16" cy="12" r="3"/>',
    history: '<path d="M4 5h16v14H4z"/><path d="M8 9h8M8 13h8M8 17h5"/>',
    copy: '<rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    lock: '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    arrow: '<path d="m9 6 6 6-6 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    spark: '<path d="m12 3 1.4 5.6L19 10l-5.6 1.4L12 17l-1.4-5.6L5 10l5.6-1.4z"/>',
    shield: '<path d="M12 3 20 6v5c0 5-3.4 8.2-8 10-4.6-1.8-8-5-8-10V6z"/><path d="m8.5 12 2.2 2.2 4.8-5"/>',
    generic: '<circle cx="12" cy="12" r="8"/><path d="M12 8v8M8 12h8"/>'
  };
  function svgIcon(name, cls) {
    return '<svg class="' + (cls || '') + '" viewBox="0 0 24 24" aria-hidden="true">' + (ICONS[name] || ICONS.generic) + '</svg>';
  }
  function serviceIcon(name) {
    var n = String(name || '').toLowerCase();
    if (n.indexOf('telegram') !== -1) return 'telegram';
    if (n.indexOf('youtube') !== -1) return 'youtube';
    if (n.indexOf('tiktok') !== -1) return 'tiktok';
    if (n.indexOf('вконт') !== -1 || n.indexOf('vk') !== -1) return 'vk';
    if (n.indexOf('instagram') !== -1) return 'instagram';
    if (n.indexOf('рефера') !== -1) return 'referrals';
    if (n.indexOf('баланс') !== -1 || n.indexOf('вывод') !== -1) return 'wallet';
    return 'spark';
  }

  function fmt(n, digits) {
    digits = digits == null ? 2 : digits;
    n = Number(n || 0);
    return n.toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }
  function haptic(kind) {
    if (!tg || !tg.HapticFeedback) return;
    try {
      if (kind === "success" || kind === "error" || kind === "warning") tg.HapticFeedback.notificationOccurred(kind);
      else tg.HapticFeedback.impactOccurred(kind || "light");
    } catch (e) {}
  }
  function openExternal(url) {
    if (tg && tg.openLink) tg.openLink(url, { try_instant_view: false });
    else window.open(url, "_blank");
  }
  function toast(msg, isError) {
    var el = document.getElementById("toast");
    if (el) el.remove();
    el = document.createElement("div");
    el.id = "toast";
    el.textContent = msg;
    el.style.cssText =
      "position:fixed;left:50%;bottom:84px;transform:translateX(-50%);z-index:999;" +
      "background:" + (isError ? "#df3f40" : "#2fa84f") + ";color:#fff;padding:10px 16px;" +
      "border-radius:12px;font-size:14px;max-width:86%;text-align:center;box-shadow:0 4px 14px rgba(0,0,0,.2);";
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 3000);
  }

  var ORDER_STATUS_LABELS = {
    new: "🆕 новая", in_progress: "🔧 в работе", awaiting_confirmation: "⏳ ожидает подтверждения",
    disputed: "⚠️ спор", done: "✅ выполнена", cancelled: "❌ отменена",
  };
  var APP_STATUS_LABELS = {
    pending: "⏳ на рассмотрении", question: "💬 ожидается ваш ответ", approved: "✅ одобрена",
    rejected: "❌ отклонена", blocked: "🚫 заблокирована",
  };
  var PROVIDER_LABELS = { cryptobot: "CryptoBot", xrocket: "xRocket" };

  // ---------- Состояние ----------
  var ME = null;
  var chatPollTimer = null;

  function stopChatPoll() {
    if (chatPollTimer) { clearInterval(chatPollTimer); chatPollTimer = null; }
  }

  function loadMe() {
    return apiGet("/me").then(function (data) { ME = data; return data; });
  }

  function refreshNotifBadge() {
    apiGet("/notifications").then(function (data) {
      var badge = document.getElementById("notif-badge");
      if (!badge) return;
      if (data.unread > 0) { badge.hidden = false; badge.textContent = data.unread > 9 ? "9+" : String(data.unread); }
      else badge.hidden = true;
    }).catch(function () {});
  }

  // ---------- Роутер ----------
  var routes = [];
  function route(pattern, handler) { routes.push({ re: pattern, handler: handler }); }
  function currentHash() { return location.hash.replace(/^#/, "") || "/home"; }

  function setActiveNav(hash) {
    var base = "/" + hash.split("/")[1];
    document.querySelectorAll("#bottom-nav a").forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("data-route") === base);
    });
  }

  function render() {
    stopChatPoll();
    var root = document.getElementById("app");
    var hash = currentHash();

    if (!ME) {
      root.innerHTML = '<div class="spinner"></div>';
      return;
    }
    if (!ME.agreement_accepted && hash !== "/agreement") {
      location.hash = "#/agreement";
      return;
    }

    for (var i = 0; i < routes.length; i++) {
      var m = hash.match(routes[i].re);
      if (m) {
        setActiveNav(hash);
        try {
          var result = routes[i].handler.apply(null, [root].concat(m.slice(1)));
          if (result && result.catch) result.catch(function (e) { renderError(root, e); });
        } catch (e) { renderError(root, e); }
        return;
      }
    }
    root.innerHTML = '<div class="empty-state"><span class="emoji">🤷</span>Раздел не найден</div>';
  }

  function renderError(root, e) {
    console.error(e);
    root.innerHTML = '<div class="error-box">' + esc(e.message || "Что-то пошло не так") + "</div>" +
      '<button class="secondary" onclick="location.reload()">Обновить</button>';
  }

  window.addEventListener("hashchange", render);

  // ---------- Экран: соглашение ----------
  route(/^\/agreement$/, function (root) {
    root.innerHTML =
      '<h1>Пользовательское соглашение</h1>' +
      '<div class="card"><p>Используя TornadoPay, вы соглашаетесь с условиями обмена и вывода средств, ' +
      'правилами работы эскроу-сервиса и обработки споров администрацией платформы. ' +
      'Средства по заявкам резервируются на балансе до подтверждения выполнения или решения администратора.</p></div>' +
      '<button id="accept-btn">Принимаю условия</button>';
    document.getElementById("accept-btn").onclick = function () {
      this.disabled = true;
      apiPost("/agreement/accept").then(function () {
        return loadMe();
      }).then(function () {
        location.hash = "#/home";
        render();
      }).catch(function (e) { toast(e.message, true); });
    };
  });

  // ---------- Экран: главная ----------
  route(/^\/home$/, function (root) {
    var roleLine = ME.role === "executor"
      ? (ME.executor_blocked ? "🚫 Исполнитель (заблокирован)" : "🧑‍💼 Исполнитель")
      : "👤 Клиент";
    root.innerHTML =
      '<h1>Привет' + (ME.username ? ", @" + esc(ME.username) : "") + '!</h1>' +
      '<div class="balance-hero"><div class="label">' + roleLine + ' · Баланс</div>' +
      '<div class="value">' + fmt(ME.balance, 4) + ' USDT</div></div>' +
      '<div class="tile-grid">' +
      tile("services", "Услуги", "Создать заявку", "#/services") +
      tile("orders", "Мои заявки", "Статусы и чат", "#/orders") +
      tile("executor", ME.role === "executor" ? "Кабинет исполнителя" : "Стать исполнителем", "", "#/executor") +
      tile("referrals", "Рефералы", "Приглашайте друзей", "#/referrals") +
      "</div>";
  });

  function tile(icon, title, sub, href) {
    return '<div class="tile" onclick="location.hash=\'' + href + '\'">' +
      '<span class="tile-icon">' + svgIcon(icon) + "</span>" +
      '<div class="tile-title">' + esc(title) + "</div>" +
      (sub ? '<div class="tile-sub">' + esc(sub) + "</div>" : "") +
      "</div>";
  }

  // ---------- Экран: уведомления ----------
  route(/^\/notifications$/, function (root) {
    root.innerHTML = '<h1>Уведомления</h1><div class="spinner"></div>';
    return apiGet("/notifications").then(function (data) {
      var badge = document.getElementById("notif-badge");
      if (badge) badge.hidden = true;
      if (!data.items.length) {
        root.innerHTML = '<h1>Уведомления</h1><div class="empty-state"><span class="action-icon" style="margin:0 auto 10px">' + svgIcon('bell') + '</span>Пока пусто</div>';
        return;
      }
      var html = '<h1>Уведомления</h1>';
      if (data.unread > 0) html += '<button class="secondary small icon-button-inline" id="mark-read-btn"><span class="btn-icon">' + svgIcon('check') + '</span> Отметить всё прочитанным</button>';
      html += data.items.map(function (n) {
        return '<div class="card">' +
          '<div style="font-weight:600">' + esc(n.title) + "</div>" +
          (n.body ? '<div class="muted" style="margin-top:4px">' + esc(n.body) + "</div>" : "") +
          '<div class="muted" style="margin-top:6px">' + fmtDate(n.created_at) + "</div>" +
          "</div>";
      }).join("");
      root.innerHTML = html;
      var btn = document.getElementById("mark-read-btn");
      if (btn) btn.onclick = function () {
        apiPost("/notifications/read").then(function () { refreshNotifBadge(); render(); });
      };
    });
  });

  // ---------- Экран: услуги ----------
  route(/^\/services$/, function (root) {
    root.innerHTML = '<h1>Услуги</h1><div class="spinner"></div>';
    return apiGet("/services").then(function (services) {
      if (!services.length) {
        root.innerHTML = '<h1>Услуги</h1><div class="empty-state"><span class="emoji">🛍</span>Пока нет доступных услуг</div>';
        return;
      }
      var rate = ME.exchange_rate || 1;
      root.innerHTML = '<h1>Услуги</h1>' + services.map(function (s) {
        var minRub = Number(s.min_amount) * rate;
        return '<div class="card tappable service-card" data-id="' + s.id + '">' +
          '<div class="service-icon">' + svgIcon(serviceIcon(s.name)) + '</div>' +
          '<div class="service-main">' +
          '<div class="service-title">' + esc(s.name) + "</div>" +
          (s.description ? '<div class="muted" style="margin-top:4px">' + esc(s.description) + "</div>" : "") +
          '<div class="muted" style="margin-top:5px">От ' + fmt(minRub, 0) + " ₽</div>" +
          '</div><div class="service-arrow">' + svgIcon('arrow') + '</div>' +
          "</div>";
      }).join("");
      root.querySelectorAll(".card[data-id]").forEach(function (el) {
        el.onclick = function () { location.hash = "#/order-new/" + el.getAttribute("data-id"); };
      });
    });
  });

  // ---------- Экран: создание заявки ----------
  route(/^\/order-new\/(\d+)$/, function (root, serviceId) {
    root.innerHTML = '<div class="spinner"></div>';
    return apiGet("/services").then(function (services) {
      var s = services.filter(function (x) { return String(x.id) === serviceId; })[0];
      if (!s) { root.innerHTML = '<div class="error-box">Услуга не найдена</div>'; return; }
      var rate = ME.exchange_rate || 1;
      root.innerHTML =
        '<h1>' + esc(s.name) + "</h1>" +
        (s.description ? '<p class="muted">' + esc(s.description) + "</p>" : "") +
        '<label>Сумма перевода, ₽</label>' +
        '<input type="number" inputmode="decimal" id="amount-input" placeholder="Например, 1000">' +
        '<label>Комментарий (необязательно)</label>' +
        '<textarea id="comment-input" placeholder="Уточнения для исполнителя"></textarea>' +
        '<div id="estimate" class="muted"></div>' +
        '<button id="create-order-btn">Создать заявку</button>';
      var amountInput = document.getElementById("amount-input");
      var estimateEl = document.getElementById("estimate");
      amountInput.oninput = function () {
        var v = parseFloat(amountInput.value);
        if (!v || v <= 0) { estimateEl.textContent = ""; return; }
        estimateEl.textContent = "≈ " + fmt(v / rate, 4) + " USDT по курсу " + fmt(rate, 2);
      };
      document.getElementById("create-order-btn").onclick = function () {
        var amount = parseFloat(amountInput.value);
        if (!amount || amount <= 0) { toast("Введите сумму", true); return; }
        this.disabled = true;
        var btn = this;
        apiPost("/orders", {
          service_id: s.id, amount_rub: amount,
          comment: document.getElementById("comment-input").value,
        }).then(function (res) {
          haptic("success");
          toast("Заявка #" + res.order_id + " создана");
          location.hash = "#/order/" + res.order_id;
        }).catch(function (e) {
          btn.disabled = false;
          toast(e.message, true);
        });
      };
    });
  });

  // ---------- Экран: список заявок ----------
  route(/^\/orders$/, function (root) {
    root.innerHTML =
      '<h1>Мои заявки</h1>' +
      '<div class="row" style="margin-bottom:10px">' +
      '<button class="secondary small" data-tab="client">Как клиент</button>' +
      '<button class="secondary small" data-tab="executor">Как исполнитель</button>' +
      "</div>" +
      '<div id="orders-list"><div class="spinner"></div></div>';
    var tab = sessionStorage.getItem("orders_tab") || "client";
    function load(t) {
      sessionStorage.setItem("orders_tab", t);
      root.querySelectorAll("[data-tab]").forEach(function (b) {
        b.style.opacity = b.getAttribute("data-tab") === t ? "1" : "0.55";
      });
      apiGet("/orders?role=" + t).then(function (orders) {
        var list = document.getElementById("orders-list");
        if (!orders.length) {
          list.innerHTML = '<div class="empty-state"><span class="emoji">📭</span>Заявок пока нет</div>';
          return;
        }
        list.innerHTML = orders.map(function (o) {
          var st = o.status;
          return '<div class="card tappable" data-id="' + o.id + '">' +
            '<div style="display:flex;justify-content:space-between;align-items:center">' +
            '<div style="font-weight:600">Заявка #' + o.id + "</div>" +
            '<span class="badge-status status-' + st + '">' + (ORDER_STATUS_LABELS[st] || st) + "</span>" +
            "</div>" +
            '<div class="muted" style="margin-top:4px">' + esc(o.name) + " · " + fmt(o.amount_rub, 0) + " ₽</div>" +
            '<div class="muted" style="margin-top:2px">' + fmtDate(o.created_at) + "</div>" +
            "</div>";
        }).join("");
        list.querySelectorAll(".card[data-id]").forEach(function (el) {
          el.onclick = function () { location.hash = "#/order/" + el.getAttribute("data-id"); };
        });
      });
    }
    root.querySelectorAll("[data-tab]").forEach(function (b) {
      b.onclick = function () { load(b.getAttribute("data-tab")); };
    });
    load(tab);
  });

  // ---------- Экран: детали заявки + чат ----------
  route(/^\/order\/(\d+)$/, function (root, orderId) {
    root.innerHTML = '<div class="spinner"></div>';
    return apiGet("/orders/" + orderId).then(function (o) {
      renderOrderDetail(root, o);
      if (o.chat_open) startChatPoll(orderId, o.chat_messages);
    });
  });

  function renderOrderDetail(root, o) {
    var st = o.status;
    var isClient = o.is_client, isExecutor = o.is_executor;
    var html = '<h1>Заявка #' + o.id + "</h1>" +
      '<div class="card">' +
      '<div class="row" style="margin-bottom:6px"><span class="badge-status status-' + st + '">' + (ORDER_STATUS_LABELS[st] || st) + "</span></div>" +
      '<div><b>Услуга:</b> ' + esc(o.name) + "</div>" +
      '<div><b>Сумма:</b> ' + fmt(o.amount_rub, 0) + " ₽ (" + fmt(o.user_amount_usdt, 4) + " USDT)</div>" +
      (o.order_comment ? '<div><b>Комментарий:</b> ' + esc(o.order_comment) + "</div>" : "") +
      '<div class="muted" style="margin-top:6px">Создана: ' + fmtDate(o.created_at) + "</div>" +
      "</div>";

    // Действия в зависимости от роли и статуса.
    var actions = "";
    if (isExecutor && st === "in_progress") {
      actions += '<button id="complete-btn">✅ Отметить выполненной</button>';
    }
    if (isClient && st === "awaiting_confirmation") {
      actions += '<button id="confirm-btn">✅ Подтвердить выполнение</button>' +
        '<button id="dispute-btn" class="danger">⚠️ Открыть спор</button>';
    }
    if (isClient && st === "done" && o.rated === false) {
      actions += '<div class="card"><div style="margin-bottom:6px">Оцените исполнителя:</div>' +
        '<div class="stars" id="rate-stars">' +
        [1, 2, 3, 4, 5].map(function (n) { return '<span class="star" data-n="' + n + '">★</span>'; }).join("") +
        "</div></div>";
    }
    html += actions;

    if (o.chat_open) {
      html += '<h2>💬 Чат</h2><div class="chat-thread" id="chat-thread">' + renderChatMessages(o.chat_messages, o) + "</div>" +
        '<div class="chat-input-row"><textarea id="chat-input" placeholder="Сообщение..." rows="1"></textarea>' +
        '<button id="chat-send-btn" class="small">➤</button></div>';
    }

    root.innerHTML = html;
    root.dataset.orderId = o.id;

    var completeBtn = document.getElementById("complete-btn");
    if (completeBtn) completeBtn.onclick = function () {
      this.disabled = true;
      apiPost("/orders/" + o.id + "/complete").then(function () {
        haptic("success"); toast("Заявка отмечена выполненной"); location.hash = "#/order/" + o.id; render();
      }).catch(function (e) { completeBtn.disabled = false; toast(e.message, true); });
    };
    var confirmBtn = document.getElementById("confirm-btn");
    if (confirmBtn) confirmBtn.onclick = function () {
      this.disabled = true;
      apiPost("/orders/" + o.id + "/confirm").then(function () {
        haptic("success"); toast("Выполнение подтверждено"); loadMe().then(function () { render(); });
      }).catch(function (e) { confirmBtn.disabled = false; toast(e.message, true); });
    };
    var disputeBtn = document.getElementById("dispute-btn");
    if (disputeBtn) disputeBtn.onclick = function () {
      if (!confirm("Открыть спор по заявке? Решение примет администратор.")) return;
      this.disabled = true;
      apiPost("/orders/" + o.id + "/dispute").then(function () {
        haptic("warning"); toast("Спор открыт"); render();
      }).catch(function (e) { disputeBtn.disabled = false; toast(e.message, true); });
    };
    var starsEl = document.getElementById("rate-stars");
    if (starsEl) {
      var stars = starsEl.querySelectorAll(".star");
      stars.forEach(function (star) {
        star.onclick = function () {
          var n = parseInt(star.getAttribute("data-n"), 10);
          stars.forEach(function (s2) { s2.classList.toggle("active", parseInt(s2.getAttribute("data-n"), 10) <= n); });
          apiPost("/orders/" + o.id + "/rate", { stars: n }).then(function () {
            haptic("success"); toast("Спасибо за оценку!"); render();
          }).catch(function (e) { toast(e.message, true); });
        };
      });
    }
    var chatInput = document.getElementById("chat-input");
    var chatSendBtn = document.getElementById("chat-send-btn");
    if (chatSendBtn) chatSendBtn.onclick = function () {
      var text = chatInput.value.trim();
      if (!text) return;
      chatSendBtn.disabled = true;
      apiPost("/orders/" + o.id + "/chat", { text: text }).then(function () {
        chatInput.value = "";
        chatSendBtn.disabled = false;
        pollChat(o.id, true);
      }).catch(function (e) { chatSendBtn.disabled = false; toast(e.message, true); });
    };
  }

  function renderChatMessages(messages, o) {
    if (!messages.length) return '<div class="muted" style="text-align:center;padding:12px 0">Сообщений пока нет</div>';
    return messages.map(function (m) {
      var mine = (o.is_client && m.sender_id === o.user_id) || (o.is_executor && m.sender_id === o.executor_id);
      var text = m.content_type === "text" ? esc(m.text_content) : "[вложение]";
      return '<div class="chat-bubble ' + (mine ? "me" : "peer") + '">' + text + "</div>";
    }).join("");
  }

  var lastChatId = 0;
  function startChatPoll(orderId, initialMessages) {
    lastChatId = (initialMessages && initialMessages.length) ? initialMessages[initialMessages.length - 1].id : 0;
    chatPollTimer = setInterval(function () { pollChat(orderId, false); }, 4000);
  }
  function pollChat(orderId, force) {
    var thread = document.getElementById("chat-thread");
    if (!thread) return;
    apiGet("/orders/" + orderId + "/chat?after_id=" + lastChatId).then(function (msgs) {
      if (!msgs.length && !force) return;
      apiGet("/orders/" + orderId).then(function (o) {
        var t2 = document.getElementById("chat-thread");
        if (!t2) return;
        t2.innerHTML = renderChatMessages(o.chat_messages, o);
        t2.scrollTop = t2.scrollHeight;
        if (o.chat_messages.length) lastChatId = o.chat_messages[o.chat_messages.length - 1].id;
      });
    }).catch(function () {});
  }

  // ---------- Экран: баланс ----------
  route(/^\/balance$/, function (root) {
    root.innerHTML = '<h1>Баланс</h1><div class="spinner"></div>';
    return apiGet("/transactions").then(function (txs) {
      var canWithdraw = ME.role === "executor" && !ME.executor_blocked;
      var html =
        '<div class="balance-hero"><div class="label">Текущий баланс</div><div class="value">' + fmt(ME.balance, 4) + " USDT</div></div>" +
        '<div class="row">' +
        '<button onclick="location.hash=\'#/deposit\'">💳 Пополнить</button>' +
        (canWithdraw ? '<button class="secondary" onclick="location.hash=\'#/withdraw\'">💸 Вывести</button>' : "") +
        "</div>" +
        "<h2>История операций</h2>";
      if (!txs.length) {
        html += '<div class="empty-state"><span class="emoji">📄</span>Операций пока нет</div>';
      } else {
        html += txs.map(function (t) {
          var amt = Number(t.amount);
          var sign = amt > 0 ? "+" : "";
          return '<div class="list-item"><div><div>' + esc(t.description || t.type) + '</div>' +
            '<div class="muted">' + fmtDate(t.created_at) + "</div></div>" +
            '<div style="font-weight:600;color:' + (amt >= 0 ? "var(--success)" : "var(--destructive)") + '">' +
            sign + fmt(amt, 4) + "</div></div>";
        }).join("");
      }
      root.innerHTML = html;
    });
  });

  // ---------- Экран: пополнение ----------
  route(/^\/deposit$/, function (root) {
    var ps = ME.payment_settings;
    root.innerHTML =
      '<h1>Пополнение</h1>' +
      '<div class="provider-choice">' + providerCard("cryptobot", ps.cryptobot, "deposit") + providerCard("xrocket", ps.xrocket, "deposit") + "</div>" +
      '<label>Сумма, USDT</label><input type="number" inputmode="decimal" id="dep-amount">' +
      '<div id="dep-hint" class="muted"></div>' +
      '<button id="dep-create-btn">Создать счёт</button>' +
      '<div id="dep-result"></div>';
    var selected = ps.cryptobot.configured && ps.cryptobot.deposit_enabled ? "cryptobot" : (ps.xrocket.configured && ps.xrocket.deposit_enabled ? "xrocket" : null);
    updateProviderSelection(root, selected);
    updateDepositHint(root, selected, ps);
    root.querySelectorAll(".provider-card").forEach(function (el) {
      el.onclick = function () {
        var p = el.getAttribute("data-provider");
        if (el.classList.contains("disabled")) { toast("Способ временно недоступен", true); return; }
        selected = p;
        updateProviderSelection(root, selected);
        updateDepositHint(root, selected, ps);
      };
    });
    document.getElementById("dep-create-btn").onclick = function () {
      var amount = parseFloat(document.getElementById("dep-amount").value);
      if (!selected) { toast("Выберите способ пополнения", true); return; }
      if (!amount || amount <= 0) { toast("Введите сумму", true); return; }
      this.disabled = true;
      var btn = this;
      apiPost("/deposits", { provider: selected, amount: amount }).then(function (res) {
        openExternal(res.pay_url);
        document.getElementById("dep-result").innerHTML =
          '<div class="card">Счёт на ' + fmt(res.amount, 2) + " USDT создан.<br>Если оплатили — нажмите проверить.</div>" +
          '<button id="dep-check-btn">🔄 Я оплатил / проверить</button>';
        document.getElementById("dep-check-btn").onclick = function () {
          this.disabled = true;
          var checkBtn = this;
          apiGet("/deposits/" + res.provider + "/" + res.invoice_id + "/status").then(function (statusRes) {
            checkBtn.disabled = false;
            if (statusRes.paid) {
              haptic("success");
              toast(statusRes.already_credited ? "Счёт уже был зачислен" : "Баланс пополнен на " + fmt(statusRes.credited_amount, 4) + " USDT");
              loadMe().then(function () { location.hash = "#/balance"; render(); });
            } else {
              toast("Оплата пока не найдена", true);
            }
          }).catch(function (e) { checkBtn.disabled = false; toast(e.message, true); });
        };
        btn.disabled = false;
      }).catch(function (e) { btn.disabled = false; toast(e.message, true); });
    };
  });

  function providerCard(key, cfg, direction) {
    var enabled = cfg.configured && (direction === "deposit" ? cfg.deposit_enabled : cfg.withdraw_enabled);
    return '<div class="provider-card' + (enabled ? "" : " disabled") + '" data-provider="' + key + '">' +
      "<div>" + PROVIDER_LABELS[key] + "</div>" +
      (cfg.configured ? (enabled ? "" : '<div class="muted" style="font-size:11px">на обслуживании</div>') : '<div class="muted" style="font-size:11px">недоступно</div>') +
      "</div>";
  }
  function updateProviderSelection(root, selected) {
    root.querySelectorAll(".provider-card").forEach(function (el) {
      el.classList.toggle("selected", el.getAttribute("data-provider") === selected);
    });
  }
  function updateDepositHint(root, provider, ps) {
    var hint = document.getElementById("dep-hint");
    if (!hint) return;
    if (!provider) { hint.textContent = "Нет доступных способов пополнения"; return; }
    hint.textContent = "Минимум: " + fmt(ps[provider].min_deposit, 2) + " USDT";
  }

  // ---------- Экран: вывод ----------
  route(/^\/withdraw$/, function (root) {
    if (!(ME.role === "executor" && !ME.executor_blocked)) {
      root.innerHTML = '<div class="empty-state"><span class="emoji">🔒</span>Вывод доступен только исполнителям</div>';
      return;
    }
    var ps = ME.payment_settings;
    root.innerHTML =
      '<h1>Вывод средств</h1>' +
      '<div class="muted" style="margin-bottom:10px">Доступно: ' + fmt(ME.balance, 4) + " USDT</div>" +
      '<div class="provider-choice">' + providerCard("cryptobot", ps.cryptobot, "withdraw") + providerCard("xrocket", ps.xrocket, "withdraw") + "</div>" +
      '<label>Сумма, USDT</label><input type="number" inputmode="decimal" id="wd-amount">' +
      '<div id="wd-hint" class="muted"></div>' +
      '<button id="wd-create-btn">Вывести</button>' +
      '<div id="wd-result"></div>';
    var selected = ps.cryptobot.configured && ps.cryptobot.withdraw_enabled ? "cryptobot" : (ps.xrocket.configured && ps.xrocket.withdraw_enabled ? "xrocket" : null);
    updateProviderSelection(root, selected);
    updateWithdrawHint(root, selected, ps);
    root.querySelectorAll(".provider-card").forEach(function (el) {
      el.onclick = function () {
        var p = el.getAttribute("data-provider");
        if (el.classList.contains("disabled")) { toast("Способ временно недоступен", true); return; }
        selected = p;
        updateProviderSelection(root, selected);
        updateWithdrawHint(root, selected, ps);
      };
    });
    document.getElementById("wd-create-btn").onclick = function () {
      var amount = parseFloat(document.getElementById("wd-amount").value);
      if (!selected) { toast("Выберите способ вывода", true); return; }
      if (!amount || amount <= 0) { toast("Введите сумму", true); return; }
      this.disabled = true;
      var btn = this;
      apiPost("/withdrawals", { provider: selected, amount: amount }).then(function (res) {
        haptic("success");
        var html = '<div class="card">✅ Заявка #' + res.withdrawal_id + " создана.</div>";
        if (res.pay_url) html += '<button id="wd-open-btn">🎁 Открыть чек</button>';
        document.getElementById("wd-result").innerHTML = html;
        if (res.pay_url) document.getElementById("wd-open-btn").onclick = function () { openExternal(res.pay_url); };
        loadMe();
        btn.disabled = false;
        document.getElementById("wd-amount").value = "";
      }).catch(function (e) { btn.disabled = false; toast(e.message, true); });
    };
  });
  function updateWithdrawHint(root, provider, ps) {
    var hint = document.getElementById("wd-hint");
    if (!hint) return;
    if (!provider) { hint.textContent = "Нет доступных способов вывода"; return; }
    hint.textContent = "Минимум: " + fmt(ps[provider].min_withdraw, 2) + " USDT";
  }

  // ---------- Экран: исполнитель ----------
  route(/^\/executor$/, function (root) {
    if (ME.role !== "executor") {
      return renderExecutorApplication(root);
    }
    return renderExecutorDashboard(root);
  });

  function renderExecutorApplication(root) {
    root.innerHTML = '<div class="spinner"></div>';
    return apiGet("/me").then(function (me) {
      ME = me;
      var app = me.executor_application;
      var blockingStatuses = ["pending", "question"];
      if (app && blockingStatuses.indexOf(app.status) !== -1) {
        var html = '<h1>Заявка на роль исполнителя</h1>' +
          '<div class="card"><div>Статус: <b>' + (APP_STATUS_LABELS[app.status] || app.status) + "</b></div>" +
          (app.admin_question ? '<div style="margin-top:8px"><b>Вопрос администратора:</b><br>' + esc(app.admin_question) + "</div>" : "") +
          "</div>";
        if (app.status === "question") {
          html += '<textarea id="answer-input" placeholder="Ваш ответ"></textarea><button id="answer-btn" class="icon-button-inline"><span class="btn-icon">' + svgIcon('check') + '</span> Отправить ответ</button>';
        }
        root.innerHTML = html;
        var answerBtn = document.getElementById("answer-btn");
        if (answerBtn) answerBtn.onclick = function () {
          var answer = document.getElementById("answer-input").value.trim();
          if (!answer) { toast("Введите ответ", true); return; }
          this.disabled = true;
          apiPost("/executor/apply/" + app.id + "/answer", { answer: answer }).then(function () {
            toast("Ответ отправлен"); render();
          }).catch(function (e) { answerBtn.disabled = false; toast(e.message, true); });
        };
        return;
      }
      var rejectionNote = (app && app.status === "rejected")
        ? '<div class="error-box">Предыдущая заявка отклонена' + (app.rejection_reason ? ": " + esc(app.rejection_reason) : "") + ". Можно подать новую." + "</div>"
        : "";
      root.innerHTML =
        '<h1>Стать исполнителем</h1>' + rejectionNote +
        '<p class="muted">Заполните короткую анкету — заявку рассмотрит администратор.</p>' +
        '<label>Опыт работы</label><textarea id="exp-input" placeholder="Расскажите о своём опыте"></textarea>' +
        '<label>С какими услугами готовы работать</label><textarea id="svc-input" placeholder="Например: обмен, выводы, карты"></textarea>' +
        '<label>Комментарий (необязательно)</label><textarea id="cmt-input"></textarea>' +
        '<button id="apply-btn" class="icon-button-inline"><span class="btn-icon">' + svgIcon('plus') + '</span> Подать заявку</button>';
      document.getElementById("apply-btn").onclick = function () {
        this.disabled = true;
        var btn = this;
        apiPost("/executor/apply", {
          experience: document.getElementById("exp-input").value,
          services: document.getElementById("svc-input").value,
          comment: document.getElementById("cmt-input").value,
        }).then(function () {
          toast("Заявка отправлена"); loadMe().then(render);
        }).catch(function (e) { btn.disabled = false; toast(e.message, true); });
      };
    });
  }

  function renderExecutorDashboard(root) {
    root.innerHTML = '<div class="spinner"></div>';
    return Promise.all([
      apiGet("/executor/stats"),
      apiGet("/executor/active-order"),
      apiGet("/executor/available-orders"),
    ]).then(function (results) {
      var stats = results[0], active = results[1], available = results[2];
      var html = '<div class="section-heading"><div style="display:flex;align-items:center;gap:9px"><span class="section-icon">' + svgIcon('executor') + '</span><h2>Кабинет исполнителя</h2></div></div>';
      if (ME.executor_blocked) html += '<div class="error-box">Вы заблокированы как исполнитель. Обратитесь в поддержку.</div>';
      html +=
        '<div class="card"><div class="row">' +
        '<div><div class="muted">Рейтинг</div><div style="font-weight:700">⭐ ' + fmt(stats.rating, 2) + " (" + stats.ratings + ")</div></div>" +
        '<div><div class="muted">Выполнено</div><div style="font-weight:700">' + stats.completed + "</div></div>" +
        '<div><div class="muted">Заработано</div><div style="font-weight:700">' + fmt(stats.earned, 2) + "</div></div>" +
        "</div></div>";

      html += '<div class="toggle-row"><div class="executor-action"><span class="action-icon">' + svgIcon('check') + '</span><span>Доступен для новых заявок</span></div><div class="switch' + (ME.executor_available ? " on" : "") + '" id="avail-switch"></div></div>';
      html += '<div class="toggle-row"><div class="executor-action"><span class="action-icon">' + svgIcon('bell') + '</span><span>Уведомления о новых заявках</span></div><div class="switch' + (ME.executor_notify_enabled ? " on" : "") + '" id="notify-switch"></div></div>';

      if (active) {
        html += "<h2>Активная заявка</h2>" +
          '<div class="card tappable" data-id="' + active.id + '">' +
          '<div style="display:flex;justify-content:space-between"><b>#' + active.id + "</b>" +
          '<span class="badge-status status-' + active.status + '">' + (ORDER_STATUS_LABELS[active.status] || active.status) + "</span></div>" +
          '<div class="muted">' + esc(active.name) + " · " + fmt(active.amount_rub, 0) + " ₽</div>" +
          "</div>";
      } else {
        html += "<h2>Свободные заявки</h2>";
        if (!available.length) {
          html += '<div class="empty-state"><span class="emoji">📭</span>Сейчас свободных заявок нет</div>';
        } else {
          html += available.map(function (o) {
            return '<div class="card"><div style="display:flex;justify-content:space-between">' +
              '<b>#' + o.id + "</b><span>" + fmt(o.amount_rub, 0) + " ₽ → " + fmt(Number(o.user_amount_usdt) + Number(o.executor_commission_amount), 4) + " USDT</span></div>" +
              '<div class="muted">' + esc(o.name) + (o.order_comment ? " · " + esc(o.order_comment) : "") + "</div>" +
              '<button class="small claim-btn icon-button-inline" data-id="' + o.id + '"><span class="btn-icon">' + svgIcon('check') + '</span> Взять в работу</button></div>';
          }).join("");
        }
      }
      html += '<h2>История</h2><div id="exec-history" class="muted">Загрузка...</div>';
      root.innerHTML = html;

      document.getElementById("avail-switch").onclick = function () {
        var next = !ME.executor_available;
        apiPost("/executor/availability", { available: next }).then(function () {
          ME.executor_available = next; render();
        }).catch(function (e) { toast(e.message, true); });
      };
      document.getElementById("notify-switch").onclick = function () {
        var next = !ME.executor_notify_enabled;
        apiPost("/executor/notify", { enabled: next }).then(function () {
          ME.executor_notify_enabled = next; render();
        }).catch(function (e) { toast(e.message, true); });
      };
      var activeCard = root.querySelector(".card[data-id]");
      if (activeCard && active) activeCard.onclick = function () { location.hash = "#/order/" + active.id; };
      root.querySelectorAll(".claim-btn").forEach(function (btn) {
        btn.onclick = function () {
          var id = btn.getAttribute("data-id");
          btn.disabled = true;
          apiPost("/orders/" + id + "/claim").then(function () {
            haptic("success"); toast("Заявка взята в работу"); location.hash = "#/order/" + id;
          }).catch(function (e) { btn.disabled = false; toast(e.message, true); });
        };
      });
      apiGet("/executor/history").then(function (history) {
        var el = document.getElementById("exec-history");
        if (!el) return;
        if (!history.length) { el.outerHTML = '<div class="empty-state"><span class="emoji">🗂</span>История пуста</div>'; return; }
        el.outerHTML = history.map(function (o) {
          return '<div class="list-item"><div><div>#' + o.id + " · " + esc(o.name) + "</div>" +
            '<div class="muted">' + fmtDate(o.settled_at || o.created_at) + "</div></div>" +
            '<span class="badge-status status-' + o.status + '">' + (ORDER_STATUS_LABELS[o.status] || o.status) + "</span></div>";
        }).join("");
      });
    });
  }

  // ---------- Экран: рефералы ----------
  route(/^\/referrals$/, function (root) {
    root.innerHTML = '<h1>Рефералы</h1><div class="spinner"></div>';
    return apiGet("/referrals").then(function (r) {
      root.innerHTML =
        '<h1>Рефералы</h1>' +
        '<div class="card"><p>Приглашайте пользователей и получайте:</p>' +
        "<ul style=\"margin:6px 0;padding-left:18px\"><li>" + fmt(r.percent, 2) + "% от комиссии платформы за каждую завершённую заявку реферала</li>" +
        "<li>" + fmt(r.flat_bonus, 2) + " USDT разово за первое пополнение реферала</li></ul></div>" +
        (r.link ? '<label>Ваша ссылка</label><input readonly id="ref-link" value="' + esc(r.link) + '"><button id="copy-ref-btn" class="secondary icon-button-inline"><span class="btn-icon">' + svgIcon('copy') + '</span> Скопировать ссылку</button>' : "") +
        '<div class="row" style="margin-top:14px"><div class="card" style="flex:1"><div class="muted">Приглашено</div><div style="font-weight:700;font-size:18px">' + r.count + "</div></div>" +
        '<div class="card" style="flex:1"><div class="muted">Заработано</div><div style="font-weight:700;font-size:18px">' + fmt(r.total_earned, 4) + "</div></div></div>";
      var copyBtn = document.getElementById("copy-ref-btn");
      if (copyBtn) copyBtn.onclick = function () {
        var input = document.getElementById("ref-link");
        input.select();
        try {
          navigator.clipboard.writeText(input.value);
          toast("Ссылка скопирована");
        } catch (e) {
          document.execCommand("copy");
          toast("Ссылка скопирована");
        }
      };
    });
  });

  // ---------- Верхняя панель ----------
  document.getElementById("notif-btn").onclick = function () { location.hash = "#/notifications"; };

  // ---------- Инициализация ----------
  loadMe().then(function () {
    render();
    refreshNotifBadge();
    setInterval(refreshNotifBadge, 20000);
  }).catch(function (e) {
    document.getElementById("app").innerHTML = '<div class="error-box">Не удалось загрузить данные: ' + esc(e.message) +
      "</div><p class=\"muted\">Откройте приложение через кнопку в боте Telegram.</p>";
  });
})();
