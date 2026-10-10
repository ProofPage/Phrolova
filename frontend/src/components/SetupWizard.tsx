import { useRef, useState } from "react";
import { useDialogKeyboard } from "../hooks/useDialogKeyboard";
import {
    FolderOpen, CheckCircle2,
    ChevronRight, ChevronLeft, Loader2,
} from "lucide-react";
import { DirInput } from "./ui/DirInput";
import { Button } from "./ui/primitives";

// ── Types ─────────────────────────────────────────────

interface SetupWizardProps {
    defaultDirectories: {
        live_download_dir: string;
        vod_download_dir: string;
    };
    onComplete: () => void;
}

type Step = 1 | 2;

interface FormData {
    live_download_dir: string;
    vod_download_dir: string;
    output_format: string;
    recording_quality: string;
}

// ── API ──────────────────────────────────────────────

async function completeSetup(data: FormData): Promise<void> {
    const res = await fetch("/api/setup/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            // 구버전 초기 설정 API를 위해 download_dir에 라이브 경로도 전달한다.
            download_dir: data.live_download_dir,
            live_download_dir: data.live_download_dir,
            vod_download_dir: data.vod_download_dir,
            live_format: data.output_format,
            recording_quality: data.recording_quality,
        }),
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail ?? "설정 저장 실패");
    }
}

// ── Step 인디케이터 ──────────────────────────────────

