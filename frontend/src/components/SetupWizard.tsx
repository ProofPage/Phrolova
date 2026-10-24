import { useLanguage } from "../contexts/LanguageContext";
import { translate } from "../i18n";
import { useEffect, useRef, useState } from "react";
import { Check, CheckCircle2, ChevronRight, ChevronLeft } from "lucide-react";
import { useDialogKeyboard } from "../hooks/useDialogKeyboard";
import { DirInput } from "./ui/DirInput";
import { Button, Field, Select } from "./ui/primitives";
import { RECORDING_OUTPUT_FORMATS } from "../utils/recordingFormats";
import "./setup-wizard.css";

interface SetupWizardProps {
    defaultDirectories: { live_download_dir: string; vod_download_dir: string };
    onComplete: () => void;
}

type Step = 1 | 2;
interface FormData {
    live_download_dir: string;
    vod_download_dir: string;
    output_format: string;
    recording_quality: string;
}

const qualities = [
    { value: "best", label: "live.highestQuality" },
    { value: "1080p", label: "1080p" },
    { value: "720p", label: "720p" },
    { value: "480p", label: "480p" },
];
const steps = ["setup.basicSettings", "setup.reviewSettings"];

async function completeSetup(data: FormData): Promise<void> {
    const res = await fetch("/api/setup/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            // 구버전 초기 설정 API를 위해 download_dir에 라이브 경로도 전달한다.
            download_dir: data.live_download_dir.trim(),
            live_download_dir: data.live_download_dir.trim(),
            vod_download_dir: data.vod_download_dir.trim(),
            live_format: data.output_format,
            recording_quality: data.recording_quality,
        }),
    });
    if (!res.ok) throw new Error("setup.couldNotSaveSettings");
}

function StepIndicator({ current }: { current: Step }) {
    useLanguage();
    return <ol className="setup-steps" aria-label={translate("setup.setupSteps")}>
        {steps.map((label, i) => <li key={label} aria-current={i + 1 === current ? "step" : undefined} data-complete={i + 1 < current}>
            <span className="setup-step-number" aria-hidden="true">{i + 1 < current ? <Check size={14} /> : i + 1}</span>
            <span>{translate(label)}</span>
        </li>)}
    </ol>;
}

function Step1({ data, onChange }: { data: FormData; onChange: (key: keyof FormData, value: string) => void }) {
    useLanguage();
    return <div className="setup-fields">
        <section className="setup-directories" aria-labelledby="setup-storage-title">
            <div className="setup-storage-heading">
                <h3 id="setup-storage-title">{translate("download.storageLocation")}</h3>
                <p className="setup-hint">{translate("setup.missingFoldersAreCreatedAutomaticallyWhenSetupIsCompleted")}</p>
            </div>
            {([
                { key: "live_download_dir", id: "setup-live-dir", label: translate("settings.liveRecordingLocation"), hint: translate("setup.saveLiveRecordingsHere") },
                { key: "vod_download_dir", id: "setup-vod-dir", label: translate("setup.videoSaveLocation"), hint: translate("setup.saveDownloadedVideosIncludingVODsAndClipsHere") },
            ] as const).map(({ key, id, label, hint }) => <div className="setup-directory" key={key}>
                <Field label={label} htmlFor={id}>
                    <DirInput id={id} value={data[key]} onChange={(value) => onChange(key, value)} multiline required describedBy={id + "-hint"} placeholder={translate("setup.enterTheFolderPath")} />
                </Field>
                <p id={id + "-hint"} className="ui-field-hint">{hint}</p>
            </div>)}
        </section>
        <section className="setup-recording-options" aria-labelledby="setup-recording-title">
            <h3 id="setup-recording-title">{translate("setup.defaultLiveRecordingOptions")}</h3>
            <div className="setup-option-fields">
                <Field label={translate("settings.liveRecordingResolution")} htmlFor="setup-quality">
                    <Select id="setup-quality" value={data.recording_quality} onChange={(event) => onChange("recording_quality", event.target.value)} options={qualities} aria-describedby="setup-quality-hint" />
                    <p id="setup-quality-hint" className="ui-field-hint">{translate("setup.highestQualityUsesTheBestResolutionProvidedByTheStream")}</p>
                </Field>
                <Field label={translate("live.outputFormatAfterRecording")} htmlFor="setup-format">
                    <Select id="setup-format" value={data.output_format} onChange={(event) => onChange("output_format", event.target.value)} options={RECORDING_OUTPUT_FORMATS} aria-describedby="setup-format-hint" />
                    <p id="setup-format-hint" className="ui-field-hint">{translate("setup.whenRecordingEndsConvertAndSaveInTheSelectedFormat")}</p>
                </Field>
            </div>
        </section>
    </div>;
}

