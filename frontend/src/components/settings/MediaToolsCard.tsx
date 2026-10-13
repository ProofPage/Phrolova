import { useLanguage } from "../../contexts/LanguageContext";
import { translate } from "../../i18n";
import { useEffect, useState } from 'react';
import { api } from '../../api/client';

export function MediaToolsCard({ ffmpegVersion }: { ffmpegVersion?: string | null }) {
    useLanguage();
    const [tools, setTools] = useState<Awaited<ReturnType<typeof api.getMediaTools>>>({});
    const [busy, setBusy] = useState(true);
    const [error, setError] = useState(false);
    const needsSetup = !busy && !error && ['streamlink', 'ffmpeg', 'ffprobe'].some(name => tools[name]?.available === false);
    useEffect(() => {
        const controller = new AbortController();
        setBusy(true); setError(false);
        void api.getMediaTools(controller.signal).then(data => {
            if (!controller.signal.aborted) setTools(data);
        }).catch(() => { if (!controller.signal.aborted) setError(true); })
          .finally(() => { if (!controller.signal.aborted) setBusy(false); });
        return () => controller.abort();
    }, []);
    return <div className="space-y-3" aria-label={translate("settings.mediaToolStatus")} aria-busy={busy}>
        <dl className="media-tool-list space-y-1 text-sm">
            {['streamlink', 'ffmpeg', 'ffprobe'].map(name => <div key={name} className="ui-info-row">
                <dt className="text-ink-faint">{name === 'streamlink' ? 'Streamlink' : name === 'ffmpeg' ? 'FFmpeg' : 'FFprobe'}</dt>
                <dd className="min-w-0 space-y-1.5">
                    <span className={`inline-flex flex-wrap justify-end items-center gap-1.5 leading-5 ${busy || error ? 'text-ink-muted' : tools[name]?.available ? 'text-ok' : 'text-warn'}`}>
                        {!busy && !error && tools[name]?.available && <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />}
                        {busy ? translate("settings.checkingExecution") : error ? translate("settings.couldNotLoadToolStatus") : tools[name]?.available ? translate("settings.toolHealthy") : tools[name]?.available === false ? translate(tools[name]?.code === 'tool_missing' ? 'settings.toolMissing' : 'settings.toolFailed', {tool: name === 'streamlink' ? 'Streamlink' : name === 'ffmpeg' ? 'FFmpeg' : 'FFprobe'}) : translate("settings.toolStatusUnavailable")}
                        {!busy && !error && tools[name]?.available && (tools[name]?.version || (name === 'ffmpeg' && ffmpegVersion)) && <span className="[overflow-wrap:anywhere]"> · v{tools[name]?.version?.replace(/^(?:ffmpeg|ffprobe) version\s+(\S+).*$/i, '$1') || ffmpegVersion}</span>}
                    </span>
                    {!busy && !error && tools[name]?.available && tools[name]?.path && <details className="text-xs text-ink-faint"><summary className="cursor-pointer">{translate("settings.installationPath")}</summary><p className="mt-2 max-h-32 overflow-auto font-mono leading-relaxed [overflow-wrap:anywhere]">{tools[name].path}</p></details>}
                </dd>
            </div>)}
        </dl>
        {needsSetup && <details className="text-xs text-ink-muted">
            <summary className="cursor-pointer rounded-[var(--radius-control)] text-ink focus-visible:outline-2 focus-visible:outline-info">{translate("settings.installationAndPathSetup")}</summary>
            <ul className="mt-3 space-y-2 leading-relaxed [overflow-wrap:anywhere]">
                {tools.streamlink?.available === false && <li>{translate("settings.streamlinkIsAPythonPackageIncludedWithTheAppReinstallTheAppOrRunPipInstallStreamlinkInItsPythonEnvironmentThenCheckAgain")}</li>}
                <li>{translate("settings.windowsInstallFfmpegExeAndFfprobeExeTogetherInTheBinFolderBesideTheAppToolsInstalledWithWinGetOrOnPATHAreAlsoDetected")}</li>
                <li>{translate("settings.linuxInstallTheFfmpegPackageTermuxNativePkgInstallFfmpeg")}</li>
                <li>{translate("settings.setCustomPathsWithFFMPEGPATHAndFFPROBEPATHCheckTheToolsAgainAfterInstallationThenRetryRecordingProcessing")}</li>
            </ul>
        </details>}
    </div>;
}
