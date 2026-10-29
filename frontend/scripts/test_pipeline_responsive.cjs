// Test script for ToolNet Fplus24h Pipeline UI at 375px, 768px, 1024px, and 1440px
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');

const SESSION_COOKIE = 'evfcwhl4nkenfgjo8m24hwdkh1y7rx3i';
const BASE_URL = 'http://127.0.0.1:3000';

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

class CDPClient {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.id = 1;
    this.callbacks = new Map();
    this.ready = new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });
    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.callbacks.has(msg.id)) {
        const { resolve, reject } = this.callbacks.get(msg.id);
        this.callbacks.delete(msg.id);
        if (msg.error) {
          reject(new Error(msg.error.message || JSON.stringify(msg.error)));
        } else {
          resolve(msg.result);
        }
      }
    };
  }

  send(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      const id = this.id++;
      this.callbacks.set(id, { resolve, reject });
      const payload = { id, method, params };
      if (sessionId) payload.sessionId = sessionId;
      this.ws.send(JSON.stringify(payload));
    });
  }

  close() {
    this.ws.close();
  }
}

async function startChrome() {
  const profileDir = `/tmp/chrome-test-${Date.now()}`;
  const proc = spawn('/snap/bin/chromium', [
    '--headless',
    '--no-sandbox',
    '--disable-gpu',
    '--remote-debugging-port=9222',
    `--user-data-dir=${profileDir}`,
  ]);

  for (let i = 0; i < 20; i++) {
    await sleep(500);
    try {
      const res = await fetch('http://127.0.0.1:9222/json/version');
      if (res.ok) {
        const data = await res.json();
        return { proc, wsUrl: data.webSocketDebuggerUrl };
      }
    } catch {
      // Keep waiting
    }
  }
  proc.kill('SIGKILL');
  throw new Error('Chromium did not start within timeout');
}

