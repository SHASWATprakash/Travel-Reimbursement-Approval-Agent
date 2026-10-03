import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Route, Routes, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownToLine, ArrowLeft, ArrowRight, ArrowUpRight, BookOpen, Check, CheckCircle2, ChevronDown,
  CircleDollarSign, Clock3, FileCheck2, FileText, Layers3, LayoutDashboard, LoaderCircle, Plane,
  Play, Search, ShieldCheck, Sparkles, TriangleAlert, XCircle } from 'lucide-react'
import { api, downloadResults } from './api'
import type { Decision, Evaluation, Mode, Policies } from './api'

const money = (value: number) => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(value)
const date = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'})
const labels: Record<Decision, string> = {APPROVE: 'Approved', PARTIAL_APPROVE: 'Partial approval', REJECT: 'Rejected', MANUAL_REVIEW: 'Manual review'}
const codes: Decision[] = ['APPROVE', 'PARTIAL_APPROVE', 'REJECT', 'MANUAL_REVIEW']
const sourceLabel = (mode: string) => mode.startsWith('rules') ? 'Rules' : mode.startsWith('live') ? 'Live' : 'Replay'
const category = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase())
const sums = (items: Evaluation[]) => items.reduce((total, item) => ({
  approved: total.approved + Math.round(item.result.approved_amount * 100),
  deducted: total.deducted + Math.round(item.result.deducted_amount * 100),
  pending: total.pending + Math.round(item.audit.pending_amount * 100),
  claimed: total.claimed + Math.round(item.claim.total_claimed * 100),
}), {approved: 0, deducted: 0, pending: 0, claimed: 0})

function Status({decision}: {decision: Decision}) {
  const Icon = decision === 'APPROVE' ? CheckCircle2 : decision === 'REJECT' ? XCircle : decision === 'MANUAL_REVIEW' ? Clock3 : FileCheck2
  return <span className={`status ${decision.toLowerCase()}`}><Icon size={13} />{labels[decision]}</span>
}
function Source({item}: {item: Evaluation}) {
  return <span className={`source ${item.audit.mode.endsWith('failed') ? 'source-failed' : ''}`}>{sourceLabel(item.audit.mode)}{item.audit.mode.endsWith('failed') ? ' · failed' : ''}</span>
}
function Empty({title, text}: {title: string; text: string}) {
  return <div className="empty"><FileText size={28} /><h3>{title}</h3><p>{text}</p></div>
}
function Metric({label, value, hint, kind = '', icon}: {label: string; value: string; hint: string; kind?: string; icon: React.ReactNode}) {
  return <div className={`metric ${kind}`}><div className="metric-top"><span>{label}</span><span className="metric-icon">{icon}</span></div><strong>{value}</strong><small>{hint}</small></div>
}
function References({refs, policies}: {refs: string[]; policies?: Policies}) {
  return <div className="references">{refs.map(ref => <details key={ref}><summary><BookOpen size={13} />{ref}<ChevronDown size={13} /></summary><p>{policies?.rules[ref] ?? 'Policy text is loading.'}</p></details>)}</div>
}

