/* Which layout fits this screen? No DOM in here, so it can be tested on its own.

     layouts  what the program offers: [{ name, kind, width, height }, …]
     screen   { width, height } of the window
     wanted   "dashboard" for a screen of its own, "overlay" for a stream source
*/
export function pickLayout(layouts, screen, wanted) {
  const candidates = layouts.filter(layout => layout.kind === wanted);
  const pool = candidates.length ? candidates : layouts;
  if (!pool.length) return '';
  const shape = Math.log(Math.max(1, screen.width) / Math.max(1, screen.height));
  let best = pool[0], bestDistance = Infinity;
  for (const layout of pool) {
    /* Distance of the shapes, as a ratio: 16:10 is as far from 16:9 as 16:9 is from 16:8.1. */
    const distance = Math.abs(Math.log(layout.width / layout.height) - shape);
    /* A preset wins a tie; among presets the order of the list decides. */
    if (distance < bestDistance - 1e-9) { best = layout; bestDistance = distance; }
  }
  return best.name;
}
