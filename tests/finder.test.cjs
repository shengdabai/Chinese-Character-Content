const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function element(dataset = {}) {
  const classes = new Set();
  const events = new Map();
  return {
    dataset, value: '', textContent: '', style: {}, open: true,
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
    },
    addEventListener: (name, handler) => events.set(name, handler),
    fire: (name) => events.get(name)?.(),
  };
}

function finder(script) {
  const rows = [
    element({rank: '1', search: '我 wo i', category: 'People'}),
    element({rank: '200', search: '工作 gong zuo work', category: 'Work'}),
    element({rank: '', search: 'rare', category: 'Work'}),
  ];
  const buttons = ['all', '100', '300'].map((rank) => element({rank}));
  buttons[0].classList.add('active');
  const controls = {finderSearch: element(), categoryFilter: element(), visibleCount: element()};
  controls.categoryFilter.value = 'all';
  const sections = rows.map((row) => ({
    style: {}, open: true,
    querySelector: () => row.classList.contains('hidden') ? null : row,
  }));
  const document = {
    getElementById: (id) => controls[id],
    querySelectorAll: (selector) => {
      switch (selector) {
        case '.char-row': return rows;
        case '.finder-section': return sections;
        case '[data-rank]': return [...buttons, ...rows];
        case '.filters button[data-rank]': return buttons;
        default: throw new Error(`Unexpected selector: ${selector}`);
      }
    },
  };
  vm.runInNewContext(script, {document});
  return {rows, buttons, controls, sections};
}

const root = path.join(__dirname, '..');
for (const [name, filename] of [
  ['published page', 'docs/common-3500.html'],
  ['generator', 'scripts/build_materials.py'],
]) {
  const source = fs.readFileSync(path.join(root, filename), 'utf8');
  let script = source.match(/<script>([\s\S]*?)<\/script>/)[1];
  if (name === 'generator') script = script.replace(/\{\{/g, '{').replace(/\}\}/g, '}');

  test(`${name}: clicking a character does not change the frequency filter`, () => {
    const {rows, buttons, controls} = finder(script);
    buttons[2].fire('click');
    assert.equal(controls.visibleCount.textContent, '2');
    rows[0].fire('click');
    assert.equal(controls.visibleCount.textContent, '2');
    assert.equal(buttons[2].classList.contains('active'), true);
    assert.equal(rows[0].classList.contains('active'), false);
  });

  test(`${name}: rank, search, category and reset compose correctly`, () => {
    const {rows, buttons, controls, sections} = finder(script);
    buttons[1].fire('click');
    assert.equal(controls.visibleCount.textContent, '1');
    assert.equal(rows[2].classList.contains('hidden'), true);
    controls.finderSearch.value = '  WORK  ';
    controls.finderSearch.fire('input');
    assert.equal(controls.visibleCount.textContent, '0');
    buttons[2].fire('click');
    assert.equal(controls.visibleCount.textContent, '1');
    controls.categoryFilter.value = 'People';
    controls.categoryFilter.fire('change');
    assert.equal(controls.visibleCount.textContent, '0');
    controls.finderSearch.value = '';
    controls.categoryFilter.value = 'all';
    buttons[0].fire('click');
    assert.equal(controls.visibleCount.textContent, '3');
    assert.equal(sections.every((section) => section.style.display === ''), true);
  });
}