function ClaimTable({items, title = 'All claims'}: {items: Evaluation[]; title?: string}) {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('ALL')
  const visible = items.filter(item => (filter === 'ALL' || item.result.decision === filter)
    && `${item.claim.claim_id} ${item.claim.employee} ${item.claim.purpose}`.toLowerCase().includes(search.toLowerCase()))
  return <section className="panel claims-panel"><div className="panel-heading"><div><h2>{title}<span className="count">{items.length}</span></h2><p>Policy-grounded recommendations for the synthetic claims.</p></div><button className="button subtle" onClick={() => downloadResults(items.map(i => i.result))}><ArrowDownToLine size={15} />Export JSON</button></div>
    <div className="table-tools"><label className="search"><Search size={16} /><input aria-label="Search claims" placeholder="Search by claim or employee…" value={search} onChange={e => setSearch(e.target.value)} /></label><label className="filter"><span className="sr-only">Filter by decision</span><select aria-label="Filter by decision" value={filter} onChange={e => setFilter(e.target.value)}><option value="ALL">All decisions</option>{codes.map(code => <option key={code} value={code}>{labels[code]}</option>)}</select></label></div>
    {visible.length ? <div className="table-scroll"><table><thead><tr><th>Claim / employee</th><th>Business purpose</th><th className="numeric">Claimed</th><th>Decision</th><th>Source</th><th><span className="sr-only">Open claim</span></th></tr></thead><tbody>{visible.map(item => <tr key={item.claim.claim_id}><td><Link className="claim-link" to={`/claims/${item.claim.claim_id}`}>{item.claim.claim_id}</Link><span className="secondary">{item.claim.employee}</span></td><td className="purpose-cell"><span>{item.claim.purpose}</span><span className="secondary">{date(item.claim.trip_start)} · {item.claim.items.length} line items</span></td><td className="numeric amount">{money(item.claim.total_claimed)}</td><td><Status decision={item.result.decision} /></td><td><Source item={item} /></td><td><Link className="icon-button" aria-label={`Open ${item.claim.claim_id}`} to={`/claims/${item.claim.claim_id}`}><ArrowUpRight size={17} /></Link></td></tr>)}</tbody></table></div> : <Empty title="No matching claims" text="Try another search or decision filter." />}
    <div className="table-footer">Showing {visible.length} of {items.length} claims<span>USD · Mock assignment data</span></div>
  </section>
}

function Overview({items}: {items: Evaluation[]}) {
  const total = sums(items)
  const reviews = items.filter(i => i.result.decision === 'MANUAL_REVIEW')
  const tools = items.reduce((n, i) => n + i.audit.events.length, 0)
  return <><div className="page-heading"><div className="eyebrow">REIMBURSEMENT WORKSPACE</div><h1>A clearer view of every claim.</h1><p>Review decisions, understand deductions, and follow the evidence.</p></div>
    <div className="metric-grid"><Metric label="Approved amount" value={money(total.approved / 100)} hint="Validated reimbursement recommendations" kind="green" icon={<CheckCircle2 size={18} />} /><Metric label="Policy deductions" value={money(total.deducted / 100)} hint="Ineligible items and amounts over caps" icon={<CircleDollarSign size={18} />} /><Metric label="Pending review" value={money(total.pending / 100)} hint={`${reviews.length} claims awaiting clarification`} kind="amber" icon={<Clock3 size={18} />} /><Metric label="Total claims" value={String(items.length).padStart(2, '0')} hint={`${money(total.claimed / 100)} submitted · synthetic scenarios`} icon={<FileText size={18} />} /></div>
    <div className="overview-band"><section className="panel distribution"><div className="panel-heading compact"><h2>Decision breakdown</h2><span className="muted">{items.length} claims</span></div><div className="decision-bar" aria-label="Decision distribution">{codes.map(code => {const count = items.filter(i => i.result.decision === code).length; return count > 0 && <span key={code} className={code.toLowerCase()} style={{flex: count}} title={`${labels[code]}: ${count}`} />})}</div><div className="legend">{codes.map(code => <div key={code}><i className={code.toLowerCase()} /><span>{labels[code]}</span><strong>{items.filter(i => i.result.decision === code).length}</strong></div>)}</div></section>
    <section className="review-callout"><div className="callout-icon"><ShieldCheck size={23} /></div><div><span className="eyebrow">HUMAN JUDGEMENT, WHEN IT MATTERS</span><h2>{reviews.length ? `${reviews.length} claims need a closer look` : 'No claims awaiting review'}</h2><p>Missing receipts and policy exceptions remain fully pending.</p><Link to="/review">Open review queue <ArrowRight size={15} /></Link></div></section></div>
    <ClaimTable items={items} /><div className="assurance"><ShieldCheck size={16} /><span>Grounded in 12 policy rules</span><i /><span>{tools} recorded tool executions</span><i /><span>Amounts independently validated</span><Link to="/audit">Inspect evidence <ArrowRight size={14} /></Link></div>
  </>
}

