// 仅使用 SQLite 返回的扫描日期计算提醒，不保存另一份更新状态。
export function monthlyUpdateReminder(item, now = new Date()) {
  if (!item.enabled) return '';
  if (!item.last_scanned_at) return '尚未更新，建议首次扫描';
  const last = new Date(item.last_scanned_at);
  if (Number.isNaN(last.getTime())) return '更新时间未知，建议检查';
  const next = new Date(last);
  const day = next.getDate();
  next.setDate(1);
  next.setMonth(next.getMonth() + 1);
  const end = new Date(next.getFullYear(), next.getMonth() + 1, 0).getDate();
  next.setDate(Math.min(day, end));
  return now >= next ? '已超过一个月，建议从第 1 页更新资料和磁链' : '';
}

export function updateReminderLine(item, now = new Date()) {
  if (!item.enabled) return '每月更新提醒：已停用';
  const warning = monthlyUpdateReminder(item, now);
  if (warning) return `每月更新提醒：${warning}`;
  const last = new Date(item.last_scanned_at);
  const next = new Date(last);
  const day = next.getDate();
  next.setDate(1);
  next.setMonth(next.getMonth() + 1);
  next.setDate(Math.min(day, new Date(next.getFullYear(), next.getMonth() + 1, 0).getDate()));
  const date = `${next.getFullYear()}-${String(next.getMonth()+1).padStart(2,'0')}-${String(next.getDate()).padStart(2,'0')}`;
  return `每月更新提醒：下次建议更新 ${date}`;
}
