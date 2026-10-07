/* "Connect devices": on the computer itself the addresses, QR codes and the PIN;
   on another device the form to enter the PIN. */
import { byId, get, post, safeNext } from './api.js';
import { t } from '../i18n.js';

async function showOwner() {
  const info = await get('/api/connect');
  byId('owner').hidden = false;
  byId('link-settings').hidden = false;
  byId('lan-off').hidden = info.lan;
  byId('lan-on').hidden = !info.lan;
  byId('pin-title').textContent = info.lan ? t('connect.pair.2', '2. Zum Bearbeiten koppeln') : t('connect.pair', 'Zum Bearbeiten koppeln');
  byId('pin').textContent = info.pin;
  byId('devices').textContent = info.devices === 1 ? t('connect.devices.one', '1 Gerät gekoppelt')
    : t('connect.devices', '{n} Geräte gekoppelt').replace('{n}', info.devices);
  if (!info.lan && info.lan_setting) {
    byId('btn-lan-on').hidden = true;
    byId('lan-on-result').textContent = t('connect.restart', 'Eingeschaltet. Starte das Programm neu, damit es gilt.');
  }
  const list = byId('addresses');
  list.textContent = '';
  if (info.lan && !info.addresses.length) {
    const none = document.createElement('p');
    none.className = 'note warn';
    none.textContent = t('connect.nonet', 'Dieser Computer ist gerade in keinem Heimnetz (WLAN oder Kabel).');
    list.appendChild(none);
  }
  info.addresses.forEach(function(address, index) {
    const row = document.createElement('div');
    row.className = 'address';
    const picture = document.createElement('img');
    picture.alt = t('connect.qr', 'QR-Code der Adresse');
    picture.src = '/api/connect/qr.svg?address=' + encodeURIComponent(address);
    const text = document.createElement('div');
    const url = document.createElement('div');
    url.className = 'url';
    url.textContent = info.urls[index].replace(/\/$/, '');
    text.appendChild(url);
    row.append(picture, text);
    list.appendChild(row);
  });
}

function showGuest() {
  byId('guest').hidden = false;
  byId('pin-input').focus();
  byId('pair-form').addEventListener('submit', async function(event) {
    event.preventDefault();
    const error = byId('pair-error');
    error.hidden = true;
    try {
      await post('/api/pair', { pin: byId('pin-input').value.trim() });
      location.replace(safeNext('/connect'));
    } catch (problem) {
      error.textContent = problem.status === 429
        ? t('connect.wait', 'Zu viele falsche Versuche. Warte ein paar Minuten.')
        : problem.status === 403 ? t('connect.wrong', 'Die PIN stimmt nicht.')
        : t('connect.failed', 'Das hat nicht geklappt. Ist das Programm noch offen?');
      error.hidden = false;
      byId('pin-input').select();
    }
  });
}

function showPaired() {
  byId('paired').hidden = false;
  byId('link-settings').hidden = false;
  byId('link-next').href = safeNext('/?edit=1');
  byId('btn-unpair').addEventListener('click', async function() {
    await post('/api/unpair');
    location.reload();
  });
}

byId('btn-new-pin').addEventListener('click', async function() {
  await post('/api/pairing/reset');
  await showOwner();
});
byId('btn-lan-on').addEventListener('click', async function() {
  await post('/api/settings', { lan: true });
  await showOwner();
});

try {
  const status = await get('/api/status');
  if (status.role === 'owner') await showOwner();
  else if (status.role === 'editor') showPaired();
  else showGuest();
} catch (problem) {
  byId('offline').hidden = false;
}
