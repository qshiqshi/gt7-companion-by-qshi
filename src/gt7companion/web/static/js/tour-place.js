/* Where a speech bubble goes: beside its target, on a side with room for it, never outside
   the screen. No DOM in here, so it can be tested on its own.

     target   { left, top, width, height }  what the bubble points at, in screen pixels; null: nothing
     bubble   { width, height }             the bubble itself
     view     { width, height }             the screen
     options  { gap, margin, prefer }       distance to the target and to the screen edge; the side tried first

   Returns { side, left, top, tail }: the side of the target the bubble sits on ("none" without a
   target: centred), its corner, and how far along its edge the tail points at the target.
*/
const SIDES = ['bottom', 'top', 'right', 'left'];
const TAIL_INSET = 22;                 // the tail keeps this far from the bubble's corners

export function placeBubble(target, bubble, view, options) {
  const gap = options && options.gap !== undefined ? options.gap : 14;
  const margin = options && options.margin !== undefined ? options.margin : 12;
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const maxLeft = Math.max(margin, view.width - bubble.width - margin);
  const maxTop = Math.max(margin, view.height - bubble.height - margin);
  if (!target) {
    return { side: 'none', left: clamp((view.width - bubble.width) / 2, margin, maxLeft),
             top: clamp((view.height - bubble.height) / 2, margin, maxTop), tail: 0 };
  }
  /* What is left over on each side once the bubble is there. */
  const spare = {
    bottom: view.height - (target.top + target.height) - gap - margin - bubble.height,
    top: target.top - gap - margin - bubble.height,
    right: view.width - (target.left + target.width) - gap - margin - bubble.width,
    left: target.left - gap - margin - bubble.width,
  };
  const prefer = options && options.prefer;
  const order = SIDES.includes(prefer) ? [prefer, ...SIDES.filter(name => name !== prefer)] : SIDES;
  /* The first side it fits on; if it fits nowhere, the side where the least is missing. */
  const side = order.find(name => spare[name] >= 0)
    || order.reduce((best, name) => (spare[name] > spare[best] ? name : best));
  const centreX = target.left + target.width / 2;
  const centreY = target.top + target.height / 2;
  if (side === 'bottom' || side === 'top') {
    const left = clamp(centreX - bubble.width / 2, margin, maxLeft);
    const top = clamp(side === 'bottom' ? target.top + target.height + gap : target.top - gap - bubble.height,
                      margin, maxTop);
    return { side, left, top, tail: clamp(centreX - left, TAIL_INSET, Math.max(TAIL_INSET, bubble.width - TAIL_INSET)) };
  }
  const top = clamp(centreY - bubble.height / 2, margin, maxTop);
  const left = clamp(side === 'right' ? target.left + target.width + gap : target.left - gap - bubble.width,
                     margin, maxLeft);
  return { side, left, top, tail: clamp(centreY - top, TAIL_INSET, Math.max(TAIL_INSET, bubble.height - TAIL_INSET)) };
}
