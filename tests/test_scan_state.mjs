import assert from 'node:assert/strict';
import test from 'node:test';
import { reconcileScanStates } from '../backend/static/scan-state.js';

test('JavDB 停止但 JPHOO 继续时仍刷新 JavDB 卡片', () => {
  const result = reconcileScanStates(
    { javdb: true, jphoo: true },
    { javdb: { status: 'stopped' }, jphoo: { status: 'running' } },
  );
  assert.deepEqual(result.next, { javdb: false, jphoo: true });
  assert.deepEqual(result.stoppedSources, ['javdb']);
  assert.equal(result.refreshLibrary, true);
});

test('两个来源都空闲时不持续刷新', () => {
  const result = reconcileScanStates(
    { javdb: false, jphoo: false },
    { javdb: { status: 'idle' }, jphoo: { status: 'completed' } },
  );
  assert.deepEqual(result.stoppedSources, []);
  assert.equal(result.refreshLibrary, false);
});