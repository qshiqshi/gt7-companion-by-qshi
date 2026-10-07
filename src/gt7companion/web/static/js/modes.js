/* What kind of screen this page is (decided in early.js) and which layout it asked for. */
const params = new URLSearchParams(location.search);

export const MODE = document.body.dataset.mode || 'view';
export const IS_EDITOR = MODE === 'edit';
export const IS_OBS = MODE === 'obs';
export const IS_VIEW = MODE === 'view';

/* ?layout=<name> pins a layout; without it the program's default is used. */
export const LAYOUT_NAME = params.get('layout') || '';

/* The same page in another mode, keeping the chosen layout. */
export function urlFor(mode) {
  const next = new URLSearchParams();
  if (LAYOUT_NAME) next.set('layout', LAYOUT_NAME);
  if (mode === 'edit') next.set('edit', '1');
  if (mode === 'obs') next.set('obs', '1');
  const query = next.toString();
  return location.pathname + (query ? '?' + query : '');
}
