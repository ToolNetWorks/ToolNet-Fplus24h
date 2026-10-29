/* Runtime tests for pure dashboard aggregation + read-only tenant API contract.
 * Uses the project's installed TypeScript; does not need Jest or Facebook.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.resolve(__dirname, '..');
const ts = require(require.resolve('typescript', { paths: [process.cwd(), root] }));
const file = path.join(process.cwd(), 'src/features/ctv/api/dashboard.ts');
const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exp = {};
const requests = [];
let payload;
const context = {
  exports: exp,
  fetch: async (url, opts) => {
    requests.push({ url, opts });
    return { ok: true, status: 200, json: async () => payload };
  },
  encodeURIComponent,
};
vm.runInNewContext(code, context);
const ticks = {
  pipeline_id: 'p1', schedule_count: 2, active_schedule_count: 2,
  due_schedule_count: 1,
  schedules: [
    { schedule_id: 'a', name: 'Morning', enabled: true, due: false,
      next_run_at: '2026-10-30T01:00:00Z', last_batch: null,
      last_tick: { outcome: 'queued', updated_at: '2026-10-29T01:00:00Z', assigned_count: 10, skipped_count: 2 } },
    { schedule_id: 'b', name: 'Evening', enabled: true, due: true,
      next_run_at: '2026-10-29T02:00:00Z', last_batch: null,
      last_tick: { outcome: 'error', updated_at: '2026-10-29T02:00:00Z', assigned_count: 0, skipped_count: 0 } },
  ],
};
const jobs = { summary: { total: 20, queued: 16, ready: 1, uncertain: 2, published: 1, failed: 0 } };
const one = exp.dashboardMetrics(ticks, jobs);
if (one.scheduledTotal !== 2 || one.due !== 1 || one.latestSkipped !== 2 || one.tickErrors !== 1 || one.queued !== 16 || one.latestTick.schedule_id !== 'b') throw Error('Mismatch in metrics');
const missing = exp.dashboardMetrics(null, jobs);
if (missing.due !== null || missing.tickErrors !== null || missing.queued !== 16) throw Error('Missing source incorrectly treated as zero');
const missingJobs = exp.dashboardMetrics(ticks, null);
if (missingJobs.queued !== null || missingJobs.latestSkipped !== 2) throw Error('Missing job data incorrectly treated as zero');
console.log('DASHBOARD METRICS + PARTIAL FAILURE: PASS');

(async () => {
  payload = { success: true, data: ticks };
  const result = await exp.getSchedulerTickStatus('p1');
  if (result.schedule_count !== 2 || requests[0].opts.method !== 'GET' || requests[0].opts.credentials !== 'same-origin' || !requests[0].url.endsWith('scheduler-ticks/status/')) throw Error('Tick read-only API contract');
  console.log('SCOPED TICK STATUS GET: PASS');
  payload = { success: true, data: { ...ticks, pipeline_id: 'foreign' } };
  try { await exp.getSchedulerTickStatus('p1'); throw Error('foreign accepted'); }
  catch (error) { if (String(error).includes('foreign accepted')) throw error; }
  console.log('CROSS-PIPELINE STATUS REJECTED: PASS');
  payload = { success: true, data: { pipeline: { id: 'p1' }, stats: { facebook_accounts: 10, connected_accounts: 8 } } };
  const accountStats = await exp.getWorkspaceAccountStats('p1');
  if (accountStats.connected_accounts !== 8) throw Error('Incorrect accounts');
  console.log('WORKSPACE COUNTERS REFRESH: PASS');
  payload = { success: true, data: { pipeline: { id: 'foreign' }, stats: { facebook_accounts: 999, connected_accounts: 999 } } };
  try { await exp.getWorkspaceAccountStats('p1'); throw Error('foreign workspace accepted'); }
  catch (error) { if (String(error).includes('foreign workspace accepted')) throw error; }
  console.log('FOREIGN WORKSPACE REJECTED: PASS');
  if (requests.some(req => req.opts.method !== 'GET')) throw Error('Unexpected write request');
  console.log('ALL REQUESTS READ ONLY: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
