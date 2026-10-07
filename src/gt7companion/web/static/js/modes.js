/* What kind of screen this page is (decided in early.js) and which layout it shows. */
import { pickLayout } from './layout-pick.js';

const params = new URLSearchParams(location.search);
const STORE_KEY = 'gt7c.layout';

export const MODE = document.body.dataset.mode || 'view';
export const IS_EDITOR = MODE === 'edit';
export const IS_OBS = MODE === 'obs';
export const IS_VIEW = MODE === 'view';

/* The layout of this screen. Set once by chooseLayout() before the connection is made. */
export let layoutName = '';
export let layouts = [];              // what the program offers

function remembered() {
  try { return localStorage.getItem(STORE_KEY) || ''; } catch (e) { return ''; }
}

/* In order: ?layout=<name> in the address, the choice made on this device earlier,
   otherwise the preset whose shape is closest to this screen. */
export async function chooseLayout() {
  const pinned = params.get('layout') || '';
  try {
    const response = await fetch('/api/layouts', { cache: 'no-store' });
    if (response.ok) layouts = (await response.json()).layouts || [];
  } catch (e) { /* the program is not reachable yet; it will use its default */ }
  const known = name => !!name && layouts.some(layout => layout.name === name);
  if (known(pinned) || (pinned && !layouts.length)) layoutName = pinned;
  else if (!IS_OBS && known(remembered())) layoutName = remembered();
  else layoutName = pickLayout(layouts, { width: window.innerWidth, height: window.innerHeight },
                               IS_OBS ? 'overlay' : 'dashboard');
  return layoutName;
}

/* Remember a choice for this device and show it. */
export function switchLayout(name) {
  try { localStorage.setItem(STORE_KEY, name); } catch (e) { /* private mode: only for now */ }
  location.assign(urlFor(MODE, name));
}

/* The same page in another mode, with a given layout (default: the one shown now). */
export function urlFor(mode, name) {
  const next = new URLSearchParams();
  const layout = name === undefined ? layoutName : name;
  if (layout) next.set('layout', layout);
  if (mode === 'edit') next.set('edit', '1');
  if (mode === 'obs') next.set('obs', '1');
  const query = next.toString();
  return location.pathname + (query ? '?' + query : '');
}

/* How a layout is called in the menus. */
export function layoutLabel(layout) {
  const label = layout.label || {};
  const language = (document.documentElement.lang || 'de').slice(0, 2);
  return label[language] || label.en || label.de || layout.name;
}
