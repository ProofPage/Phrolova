import { useState, useEffect } from "react";
import {
    FolderOpen, Shield, CheckCircle2,
    ChevronRight, ChevronLeft, Loader2, Eye, EyeOff,
} from "lucide-react";
import { DirInput } from "./ui/DirInput";
import { Button, Input } from "./ui/primitives";

// ── Types ─────────────────────────────────────────────

interface SetupWizardProps {
    defaultDirectories: {
        live_download_dir: string;
        vod_download_dir: string;
    };
    onComplete: () => void;
}

type Step = 1 | 2 | 3;

interface FormData {
    live_download_dir: string;
    vod_download_dir: string;
    output_format: string;
    recording_quality: string;
    nid_aut: string;
    nid_ses: string;
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
            output_format: data.output_format,
            recording_quality: data.recording_quality,
            nid_aut: data.nid_aut || null,
            nid_ses: data.nid_ses || null,
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
        <div className="flex items-center gap-2 mb-8">
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
    const formats = ["ts", "mp4", "mkv"];

    return (
        <div className="space-y-6">
            {/* 라이브 저장 경로 */}
            <div>
                <label className="block text-sm font-medium text-ink-muted mb-2">
                    <FolderOpen className="inline w-4 h-4 mr-1 text-[var(--primary)]" />
                    라이브 저장 위치 <span className="text-danger">*</span>
                </label>
                <DirInput
                    value={data.live_download_dir}
                    onChange={(val) => onChange("live_download_dir", val)}
                    placeholder="예: C:\\Recordings\\Live 또는 /home/user/recordings/live"
                />
                <p className="text-xs text-ink-faint mt-1.5 flex items-start gap-1">
                    라이브 녹화와 채팅 로그를 저장합니다. 폴더가 없으면 자동으로 만듭니다.
                </p>
            </div>

            {/* 영상 다운로드 저장 경로 */}
            <div>
                <label className="block text-sm font-medium text-ink-muted mb-2">
                    <FolderOpen className="inline w-4 h-4 mr-1 text-[var(--primary)]" />
                    영상 저장 위치 <span className="text-danger">*</span>
                </label>
                <DirInput
                    value={data.vod_download_dir}
                    onChange={(val) => onChange("vod_download_dir", val)}
                    placeholder="예: C:\\Recordings\\Video 또는 /home/user/recordings/video"
                />
                <p className="text-xs text-ink-faint mt-1.5 flex items-start gap-1">
                    치지직 다시보기·클립, YouTube와 외부 영상이 이곳에 저장됩니다.
                </p>
            </div>

            {/* 라이브 품질 */}
            <div>
                <label className="block text-sm font-medium text-ink-muted mb-2">라이브 녹화 화질</label>
                <div className="grid grid-cols-4 gap-2">
                    {qualities.map((q) => (
                        <button
                            key={q}
                            type="button"
                            onClick={() => onChange("recording_quality", q)}
                            className={`py-2 rounded-lg text-sm font-medium border transition-all ${data.recording_quality === q
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
                <label className="block text-sm font-medium text-ink-muted mb-2">라이브 녹화 파일 형식</label>
                <div className="grid grid-cols-3 gap-2">
                    {formats.map((f) => (
                        <button
                            key={f}
                            type="button"
                            onClick={() => onChange("output_format", f)}
                            className={`py-2 rounded-lg text-sm font-medium border transition-all ${data.output_format === f
                                ? "bg-[var(--primary-dim)] border-[var(--primary)] text-[var(--primary)]"
                                : "bg-surface-3 border-line-strong text-ink-faint hover:border-[var(--primary)]"
                                }`}
                        >
                            .{f.toUpperCase()}
                        </button>
                    ))}
                </div>
                <p className="text-xs text-ink-faint mt-1.5">
                    TS는 녹화가 중단되어도 파일을 재생할 수 있어 라이브 녹화에 적합합니다.
                </p>
            </div>
        </div>
    );
}

// ── Step 2: 치지직 인증 쿠키 ─────────────────────────

function Step2({ data, onChange }: { data: FormData; onChange: (k: keyof FormData, v: string) => void }) {
    const [showAut, setShowAut] = useState(false);
    const [showSes, setShowSes] = useState(false);

    return (
        <div className="space-y-5">
            <div className="bg-surface-3 border border-line rounded-[var(--radius-card)] p-4 text-sm text-ink-muted leading-relaxed">
                <Shield className="inline w-4 h-4 mr-1 text-[var(--primary)]" />
                치지직 로그인 쿠키를 등록하면 <span className="text-ink font-medium">성인 방송 녹화</span>와{" "}
                <span className="text-ink font-medium">1080p 고화질</span>에 접근할 수 있습니다.
                <br />
                <span className="text-ink-faint text-xs mt-1 block">
                    브라우저 개발자 도구 (F12) → Application → Cookies → naver.com에서 확인할 수 있습니다.
                    이 단계는 건너뛸 수 있으며 나중에 설정 페이지에서 변경 가능합니다.
                </span>
            </div>

            {/* NID_AUT */}
            <div>
                <label className="block text-sm font-medium text-ink-muted mb-2">NID_AUT</label>
                <div className="relative">
                    <Input
                        type={showAut ? "text" : "password"}
                        value={data.nid_aut}
                        onChange={(e) => onChange("nid_aut", e.target.value)}
                        placeholder="NID_AUT 쿠키 값"
                        className="pr-10 font-mono"
                    />
                    <button
                        type="button"
                        onClick={() => setShowAut((v) => !v)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-faint hover:text-ink-muted"
                    >
                        {showAut ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                </div>
            </div>

            {/* NID_SES */}
            <div>
                <label className="block text-sm font-medium text-ink-muted mb-2">NID_SES</label>
                <div className="relative">
                    <Input
                        type={showSes ? "text" : "password"}
                        value={data.nid_ses}
                        onChange={(e) => onChange("nid_ses", e.target.value)}
                        placeholder="NID_SES 쿠키 값"
                        className="pr-10 font-mono"
                    />
                    <button
                        type="button"
                        onClick={() => setShowSes((v) => !v)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-faint hover:text-ink-muted"
                    >
                        {showSes ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                </div>
            </div>
        </div>
    );
}

// ── Step 3: 확인 및 완료 ─────────────────────────────

function Step3({ data }: { data: FormData }) {
    const rows: { label: string; value: string }[] = [
        { label: "라이브 저장 위치", value: data.live_download_dir || "(미설정)" },
        { label: "영상 저장 위치", value: data.vod_download_dir || "(미설정)" },
        { label: "라이브 녹화 화질", value: data.recording_quality },
        { label: "라이브 녹화 파일 형식", value: `.${data.output_format.toUpperCase()}` },
        { label: "치지직 인증", value: data.nid_aut && data.nid_ses ? "✅ 설정됨" : "⏭️ 건너뜀 (나중에 설정 가능)" },
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
                        <span className="text-ink font-medium text-right max-w-[60%] truncate">{row.value}</span>
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
    const [step, setStep] = useState<Step>(1);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [data, setData] = useState<FormData>(() => ({
        live_download_dir: defaultDirectories.live_download_dir,
        vod_download_dir: defaultDirectories.vod_download_dir,
        output_format: "ts",
        recording_quality: "best",
        nid_aut: "",
        nid_ses: "",
    }));

    const onChange = (k: keyof FormData, v: string) =>
        setData((prev) => ({ ...prev, [k]: v }));

    const canNext = step === 1
        ? data.live_download_dir.trim().length > 0 && data.vod_download_dir.trim().length > 0
        : true;

    const handleNext = () => {
        if (step < 3) setStep((s) => (s + 1) as Step);
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
        2: { title: "치지직 인증 쿠키 (선택)", subtitle: "성인 방송 및 1080p 녹화를 위한 로그인 쿠키를 입력하세요." },
        3: { title: "설정 확인", subtitle: "아래 내용을 확인하고 완료 버튼을 누르세요." },
    };

    return (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center animate-backdrop">
            {/* 배경 블러 */}
            <div className="absolute inset-0 bg-black/80 " />

            {/* 카드 */}
            <div className="relative bg-surface-2 border border-line-strong rounded-[var(--radius-card)] shadow-2xl surface-raise w-full max-w-lg mx-4 max-h-[calc(100vh-2rem)] animate-modal-in overflow-y-auto">


                <div className="p-8">
                    {/* 헤더 */}
                    <div className="mb-6">
                        <div className="flex items-center gap-2 mb-1">
                            <span className="text-xs font-semibold text-[var(--primary)] uppercase tracking-widest">
                                Phrolova
                            </span>
                        </div>
                        <h2 className="text-2xl font-bold text-ink">
                            {stepTitles[step].title}
                        </h2>
                        <p className="text-sm text-ink-muted mt-1">{stepTitles[step].subtitle}</p>
                    </div>

                    {/* Step 인디케이터 */}
                    <StepIndicator current={step} total={3} />

                    {/* Step 콘텐츠 */}
                    <div className="min-h-[240px]">
                        {step === 1 && <Step1 data={data} onChange={onChange} />}
                        {step === 2 && <Step2 data={data} onChange={onChange} />}
                        {step === 3 && <Step3 data={data} />}
                    </div>

                    {/* 에러 */}
                    {error && (
                        <p className="mt-4 text-sm text-danger bg-danger/10 border border-danger/20 rounded-[var(--radius-control)] px-4 py-2">
                            {error}
                        </p>
                    )}

                    {/* 버튼 */}
                    <div className="flex items-center justify-between mt-8">
                        <Button type="button" icon={ChevronLeft} onClick={handleBack} disabled={step === 1} variant="ghost">이전</Button>

                        {step < 3 ? (
                            <Button
                                type="button"
                                onClick={handleNext}
                                disabled={!canNext}
                                variant="primary"
                                className="px-6"
                            >
                                {step === 2 && !data.nid_aut ? "건너뛰기" : "다음"}
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
