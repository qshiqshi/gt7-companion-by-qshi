// Löst in Node die nackten Namen `three` und `three/addons/…` so auf wie die Import-Map im Browser
// (kein Test – der Name endet nicht auf .test.mjs). Einbinden: register('./_three-hooks.mjs', import.meta.url)

const root = new URL('../../src/gt7companion/web/static/vendor/three/', import.meta.url);

export function resolve(specifier, context, nextResolve) {
  if (specifier === 'three') {
    return { url: new URL('build/three.module.js', root).href, shortCircuit: true };
  }
  if (specifier.startsWith('three/addons/')) {
    return { url: new URL(`examples/jsm/${specifier.slice('three/addons/'.length)}`, root).href, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