function ClaimDetail({items, policies, busy, evaluate}: {items: Evaluation[]; policies?: Policies; busy: boolean; evaluate: (ids?: string[]) => void}) {
  const {id} = useParams()
  const item = items.find(i => i.claim.claim_id === id)
  if (!item) return <Empty title="Claim not found" text="Choose a claim from the overview." />
  const {claim, result, audit} = item
  const review = result.decision === 'MANUAL_REVIEW'
  return <><Link to="/" className="back-link"><ArrowLeft size={15} />Back to overview</Link><div className="detail-heading"><div><div className="eyebrow">CLAIM DETAIL</div><h1>{claim.claim_id}<Status decision={result.decision} /></h1><p>{claim.employee} <span className="separator">/</span> {claim.purpose}</p></div><div className="button-row"><button className="button subtle" onClick={() => downloadResults([result], `${claim.claim_id}.json`)}><ArrowDownToLine size={15} />Export JSON</button><button className="button primary" disabled={busy} onClick={() => evaluate([claim.claim_id])}><Play size={14} />Evaluate claim</button></div></div>
    <div className="detail-metrics"><Metric label="Approved" value={money(result.approved_amount)} hint="Posted recommendation" kind="green" icon={<CheckCircle2 size={18} />} /><Metric label="Deducted" value={money(result.deducted_amount)} hint="Posted policy deductions" icon={<CircleDollarSign size={18} />} /><Metric label="Pending" value={money(audit.pending_amount)} hint={review ? 'Entire claim held for review' : 'No amount awaiting review'} kind="amber" icon={<Clock3 size={18} />} /></div>
    {review && <div className="notice amber-notice"><TriangleAlert size={18} /><div><strong>Manual review holds the full claim.</strong><p>Line-item calculations below are provisional. They do not post an approval or deduction.</p></div></div>}
    <div className="detail-grid"><div><section className="panel"><div className="panel-heading"><div><h2>Expense breakdown</h2><p>{claim.items.length} line items · {money(claim.total_claimed)} claimed</p></div></div><div className="table-scroll"><table><thead><tr><th>Expense</th><th>Receipt</th><th className="numeric">Claimed</th><th className="numeric">{review ? 'Provisional allowed' : 'Allowed'}</th><th className="numeric">{review ? 'Provisional excess' : 'Deduction'}</th></tr></thead><tbody>{claim.items.map(expense => {const line = audit.lines.find(l => l.item_id === expense.item_id); return <tr key={expense.item_id}><td><strong className="expense-title">{category(expense.category)}</strong><span className="secondary">{expense.description}</span>{line?.policy_refs.map(ref => <Link className="inline-ref" key={ref} to={`/audit?claim=${claim.claim_id}#${ref}`}>{ref}</Link>)}</td><td><span className={`receipt ${expense.receipt_attached && expense.receipt_itemized ? 'present' : 'missing'}`}>{expense.receipt_attached && expense.receipt_itemized ? <Check size={13} /> : <TriangleAlert size={13} />}{expense.receipt_attached ? expense.receipt_itemized ? 'Attached' : 'Not itemized' : 'Missing'}</span></td><td className="numeric">{money(expense.amount)}</td><td className="numeric">{line ? money(line.provisional_allowed) : '—'}</td><td className="numeric">{line ? money(line.provisional_deducted) : '—'}</td></tr>})}</tbody></table></div></section>
    <section className="panel reasoning"><div className="panel-heading"><div><h2><Sparkles size={17} />Decision & reasoning</h2><p>Each finding connects the recommendation to policy.</p></div></div><div className="panel-body">{audit.findings.map((finding, index) => <div className="finding" key={`${finding.code}-${index}`}><span className={`finding-icon ${finding.review ? 'warning' : ''}`}>{finding.review ? <TriangleAlert size={15} /> : <FileCheck2 size={15} />}</span><div><code>{finding.code}</code><p>{finding.message}</p><References refs={finding.policy_refs} policies={policies} /></div></div>)}{audit.validation_errors.length > 0 && <div className="notice"><TriangleAlert size={17} /><p>Agent validation messages: {audit.validation_errors.join(' · ')}</p></div>}<details className="explanation"><summary>Complete exported explanation</summary><p>{result.explanation}</p></details></div></section></div>
    <aside><section className="panel context"><h2>Claim context</h2><dl><dt>Trip starts</dt><dd>{date(claim.trip_start)}</dd><dt>Trip ends</dt><dd>{date(claim.trip_end)}</dd><dt>Submitted</dt><dd>{date(claim.submitted)}</dd><dt>Business documented</dt><dd>{claim.business_documented ? 'Yes' : 'No'}</dd><dt>Currency</dt><dd>USD</dd></dl><hr /><h3>Evaluation evidence</h3><dl><dt>Source</dt><dd><Source item={item} /></dd><dt>Confidence</dt><dd>{Math.round(result.confidence * 100)}%</dd><dt>Executed tools</dt><dd>{result.tools_used.length}</dd><dt>Evaluation time</dt><dd>{(audit.duration_ms / 1000).toFixed(2)}s</dd></dl><p className="small-note">Confidence describes support for the recommendation, using a documented heuristic.</p><Link className="text-link" to={`/audit?claim=${claim.claim_id}`}>View execution trace <ArrowRight size={14} /></Link></section><section className="panel context"><h2>Supporting policy</h2><References refs={result.policy_refs} policies={policies} /></section></aside></div>
  </>
}