async function run() {
  console.log('--- STARTING CHROMIUM CDP CLIENT ---');
  const { proc, wsUrl } = await startChrome();

  try {
    const client = new CDPClient(wsUrl);
    await client.ready;

    // Create a target
    const { targetId } = await client.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await client.send('Target.attachToTarget', { targetId, flatten: true });

    // Enable domains
    await client.send('Page.enable', {}, sessionId);
    await client.send('Network.enable', {}, sessionId);
    await client.send('Runtime.enable', {}, sessionId);

    // Set authentication session cookie
    await client.send('Network.setCookie', {
      name: 'sessionid',
      value: SESSION_COOKIE,
      domain: '127.0.0.1',
      path: '/',
      httpOnly: true,
      secure: false,
    }, sessionId);

    async function evalScript(expression) {
      const res = await client.send('Runtime.evaluate', {
        expression,
        returnByValue: true,
        awaitPromise: true,
      }, sessionId);
      return res.result?.value;
    }

    const viewports = [
      { width: 375, height: 667, name: '375px (Mobile)' },
      { width: 768, height: 1024, name: '768px (Tablet)' },
      { width: 1024, height: 768, name: '1024px (Small Desktop)' },
      { width: 1440, height: 900, name: '1440px (Wide Desktop)' },
    ];

    for (const vp of viewports) {
      console.log(`\n=== TESTING VIEWPORT: ${vp.name} (${vp.width}x${vp.height}) ===`);

      // Set viewport
      await client.send('Emulation.setDeviceMetricsOverride', {
        width: vp.width,
        height: vp.height,
        deviceScaleFactor: 1,
        mobile: vp.width < 768,
      }, sessionId);

      // Navigate
      await client.send('Page.navigate', { url: `${BASE_URL}/pipelines/` }, sessionId);

      // Wait for page load and items to render
      let loaded = false;
      for (let i = 0; i < 20; i++) {
        await sleep(500);
        const count = await evalScript(`document.querySelectorAll('tbody tr, article').length`);
        if (count > 0) {
          loaded = true;
          break;
        }
      }
      assert.ok(loaded, `Pipeline list items did not load at ${vp.width}px`);

      if (vp.width === 375) {
        // MOBILE SPECIFIC CHECKS
        const mobileChecks = await evalScript(`(() => {
          const tableContainer = document.querySelector('.hidden.overflow-x-auto.md\\\\:block');
          const table = document.querySelector('table');
          const cards = document.querySelectorAll('article');
          const docScrollWidth = document.documentElement.scrollWidth;

          return {
            tableHidden: !table || table.offsetParent === null,
            cardsCount: cards.length,
            docScrollWidth,
            hasHorizontalOverflow: docScrollWidth > 375,
          };
        })()`);

        console.log('Mobile layout state:', mobileChecks);
        assert.ok(mobileChecks.tableHidden, 'Table must be hidden on 375px mobile');
        assert.ok(mobileChecks.cardsCount > 0, 'Cards must be visible on 375px mobile');
        assert.ok(!mobileChecks.hasHorizontalOverflow, `Horizontal scroll detected on 375px! scrollWidth=${mobileChecks.docScrollWidth}`);

        // Click "Thao tác" button on first card
        const menuOpened = await evalScript(`(() => {
          const firstCard = document.querySelector('article');
          const buttons = Array.from(firstCard.querySelectorAll('button'));
          const actionBtn = buttons.find(b => b.textContent.includes('Thao tác'));
          if (!actionBtn) return { error: 'Thao tác button not found' };
          actionBtn.click();
          return { clicked: true };
        })()`);
        assert.ok(menuOpened.clicked, 'Failed to click Thao tác button on mobile');

        await sleep(300);

        // Verify dropdown menu
        const menuDetails = await evalScript(`(() => {
          const menu = document.querySelector('[role="menu"]');
          if (!menu) return null;
          const rect = menu.getBoundingClientRect();
          const items = Array.from(menu.querySelectorAll('[role="menuitem"]')).map(el => el.textContent.trim());
          return {
            visible: true,
            top: rect.top,
            left: rect.left,
            right: rect.right,
            bottom: rect.bottom,
            width: rect.width,
            insideViewport: rect.left >= 0 && rect.right <= 375,
            items,
          };
        })()`);

        console.log('Mobile menu state:', menuDetails);
        assert.ok(menuDetails, 'Dropdown menu did not open on mobile');
        assert.ok(menuDetails.insideViewport, 'Dropdown menu overflows 375px screen');
        assert.ok(menuDetails.items.some(t => t.includes('Khóa Pipeline') || t.includes('Mở khóa Pipeline')), 'Missing Khóa/Mở khóa');
        assert.ok(menuDetails.items.some(t => t.includes('Đổi mật khẩu CTV')), 'Missing Đổi mật khẩu');
        assert.ok(menuDetails.items.some(t => t.includes('Facebook Accounts')), 'Missing Facebook Accounts');
        assert.ok(menuDetails.items.some(t => t.includes('Facebook Groups')), 'Missing Facebook Groups');
        assert.ok(menuDetails.items.some(t => t.includes('Album Library')), 'Missing Album Library');
        assert.ok(menuDetails.items.some(t => t.includes('Xóa Pipeline')), 'Missing Xóa Pipeline');

        console.log('✓ 375px Mobile: Card layout, no horizontal scroll, dropdown within bounds PASS');
      } else {
        // TABLET & DESKTOP CHECKS
        const desktopChecks = await evalScript(`(() => {
          const table = document.querySelector('table');
          const cards = document.querySelectorAll('article');
          const firstRow = document.querySelector('tbody tr');
          const rowHeight = firstRow ? firstRow.getBoundingClientRect().height : 0;
          const buttonsInRow = firstRow ? Array.from(firstRow.querySelectorAll('button')).filter(b => b.offsetParent !== null).map(b => b.textContent.trim()) : [];

          return {
            tableVisible: !!table && table.offsetParent !== null,
            cardsHidden: cards.length === 0 || cards[0].offsetParent === null,
            rowHeight,
            buttonsInRow,
          };
        })()`);

        console.log(`${vp.name} state:`, desktopChecks);
        assert.ok(desktopChecks.tableVisible, `Table must be visible on ${vp.name}`);
        assert.ok(desktopChecks.cardsHidden, `Cards must be hidden on ${vp.name}`);
        assert.ok(desktopChecks.rowHeight < 75 && desktopChecks.rowHeight >= 45, `Row height (${desktopChecks.rowHeight}px) not in expected range 45-75px`);
        assert.ok(desktopChecks.buttonsInRow.some(t => t.includes('Chỉnh sửa')), 'Row must have Chỉnh sửa button');
        assert.ok(desktopChecks.buttonsInRow.some(t => t.includes('Thao tác')), 'Row must have Thao tác button');
        assert.strictEqual(desktopChecks.buttonsInRow.length, 2, 'Row must only have 2 visible buttons');

        // Click "Thao tác" button on row
        const rowClick = await evalScript(`(() => {
          const firstRow = document.querySelector('tbody tr');
          const buttons = Array.from(firstRow.querySelectorAll('button'));
          const actionBtn = buttons.find(b => b.textContent.includes('Thao tác'));
          if (!actionBtn) return { error: 'Action button not found' };
          actionBtn.click();
          return { clicked: true };
        })()`);
        assert.ok(rowClick.clicked, 'Failed to click Thao tác button');

        await sleep(300);

        // Verify dropdown menu
        const menuDetails = await evalScript(`(() => {
          const menu = document.querySelector('[role="menu"]');
          if (!menu) return null;
          const rect = menu.getBoundingClientRect();
          const items = Array.from(menu.querySelectorAll('[role="menuitem"]')).map(el => el.textContent.trim());
          return {
            visible: true,
            top: rect.top,
            left: rect.left,
            right: rect.right,
            bottom: rect.bottom,
            width: rect.width,
            insideViewport: rect.left >= 0 && rect.right <= window.innerWidth && rect.bottom <= window.innerHeight,
            items,
          };
        })()`);

        console.log(`${vp.name} menu state:`, menuDetails);
        assert.ok(menuDetails, 'Dropdown menu did not open on row click');
        assert.ok(menuDetails.insideViewport, 'Dropdown menu is clipped outside viewport');
        assert.strictEqual(menuDetails.items.length, 6, 'Menu must contain exactly 6 items');

        console.log(`✓ ${vp.name}: Table layout, compact row height (${desktopChecks.rowHeight}px), 2 buttons, dropdown PASS`);
      }
    }

    client.close();
    console.log('\n=============================================');
    console.log('ALL RESPONSIVE VIEWPORT TESTS PASSED: 375px, 768px, 1024px, 1440px');
    console.log('=============================================');
  } finally {
    proc.kill('SIGKILL');
  }
}

run().catch((err) => {
  console.error('\nTEST SUITE FAILED:', err);
  process.exit(1);
});
