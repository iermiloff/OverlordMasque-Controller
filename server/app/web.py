from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["web"])

CABINET_HTML = """<!doctype html>
<html lang="ru" class="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>OverlordMasque Online — Кабинет</title>
  <script src="https://tailwindcss.com"></script>
</head>
<body class="bg-zinc-950 text-zinc-100 min-h-screen font-sans">
  <div class="max-w-5xl mx-auto p-6">
    <header class="flex justify-between items-center border-b border-zinc-800 pb-4 mb-6">
      <h1 class="text-2xl font-black tracking-wider text-red-600">OVERLORD MASQUE ONLINE</h1>
      <button id="btnLogout" onclick="logout()" class="hidden text-sm bg-zinc-800 hover:bg-zinc-700 px-3 py-1.5 rounded">
        Выйти
      </button>
    </header>

    <div id="payBanner" class="hidden mb-4 p-3 rounded-lg border text-sm"></div>

    <!-- ФОРМА ВХОДА -->
    <div id="loginBox" class="max-w-md mx-auto bg-zinc-900 p-6 rounded-xl border border-zinc-800">
      <h2 class="text-lg font-bold mb-4">Вход в личный кабинет</h2>
      <input id="inpLogin" placeholder="Логин" class="w-full mb-3 px-3 py-2 bg-zinc-950 border border-zinc-700 rounded" />
      <input id="inpPass" type="password" placeholder="Пароль" class="w-full mb-4 px-3 py-2 bg-zinc-950 border border-zinc-700 rounded" />
      <button onclick="doLogin()" class="w-full bg-red-700 hover:bg-red-600 font-bold py-2 rounded">Войти</button>
      <p id="loginErr" class="text-red-400 text-sm mt-3"></p>
    </div>

    <!-- КАБИНЕТ ПОЛЬЗОВАТЕЛЯ -->
    <div id="userBox" class="hidden space-y-6">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="bg-zinc-900 p-4 rounded-xl border border-zinc-800">
          <div class="text-xs text-zinc-400">Статус подписки</div>
          <div id="uStatus" class="text-xl font-bold mt-1">—</div>
          <div id="uExpires" class="text-xs text-zinc-400 mt-1">—</div>
        </div>
        <div class="bg-zinc-900 p-4 rounded-xl border border-zinc-800">
          <div class="text-xs text-zinc-400">Использовано трафика</div>
          <div id="uTraffic" class="text-xl font-bold mt-1">—</div>
          <div id="uLimit" class="text-xs text-zinc-400 mt-1">—</div>
        </div>
        <div class="bg-zinc-900 p-4 rounded-xl border border-zinc-800">
          <div class="text-xs text-zinc-400">Лимит устройств</div>
          <div id="uDevices" class="text-xl font-bold mt-1">—</div>
          <div class="text-xs text-zinc-400 mt-1">Аккаунт: <span id="uLogin"></span></div>
        </div>
      </div>

      <!-- ТАРИФЫ И ОПЛАТА PLATEGA -->
      <div class="bg-zinc-900 p-5 rounded-xl border border-zinc-800">
        <h3 class="font-bold text-lg mb-3">Продление подписки (Platega: СБП / Карты / Крипта)</h3>
        <div id="plansGrid" class="grid grid-cols-1 md:grid-cols-3 gap-4"></div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <!-- СТАТИСТИКА ПО НОДАМ -->
        <div class="bg-zinc-900 p-5 rounded-xl border border-zinc-800">
          <h3 class="font-bold text-lg mb-3">Статистика по серверам</h3>
          <div id="nodesList" class="space-y-2 text-sm"></div>
        </div>

        <!-- ПРИВЯЗАННЫЕ УСТРОЙСТВА -->
        <div class="bg-zinc-900 p-5 rounded-xl border border-zinc-800">
          <h3 class="font-bold text-lg mb-3">Активные устройства</h3>
          <div id="devicesList" class="space-y-2 text-sm"></div>
        </div>
      </div>
    </div>

    <!-- АДМИН-ПАНЕЛЬ -->
    <div id="adminBox" class="hidden mt-8 bg-zinc-900 p-5 rounded-xl border border-red-900/50 space-y-6">
      <h2 class="text-xl font-bold text-red-500">Панель администратора</h2>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
        <!-- ДОБАВИТЬ НОДУ -->
        <div class="bg-zinc-950 p-4 rounded-lg border border-zinc-800 space-y-2 text-sm">
          <h3 class="font-bold text-base mb-2">1. Добавить 3x-ui ноду</h3>
          <input id="nName" placeholder="Имя (DE-Frankfurt)" class="w-full p-2 bg-zinc-900 border border-zinc-700 rounded" />
          <input id="nUrl" placeholder="URL (https://ip:port/path)" class="w-full p-2 bg-zinc-900 border border-zinc-700 rounded" />
          <input id="nToken" placeholder="API Token 3x-ui" class="w-full p-2 bg-zinc-900 border border-zinc-700 rounded" />
          <div class="flex gap-2">
            <input id="nInb" type="number" placeholder="Inbound ID" class="w-1/2 p-2 bg-zinc-900 border border-zinc-700 rounded" />
            <input id="nPort" type="number" value="443" placeholder="Port" class="w-1/2 p-2 bg-zinc-900 border border-zinc-700 rounded" />
          </div>
          <input id="nDom" placeholder="Public Domain (vpn.site.ru)" class="w-full p-2 bg-zinc-900 border border-zinc-700 rounded" />
          <label class="flex items-center gap-2 text-xs text-zinc-400">
            <input id="nTls" type="checkbox" checked /> Проверять TLS сертификат панели
          </label>
          <button onclick="addNode()" class="w-full bg-red-700 hover:bg-red-600 py-2 rounded font-bold">Добавить ноду</button>
        </div>

        <!-- ДОБАВИТЬ ТАРИФ -->
        <div class="bg-zinc-950 p-4 rounded-lg border border-zinc-800 space-y-2 text-sm">
          <h3 class="font-bold text-base mb-2">2. Создать тариф Platega</h3>
          <input id="pTitle" placeholder="Название (1 Месяц)" class="w-full p-2 bg-zinc-900 border border-zinc-700 rounded" />
          <div class="flex gap-2">
            <input id="pDays" type="number" value="30" placeholder="Дней" class="w-1/2 p-2 bg-zinc-900 border border-zinc-700 rounded" />
            <input id="pGb" type="number" value="0" placeholder="ГБ (0=∞)" class="w-1/2 p-2 bg-zinc-900 border border-zinc-700 rounded" />
          </div>
          <input id="pPrice" type="number" placeholder="Цена в рублях (299)" class="w-full p-2 bg-zinc-900 border border-zinc-700 rounded" />
          <button onclick="addPlan()" class="w-full bg-red-700 hover:bg-red-600 py-2 rounded font-bold">Создать тариф</button>
          <div id="adminPlans" class="pt-2 space-y-1 text-xs text-zinc-400"></div>
        </div>

        <!-- СОЗДАТЬ ПОЛЬЗОВАТЕЛЯ -->
        <div class="bg-zinc-950 p-4 rounded-lg border border-zinc-800 space-y-2 text-sm">
          <h3 class="font-bold text-base mb-2">3. Создать пользователя</h3>
          <input id="cuLogin" placeholder="Логин" class="w-full p-2 bg-zinc-900 border border-zinc-700 rounded" />
          <input id="cuPass" placeholder="Пароль (мин. 8 симв.)" class="w-full p-2 bg-zinc-900 border border-zinc-700 rounded" />
          <div class="flex gap-2">
            <input id="cuDays" type="number" value="30" placeholder="Дней" class="w-1/2 p-2 bg-zinc-900 border border-zinc-700 rounded" />
            <input id="cuGb" type="number" value="0" placeholder="ГБ (0=∞)" class="w-1/2 p-2 bg-zinc-900 border border-zinc-700 rounded" />
          </div>
          <input id="cuNodes" placeholder="ID нод (пусто = все)" class="w-full p-2 bg-zinc-900 border border-zinc-700 rounded" />
          <button onclick="addUser()" class="w-full bg-red-700 hover:bg-red-600 py-2 rounded font-bold">Создать и Sync</button>
        </div>
      </div>

      <!-- СПИСОК НОД -->
      <div>
        <h3 class="font-bold mb-2">Подключённые серверы (3x-ui)</h3>
        <div id="adminNodes" class="text-xs space-y-2"></div>
      </div>

      <!-- СПИСОК ПОЛЬЗОВАТЕЛЕЙ -->
      <div>
        <h3 class="font-bold mb-2">Пользователи и синхронизация</h3>
        <div id="adminUsers" class="text-xs space-y-2"></div>
      </div>
    </div>
  </div>

<script>
let token = localStorage.getItem('omc_token') || '';
const fmtBytes = b => b === 0 ? '0 Б' : (b / (1024 ** 3)).toFixed(2) + ' ГБ';

function checkPayBanner() {
  const p = new URLSearchParams(location.search).get('pay');
  const el = document.getElementById('payBanner');
  if (p === 'success') {
    el.className = 'mb-4 p-3 rounded-lg border border-green-700 bg-green-950/60 text-green-300 text-sm';
    el.innerText = 'Оплата принята! Подписка обновится в течение нескольких секунд.';
  } else if (p === 'fail') {
    el.className = 'mb-4 p-3 rounded-lg border border-red-700 bg-red-950/60 text-red-300 text-sm';
    el.innerText = 'Оплата не завершена или отменена.';
  }
}

async function api(path, opts = {}) {
  opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  if (token) opts.headers['Authorization'] = 'Bearer ' + token;
  const r = await fetch('/api/v1' + path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || 'Ошибка ' + r.status);
  return data;
}

async function doLogin() {
  try {
    let devId = localStorage.getItem('omc_dev');
    if (!devId) {
      devId = 'web-' + Math.random().toString(36).slice(2, 12);
      localStorage.setItem('omc_dev', devId);
    }
    const res = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        login: document.getElementById('inpLogin').value.trim(),
        password: document.getElementById('inpPass').value,
        device_id: devId,
        device_name: 'Web Browser',
        platform: 'web'
      })
    });
    token = res.access_token;
    localStorage.setItem('omc_token', token);
    await loadCabinet();
  } catch (e) {
    document.getElementById('loginErr').innerText = e.message;
  }
}

function logout() {
  localStorage.removeItem('omc_token');
  location.reload();
}

async function buyPlan(planId) {
  try {
    const res = await api('/payments', { method: 'POST', body: JSON.stringify({ plan_id: planId }) });
    if (res.redirect_url) window.location.href = res.redirect_url;
  } catch (e) {
    alert(e.message);
  }
}

async function removeDevice(id) {
  if (!confirm('Отвязать это устройство?')) return;
  try {
    await api('/me/devices/' + id, { method: 'DELETE' });
    await loadCabinet();
  } catch (e) {
    alert(e.message);
  }
}

async function loadCabinet() {
  checkPayBanner();
  if (!token) return;
  try {
    const me = await api('/me');
    document.getElementById('loginBox').classList.add('hidden');
    document.getElementById('userBox').classList.remove('hidden');
    document.getElementById('btnLogout').classList.remove('hidden');

    document.getElementById('uLogin').innerText = me.login;
    document.getElementById('uStatus').innerText = me.active ? 'АКТИВНА' : 'НЕ АКТИВНА';
    document.getElementById('uStatus').className = 'text-xl font-bold mt-1 ' + (me.active ? 'text-green-500' : 'text-red-500');
    document.getElementById('uExpires').innerText = me.expires_at ? 'До: ' + new Date(me.expires_at).toLocaleString() : 'Бессрочно';
    document.getElementById('uTraffic').innerText = fmtBytes(me.traffic_used);
    document.getElementById('uLimit').innerText = me.traffic_limit ? 'Лимит: ' + fmtBytes(me.traffic_limit) : 'Безлимит';
    document.getElementById('uDevices').innerText = me.devices.length + ' / ' + me.max_devices;

    document.getElementById('nodesList').innerHTML = me.nodes.map(n =>
      `<div class="flex justify-between bg-zinc-950 p-3 rounded border border-zinc-800">
        <span class="font-semibold">${n.name} <span class="text-xs text-zinc-500 uppercase">(${n.protocol})</span></span>
        <span class="text-zinc-400">↑ ${fmtBytes(n.up)} / ↓ ${fmtBytes(n.down)}</span>
      </div>`
    ).join('') || '<div class="text-zinc-500">Нет привязанных серверов</div>';

    document.getElementById('devicesList').innerHTML = me.devices.map(d =>
      `<div class="flex justify-between items-center bg-zinc-950 p-3 rounded border border-zinc-800">
        <div>
          <div class="font-semibold">${d.device_name} <span class="text-xs text-zinc-500">(${d.platform})</span></div>
          <div class="text-xs text-zinc-500">${new Date(d.last_seen_at).toLocaleString()}</div>
        </div>
        <button onclick="removeDevice(${d.id})" class="text-xs bg-zinc-800 hover:bg-red-800 px-2.5 py-1 rounded">Удалить</button>
      </div>`
    ).join('') || '<div class="text-zinc-500">Нет устройств</div>';

    const plans = await api('/plans');
    document.getElementById('plansGrid').innerHTML = plans.map(p =>
      `<div class="bg-zinc-950 p-4 rounded-lg border border-zinc-800 flex flex-col justify-between">
        <div>
          <div class="font-bold text-base">${p.title}</div>
          <div class="text-xs text-zinc-400 mt-1">${p.days} дн. · ${p.traffic_gb ? p.traffic_gb + ' ГБ' : 'Безлимит'}</div>
        </div>
        <button onclick="buyPlan(${p.id})" class="mt-4 w-full bg-red-700 hover:bg-red-600 py-1.5 rounded font-bold text-sm">
          Оплатить ${p.price} ₽
        </button>
      </div>`
    ).join('') || '<div class="text-zinc-500 text-sm">Тарифы пока не добавлены администратором</div>';

    if (me.is_admin) {
      await loadAdmin();
    }
  } catch (e) {
    localStorage.removeItem('omc_token');
  }
}

async function loadAdmin() {
  document.getElementById('adminBox').classList.remove('hidden');
  const [nodes, users, plans] = await Promise.all([
    api('/admin/nodes'),
    api('/admin/users'),
    api('/admin/plans')
  ]);

  document.getElementById('adminPlans').innerHTML = plans.map(p =>
    `<div class="flex justify-between items-center bg-zinc-900 px-2 py-1 rounded">
      <span>${p.title} (${p.price} ₽)</span>
      <button onclick="delPlan(${p.id})" class="text-red-400 hover:underline">Удалить</button>
    </div>`
  ).join('');

  document.getElementById('adminNodes').innerHTML = nodes.map(n =>
    `<div class="bg-zinc-950 p-3 rounded border border-zinc-800 flex justify-between items-center">
      <div>
        <b>[ID: ${n.id}] ${n.name}</b> · ${n.public_domain}:${n.public_port} · Inbound #${n.inbound_id} (${n.protocol})
        <div class="text-zinc-500">${n.panel_url}</div>
      </div>
      <div class="flex gap-2">
        <button onclick="testNode(${n.id})" class="bg-zinc-800 hover:bg-zinc-700 px-2.5 py-1 rounded">Test 3x-ui</button>
        <button onclick="delNode(${n.id})" class="bg-red-900/60 hover:bg-red-800 px-2.5 py-1 rounded">Удалить</button>
      </div>
    </div>`
  ).join('') || '<div class="text-zinc-500">Ноды не добавлены</div>';

  document.getElementById('adminUsers').innerHTML = users.map(u =>
    `<div class="bg-zinc-950 p-3 rounded border border-zinc-800 flex flex-wrap justify-between items-center gap-2">
      <div>
        <b>${u.login}</b> (ID: ${u.id}) · ${u.is_active ? 'Активен' : 'Заблокирован'} · Трафик: ${fmtBytes(u.traffic_used)}
        <div class="text-zinc-500">До: ${u.expires_at ? new Date(u.expires_at).toLocaleString() : '∞'} | Ноды: ${u.nodes.map(n => `${n.name} [${n.synced ? 'OK' : n.error || 'Wait'}]`).join(', ') || 'нет'}</div>
      </div>
      <div class="flex gap-2">
        <button onclick="addDays(${u.id}, 30)" class="bg-zinc-800 hover:bg-zinc-700 px-2 py-1 rounded">+30д</button>
        <button onclick="resyncUser(${u.id})" class="bg-zinc-800 hover:bg-zinc-700 px-2 py-1 rounded">Sync</button>
        <button onclick="delUser(${u.id})" class="bg-red-900/60 hover:bg-red-800 px-2 py-1 rounded">Удалить</button>
      </div>
    </div>`
  ).join('');
}

async function addNode() {
  try {
    await api('/admin/nodes', {
      method: 'POST',
      body: JSON.stringify({
        name: document.getElementById('nName').value,
        panel_url: document.getElementById('nUrl').value,
        api_token: document.getElementById('nToken').value,
        inbound_id: parseInt(document.getElementById('nInb').value),
        public_domain: document.getElementById('nDom').value,
        public_port: parseInt(document.getElementById('nPort').value),
        verify_tls: document.getElementById('nTls').checked
      })
    });
    await loadAdmin();
  } catch (e) {
    alert(e.message);
  }
}

async function testNode(id) {
  try {
    const res = await api(`/admin/nodes/${id}/test`, { method: 'POST' });
    const list = res.inbounds.map(i => `#${i.id}: ${i.remark} (${i.protocol}:${i.port})`).join('\n');
    alert('Связь с 3x-ui установлена!\nДоступные инбаунды:\n' + (list || 'список пуст'));
  } catch (e) {
    alert('Ошибка связи с 3x-ui: ' + e.message);
  }
}

async function delNode(id) {
  if (!confirm('Удалить ноду из контроллера?')) return;
  await api(`/admin/nodes/${id}`, { method: 'DELETE' });
  await loadAdmin();
}

async function addPlan() {
  try {
    await api('/admin/plans', {
      method: 'POST',
      body: JSON.stringify({
        title: document.getElementById('pTitle').value,
        days: parseInt(document.getElementById('pDays').value),
        traffic_gb: parseInt(document.getElementById('pGb').value),
        price: parseFloat(document.getElementById('pPrice').value)
      })
    });
    await loadAdmin();
  } catch (e) {
    alert(e.message);
  }
}

async function delPlan(id) {
  await api(`/admin/plans/${id}`, { method: 'DELETE' });
  await loadAdmin();
}

async function addUser() {
  try {
    const raw = document.getElementById('cuNodes').value.trim();
    const nIds = raw ? raw.split(',').map(s => parseInt(s.trim())).filter(Boolean) : [];
    const res = await api('/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        login: document.getElementById('cuLogin').value,
        password: document.getElementById('cuPass').value,
        days: parseInt(document.getElementById('cuDays').value),
        traffic_gb: parseInt(document.getElementById('cuGb').value),
        node_ids: nIds
      })
    });
    alert('Создан! Ошибки sync: ' + (res.sync_errors.length ? res.sync_errors.join('; ') : 'нет'));
    await loadAdmin();
  } catch (e) {
    alert(e.message);
  }
}

async function addDays(id, days) {
  await api(`/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify({ add_days: days }) });
  await loadAdmin();
}

async function resyncUser(id) {
  const res = await api(`/admin/users/${id}/sync`, { method: 'POST' });
  alert('Sync завершён. Ошибки: ' + (res.sync_errors.length ? res.sync_errors.join('; ') : 'нет'));
  await loadAdmin();
}

async function delUser(id) {
  if (!confirm('Удалить пользователя и его аккаунты на всех нодах?')) return;
  await api(`/admin/users/${id}`, { method: 'DELETE' });
  await loadAdmin();
}

loadCabinet();
</script>
</body>
</html>
"""


@router.get("/cabinet", response_class=HTMLResponse)
async def cabinet_page():
    return CABINET_HTML
