/* A short guided tour: speech bubbles that point at the real controls, one step at a time.
   Every step can be skipped, and a tour that was seen once never starts by itself again
   (remembered on this device).

     runTour('view', [{ target: '#btn-edit', title: '…', text: '…', prefer: 'bottom' }, …])

   A step without a target is shown in the middle of the screen; a step whose target is
   not on the page (a hidden button) is left out. Texts are written in German like
   everywhere else; i18n-classic.js translates them as they appear. */
import { t } from './i18n.js';
import { placeBubble } from './tour-place.js';

const SEEN = 'gt7c.tour.';
const PAD = 6;                         // room between a control and the ring around it
let running = null;                    // closes the tour that is open now

export function tourSeen(name) {
  try { return localStorage.getItem(SEEN + name) === '1'; } catch (e) { return false; }
}

function remember(name) {
  try { localStorage.setItem(SEEN + name, '1'); } catch (e) { /* private mode: only for now */ }
}

/* ?tour=1 in the address asks for the tour once. The address is tidied at once, so
   reloading the page does not start it again. */
export function tourAsked() {
  const params = new URLSearchParams(location.search);
  if (!params.has('tour')) return false;
  params.delete('tour');
  const query = params.toString();
  history.replaceState(history.state, '', location.pathname + (query ? '?' + query : '') + location.hash);
  return true;
}

function find(target) {
  return typeof target === 'function' ? target() : document.querySelector(target);
}

function onPage(element) {
  if (!element) return false;
  const box = element.getBoundingClientRect();
  return box.width > 0 && box.height > 0;
}

function make(tag, name, text) {
  const element = document.createElement(tag);
  if (name) element.className = name;
  if (text) element.textContent = text;
  return element;
}

export function runTour(name, allSteps) {
  if (running) running(false);
  const steps = allSteps.filter(step => !step.target || onPage(find(step.target)));
  if (!steps.length) return false;

  const root = make('div', 'tour');
  const shade = make('div', 'tour-shade');
  const spot = make('div', 'tour-spot');
  const bubble = make('section', 'tour-bubble');
  bubble.setAttribute('role', 'dialog');
  bubble.setAttribute('aria-modal', 'true');
  bubble.setAttribute('aria-labelledby', 'tour-title');
  bubble.setAttribute('aria-describedby', 'tour-count tour-text');
  const count = make('p', 'tour-count');
  count.id = 'tour-count';
  const title = make('h2', 'tour-title');
  title.id = 'tour-title';
  const text = make('p', 'tour-text');
  text.id = 'tour-text';
  const actions = make('div', 'tour-actions');
  const skip = make('button', 'tour-skip', 'Überspringen');
  const back = make('button', 'tour-back', 'Zurück');
  const next = make('button', 'tour-next');
  [skip, back, next].forEach(button => { button.type = 'button'; });
  actions.append(skip, back, next);
  bubble.append(count, title, text, actions);
  root.append(shade, spot, bubble);

  const before = document.activeElement;
  let current = 0;
  let watched = null;                  // the target whose size is followed

  function place() {
    const step = steps[current];
    const target = step.target ? find(step.target) : null;
    const box = onPage(target) ? target.getBoundingClientRect() : null;
    const ring = box && { left: box.left - PAD, top: box.top - PAD, width: box.width + 2 * PAD, height: box.height + 2 * PAD };
    root.classList.toggle('has-target', !!ring);
    spot.hidden = !ring;
    if (ring) {
      spot.style.left = ring.left + 'px';
      spot.style.top = ring.top + 'px';
      spot.style.width = ring.width + 'px';
      spot.style.height = ring.height + 'px';
    }
    const at = placeBubble(ring, { width: bubble.offsetWidth, height: bubble.offsetHeight },
                           { width: window.innerWidth, height: window.innerHeight }, { prefer: step.prefer });
    bubble.style.left = at.left + 'px';
    bubble.style.top = at.top + 'px';
    bubble.dataset.side = at.side;
    bubble.style.setProperty('--tail', at.tail + 'px');
  }

  const follow = window.ResizeObserver ? new ResizeObserver(place) : null;   // a translated text changes the bubble

  function show(index) {
    current = index;
    const step = steps[index];
    count.textContent = t('Schritt {n} von {m}', { n: index + 1, m: steps.length });
    title.textContent = step.title;
    text.textContent = step.text;
    back.hidden = index === 0;
    next.textContent = index === steps.length - 1 ? 'Fertig' : 'Weiter';
    const target = step.target ? find(step.target) : null;
    if (follow && watched !== target) {
      if (watched) follow.unobserve(watched);
      if (target) follow.observe(target);
      watched = target;
    }
    place();
    next.focus({ preventScroll: true });
  }

  function close(finished) {
    if (running !== close) return;
    running = null;
    remember(name);                    // skipped or finished: it does not come back on its own
    document.removeEventListener('keydown', key, true);
    window.removeEventListener('resize', place);
    window.removeEventListener('gt7:stage', place);
    if (follow) follow.disconnect();
    root.remove();
    document.body.classList.remove('tour-open');
    if (before && before.focus && document.contains(before)) before.focus({ preventScroll: true });
    window.dispatchEvent(new CustomEvent('gt7:tour', { detail: { name: name, open: false, finished: !!finished } }));
  }

  function go(by) {
    const index = current + by;
    if (index < 0) return;
    if (index >= steps.length) close(true); else show(index);
  }

  /* The keys belong to the tour while it is open: the page behind must not move widgets with them. */
  function key(event) {
    event.stopPropagation();
    if (event.metaKey || event.ctrlKey || event.altKey) return;      // the browser's own shortcuts stay
    if (event.key === 'Escape') close(false);
    else if (event.key === 'ArrowRight') go(1);
    else if (event.key === 'ArrowLeft') go(-1);
    else if (event.key === 'Tab') {
      const buttons = [skip, back, next].filter(button => !button.hidden);
      const at = buttons.indexOf(document.activeElement);
      buttons[(at + (event.shiftKey ? buttons.length - 1 : 1) + buttons.length) % buttons.length].focus();
    } else {
      return;                          // Enter and Space press the button that has the focus
    }
    event.preventDefault();
  }

  shade.addEventListener('pointerdown', event => event.preventDefault());     // the focus stays in the bubble
  skip.addEventListener('click', () => close(false));
  back.addEventListener('click', () => go(-1));
  next.addEventListener('click', () => go(1));
  document.addEventListener('keydown', key, true);
  window.addEventListener('resize', place);
  window.addEventListener('gt7:stage', place);
  if (follow) follow.observe(bubble);

  running = close;
  document.body.classList.add('tour-open');
  document.body.append(root);
  window.dispatchEvent(new CustomEvent('gt7:tour', { detail: { name: name, open: true } }));
  show(0);
  return true;
}