const reviewActions: Record<string, string> = {
  RECEIPT_MISSING: 'Request the required itemized receipt.', AIRFARE_CLASS_EXCEPTION: 'Verify whether airfare pre-approval exists.',
  CONFLICTING_INFORMATION: 'Reconcile conflicting dates, counts, or totals.', POLICY_AMBIGUITY: 'Obtain the missing facts or a dated expense breakdown.',
  DIRECTOR_APPROVAL_REQUIRED: 'Obtain director approval for the reimbursable amount.', LATE_SUBMISSION: 'Review the late-submission exception.',
  MODEL_UNAVAILABLE: 'Restore the local model service and evaluate again.', OUTPUT_VALIDATION_FAILED: 'Inspect the agent validation evidence before retrying.',
}
function ManualReview({items}: {items: Evaluation[]}) {
  const pending = items.filter(i => i.result.decision === 'MANUAL_REVIEW')
  const total = sums(pending)
  return <><div className="page-heading"><div className="eyebrow">HUMAN REVIEW</div><h1>A little context makes the difference.</h1><p>Resolve documentation gaps and exceptions before reimbursement.</p></div><div className="review-summary"><div><Clock3 size={22} /><span><strong>{pending.length} claims</strong> awaiting review</span></div><span className="pending-total">{money(total.pending / 100)} <small>fully pending</small></span></div>
    {pending.length ? <div className="review-grid">{pending.map(item => <section className="panel review-card" key={item.claim.claim_id}><div className="review-card-top"><div className="avatar">{item.claim.employee.split(/[. ]+/).filter(Boolean).map(x => x[0]).join('').slice(0, 2)}</div><div><Link className="claim-link" to={`/claims/${item.claim.claim_id}`}>{item.claim.claim_id}</Link><span className="secondary">{item.claim.employee}</span></div><Status decision="MANUAL_REVIEW" /></div><h2>{item.claim.purpose}</h2><div className="pending-amount"><span>Pending amount</span><strong>{money(item.audit.pending_amount)}</strong></div><div className="reason-tags">{item.audit.reason_codes.filter(code => reviewActions[code]).map(code => <code key={code}>{code}</code>)}</div><h3>Reviewer checklist</h3><ul className="checklist">{[...new Set(item.audit.reason_codes.filter(code => reviewActions[code]).map(code => reviewActions[code]))].map(action => <li key={action}><span className="check-box" />{action}</li>)}</ul><p className="small-note">Approved {money(item.result.approved_amount)} · Deducted {money(item.result.deducted_amount)}. Provisional calculations are available in claim detail.</p><div className="review-card-footer"><Source item={item} /><Link className="button subtle" to={`/claims/${item.claim.claim_id}`}>Review claim <ArrowRight size={14} /></Link></div></section>)}</div> : <Empty title="Review queue is clear" text="No current recommendation requires manual review." />}
    <div className="assurance"><ShieldCheck size={16} />This prototype recommends decisions. It does not authorize payments or record reviewer approvals.</div></>
}

