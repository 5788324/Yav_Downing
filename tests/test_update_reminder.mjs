import assert from 'node:assert/strict';
import test from 'node:test';
import { monthlyUpdateReminder } from '../backend/static/update-reminder.js';
test('月末按下一月最后一天计算，未到期不提醒', () => {
 const item={enabled:1,last_scanned_at:'2026-01-31T10:00:00+08:00'};
 assert.equal(monthlyUpdateReminder(item,new Date('2026-02-28T09:59:00+08:00')), '');
 assert.match(monthlyUpdateReminder(item,new Date('2026-02-28T10:00:00+08:00')), /已超过一个月/);
});
test('停用不提醒，未扫描和无效日期提供提示', () => {
 assert.equal(monthlyUpdateReminder({enabled:0}), '');
 assert.match(monthlyUpdateReminder({enabled:1}), /尚未更新/);
 assert.match(monthlyUpdateReminder({enabled:1,last_scanned_at:'bad'}), /未知/);
});
