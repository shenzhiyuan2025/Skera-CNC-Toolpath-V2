import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock3, FileUp, Gauge, History, LoaderCircle, Settings, ShieldAlert, Upload, UserCircle2 } from 'lucide-react';
import { getToolpathJob, startToolpathJob, ToolpathEvaluationResult, ToolpathJobMode, ToolpathJobStatusResponse } from '../services/toolpathApi';

type UiLevel = 'blocker' | 'high' | 'medium' | 'low';
type Lamp = 'green' | 'yellow' | 'red';

const issueStyle: Record<string, string> = {
  blocker: 'bg-red-100 text-red-700',
  critical: 'bg-red-100 text-red-700',
  high: 'bg-orange-100 text-orange-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-blue-100 text-blue-700',
  info: 'bg-slate-100 text-slate-700'
};

const lampStyle: Record<Lamp, string> = {
  green: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  yellow: 'bg-amber-100 text-amber-700 border-amber-200',
  red: 'bg-red-100 text-red-700 border-red-200'
};

const lampText: Record<Lamp, string> = {
  green: '绿灯：检查通过，可继续加工',
  yellow: '黄灯：存在注意事项，建议确认后继续',
  red: '红灯：存在关键问题，需处理后继续'
};

export const ToolpathBenchmark: React.FC = () => {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [gcodeText, setGcodeText] = useState('');
  const [filePreviewText, setFilePreviewText] = useState('');
  const [softwareSource, setSoftwareSource] = useState('');
  const [machineModel, setMachineModel] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ToolpathEvaluationResult | null>(null);
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobFileId, setJobFileId] = useState<string | null>(null);
  const [jobMode, setJobMode] = useState<ToolpathJobMode>('sample');
  const [jobProgress, setJobProgress] = useState<{ percent: number; lines: number; bytes: number; totalBytes: number } | null>(null);
  const pollTimer = useRef<number | null>(null);

  const hasResult = Boolean(result);
  const displayResult = result;

  const issueCounts = displayResult?.issue_counts ?? { blocker: 0, high: 0, medium: 0, low: 0 };

  const lamp = useMemo<Lamp>(() => displayResult?.final_conclusion ?? 'yellow', [displayResult?.final_conclusion]);

  const scorePanels = useMemo(
    () => [
      { key: 'D1', label: 'D1 安全与可达性', score: displayResult?.dimension_scores.D1 ?? 0, max: 25 },
      { key: 'D2', label: 'D2 几何正确性与覆盖', score: displayResult?.dimension_scores.D2 ?? 0, max: 20 },
      { key: 'D3', label: 'D3 表面质量潜力', score: displayResult?.dimension_scores.D3 ?? 0, max: 15 },
      { key: 'D4', label: 'D4 效率', score: displayResult?.dimension_scores.D4 ?? 0, max: 12 },
      { key: 'D5', label: 'D5 运动平稳性', score: displayResult?.dimension_scores.D5 ?? 0, max: 10 },
      { key: 'D6', label: 'D6 规范与适配', score: displayResult?.dimension_scores.D6 ?? 0, max: 8 },
      { key: 'D7', label: 'D7 工艺策略', score: displayResult?.dimension_scores.D7 ?? 0, max: 10 }
    ],
    [displayResult?.dimension_scores]
  );

  const handleAnalyze = async () => {
    const trimmedText = gcodeText.trim();
    if (!file && !trimmedText) {
      setError('请上传刀路文件或输入 G 代码文本');
      return;
    }
    if (pollTimer.current) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
    setLoading(true);
    setError('');
    setJobProgress({ percent: 0, lines: 0, bytes: 0, totalBytes: 0 });
    setJobMode('sample');
    try {
      const start = await startToolpathJob({
        file: file || undefined,
        gcodeText: trimmedText || undefined,
        softwareSource: softwareSource.trim(),
        machineModel: machineModel.trim(),
        mode: 'sample',
        sampleLines: 50000
      });
      setJobId(start.job_id);
      setJobFileId(start.file_id);

      const pollOnce = async () => {
        const status: ToolpathJobStatusResponse = await getToolpathJob(start.job_id);
        const rawPercent = typeof status.progress?.percent === 'number' ? status.progress.percent : 0;
        const rawLines = typeof status.progress?.lines === 'number' ? status.progress.lines : 0;
        const rawBytes = typeof status.progress?.bytes === 'number' ? status.progress.bytes : 0;
        const rawTotalBytes = typeof status.progress?.total_bytes === 'number' ? status.progress.total_bytes : 0;
        setJobProgress({
          percent: Number.isFinite(rawPercent) ? Math.max(0, Math.min(1, rawPercent)) : 0,
          lines: Number.isFinite(rawLines) ? Math.max(0, rawLines) : 0,
          bytes: Number.isFinite(rawBytes) ? Math.max(0, rawBytes) : 0,
          totalBytes: Number.isFinite(rawTotalBytes) ? Math.max(0, rawTotalBytes) : 0
        });
        if (status.status === 'done' && status.result) {
          setResult(status.result);
          setLoading(false);
          if (pollTimer.current) {
            window.clearInterval(pollTimer.current);
            pollTimer.current = null;
          }
        } else if (status.status === 'error') {
          setError(status.error || '评测失败');
          setLoading(false);
          if (pollTimer.current) {
            window.clearInterval(pollTimer.current);
            pollTimer.current = null;
          }
        }
      };

      await pollOnce();
      pollTimer.current = window.setInterval(() => {
        void pollOnce();
      }, 800);
    } catch (e) {
      setError(e instanceof Error ? e.message : '评测失败');
    } finally {
      if (!pollTimer.current) {
        setLoading(false);
      }
    }
  };

  const handleAnalyzeFull = async () => {
    if (!jobFileId) {
      setError('缺少 file_id，无法继续全部评测（请重新开始一次采样评测）');
      return;
    }
    if (pollTimer.current) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
    setLoading(true);
    setError('');
    setJobProgress({ percent: 0, lines: 0, bytes: 0, totalBytes: 0 });
    setJobMode('full');
    try {
      const start = await startToolpathJob({
        fileId: jobFileId,
        softwareSource: softwareSource.trim(),
        machineModel: machineModel.trim(),
        mode: 'full'
      });
      setJobId(start.job_id);

      const pollOnce = async () => {
        const status: ToolpathJobStatusResponse = await getToolpathJob(start.job_id);
        const rawPercent = typeof status.progress?.percent === 'number' ? status.progress.percent : 0;
        const rawLines = typeof status.progress?.lines === 'number' ? status.progress.lines : 0;
        const rawBytes = typeof status.progress?.bytes === 'number' ? status.progress.bytes : 0;
        const rawTotalBytes = typeof status.progress?.total_bytes === 'number' ? status.progress.total_bytes : 0;
        setJobProgress({
          percent: Number.isFinite(rawPercent) ? Math.max(0, Math.min(1, rawPercent)) : 0,
          lines: Number.isFinite(rawLines) ? Math.max(0, rawLines) : 0,
          bytes: Number.isFinite(rawBytes) ? Math.max(0, rawBytes) : 0,
          totalBytes: Number.isFinite(rawTotalBytes) ? Math.max(0, rawTotalBytes) : 0
        });
        if (status.status === 'done' && status.result) {
          setResult(status.result);
          setLoading(false);
          if (pollTimer.current) {
            window.clearInterval(pollTimer.current);
            pollTimer.current = null;
          }
        } else if (status.status === 'error') {
          setError(status.error || '评测失败');
          setLoading(false);
          if (pollTimer.current) {
            window.clearInterval(pollTimer.current);
            pollTimer.current = null;
          }
        }
      };

      await pollOnce();
      pollTimer.current = window.setInterval(() => {
        void pollOnce();
      }, 800);
    } catch (e) {
      setError(e instanceof Error ? e.message : '评测失败');
    } finally {
      if (!pollTimer.current) {
        setLoading(false);
      }
    }
  };

  const loadPreviewFromFile = async (picked: File) => {
    try {
      const text = await picked.slice(0, 256 * 1024).text();
      const lines = text.split('\n').slice(0, 400).join('\n');
      setFilePreviewText(lines);
    } catch {
      setFilePreviewText('');
    }
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) {
      setFile(dropped);
      void loadPreviewFromFile(dropped);
    }
  };

  const gcodePreviewSource = (gcodeText || filePreviewText || 'N10 G90 G21\nN20 G0 X0 Y0 Z25\nN30 G1 Z-1 F200\nN40 G1 X20 Y0 F600\nN50 G1 X40 Y12 F680\nN60 G0 Z20\nN70 M30').split('\n');
  const issueLineSeverity = useMemo(() => {
    const order: Record<UiLevel, number> = { blocker: 4, high: 3, medium: 2, low: 1 };
    const map = new Map<number, UiLevel>();
    for (const it of displayResult?.issues ?? []) {
      const r = it.line_range;
      if (!r || r.length < 2) {
        continue;
      }
      const start = Math.max(1, Math.floor(r[0]));
      const end = Math.max(start, Math.floor(r[1]));
      for (let ln = start; ln <= end; ln += 1) {
        const prev = map.get(ln);
        if (!prev || order[it.severity as UiLevel] > order[prev]) {
          map.set(ln, it.severity as UiLevel);
        }
      }
    }
    return map;
  }, [displayResult?.issues]);

  const categoryBuckets = useMemo(() => {
    const buckets = new Map<string, ToolpathEvaluationResult['issues']>();
    for (const it of displayResult?.issues ?? []) {
      const key = it.category || 'uncategorized';
      const arr = buckets.get(key) ?? [];
      arr.push(it);
      buckets.set(key, arr);
    }
    return Array.from(buckets.entries()).sort((a, b) => b[1].length - a[1].length);
  }, [displayResult?.issues]);

  useEffect(() => {
    return () => {
      if (pollTimer.current) {
        window.clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, []);

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-8">
            <h1 className="text-xl font-semibold tracking-tight">刀路测评工具</h1>
            <nav className="flex items-center gap-5 text-sm text-slate-600">
              <span className="inline-flex items-center gap-1.5 text-slate-900"><Gauge className="h-4 w-4" />任务入口</span>
              <span className="inline-flex items-center gap-1.5"><History className="h-4 w-4" />历史记录</span>
              <span className="inline-flex items-center gap-1.5"><Settings className="h-4 w-4" />配置入口</span>
            </nav>
          </div>
          <button className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700">
            <UserCircle2 className="h-4 w-4" />
            工程用户
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-5 px-6 py-6">
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800">任务输入</h2>
          </div>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <label className="space-y-1">
              <span className="text-xs text-slate-600">软件来源（选填）</span>
              <input
                value={softwareSource}
                onChange={(e) => setSoftwareSource(e.target.value)}
                placeholder="如：AICAM / PowerMill / HyperMill"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-slate-600">机床型号（选填）</span>
              <input
                value={machineModel}
                onChange={(e) => setMachineModel(e.target.value)}
                placeholder="如：Desk 5X CNC"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
              />
            </label>
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div
              onDrop={onDrop}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              className={`rounded-xl border-2 border-dashed p-6 text-center transition-colors ${dragging ? 'border-slate-700 bg-slate-50' : 'border-slate-300 bg-slate-50'}`}
            >
              <FileUp className="mx-auto mb-2 h-8 w-8 text-slate-400" />
              <p className="text-sm font-medium text-slate-700">拖拽 .nc / .tap / .gcode 文件</p>
              <label className="mt-3 inline-flex cursor-pointer items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700">
                <Upload className="h-4 w-4" />
                选择文件
                <input
                  type="file"
                  className="hidden"
                  accept=".nc,.tap,.gcode,.txt"
                  onChange={(e) => {
                    const picked = e.target.files?.[0] || null;
                    setFile(picked);
                    if (picked) {
                      void loadPreviewFromFile(picked);
                    } else {
                      setFilePreviewText('');
                    }
                  }}
                />
              </label>
              {file && <p className="mt-2 text-xs text-slate-500">已选择：{file.name}</p>}
            </div>
            <div className="space-y-2">
              <textarea
                value={gcodeText}
                onChange={(e) => setGcodeText(e.target.value)}
                className="min-h-[150px] w-full rounded-xl border border-slate-300 px-3 py-2 font-mono text-xs outline-none focus:border-slate-500"
                placeholder={'G90 G21\nG0 X0 Y0 Z20\nG1 Z-1 F200\nG1 X20 Y0 F600'}
              />
              <div className="flex items-center justify-between">
                <p className="text-xs text-slate-500">支持文件或文本任一输入</p>
                <button
                  onClick={handleAnalyze}
                  disabled={loading}
                  className="inline-flex items-center gap-1 rounded-lg bg-slate-800 px-3 py-1.5 text-sm text-white disabled:opacity-60"
                >
                  {loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Gauge className="h-4 w-4" />}
                  开始测评
                </button>
              </div>
            </div>
          </div>
          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
          {loading && jobProgress && (
            <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div className="mb-2 flex items-center justify-between text-xs text-slate-600">
                <span>{jobMode === 'sample' ? '流式评测中（采样前5万行）' : '流式评测中（全部评测）'}</span>
                <span className="font-semibold text-slate-700">{Math.round(jobProgress.percent * 100)}%</span>
              </div>
              <div className="h-2 rounded-full bg-slate-200">
                <div className="h-2 rounded-full bg-slate-700" style={{ width: `${Math.round(jobProgress.percent * 100)}%` }} />
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                <span>已处理 {jobProgress.lines.toLocaleString()} 行</span>
                {jobProgress.totalBytes > 0 && <span>{(jobProgress.bytes / 1024 / 1024).toFixed(1)} / {(jobProgress.totalBytes / 1024 / 1024).toFixed(1)} MB</span>}
                {jobId && <span>Job: {jobId.slice(0, 8)}</span>}
              </div>
            </div>
          )}
        </section>

        {hasResult && (
          <>
        <section className={`rounded-2xl border p-5 shadow-sm ${lampStyle[lamp]}`}>
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div>
              <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-current/30 px-3 py-1 text-sm font-medium">
                {lamp === 'red' ? <AlertTriangle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                {lampText[lamp]}
              </div>
              <div className="text-3xl font-bold">总分 {displayResult?.total_score.toFixed(1)}</div>
            </div>
            <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
              <div><span className="text-slate-500">任务：</span><span className="font-medium text-slate-800">AICAM-Bench-20260416</span></div>
              <div><span className="text-slate-500">软件来源：</span><span className="font-medium text-slate-800">{softwareSource.trim() || '未填写'}</span></div>
              <div><span className="text-slate-500">文件：</span><span className="font-medium text-slate-800">{file?.name || String(displayResult?.task_meta?.file_name || '未命名')}</span></div>
              <div><span className="text-slate-500">机床：</span><span className="font-medium text-slate-800">{machineModel.trim() || 'Desk 5X CNC'}</span></div>
              <div className="inline-flex items-center gap-1.5"><Clock3 className="h-4 w-4 text-slate-500" /><span className="text-slate-500">测评时间：</span><span className="font-medium text-slate-800">{new Date().toLocaleString()}</span></div>
            </div>
          </div>
          {(() => {
            const sampling = (displayResult?.task_meta as Record<string, unknown> | undefined)?.sampling as
              | { sampled?: boolean; max_lines?: number; truncated?: boolean }
              | undefined;
            const sampled = Boolean(sampling?.sampled);
            const maxLines = sampling?.max_lines ?? 50000;
            const truncated = Boolean(sampling?.truncated);
            const canFull = sampled && truncated && displayResult?.final_conclusion !== 'red' && Boolean(jobFileId);
            if (!sampled) {
              return null;
            }
            return (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-current/20 bg-white/70 px-4 py-3 text-sm">
                <div className="text-slate-700">采样前{maxLines.toLocaleString()}行代码进行评测</div>
                {canFull && (
                  <button
                    type="button"
                    onClick={handleAnalyzeFull}
                    disabled={loading}
                    className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-60"
                  >
                    {loading && jobMode === 'full' ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
                    全部评测
                  </button>
                )}
              </div>
            );
          })()}
        </section>

        <section className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm xl:col-span-3">
            <h2 className="mb-3 text-sm font-semibold text-slate-800">安全门禁摘要</h2>
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
                <span className="text-slate-600">门禁状态</span>
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${displayResult?.final_conclusion === 'red' ? 'bg-red-100 text-red-700' : 'bg-emerald-100 text-emerald-700'}`}>
                  {displayResult?.final_conclusion === 'red' ? '触发阻断' : '通过'}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
                <span className="text-slate-600">Blocker</span>
                <span className="font-semibold text-red-600">{issueCounts.blocker}</span>
              </div>
              <div className="rounded-lg bg-slate-50 px-3 py-2 text-slate-600">{displayResult?.summary}</div>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm xl:col-span-6">
            <h2 className="mb-3 text-sm font-semibold text-slate-800">七维评分面板</h2>
            <div className="space-y-3">
              {scorePanels.map((item) => {
                const ratio = Math.min(100, (item.score / item.max) * 100);
                return (
                  <div key={item.key}>
                    <div className="mb-1 flex items-center justify-between text-xs">
                      <span className="text-slate-600">{item.label}</span>
                      <span className="font-semibold text-slate-800">{item.score.toFixed(1)} / {item.max}</span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-100">
                      <div className="h-2 rounded-full bg-slate-700" style={{ width: `${ratio}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm xl:col-span-3">
            <h2 className="mb-3 text-sm font-semibold text-slate-800">问题统计</h2>
            <div className="space-y-2">
              {categoryBuckets.length === 0 && (
                <div className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">未发现问题</div>
              )}
              {categoryBuckets.map(([category, items]) => {
                const isOpen = expandedCategory === category;
                return (
                  <div key={category} className="rounded-lg border border-slate-200 bg-white">
                    <button
                      type="button"
                      onClick={() => setExpandedCategory(isOpen ? null : category)}
                      className="flex w-full items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-left text-sm"
                    >
                      <span className="text-slate-700">{category}</span>
                      <span className="rounded bg-slate-200 px-2 py-0.5 text-xs font-semibold text-slate-700">{items.length}</span>
                    </button>
                    {isOpen && (
                      <div className="max-h-[220px] overflow-auto px-3 py-2 text-xs text-slate-700">
                        <div className="space-y-2">
                          {items.slice(0, 40).map((it) => (
                            <div key={`${it.code}_${it.line_range?.[0] ?? 0}`} className="rounded-md bg-slate-50 px-2 py-1.5">
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-semibold text-slate-800">{it.code}</span>
                                <span className={`rounded px-2 py-0.5 ${issueStyle[it.severity] || issueStyle.low}`}>{it.severity}</span>
                              </div>
                              <div className="mt-1 text-slate-600">
                                <span className="font-medium text-slate-700">{it.line_range?.length ? `L${it.line_range[0]}-${it.line_range[1]}` : '-'}</span>
                                <span className="mx-2 text-slate-300">·</span>
                                <span>{it.description}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        <section className="grid grid-cols-1 gap-4 xl:grid-cols-12">
          <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm xl:col-span-8">
            <h2 className="mb-3 text-sm font-semibold text-slate-800">关键问题列表</h2>
            <div className="overflow-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left">严重级别</th>
                    <th className="px-3 py-2 text-left">问题标题</th>
                    <th className="px-3 py-2 text-left">所属维度</th>
                    <th className="px-3 py-2 text-left">简短建议</th>
                    <th className="px-3 py-2 text-left">行号范围</th>
                  </tr>
                </thead>
                <tbody>
                  {displayResult?.issues.slice(0, 8).map((item, idx) => (
                    <tr key={`${item.code}_${idx}`} className="border-t border-slate-100 text-xs">
                      <td className="px-3 py-2">
                        <span className={`rounded px-2 py-0.5 ${issueStyle[item.severity] || issueStyle.low}`}>{item.severity}</span>
                      </td>
                      <td className="px-3 py-2 text-slate-700">{item.title}</td>
                      <td className="px-3 py-2 text-slate-500">{item.dimension}</td>
                      <td className="px-3 py-2 text-slate-600">{item.suggestion || '-'}</td>
                      <td className="px-3 py-2 text-slate-500">{item.line_range?.length ? `${item.line_range[0]}-${item.line_range[1]}` : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-[#121821] p-4 shadow-sm xl:col-span-4">
            <h2 className="mb-3 inline-flex items-center gap-2 text-sm font-semibold text-slate-100">
              <ShieldAlert className="h-4 w-4 text-slate-300" />
              G代码预览
            </h2>
            <div className="max-h-[280px] overflow-auto rounded-lg bg-[#0b1118] p-3 font-mono text-xs text-slate-200">
              {gcodePreviewSource.slice(0, 240).map((line, idx) => {
                const lineNo = idx + 1;
                const sev = issueLineSeverity.get(lineNo);
                const bg = sev === 'blocker'
                  ? 'bg-red-950/40'
                  : sev === 'high'
                    ? 'bg-orange-950/35'
                    : sev === 'medium'
                      ? 'bg-amber-950/30'
                      : sev === 'low'
                        ? 'bg-blue-950/25'
                        : '';
                const fg = sev === 'blocker'
                  ? 'text-red-200 font-semibold'
                  : sev === 'high'
                    ? 'text-orange-200 font-semibold'
                    : sev === 'medium'
                      ? 'text-amber-200'
                      : sev === 'low'
                        ? 'text-blue-200'
                        : 'text-slate-200';
                return (
                  <div key={idx} className={`grid grid-cols-[36px_1fr] gap-2 rounded px-1 py-0.5 ${bg}`}>
                    <span className="text-slate-500">{lineNo}</span>
                    <span className={fg}>{line}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
          </>
        )}
      </main>
    </div>
  );
};