function Audit({items, policies}: {items: Evaluation[]; policies?: Policies}) {
  const [params, setParams] = useSearchParams()
  const item = items.find(i => i.claim.claim_id === params.get('claim')) ?? items[0]
  const [view, setView] = useState<'trace' | 'policy'>(window.location.hash.startsWith('#POL-') ? 'policy' : 'trace')
  useEffect(() => { if (view === 'policy' && window.location.hash) document.getElementById(window.location.hash.slice(1))?.scrollIntoView({block: 'center'}) }, [view, policies])
  if (!item) return null
  const {audit} = item
  return <><div className="page-heading"><div className="eyebrow">POLICY & AUDIT</div><h1>Evidence behind the recommendation.</h1><p>Inspect the retrieved context, model-selected tools, and validation checks.</p></div><div className="audit-controls"><div className="tabs"><button className={view === 'trace' ? 'active' : ''} onClick={() => setView('trace')}>Execution trace</button><button className={view === 'policy' ? 'active' : ''} onClick={() => setView('policy')}>Policy library <span>12</span></button></div><label>Claim<select aria-label="Audit claim" value={item.claim.claim_id} onChange={e => setParams({claim: e.target.value})}>{items.map(i => <option key={i.claim.claim_id}>{i.claim.claim_id}</option>)}</select></label></div>
    {view === 'policy' ? <section className="panel policy-library"><div className="panel-heading"><div><h2>Authoritative travel policy</h2><p>Exact supplied rules · Appendix A · USD</p></div><BookOpen size={20} /></div><div className="policy-grid">{Object.entries(policies?.rules ?? {}).map(([ref, text]) => <article key={ref} id={ref}><code>{ref}</code><p>{text}</p></article>)}</div></section> : <><div className="audit-metrics"><div><span>Execution source</span><strong>{sourceLabel(audit.mode)}{audit.mode.endsWith('failed') ? ' failed' : ''}</strong></div><div><span>Business tools called</span><strong>{audit.events.length}<small> / 6 required</small></strong></div><div><span>Model turns</span><strong>{audit.model_turns.length}<small> / 6 maximum</small></strong></div><div><span>Validation</span><strong className={audit.mode.endsWith('failed') ? 'warning-text' : 'green-text'}>{audit.mode.endsWith('failed') ? 'Held for review' : 'Passed'}</strong></div></div>
    <div className="notice"><Layers3 size={18} /><div><strong>{sourceLabel(audit.mode)} · {audit.model}</strong><p>{audit.mode.startsWith('rules') ? 'Deterministic policy checks execute through MCP in a fixed order. No model is invoked or credited with tool selection.' : audit.mode.startsWith('replay') ? 'Authentic captured model messages are replayed. Every policy tool executes again through MCP, and evidence must match.' : 'Fresh local inference through LangChain and Ollama. Tools execute through MCP.'}</p></div></div>
    <section className="panel trace"><div className="panel-heading"><div><h2>Tool execution timeline</h2><p>Actual tool arguments and returned evidence.</p></div><span className="source">MCP</span></div><div className="timeline">{audit.events.map((event, index) => <details className="tool-event" key={`${event.call_id}-${index}`}><summary><span className="step">{String(index + 1).padStart(2, '0')}</span><div><strong>{event.name}</strong><span>{event.call_id} · {event.transport ?? 'MCP'}</span></div><span className="tool-time">{event.duration_ms.toFixed(2)} ms</span><ChevronDown size={16} /></summary><div className="tool-body"><h3>Arguments</h3><pre>{JSON.stringify(event.arguments, null, 2)}</pre><h3>Returned evidence</h3><pre>{JSON.stringify(event.output, null, 2)}</pre></div></details>)}{audit.events.length === 0 && <Empty title="No completed tool calls" text="Inspect validation messages for the failure before retrying." />}</div></section>
    <div className="audit-bottom"><section className="panel context"><h2>Workflow verification</h2><dl><dt>MCP server</dt><dd>{audit.mcp.server}</dd><dt>Transport</dt><dd>{audit.mcp.transport}</dd><dt>Methods</dt><dd>{audit.mcp.methods.join(', ') || 'None completed'}</dd><dt>Elapsed time</dt><dd>{(audit.duration_ms / 1000).toFixed(2)} seconds</dd></dl><p className="small-note">{audit.validator}</p><details><summary>Policy version</summary><code className="hash">{audit.policy_version}</code></details></section><section className="panel context"><h2>Model & validation evidence</h2><details><summary>Structured model recommendation</summary><pre>{JSON.stringify(audit.model_proposal, null, 2)}</pre></details><details><summary>Model turns ({audit.model_turns.length})</summary><pre>{JSON.stringify(audit.model_turns, null, 2)}</pre></details><details><summary>Validation messages ({audit.validation_errors.length})</summary><pre>{JSON.stringify(audit.validation_errors, null, 2)}</pre></details><details><summary>MCP requests</summary><pre>{JSON.stringify(audit.mcp.requests, null, 2)}</pre></details></section></div></>}
  </>
}