function StepIndicator({ current, total }: { current: Step; total: number }) {
    return (
        <div className="flex items-center gap-2 mb-8 max-sm:mb-4">
            {Array.from({ length: total }, (_, i) => i + 1).map((n) => (
                <div key={n} className="flex items-center gap-2">
                    <div
                        className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all duration-300 ${n < current
                            ? "btn-primary"
                            : n === current
                                ? "bg-[var(--primary-dim)] border-2 border-[var(--primary)] text-[var(--primary)]"
                                : "bg-surface-3 border border-line-strong text-ink-faint"
                            }`}
                    >
                        {n < current ? <CheckCircle2 className="w-4 h-4" /> : n}
                    </div>
                    {n < total && (
                        <div
                            className={`h-0.5 w-8 rounded transition-all duration-300 ${n < current ? "bg-[var(--primary)]" : "bg-line-strong"
                                }`}
                        />
                    )}
                </div>
            ))}
        </div>
    );
}

// ── Step 1: 기본 설정 ────────────────────────────────

function Step1({ data, onChange }: { data: FormData; onChange: (k: keyof FormData, v: string) => void }) {
    const qualities = ["best", "1080p", "720p", "480p"];
    const formats = ["mp4", "mkv"];

    return (
        <div className="space-y-6 max-sm:space-y-4">
            {/* 라이브 저장 경로 */}
            <div>
                <label htmlFor="setup-live-dir" className="block text-sm font-medium text-ink-muted mb-2">
                    <FolderOpen className="inline w-4 h-4 mr-1 text-[var(--primary)]" />
                    라이브 저장 위치 <span className="text-danger">*</span>
                </label>
                <DirInput
                    id="setup-live-dir"
                    value={data.live_download_dir}
                    onChange={(val) => onChange("live_download_dir", val)}
                    placeholder="예: C:\\Recordings\\Live 또는 /home/user/recordings/live"
                />
                <p className="text-xs text-ink-faint mt-1.5 flex items-start gap-1">
                    라이브 녹화 파일을 저장합니다. 폴더가 없으면 자동으로 만듭니다.
                </p>
            </div>

            {/* 영상 다운로드 저장 경로 */}
            <div>
                <label htmlFor="setup-vod-dir" className="block text-sm font-medium text-ink-muted mb-2">
                    <FolderOpen className="inline w-4 h-4 mr-1 text-[var(--primary)]" />
                    영상 저장 위치 <span className="text-danger">*</span>
                </label>
                <DirInput
                    id="setup-vod-dir"
                    value={data.vod_download_dir}
                    onChange={(val) => onChange("vod_download_dir", val)}
                    placeholder="예: C:\\Recordings\\Video 또는 /home/user/recordings/video"
                />
                <p className="text-xs text-ink-faint mt-1.5 flex items-start gap-1">
                    치지직 다시보기·클립, 유튜브와 외부 영상이 이곳에 저장됩니다.
                </p>
            </div>

            {/* 라이브 품질 */}
            <div>
                <label className="block text-sm font-medium text-ink-muted mb-2">라이브 녹화 화질</label>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    {qualities.map((q) => (
                        <button
                            key={q}
                            type="button"
                            onClick={() => onChange("recording_quality", q)}
                            aria-pressed={data.recording_quality === q}
                            className={`ui-chip max-sm:min-h-11 py-2 rounded-lg text-sm font-medium border transition-all ${data.recording_quality === q
                                ? "bg-[var(--primary-dim)] border-[var(--primary)] text-[var(--primary)]"
                                : "bg-surface-3 border-line-strong text-ink-faint hover:border-[var(--primary)]"
                                }`}
                        >
                            {q}
                        </button>
                    ))}
                </div>
            </div>

            {/* 파일 형식 */}
            <div>
                <label className="block text-sm font-medium text-ink-muted mb-2">녹화 완료 후 저장 형식</label>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    {formats.map((f) => (
                        <button
                            key={f}
                            type="button"
                            onClick={() => onChange("output_format", f)}
                            aria-pressed={data.output_format === f}
                            className={`ui-chip max-sm:min-h-11 py-2 rounded-lg text-sm font-medium border transition-all ${data.output_format === f
                                ? "bg-[var(--primary-dim)] border-[var(--primary)] text-[var(--primary)]"
                                : "bg-surface-3 border-line-strong text-ink-faint hover:border-[var(--primary)]"
                                }`}
                        >
                            .{f.toUpperCase()}
                        </button>
                    ))}
                </div>
                <p className="text-xs text-ink-faint mt-1.5">
                    Streamlink로 TS를 저장하고, 녹화 종료 후 선택한 형식으로 변환합니다.
                </p>
            </div>
        </div>
    );
}

// ── Step 2: 확인 및 완료 ─────────────────────────────

function Step2({ data }: { data: FormData }) {
    const rows: { label: string; value: string }[] = [
        { label: "라이브 저장 위치", value: data.live_download_dir || "(미설정)" },
        { label: "영상 저장 위치", value: data.vod_download_dir || "(미설정)" },
        { label: "라이브 녹화 화질", value: data.recording_quality },
        { label: "녹화 완료 후 저장 형식", value: `.${data.output_format.toUpperCase()}` },
    ];

    return (
        <div className="space-y-4">
            <div className="bg-surface-3 border border-line rounded-[var(--radius-card)] overflow-hidden">
                {rows.map((row, i) => (
                    <div
                        key={row.label}
                        className={`flex items-center justify-between px-4 py-3 text-sm ${i < rows.length - 1 ? "border-b border-line" : ""
                            }`}
                    >
                        <span className="text-ink-muted">{row.label}</span>
                        <span className="text-ink font-medium text-right max-w-[60%] truncate max-sm:whitespace-normal max-sm:break-all">{row.value}</span>
                    </div>
                ))}
            </div>
            <p className="text-xs text-ink-faint text-center">
                모든 설정은 나중에 <span className="text-ink-muted">설정 페이지</span>에서 변경할 수 있습니다.
            </p>
        </div>
    );
}

// ── Main SetupWizard ─────────────────────────────────

export function SetupWizard({ defaultDirectories, onComplete }: SetupWizardProps) {
    const dialogRef = useRef<HTMLDivElement>(null);
    useDialogKeyboard(dialogRef, () => {});
    const [step, setStep] = useState<Step>(1);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [data, setData] = useState<FormData>(() => ({
        live_download_dir: defaultDirectories.live_download_dir,
        vod_download_dir: defaultDirectories.vod_download_dir,
        output_format: "mp4",
        recording_quality: "best",
    }));

    const onChange = (k: keyof FormData, v: string) =>
        setData((prev) => ({ ...prev, [k]: v }));

    const canNext = step === 1
        ? data.live_download_dir.trim().length > 0 && data.vod_download_dir.trim().length > 0
        : true;

    const handleNext = () => {
        if (step < 2) setStep((s) => (s + 1) as Step);
    };

    const handleBack = () => {
        if (step > 1) setStep((s) => (s - 1) as Step);
    };

    const handleSave = async () => {
        setSaving(true);
        setError(null);
        try {
            await completeSetup(data);
            onComplete();
        } catch (e) {
        setError("설정을 저장하지 못했습니다. 입력값을 확인하고 다시 시도해 주세요.");
        } finally {
            setSaving(false);
        }
    };

    const stepTitles: Record<Step, { title: string; subtitle: string }> = {
        1: { title: "기본 설정", subtitle: "라이브와 영상의 저장 위치, 기본 화질을 설정하세요." },
        2: { title: "설정 확인", subtitle: "아래 내용을 확인하고 완료 버튼을 누르세요." },
    };

    return (
        <div className="ui-overlay fixed inset-0 z-[9998] flex items-center justify-center animate-backdrop">
            {/* 배경 블러 */}
            <div className="absolute inset-0 bg-black/80 " />

            {/* 카드 */}
            <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="setup-title" tabIndex={-1} className="setup-dialog ui-dialog relative bg-surface-2 border border-line-strong rounded-[var(--radius-card)] shadow-2xl surface-raise w-full max-w-lg mx-4 max-h-[calc(100vh-2rem)] max-lg:max-h-[calc(100dvh-2rem)] animate-modal-in overflow-y-auto">


                <div className="p-8 max-sm:p-4">
                    {/* 헤더 */}
                    <div className="mb-6 max-sm:mb-4">
                        <div className="flex items-center gap-2 mb-1">
                            <span className="text-xs font-semibold text-[var(--primary)] uppercase tracking-widest">
                                Phrolova
                            </span>
                        </div>
                        <h2 id="setup-title" className="text-2xl font-bold text-ink">
                            {stepTitles[step].title}
                        </h2>
                        <p className="text-sm text-ink-muted mt-1">{stepTitles[step].subtitle}</p>
                    </div>

                    {/* Step 인디케이터 */}
                    <StepIndicator current={step} total={2} />

                    {/* Step 콘텐츠 */}
                    <div className="min-h-[240px] max-sm:min-h-0">
                        {step === 1 && <Step1 data={data} onChange={onChange} />}
                        {step === 2 && <Step2 data={data} />}
                    </div>

                    {/* 에러 */}
                    {error && (
                        <p role="alert" className="mt-4 text-sm text-danger bg-danger/10 border border-danger/20 rounded-[var(--radius-control)] px-4 py-2">
                            {error}
                        </p>
                    )}

                    {/* 버튼 */}
                    <div className="dialog-actions flex flex-wrap gap-2 items-center justify-between mt-8 max-sm:mt-4">
                        <Button type="button" icon={ChevronLeft} onClick={handleBack} disabled={step === 1} variant="ghost">이전</Button>

                        {step < 2 ? (
                            <Button
                                type="button"
                                onClick={handleNext}
                                disabled={!canNext}
                                variant="primary"
                                className="px-6"
                            >
                                다음
                                <ChevronRight className="w-4 h-4" />
                            </Button>
                        ) : (
                            <Button
                                type="button"
                                onClick={handleSave}
                                disabled={saving}
                                variant="primary"
                                className="px-6"
                            >
                                {saving ? (
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                ) : (
                                    <CheckCircle2 className="w-4 h-4" />
                                )}
                                {saving ? "저장 중..." : "설정 완료"}
                            </Button>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
