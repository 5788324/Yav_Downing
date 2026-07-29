export function reconcileScanStates(previous, scans) {
  const next = { ...previous };
  const stoppedSources = [];
  for (const [source, scan] of Object.entries(scans)) {
    const active = scan.status === 'running' || scan.status === 'stopping';
    if (previous[source] && !active) stoppedSources.push(source);
    next[source] = active;
  }
  return {
    next,
    stoppedSources,
    refreshLibrary: Object.values(next).some(Boolean) || stoppedSources.length > 0,
  };
}