export default function App() {
  const client = useQueryClient()
  const latest = useQuery({queryKey: ['evaluations'], queryFn: api.latest})
  const policies = useQuery({queryKey: ['policies'], queryFn: api.policies})
  const health = useQuery({queryKey: ['health'], queryFn: api.health})
  const [mode, setMode] = useState<Mode>('rules')
  const [jobId, setJobId] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const completedJob = useRef<string | null>(null)
  const mutation = useMutation({mutationFn: (ids?: string[]) => api.evaluate(mode, ids),
    onSuccess: job => { setJobId(job.job_id); setMessage('Evaluation queued.'); },
    onError: error => setMessage(error.message),
  })
  const job = useQuery({queryKey: ['job', jobId], queryFn: () => api.job(jobId!), enabled: !!jobId, retry: false,
    refetchInterval: query => query.state.data?.status === 'completed' || query.state.data?.status === 'failed' ? false : 700,
  })
  useEffect(() => {
    const data = job.data
    if (!data || data.status !== 'completed' && data.status !== 'failed' || completedJob.current === data.job_id) return
    completedJob.current = data.job_id
    setMessage(data.status === 'completed' ? `${data.completed_count} claim${data.completed_count === 1 ? '' : 's'} evaluated in ${data.mode} mode.` : data.error ?? 'Evaluation failed.')
    void client.invalidateQueries({queryKey: ['evaluations']})
    void client.invalidateQueries({queryKey: ['health']})
    setJobId(null)
  }, [job.data, client])
  const items = latest.data?.evaluations ?? []
  const busy = mutation.isPending || !!jobId
  const reviews = items.filter(i => i.result.decision === 'MANUAL_REVIEW').length
  const evaluate = (ids?: string[]) => { if (!busy) { setMessage('Submitting evaluation…'); mutation.mutate(ids) } }
  const progress = jobId ? `${job.data?.status === 'running' ? 'Evaluating' : 'Queued'} · ${job.data?.completed_count ?? 0}/${job.data?.claim_ids.length ?? 0} claims` : message
  return <div className="app-shell"><a href="#main-content" className="skip-link">Skip to content</a><aside className="sidebar"><Link to="/" className="brand"><span className="brand-icon"><Plane size={22} /></span><span>TravelDesk<small>REIMBURSEMENT INTELLIGENCE</small></span></Link><div className="workspace-label">WORKSPACE</div><nav aria-label="Main navigation"><NavLink to="/" end><LayoutDashboard size={18} />Overview</NavLink><NavLink to="/claims"><FileText size={18} />Claims<span className="nav-count">{items.length}</span></NavLink><NavLink to="/review"><Clock3 size={18} />Manual review{reviews > 0 && <span className="nav-count warning-count">{reviews}</span>}</NavLink><NavLink to="/audit"><BookOpen size={18} />Policy & audit</NavLink></nav><div className="sidebar-bottom"><div className="policy-seal"><ShieldCheck size={20} /><div><strong>Policy comes first.</strong><p>Every recommendation is backed by rules and verifiable evidence.</p></div></div><div className="profile"><span className="profile-avatar">SP</span><div><strong>Shaswat Prakash</strong><small>Developer workspace</small></div><span className="profile-dot" /></div></div></aside>
    <div className="workspace"><header className="topbar"><div className="breadcrumb">Workspace <span>/</span> <strong>Travel reimbursements</strong></div><div className="topbar-right"><span className={`model-indicator ${health.data?.live_available ? 'online' : ''}`}><i />{health.data?.live_available ? 'Local model ready' : 'Policy engine ready'}</span><span className="demo-label">DEMO</span></div></header><div className="actionbar"><span className="dataset-label"><Layers3 size={15} />Synthetic scenario library <span>· USD</span></span><div className="button-row"><label className="mode-control">Mode<select aria-label="Evaluation mode" disabled={busy} value={mode} onChange={e => setMode(e.target.value as Mode)}><option value="rules">Rules</option><option value="replay">Replay</option><option value="live">Live</option></select></label><button className="button primary" disabled={busy || !items.length} onClick={() => evaluate()}>{busy ? <LoaderCircle className="spin" size={15} /> : <Play size={14} />}Evaluate all</button></div></div>
    <main id="main-content" className="main-content"><div className="mode-note"><Sparkles size={14} /><span>{mode === 'rules' ? 'Rules computes an explicit policy baseline through MCP. It does not invoke an AI model.' : mode === 'replay' ? 'Replay re-executes MCP tools against authentic captured model interactions.' : `Live runs fresh local inference using ${health.data?.model ?? 'Ollama'}. Allow up to ${health.data?.deadline_seconds ?? 120} seconds per claim.`} Displayed results retain their original source.</span></div>
    {(busy || message) && <div className={`job-status ${mutation.isError || job.data?.status === 'failed' ? 'error-status' : ''}`} role="status" aria-live="polite">{busy ? <LoaderCircle size={16} className="spin" /> : <CheckCircle2 size={16} />}<span>{progress}</span></div>}
    {job.isError && <div className="notice error-notice" role="alert"><TriangleAlert size={18} /><div><strong>Could not check evaluation status.</strong><p>The job may still be running. Retry checking before starting another evaluation.</p><button className="button subtle" onClick={() => void job.refetch()}>Retry status check</button></div></div>}
    {latest.isPending ? <div className="loading-state" role="status"><LoaderCircle className="spin" size={28} /><h2>Loading your workspace</h2><p>Fetching validated decisions and policy evidence.</p></div> : latest.isError ? <div className="panel loading-state" role="alert"><TriangleAlert size={28} /><h2>Cannot connect to the backend</h2><p>{latest.error.message}</p><button className="button primary" onClick={() => void latest.refetch()}>Retry connection</button></div> : <>{policies.isError && <div className="notice error-notice" role="alert"><TriangleAlert size={16} /><p>Policy text could not be loaded.</p><button onClick={() => void policies.refetch()} className="button subtle">Retry policies</button></div>}<Routes><Route path="/" element={<Overview items={items} />} /><Route path="/claims" element={<><div className="page-heading"><div className="eyebrow">CLAIM EXPLORER</div><h1>The details behind each decision.</h1><p>Open a claim to inspect receipts, limits, explanations, and evidence.</p></div><ClaimTable items={items} /></>} /><Route path="/claims/:id" element={<ClaimDetail items={items} policies={policies.data} busy={busy} evaluate={evaluate} />} /><Route path="/review" element={<ManualReview items={items} />} /><Route path="/audit" element={<Audit items={items} policies={policies.data} />} /><Route path="*" element={<Empty title="Page not found" text="Use the navigation to return to your workspace." />} /></Routes></>}
    <footer className="footer"><span>TravelDesk <i /> Policy-grounded reimbursement prototype</span><span>LangChain · Ollama · MCP</span></footer></main></div></div>
}
