export function reconcileScanStates(previous, scans) {
  const next = { ...previous };
  const stoppedSources = [];
  for (const [source, scan] of Object.entries(scans)) {
    const active = new Set(['starting', 'running', 'stopping']).has(scan.status);
    if (previous[source] && !active) stoppedSources.push(source);
    next[source] = active;
  }
  return {
    next,
    stoppedSources,
    refreshLibrary: Object.values(next).some(Boolean) || stoppedSources.length > 0,
  };
}