function Step2({ data }: { data: FormData }) {
    useLanguage();
    const qualityLabel = qualities.find((option) => option.value === data.recording_quality)?.label;
    const formatLabel = RECORDING_OUTPUT_FORMATS.find((option) => option.value === data.output_format)?.label;
    const rows = [
        { label: "settings.liveRecordingLocation", value: data.live_download_dir.trim(), path: true },
        { label: "setup.videoSaveLocation", value: data.vod_download_dir.trim(), path: true },
        { label: "settings.liveRecordingResolution", value: qualityLabel ? translate(qualityLabel) : data.recording_quality, path: false },
        { label: "live.outputFormatAfterRecording", value: formatLabel ? translate(formatLabel) : data.output_format, path: false },
    ];
    return <div className="setup-review">
        <dl className="setup-summary">
            {rows.map(({ label, value, path }) => <div key={label}>
                <dt>{translate(label)}</dt>
                <dd className={path ? "setup-summary-path" : undefined}>{value}</dd>
            </div>)}
        </dl>
        <p className="setup-hint">{translate("setup.goBackToEditYourChoices")}</p>
    </div>;
}

export function SetupWizard({ defaultDirectories, onComplete }: SetupWizardProps) {
    useLanguage();
    const dialogRef = useRef<HTMLDivElement>(null);
    const headingRef = useRef<HTMLHeadingElement>(null);
    const bodyRef = useRef<HTMLDivElement>(null);
    const errorRef = useRef<HTMLParagraphElement>(null);
    const savingRef = useRef(false);
    useDialogKeyboard(dialogRef, () => {});
    const [step, setStep] = useState<Step>(1);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [data, setData] = useState<FormData>(() => ({ ...defaultDirectories, output_format: "mkv", recording_quality: "best" }));

    useEffect(() => {
        // 다음 버튼이 사라져도 초점이 배경 화면으로 빠지지 않게 한다.
        headingRef.current?.focus({ preventScroll: true });
        if (bodyRef.current) bodyRef.current.scrollTop = 0;
    }, [step]);
    useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);

    const onChange = (key: keyof FormData, value: string) => setData((prev) => ({ ...prev, [key]: value }));
    const canNext = !!data.live_download_dir.trim() && !!data.vod_download_dir.trim();
    const handleSave = async () => {
        if (savingRef.current) return;
        savingRef.current = true;
        setSaving(true);
        setError(null);
        try {
            await completeSetup(data);
            onComplete();
        } catch {
            setError("setup.couldNotSaveSettingsCheckTheSaveLocationsAndTryAgain");
        } finally {
            savingRef.current = false;
            setSaving(false);
        }
    };

    return <div className="ui-overlay setup-overlay fixed inset-0 z-[9998] flex items-center justify-center animate-backdrop">
        <div className="absolute inset-0 bg-black/80" />
        <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="setup-title" aria-describedby="setup-description" tabIndex={-1} className="setup-dialog ui-dialog relative animate-modal-in">
            <header className="setup-header">
                <h2 id="setup-title" ref={headingRef} tabIndex={-1} data-dialog-initial-focus>{translate(steps[step - 1])}</h2>
                <p id="setup-description">{step === 1 ? translate("setup.chooseSaveLocationsAndDefaultLiveRecordingOptions") : translate("setup.reviewYourChoicesAndCompleteSetup")}</p>
                <StepIndicator current={step} />
            </header>
            <div className="setup-body" ref={bodyRef}>
                {step === 1 ? <Step1 data={data} onChange={onChange} /> : <Step2 data={data} />}
                {error && <p ref={errorRef} tabIndex={-1} role="alert" className="setup-error">{translate(error)}</p>}
            </div>
            <footer className="setup-footer">
                <p className="setup-hint">{!canNext ? translate("setup.enterBothLiveAndVideoSaveLocations") : translate("setup.youCanChangeTheseSettingsLater")}</p>
                <div className="setup-navigation">
                    {step === 2 && <Button type="button" icon={ChevronLeft} onClick={() => { setError(null); setStep(1); }} disabled={saving}>{translate("setup.back")}</Button>}
                    {step === 1 ? <Button type="button" variant="primary" disabled={!canNext} onClick={() => setStep(2)}>{translate("setup.reviewSettings")}<ChevronRight size={16} /></Button>
                        : <Button type="button" variant="primary" icon={CheckCircle2} loading={saving} onClick={handleSave}>{saving ? translate("settings.saving") : translate("setup.completeSetup")}</Button>}
                </div>
            </footer>
        </div>
    </div>;
}
